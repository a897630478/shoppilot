# M4b 售后客服 Agent（Exam 平移 + 轻量 HitL）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付第四个电商能力的前半——**售后客服 Agent**：用户对订单发起物流/退款/换货工单，Agent 按类型分流处理（规则校验 + LLM 回复），退款超阈值或规则不明时**转人工审批**（运营端批准/驳回），全流程前端可用；统一入口 `service` 意图改为真引导。

**Architecture:** 新建 `backend/agents/service/`（线性图 + 条件边三轨分流，无 checkpointer——工单是一次性任务）；**轻量 HitL 取代 Exam 的 interrupt/Command 模式**：图跑完把 `service_tickets` 落为 `pending(needs_review)` 或 `resolved`，审批 = 直接 UPDATE（审批语义只是批准/驳回 AI 建议，无需恢复图——规格 §4.2 的审批环保留，机制简化）；API 照抄 exam.py 的 202 异步三段式；前端复用教师端列表/审批页模式（requiresTeacher 守卫）。

**Tech Stack:** LangGraph 条件边三轨、`get_structured_llm("aftersale")`、FastAPI 异步任务、Vue3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §4.2、§5.1、§5.2、§7 M4

## Global Constraints

- Python：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`；前端门禁 `npm run build`（0 错误）。
- `service_tickets` 表已建（不改结构）：`ticket_type CHECK IN ('logistics','refund','exchange')`、`status CHECK IN ('pending','processing','resolved','rejected')`、`ai_result JSONB`、`needs_review BOOL`、`reviewed_by/reviewed_at`。
- `orders.status IN ('created','paid','shipped','completed','cancelled')`，`total_amount NUMERIC NOT NULL`。
- **退款审批阈值**：`REFUND_REVIEW_THRESHOLD = 100.00`（CNY，`total_amount > 100` → needs_review；常量放 nodes.py 顶部，可调）。
- **AI 不写库**：Agent 只 UPDATE 自己的工单行（`save_ticket`）；订单表只读；审批只由 `/service/tickets/{id}/review` 端点执行。
- 三轨分流规则（按用户在下单页选择的 `ticket_type`，不做 LLM 意图分类）：
  - `logistics`：订单状态→话术模板+LLM 润色；**永不 needs_review**，直接 resolved
  - `refund`：状态 ∈ paid/shipped/completed 才可退（否则规则不明→needs_review）；金额>100→needs_review；否则 resolved
  - `exchange`：状态同 refund 校验（不明→needs_review）；金额不限；resolved 或 needs_review
- LLM：`llm_factory` 路由表加 `"aftersale": "deepseek-chat"`；失败降级 = `fallback_used=True` + 通用话术 + refund/exchange 场景强制 needs_review（宁多审不漏审）。
- 教育 Exam/Resume/Interview 不动（M5 清理）；`/chat` service 引导最后更新。
- 异步模式照抄 exam.py：模块级 `_graph`、`asyncio.create_task`、`_background_tasks` 强引用、done_callback 失败回滚（processing→rejected + ai_result.error）。

## 文件结构总览

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/agents/service/{__init__,state,prompts,nodes,graph}.py` | 售后 Agent | 新建 |
| `backend/core/llm_factory.py` | 加 `"aftersale"` 键 | 修改 1 行 |
| `backend/api/v1/service.py` | 工单四端点 | 新建 |
| `backend/api/router.py` | 挂 `/service` | 修改 2 行 |
| `frontend/src/api/service.ts` | 工单 API 封装 | 新建 |
| `frontend/src/views/service/ServiceTicketsView.vue` | 我的售后（列表+详情） | 新建 |
| `frontend/src/views/operator/ServiceReviewView.vue` | 运营端审批页 | 新建 |
| `frontend/src/views/order/OrderListView.vue` | 「申请售后」入口 | 修改 |
| `frontend/src/router/index.ts` | 2 条路由 | 修改 |
| `frontend/src/components/layout/Sidebar.vue` | 用户菜单+审批菜单 | 修改 |
| `backend/api/v1/unified_chat.py` | service 引导文案 | 修改 1 处 |
| `scripts/manual_tests/test_m4b_service_agent.py` | Agent 图端到端 | 新建 |
| `scripts/manual_tests/test_m4b_service_api.py` | 工单→审批全链路 | 新建 |

