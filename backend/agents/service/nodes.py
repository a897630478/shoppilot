# backend/agents/service/nodes.py
# 售后客服三轨（logistics/refund/exchange）——分流骨架平移自 Exam 三轨并行
import asyncio
import json

from langchain_core.messages import HumanMessage
from sqlalchemy import text

from backend.agents.service.prompts import (
    SYSTEM_PROMPT,
    LOGISTICS_PROMPT,
    REFUND_PROMPT,
    EXCHANGE_PROMPT,
    FALLBACK_REPLY,
)
from backend.agents.service.state import ServiceState, TicketReply
from backend.core.llm_factory import get_structured_llm
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

# 退款审批阈值（CNY）：订单金额超过该值必须转人工（spec §4.2）
REFUND_REVIEW_THRESHOLD = 100.00

# 各类型允许自动处理的订单状态
_ELIGIBLE_STATUSES = ("paid", "shipped", "completed")

_STATUS_LOGISTICS = {
    "created":   "订单已创建，尚未支付，暂无物流信息",
    "paid":      "订单已支付，正在等待商家发货",
    "shipped":   "商品已发货，运输途中，请留意物流更新",
    "completed": "订单已完成，商品已签收",
    "cancelled": "订单已取消，无物流进度",
}


def route_by_type(state: ServiceState) -> str:
    t = state.get("ticket_type", "")
    return t if t in ("logistics", "refund", "exchange") else "logistics"


async def load_order_node(state: ServiceState) -> dict:
    """只读加载订单与商品信息（AI 不写订单表）。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT o.status, o.total_amount, o.quantity, o.user_id, p.title "
            "FROM orders o JOIN products p ON p.id = o.product_id WHERE o.id = :oid"
        ), {"oid": state["order_id"]})).first()
    if row is None:
        raise ValueError(f"order not found: {state['order_id']}")
    if str(row[3]) != state["user_id"]:
        raise ValueError("order not owned by user")
    logger.info("service.load_order", status=row[0], amount=float(row[1]))
    return {
        "order_status": row[0],
        "total_amount": float(row[1]),
        "quantity": row[2],
        "product_title": row[4],
    }


def _fmt(state: ServiceState, rule_note: str) -> dict:
    return dict(
        product_title=state["product_title"],
        quantity=state["quantity"],
        order_status=state["order_status"],
        total_amount=state["total_amount"],
        reason=state["reason"],
        rule_note=rule_note,
    )


async def _llm_reply(prompt: str) -> TicketReply | None:
    for attempt in range(3):
        try:
            return await get_structured_llm("aftersale", TicketReply).ainvoke(
                [HumanMessage(content=SYSTEM_PROMPT + "\n\n" + prompt)]
            )
        except Exception as e:
            if attempt == 2:
                logger.warning("service.llm_failed", error=str(e))
                return None
            await asyncio.sleep(1)
    return None


async def logistics_track_node(state: ServiceState) -> dict:
    """轨一：物流查询——状态话术 + LLM 润色，永不转人工。"""
    status_note = _STATUS_LOGISTICS.get(state["order_status"], "订单状态未知")
    prompt = LOGISTICS_PROMPT.format_map(_fmt(state, f"当前状态说明：{status_note}"))
    result = await _llm_reply(prompt)
    reply = result.reply if result else f"您好，{status_note}。{FALLBACK_REPLY}"
    return {"reply": reply, "suggestion": "",
            "confidence": result.confidence if result else 0.3,
            "needs_review": False, "final_status": "resolved",
            "fallback_used": result is None}


async def refund_track_node(state: ServiceState) -> dict:
    """轨二：退款——状态合法性 + 金额阈值双重规则，LLM 出答复。"""
    status_ok = state["order_status"] in _ELIGIBLE_STATUSES
    amount = state["total_amount"]
    amount_big = amount > REFUND_REVIEW_THRESHOLD
    if not status_ok:
        rule_note = (f"订单状态为 {state['order_status']}，不满足退款条件"
                     f"（允许状态：paid/shipped/completed），判定为规则不明，需人工确认")
    elif amount_big:
        rule_note = f"退款金额 {amount} 元超过自动审批阈值 {REFUND_REVIEW_THRESHOLD} 元，必须转人工审批"
    else:
        rule_note = f"订单状态与金额（{amount} 元）均符合自动退款条件"

    prompt = REFUND_PROMPT.format_map(_fmt(state, rule_note))
    result = await _llm_reply(prompt)

    if result is None:  # LLM 失败 → 强制人工（宁多审不漏审）
        return {"reply": FALLBACK_REPLY, "suggestion": "LLM 失败，规则结果待人工复核",
                "confidence": 0.0, "needs_review": True,
                "final_status": "pending", "fallback_used": True}

    needs_review = (not status_ok) or amount_big or result.confidence < 0.7
    return {"reply": result.reply, "suggestion": result.suggestion,
            "confidence": result.confidence, "needs_review": needs_review,
            "final_status": "pending" if needs_review else "resolved",
            "fallback_used": False}


async def exchange_track_node(state: ServiceState) -> dict:
    """轨三：换货——状态合法性校验（金额不限）。"""
    status_ok = state["order_status"] in _ELIGIBLE_STATUSES
    if not status_ok:
        rule_note = (f"订单状态为 {state['order_status']}，不满足换货条件"
                     f"（允许状态：paid/shipped/completed），需人工确认")
    else:
        rule_note = "订单状态符合换货条件"

    prompt = EXCHANGE_PROMPT.format_map(_fmt(state, rule_note))
    result = await _llm_reply(prompt)

    if result is None:
        return {"reply": FALLBACK_REPLY, "suggestion": "LLM 失败，待人工复核",
                "confidence": 0.0, "needs_review": True,
                "final_status": "pending", "fallback_used": True}

    needs_review = (not status_ok) or result.confidence < 0.7
    return {"reply": result.reply, "suggestion": result.suggestion,
            "confidence": result.confidence, "needs_review": needs_review,
            "final_status": "pending" if needs_review else "resolved",
            "fallback_used": False}


async def aggregate_node(state: ServiceState) -> dict:
    """汇总决策日志（状态已在分轨产出，此处仅记录）。"""
    logger.info("service.decided", type=state["ticket_type"],
                needs_review=state["needs_review"], status=state["final_status"],
                confidence=state["confidence"])
    return {}


async def save_ticket_node(state: ServiceState) -> dict:
    """工单持久化（只 UPDATE 自己的工单行；审批由 API 端点负责）。"""
    ai_result = {
        "reply": state["reply"],
        "suggestion": state["suggestion"],
        "confidence": state["confidence"],
        "rule": {"order_status": state["order_status"],
                 "total_amount": state["total_amount"],
                 "threshold": REFUND_REVIEW_THRESHOLD},
        "fallback_used": state["fallback_used"],
    }
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE service_tickets SET ai_result = :ai, needs_review = :nr, "
            "status = :st, updated_at = NOW() WHERE id = :tid"
        ), {
            "ai": json.dumps(ai_result, ensure_ascii=False),
            "nr": state["needs_review"],
            "st": state["final_status"],
            "tid": state["ticket_id"],
        })
        await db.commit()
    logger.info("service.saved", ticket_id=state["ticket_id"],
                status=state["final_status"])
    return {}
