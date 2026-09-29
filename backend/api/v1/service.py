# backend/api/v1/service.py
# 售后工单 API（M4b）——异步处理 + DB 轻量 HitL 审批
import asyncio
import json
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.agents.service.graph import build_service_graph
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)

_graph = build_service_graph()            # 模块级编译一次
_background_tasks: set = set()           # 强引用防 GC（平移自 resume/exam 模式）


class TicketCreateRequest(BaseModel):
    order_id: str
    ticket_type: Literal["logistics", "refund", "exchange"]
    reason: str = Field(..., min_length=5, max_length=300)


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject"]
    comment: Optional[str] = Field(None, max_length=500)


async def _mark_failed(ticket_id: str, msg: str) -> None:
    """失败回滚：processing → rejected（CHECK 无 failed 值），error 记入 ai_result。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT ai_result FROM service_tickets WHERE id = :tid"
        ), {"tid": ticket_id})).first()
        ai = row[0] if isinstance(row[0], dict) else json.loads(row[0] or "{}") if row and row[0] else {}
        ai["error"] = msg[:500]
        await db.execute(text(
            "UPDATE service_tickets SET status='rejected', ai_result=:ai, "
            "updated_at=NOW() WHERE id=:tid AND status='processing'"
        ), {"ai": json.dumps(ai, ensure_ascii=False), "tid": ticket_id})
        await db.commit()


def _track(task: asyncio.Task, ticket_id: str) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            logger.error("service.ticket_failed", ticket_id=ticket_id,
                         error=str(t.exception()))
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_mark_failed(ticket_id, str(t.exception())))
            except RuntimeError:
                logger.error("service.mark_failed_no_loop", ticket_id=ticket_id)
    task.add_done_callback(_on_done)


def _row_to_ticket(row) -> dict:
    ai = row[4]
    if isinstance(ai, str):
        ai = json.loads(ai or "{}")
    return {
        "id": row[0], "order_id": row[1],
        "product_title": row[2], "ticket_type": row[3],
        "ai_result": ai,
        "reason": row[5], "status": row[6], "needs_review": row[7],
        "created_at": row[8].isoformat() if row[8] else None,
        "reviewed_at": row[9].isoformat() if row[9] else None,
    }


_TICKET_SELECT = """
    SELECT t.id, t.order_id, p.title AS product_title, t.ticket_type,
           t.ai_result, t.reason, t.status, t.needs_review,
           t.created_at, t.reviewed_at
    FROM service_tickets t
    JOIN orders o ON o.id = t.order_id
    JOIN products p ON p.id = o.product_id
"""


@router.post("/tickets", status_code=202)
async def create_ticket(req: TicketCreateRequest, current_user: dict = Depends(get_current_user)):
    """发起售后工单（异步处理）。校验订单归属；每单同时只允许一个未完结工单。"""
    async with AsyncSessionLocal() as db:
        order = (await db.execute(text(
            "SELECT user_id FROM orders WHERE id = :oid"
        ), {"oid": req.order_id})).first()
        if order is None:
            raise HTTPException(status_code=404, detail="order not found")
        if str(order[0]) != current_user["user_id"]:
            raise HTTPException(status_code=403, detail="not your order")
        # 每单一个未完结工单（processing/pending），防止重复提交
        open_ticket = (await db.execute(text(
            "SELECT id, status FROM service_tickets "
            "WHERE order_id = :oid AND status IN ('processing','pending') LIMIT 1"
        ), {"oid": req.order_id})).first()
        if open_ticket is not None:
            raise HTTPException(
                status_code=409,
                detail=f"该订单已有处理中的工单（{open_ticket[1]}），请等待完成后再发起",
            )
        ticket_id = str(uuid.uuid4())
        await db.execute(text(
            "INSERT INTO service_tickets (id, tenant_id, order_id, user_id, "
            "ticket_type, reason, status) "
            "VALUES (:tid, :tenant, :oid, :uid, :tt, :reason, 'processing')"
        ), {"tid": ticket_id, "tenant": current_user["tenant_id"],
            "oid": req.order_id, "uid": current_user["user_id"],
            "tt": req.ticket_type, "reason": req.reason})
        await db.commit()

    task = asyncio.create_task(_graph.ainvoke({
        "messages": [],
        "tenant_id": current_user["tenant_id"],
        "user_id": current_user["user_id"],
        "ticket_id": ticket_id,
        "order_id": req.order_id,
        "ticket_type": req.ticket_type,
        "reason": req.reason,
        "order_status": "", "total_amount": 0.0, "product_title": "", "quantity": 1,
        "reply": "", "suggestion": "", "confidence": 0.0,
        "needs_review": False, "final_status": "", "fallback_used": False,
    }))
    _track(task, ticket_id)
    logger.info("service.ticket_created", ticket_id=ticket_id, type=req.ticket_type)
    return {"ticket_id": ticket_id, "status": "processing"}


@router.get("/tickets")
async def list_my_tickets(current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            _TICKET_SELECT + " WHERE t.user_id = :uid ORDER BY t.created_at DESC LIMIT 100"
        ), {"uid": current_user["user_id"]})).fetchall()
    items = [_row_to_ticket(r) for r in rows]
    return {"total": len(items), "items": items}


@router.get("/pending-reviews")
async def list_pending_reviews(current_user: dict = Depends(get_current_user)):
    """运营审批列表（teacher/admin）。"""
    if current_user.get("role") not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="operator only")
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            _TICKET_SELECT + " WHERE t.needs_review = TRUE AND t.status = 'pending' "
            "ORDER BY t.created_at DESC LIMIT 100"
        ))).fetchall()
    items = [_row_to_ticket(r) for r in rows]
    return {"total": len(items), "items": items}


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            _TICKET_SELECT + " WHERE t.id = :tid"
        ), {"tid": ticket_id})).first()
    if row is None:
        raise HTTPException(status_code=404, detail="ticket not found")
    # 只能看自己的（operator 可看全部，审批列表页需要）
    mine = (await _owner_check(ticket_id, current_user))
    if not mine and current_user.get("role") not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="not your ticket")
    return _row_to_ticket(row)


async def _owner_check(ticket_id: str, current_user: dict) -> bool:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT user_id FROM service_tickets WHERE id = :tid"
        ), {"tid": ticket_id})).first()
    return bool(row) and str(row[0]) == current_user["user_id"]


@router.post("/tickets/{ticket_id}/review")
async def review_ticket(ticket_id: str, req: ReviewRequest, current_user: dict = Depends(get_current_user)):
    """运营审批：approve → resolved；reject → rejected。仅 pending+needs_review 可审。"""
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
        ai = row[2] if isinstance(row[2], dict) else json.loads(row[2] or "{}")
        ai["operator_comment"] = req.comment or ""
        ai["operator_action"] = req.action
        new_status = "resolved" if req.action == "approve" else "rejected"
        await db.execute(text(
            "UPDATE service_tickets SET status = :st, ai_result = :ai, "
            "reviewed_by = :uid, reviewed_at = NOW(), updated_at = NOW() "
            "WHERE id = :tid"
        ), {"st": new_status, "ai": json.dumps(ai, ensure_ascii=False),
            "uid": current_user["user_id"], "tid": ticket_id})
        await db.commit()
    logger.info("service.reviewed", ticket_id=ticket_id, action=req.action)
    return {"ticket_id": ticket_id, "status": new_status}