---

### Task 1: 售后客服 Agent（backend/agents/service/）

**Files:**
- Create: `backend/agents/service/__init__.py`（空）、`state.py`、`prompts.py`、`nodes.py`、`graph.py`
- Modify: `backend/core/llm_factory.py`（加 `"aftersale"`）
- Test: `scripts/manual_tests/test_m4b_service_agent.py`

**Interfaces:**
- Consumes: `orders/products/service_tickets` 表；`get_llm/get_structured_llm`
- Produces:
  - `build_service_graph()` → 可调用函数返回编译图（**条件边三轨**：`load_order → route_by_type → {logistics|refund|exchange} → aggregate → save_ticket`）
  - initial_state：`{"ticket_id","tenant_id","user_id","order_id","ticket_type","reason", ...}`（API 层传入）
  - 终态：工单行 `status ∈ {resolved, pending}`、`needs_review`、`ai_result` 填充
  - Pydantic：`TicketReply {reply: str, suggestion: str, confidence: float}`（suggestion=给审批人的处理建议）

- [ ] **Step 1: llm_factory 加键**

`llm_factory.py` 路由表追加：

```python
    "aftersale":        "deepseek-chat",   # 售后客服（M4b）
```

- [ ] **Step 2: 写 state 与 prompts**

`state.py`：

```python
# backend/agents/service/state.py
# 售后客服 Agent 状态（M4b：由 Exam 三轨批改平移；一次性线性图 + 条件分流）
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class TicketReply(BaseModel):
    """工单回复（结构化输出）"""
    reply: str = Field(..., description="给客户的中文回复，60~120字，礼貌清晰")
    suggestion: str = Field(..., description="给审批人的处理建议（如需人工），30~60字；自动处理时可为空串")
    confidence: float = Field(..., ge=0, le=1, description="处理方案置信度")


class ServiceState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_id: str
    user_id: str
    ticket_id: str
    order_id: str
    ticket_type: str                   # logistics | refund | exchange
    reason: str                        # 用户填写的诉求
    # load_order 产出
    order_status: str
    total_amount: float
    product_title: str
    quantity: int
    # 分轨产出
    reply: str
    suggestion: str
    confidence: float
    needs_review: bool
    final_status: str                  # resolved | pending
    fallback_used: bool
```

`prompts.py`：

```python
# backend/agents/service/prompts.py
# 售后客服提示词（M4b：由试卷批改平移）

SYSTEM_PROMPT = (
    "你是 ShopPilot 商城的售后客服专员。要求：回复礼貌专业、基于给定的订单事实，"
    "不承诺无法核实的补偿，不编造订单状态；涉及金额以给定数据为准。"
)

COMMON_FMT = """
订单事实：
- 商品：{product_title} × {quantity}
- 订单状态：{order_status}
- 订单金额：{total_amount} 元
- 客户诉求：{reason}

只输出 JSON：{{"reply": "给客户的回复", "suggestion": "给审批人的处理建议，自动处理时为空串", "confidence": 0到1的小数}}
"""

LOGISTICS_PROMPT = """客户查询物流进度。按订单状态如实说明当前环节，告知后续预期，无需审批。
""" + COMMON_FMT

REFUND_PROMPT = """客户申请退款。
规则（已由系统校验，遵循其结论）：{rule_note}
生成给客户的退款答复；若需人工审批，suggestion 说明审批要点（金额、依据）。
""" + COMMON_FMT

EXCHANGE_PROMPT = """客户申请换货。
规则（已由系统校验，遵循其结论）：{rule_note}
生成给客户的换货答复；若需人工审批，suggestion 说明审批要点。
""" + COMMON_FMT

FALLBACK_REPLY = (
    "您的售后诉求已收到。当前智能客服暂时无法完成自动处理，"
    "已转交人工审核，我们会尽快通过站内消息给您答复，请留意订单页状态更新。"
)
```

- [ ] **Step 3: 写 nodes（条件分流三轨）**

`nodes.py` 核心（完整实现）：

```python
# backend/agents/service/nodes.py
# 售后客服三轨（logistics/refund/exchange）——分流骨架平移自 Exam 三轨并行
import json

from langchain_core.messages import HumanMessage
from sqlalchemy import text

from backend.agents.service.prompts import (
    SYSTEM_PROMPT, LOGISTICS_PROMPT, REFUND_PROMPT, EXCHANGE_PROMPT, FALLBACK_REPLY,
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


def _fmt(state: ServiceState, rule_note: str) -> str:
    return dict(product_title=state["product_title"], quantity=state["quantity"],
                order_status=state["order_status"], total_amount=state["total_amount"],
                reason=state["reason"], rule_note=rule_note)


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
            import asyncio
            await asyncio.sleep(1)
    return None


async def logistics_track_node(state: ServiceState) -> dict:
    """轨一：物流查询——状态话术 + LLM 润色，永不转人工。"""
    status_note = _STATUS_LOGISTICS.get(state["order_status"], "订单状态未知")
    prompt = LOGISTICS_PROMPT.format_map(_fmt(state, f"当前状态说明：{status_note}"))
    result = await _llm_reply(prompt)
    reply = result.reply if result else f您好，{status_note}。{FALLBACK_REPLY}"
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

    if result is None:                                  # LLM 失败 → 强制人工（宁多审不漏审）
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
```

（注意：上面 `f您好，...` 为文档笔误示例——实现时写成合法 f-string：`f"您好，{status_note}。{FALLBACK_REPLY}"`。）

- [ ] **Step 4: 写 graph（条件边）**

`graph.py`：

```python
# backend/agents/service/graph.py
# 售后客服图：load_order → route_by_type →(条件边) 三轨之一 → aggregate → save_ticket
# 一次性任务：无 checkpointer（审批走 DB 轻量 HitL，不使用 interrupt/resume）
from langgraph.graph import StateGraph, START, END

from backend.agents.service.state import ServiceState
from backend.agents.service.nodes import (
    load_order_node,
    route_by_type,
    logistics_track_node,
    refund_track_node,
    exchange_track_node,
    aggregate_node,
    save_ticket_node,
)


def build_service_graph():
    builder = StateGraph(ServiceState)

    builder.add_node("load_order", load_order_node)
    builder.add_node("logistics",  logistics_track_node)
    builder.add_node("refund",     refund_track_node)
    builder.add_node("exchange",   exchange_track_node)
    builder.add_node("aggregate",  aggregate_node)
    builder.add_node("save_ticket", save_ticket_node)

    builder.add_edge(START, "load_order")
    builder.add_conditional_edges(
        "load_order",
        route_by_type,
        {"logistics": "logistics", "refund": "refund", "exchange": "exchange"},
    )
    builder.add_edge("logistics",  "aggregate")
    builder.add_edge("refund",     "aggregate")
    builder.add_edge("exchange",   "aggregate")
    builder.add_edge("aggregate",  "save_ticket")
    builder.add_edge("save_ticket", END)
    return builder.compile()
```

- [ ] **Step 5: Agent 端到端测试**

`scripts/manual_tests/test_m4b_service_agent.py`：

```python
# scripts/manual_tests/test_m4b_service_agent.py
# 直接跑售后图：退款大额订单 → pending+needs_review（真实 LLM 1 次；需 PG）
import asyncio
import json
import uuid

from sqlalchemy import text

from backend.agents.service.graph import build_service_graph
from backend.dependencies import AsyncSessionLocal


def test_refund_large_amount_needs_review():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as db:
        # 找一个 paid/shipped/completed 且金额最大的订单；没有就造一个
        row = (await db.execute(text(
            "SELECT id, user_id, total_amount FROM orders "
            "WHERE status IN ('paid','shipped','completed') "
            "ORDER BY total_amount DESC LIMIT 1"
        ))).first()
        if row and float(row[2]) > 100:
            order_id, user_id = str(row[0]), str(row[1])
        else:
            prod = (await db.execute(text(
                "SELECT id, price FROM products WHERE is_active LIMIT 1"))).first()
            uid = (await db.execute(text("SELECT id FROM users LIMIT 1"))).scalar()
            order_id, user_id = str(uuid.uuid4()), str(uid)
            await db.execute(text(
                "INSERT INTO orders (id, user_id, product_id, quantity, unit_price, "
                "total_amount, receiver, address, status) "
                "VALUES (:oid, :uid, :pid, 1, :p, 199.00, '测试', '地址', 'paid')"
            ), {"oid": order_id, "uid": user_id, "pid": prod[0], "p": prod[1]})
            await db.commit()

        ticket_id = str(uuid.uuid4())
        await db.execute(text(
            "INSERT INTO service_tickets (id, order_id, user_id, ticket_type, reason, status) "
            "VALUES (:tid, :oid, :uid, 'refund', '不想要了，申请退款', 'processing')"
        ), {"tid": ticket_id, "oid": order_id, "uid": user_id})
        await db.commit()

    graph = build_service_graph()
    await graph.ainvoke({
        "messages": [],
        "tenant_id": "tenant_default",
        "user_id": user_id,
        "ticket_id": ticket_id,
        "order_id": order_id,
        "ticket_type": "refund",
        "reason": "不想要了，申请退款",
        "order_status": "", "total_amount": 0.0, "product_title": "", "quantity": 1,
        "reply": "", "suggestion": "", "confidence": 0.0,
        "needs_review": False, "final_status": "", "fallback_used": False,
    })

    async with AsyncSessionLocal() as db:
        t = (await db.execute(text(
            "SELECT status, needs_review, ai_result FROM service_tickets WHERE id = :tid"
        ), {"tid": ticket_id})).first()
    assert t[0] == "pending" and t[1] is True, t
    ai = t[2] if isinstance(t[2], dict) else json.loads(t[2])
    assert ai["reply"] and len(ai["reply"]) >= 20
    assert ai["suggestion"]
```

- [ ] **Step 6: 运行**

Run: `& $py -m pytest scripts/manual_tests/test_m4b_service_agent.py -v`
Expected: PASS（199 元 > 100 阈值 → pending + needs_review）

---

### Task 2: `/service` API 与挂载

**Files:**
- Create: `backend/api/v1/service.py`
- Modify: `backend/api/router.py`（2 行）
- Test: `scripts/manual_tests/test_m4b_service_api.py`

**Interfaces:**
- Consumes: `build_service_graph`
- Produces:
  - `POST /api/v1/service/tickets` body `{"order_id","ticket_type","reason"}` → 202 `{"ticket_id","status":"processing"}`；404 订单不存在/非本人
  - `GET /api/v1/service/tickets` → 当前用户工单列表（含 `product_title` join、`ai_result`、`needs_review`、`reviewed_at`）
  - `GET /api/v1/service/tickets/{id}` → 单工单（轮询用；含 ai_result.reply/suggestion）
  - `POST /api/v1/service/tickets/{id}/review` body `{"action":"approve"|"reject","comment":str?}` → 审批（仅 `needs_review && status='pending'` 可审，否则 409）；approve→`resolved`、reject→`rejected`；`reviewed_by/at` 落库；`comment` 合并进 `ai_result.operator_comment`
  - 审批端点**不校验 isTeacher**还是校验？→ 校验：`current_user["role"] in ("teacher","admin")`（运营语义沿用现有三角色），非审批角色 403

- [ ] **Step 1: 写冒烟测试**

`scripts/manual_tests/test_m4b_service_api.py`：

```python
# scripts/manual_tests/test_m4b_service_api.py
# 需后端 :8000：下单→售后工单→轮询→审批闭环（真实 LLM 1~2 次）
import time

import httpx

BASE = "http://localhost:8000"


def _login(username: str) -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": username, "password": "Student@123456" if username.startswith("student") else "Teacher@123456",
    })
    if r.status_code != 200:
        r = httpx.post(f"{BASE}/api/v1/auth/login", json={
            "username": username, "password": "Teacher@123456",
        })
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def test_ticket_and_approval_flow():
    student = _login("student01@eduagent.local")

    # 1) 造单：下单 + 模拟支付
    p = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=student).json()
    pid = p["items"][0]["id"]
    o = httpx.post(f"{BASE}/api/v1/orders", json={
        "product_id": pid, "quantity": 3, "receiver": "测试", "address": "地址",
    }, headers=student, timeout=30)
    assert o.status_code == 200, o.text
    order_id = o.json()["id"]
    httpx.post(f"{BASE}/api/v1/orders/{order_id}/pay", headers=student, timeout=30)

    # 2) 发起大额退款工单（quantity=3 应使金额可能>100；若单价过低则以规则为准）
    t = httpx.post(f"{BASE}/api/v1/service/tickets", json={
        "order_id": order_id, "ticket_type": "refund", "reason": "商品质量问题，要求退款",
    }, headers=student, timeout=30)
    assert t.status_code == 202, t.text
    tid = t.json()["ticket_id"]

    # 3) 轮询至终态
    deadline = time.time() + 180
    body = {}
    while time.time() < deadline:
        g = httpx.get(f"{BASE}/api/v1/service/tickets/{tid}", headers=student, timeout=30)
        assert g.status_code == 200, g.text
        body = g.json()
        if body["status"] in ("resolved", "pending", "rejected"):
            break
        time.sleep(4)
    assert body["status"] in ("resolved", "pending"), body
    assert body["ai_result"]["reply"], "missing reply"

    # 4) 若 pending → 运营审批
    if body["status"] == "pending":
        teacher = _login("teacher01@eduagent.local")
        pending = httpx.get(f"{BASE}/api/v1/service/pending-reviews", headers=teacher, timeout=30)
        assert pending.status_code == 200, pending.text
        assert any(x["id"] == tid for x in pending.json()["items"]), "ticket not in pending list"
        rv = httpx.post(f"{BASE}/api/v1/service/tickets/{tid}/review", json={
            "action": "approve", "comment": "情况属实，同意退款",
        }, headers=teacher, timeout=30)
        assert rv.status_code == 200, rv.text
        after = httpx.get(f"{BASE}/api/v1/service/tickets/{tid}", headers=student, timeout=30)
        assert after.json()["status"] == "resolved"
        # 学员无权审批
        forbidden = httpx.post(f"{BASE}/api/v1/service/tickets/{tid}/review",
                               json={"action": "approve"}, headers=student, timeout=30)
        assert forbidden.status_code in (403, 409)
```

（端点清单里加 `GET /service/pending-reviews`：运营审批列表，role 校验 teacher/admin，返回 `needs_review=TRUE AND status='pending'` 的工单。）

- [ ] **Step 2: 确认失败**（404）→ **Step 3 实现 `service.py`**

结构照抄 M4a `reviews.py` 的异步三段式（`_graph`/`_background_tasks`/`_track`/`_mark_failed`——失败时 `status='rejected'` + `ai_result.error`，因为 CHECK 无 `failed` 值）；工单列表 SQL join `orders+products`；审批端点：

```python
@router.post("/tickets/{ticket_id}/review")
async def review_ticket(ticket_id: str, req: ReviewRequest, current_user = Depends(get_current_user)):
    if current_user.get("role") not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="operator only")
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT status, needs_review, ai_result FROM service_tickets WHERE id = :tid"
        ), {"tid": ticket_id})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="ticket not found")
        if row[0] != "pending" or not row[1]:
            raise HTTPException(status_code=409, detail="ticket not awaiting review")
        new_status = "resolved" if req.action == "approve" else "rejected"
        ai = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
        ai["operator_comment"] = req.comment or ""
        ai["operator_action"] = req.action
        await db.execute(text(
            "UPDATE service_tickets SET status = :st, ai_result = :ai, "
            "reviewed_by = :uid, reviewed_at = NOW(), updated_at = NOW() WHERE id = :tid"
        ), {"st": new_status, "ai": json.dumps(ai, ensure_ascii=False),
            "uid": current_user["user_id"], "tid": ticket_id})
        await db.commit()
    return {"ticket_id": ticket_id, "status": new_status}
```

（`GET /tickets` 列表、`GET /tickets/{id}`、`GET /pending-reviews`、`POST /tickets` 见 Interfaces 契约，SQL 按契约列写。`ReviewRequest {action: Literal["approve","reject"], comment: str|None}`。）

- [ ] **Step 4: 挂路由**（router.py import+include，prefix `/service`, tag `售后客服`）

- [ ] **Step 5: 重启后端跑冒烟**

Expected: `test_ticket_and_approval_flow` PASS（若 quantity=3 金额未过阈值，工单会直接 resolved——测试已兼容两种终态；409/403 断言覆盖权限）

---

### Task 3: 前端用户侧（工单入口与我的售后）

**Files:**
- Create: `frontend/src/api/service.ts`、`frontend/src/views/service/ServiceTicketsView.vue`
- Modify: `frontend/src/views/order/OrderListView.vue`（申请售后入口）
- Modify: `frontend/src/router/index.ts`、`frontend/src/components/layout/Sidebar.vue`
- Gate: `npm run build`

**Interfaces:**
- Consumes: Task 2 契约
- Produces: 路由 `service-tickets`（path `service`）；订单行「申请售后」对话框（type 单选 + reason 文本域）

- [ ] **Step 1: `frontend/src/api/service.ts`**

```ts
// frontend/src/api/service.ts
import client from './client'

export type TicketType = 'logistics' | 'refund' | 'exchange'

export interface TicketCreateReq {
  order_id: string
  ticket_type: TicketType
  reason: string
}

export interface TicketItem {
  id: string
  order_id: string
  product_title: string
  ticket_type: TicketType
  reason: string
  status: 'pending' | 'processing' | 'resolved' | 'rejected'
  needs_review: boolean
  ai_result: {
    reply?: string
    suggestion?: string
    confidence?: number
    operator_comment?: string
    operator_action?: string
    error?: string
  } | null
  created_at: string | null
  reviewed_at: string | null
}

export const serviceApi = {
  create: (data: TicketCreateReq) =>
    client.post<{ ticket_id: string; status: string }>('/service/tickets', data),
  listMine: () => client.get<{ total: number; items: TicketItem[] }>('/service/tickets'),
  get: (id: string) => client.get<TicketItem>(`/service/tickets/${id}`),
  listPending: () => client.get<{ total: number; items: TicketItem[] }>('/service/pending-reviews'),
  review: (id: string, action: 'approve' | 'reject', comment?: string) =>
    client.post<{ ticket_id: string; status: string }>(`/service/tickets/${id}/review`, { action, comment }),
}
```

- [ ] **Step 2: 订单页「申请售后」**

`OrderListView.vue`：script 加售后对话框状态（`afterSaleVisible/orderId/type/reason`）与 `openAfterSale(row)`（仅 `paid|shipped|completed` 显示按钮）、`submitAfterSale()` → `serviceApi.create` → 成功 `ElMessage` + `router.push('/service')`；template 操作列在「模拟支付」旁加：

```html
            <el-button
              v-if="['paid','shipped','completed'].includes(row.status)"
              size="small" @click="openAfterSale(row)"
            >申请售后</el-button>
```

对话框（type 用 `el-radio-group`：物流查询/退款/换货；reason `el-input textarea` 必填 5~300 字）。

- [ ] **Step 3: `ServiceTicketsView.vue`（我的售后）**

表格列：商品/类型（tag）/诉求/状态（pending=审核中 warning、processing=处理中 info、resolved=已解决 success、rejected=已驳回 danger）/AI 回复（展开行显示 `ai_result.reply`，`needs_review` 时附「已转人工审核」与 `suggestion`、审批后显示 `operator_comment`）；`processing` 状态 4s 递归轮询整表；空态引导去订单页。根类 `.service-tickets { max-width: 1100px }`。

- [ ] **Step 4: 路由与菜单**

router children：

```ts
        // 我的售后（M4b）
        {
          path: 'service',
          name: 'service-tickets',
          component: () => import('@/views/service/ServiceTicketsView.vue'),
        },
```

Sidebar 用户区（「我的订单」后）加（图标 `Headset`）：「售后服务」→ `/service`。

- [ ] **Step 5: 构建 + 手测**

`npm run build` → 0 错误。手测：订单页（有已支付订单）出现「申请售后」→ 对话框选退款填理由 → 跳我的售后 → processing 轮询 → resolved 显示 AI 回复（或 pending 显示转人工）。

---

### Task 4: 运营审批页 + 统一入口 + 全量回归

**Files:**
- Create: `frontend/src/views/operator/ServiceReviewView.vue`
- Modify: `frontend/src/router/index.ts`（teacher 路由）、`Sidebar.vue`（教师区菜单）
- Modify: `backend/api/v1/unified_chat.py`（service 引导）
- Gate: 全套回归

- [ ] **Step 1: 审批页 `ServiceReviewView.vue`**

模式照抄 `ExamReviewView`：`onMounted` 拉 `serviceApi.listPending()`；表格（商品/类型/金额诉求/理由/AI 建议 `ai_result.suggestion`）；行操作「批准」（默认 comment 空）与「驳回」（弹窗必填 comment）→ `serviceApi.review` → 刷新列表；空态「暂无待审批工单」。路由：

```ts
        {
          path: 'operator/service-review',
          name: 'operator-service-review',
          component: () => import('@/views/operator/ServiceReviewView.vue'),
          meta: { requiresTeacher: true },
        },
```

Sidebar 教师区（`v-if="auth.isTeacher"` 内）追加（图标 `Checked`）：「售后审批」→ `/operator/service-review`。

- [ ] **Step 2: 统一入口 service 引导更新**

`unified_chat.py` `_GUIDANCE_BY_LABEL["service"]`：

```python
    "service": {
        "message": "售后服务已上线：请到「我的订单」找到对应订单，点击「申请售后」发起物流/退款/换货工单，AI 将自动处理或转人工审批。",
        "action_label": "查看我的订单",
        "action_url": "/orders",
    },
```

（review/guide 两张卡不动。）

- [ ] **Step 3: 全量回归**

重启后端：

```powershell
& $py -m pytest tests/ scripts/manual_tests/test_m2_retrieval.py scripts/manual_tests/test_m2_qa_chat.py scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py scripts/manual_tests/test_off_pipeline.py scripts/manual_tests/test_m3_unified_route.py scripts/manual_tests/test_m4a_review_api.py scripts/manual_tests/test_m4b_service_api.py -q
```

Expected: 全 passed（约 21 个）

- [ ] **Step 4: M4b 黄金路径手测**

1. 订单页（已支付订单）→ 申请售后（物流）→ 我的售后快速 resolved 显示回复
2. 申请退款（大额）→ pending 转人工 → 切 admin/teacher 账号 → 售后审批页 → 批准 → 工单变已解决
3. `/chat` 输入「我要退货」→ service 引导新文案 → 跳订单页
4. 学员账号访问 `/operator/service-review` → 被守卫重定向
5. 教育考试批改页仍可访问（不破坏）

## M4b 完成定义（DoD）

- [ ] 三类型工单端到端可跑：logistics 自动 resolved；refund 金额>100 或状态不符 → pending+needs_review
- [ ] 审批闭环：teacher/admin 批准/驳回 → 状态与 `reviewed_by/at` 落库；非审批角色 403；非 pending 409
- [ ] 订单页入口 + 我的售后页 + 审批页全部可用；`npm run build` 0 错误
- [ ] `/chat` service 引导已上线文案；全套 pytest 绿；教育页面无破坏

## 明确不做（M4b 范围外）

- 多轮导购 Agent（M5）、教育代码清理与品牌改名（M5）
- LangGraph interrupt/Command 恢复式 HitL（已显式用 DB 轻量 HitL 替代——语义等价、复杂度更低）
- 工单驳回后用户重新提交的多轮迭代（重新发起新工单即可）
- 物流轨迹真实对接（状态话术基于 orders.status）
- FAQ 待补录管理页（沿用既有教师「知识库待补充」页，M5 收编）
