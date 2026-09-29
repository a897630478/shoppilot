# backend/api/v1/reviews.py
# 评价分析报告 API（M4a：由 /resume 平移）——异步触发 + 轮询查询
import asyncio
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.agents.review.graph import build_review_graph
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)

_graph = build_review_graph()            # 模块级编译一次
_background_tasks: set = set()           # 强引用防 GC（平移自 resume.py）
_TIMEOUT_MINUTES = 15


class ReportCreateRequest(BaseModel):
    product_id: str = Field(..., description="商品 ID")


async def _mark_failed(report_id: str, msg: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE review_reports SET status='failed', error_msg=:e, updated_at=NOW() "
            "WHERE id=:rid AND status='processing'"
        ), {"e": msg, "rid": report_id})
        await db.commit()


def _track(task: asyncio.Task, report_id: str) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    def _on_done(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            logger.error("review.report_failed", report_id=report_id,
                         error=str(t.exception()))
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_mark_failed(report_id, str(t.exception())[:500]))
            except RuntimeError:
                logger.error("review.mark_failed_no_loop", report_id=report_id)
    task.add_done_callback(_on_done)


@router.post("/reports", status_code=202)
async def create_report(req: ReportCreateRequest, current_user: dict = Depends(get_current_user)):
    """触发商品口碑分析（异步）；同商品已有 processing 报告时幂等复用。"""
    async with AsyncSessionLocal() as db:
        prod = (await db.execute(text(
            "SELECT id FROM products WHERE id=:pid AND is_active"
        ), {"pid": req.product_id})).first()
        if prod is None:
            raise HTTPException(status_code=404, detail="product not found")
        existing = (await db.execute(text(
            "SELECT id FROM review_reports WHERE product_id=:pid AND status='processing'"
        ), {"pid": req.product_id})).first()
        if existing:
            return {"report_id": str(existing[0]), "status": "processing"}
        report_id = str(uuid.uuid4())
        await db.execute(text(
            "INSERT INTO review_reports (id, tenant_id, product_id, triggered_by, status) "
            "VALUES (:rid, :tid, :pid, :uid, 'processing')"
        ), {"rid": report_id, "tid": current_user["tenant_id"],
            "pid": req.product_id, "uid": current_user["user_id"]})
        await db.commit()

    task = asyncio.create_task(_graph.ainvoke({
        "messages": [],
        "tenant_id": current_user["tenant_id"],
        "product_id": req.product_id,
        "report_id": report_id,
        "triggered_by": current_user["user_id"],
        "product_title": "", "product_category": None, "reviews": [],
        "dimension_scores": [], "weighted_score": 0.0,
        "pros": [], "cons": [], "summary": None, "fallback_used": False,
    }))
    _track(task, report_id)
    logger.info("review.report_created", report_id=report_id)
    return {"report_id": report_id, "status": "processing"}


def _row_to_dict(row, title: str | None) -> dict:
    scores = row[2]
    if isinstance(scores, str):
        scores = json.loads(scores or "{}")
    scores = scores or {}
    pros, cons = row[3], row[4]
    if isinstance(pros, str):
        pros = json.loads(pros or "[]")
    if isinstance(cons, str):
        cons = json.loads(cons or "[]")
    return {
        "report_id": row[0], "product_id": row[1], "product_title": title,
        "status": row[5],
        "weighted_score": scores.get("weighted_score"),
        "dimensions": scores.get("dimensions", []),
        "pros": pros or [], "cons": cons or [],
        "summary": row[6], "error_msg": row[7],
    }


@router.get("/reports/latest")
async def get_latest_report(product_id: str, current_user: dict = Depends(get_current_user)):
    """某商品最新一份报告；无记录 404。（必须先于 /reports/{report_id} 注册）"""
    async with AsyncSessionLocal() as db:
        rid = (await db.execute(text(
            "SELECT id FROM review_reports WHERE product_id = :pid "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"pid": product_id})).scalar()
    if not rid:
        raise HTTPException(status_code=404, detail="no report")
    return await get_report(str(rid), current_user)


@router.get("/reports/{report_id}")
async def get_report(report_id: str, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT r.id, r.product_id, r.scores, r.pros, r.cons, r.status, "
            "r.summary, r.error_msg, p.title "
            "FROM review_reports r JOIN products p ON p.id = r.product_id "
            "WHERE r.id = :rid"
        ), {"rid": report_id})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="report not found")
        # 15min 超时兜底（平移自 resume.py）
        if row[5] == "processing":
            age = (await db.execute(text(
                "SELECT EXTRACT(EPOCH FROM (NOW() - created_at))/60 "
                "FROM review_reports WHERE id = :rid"
            ), {"rid": report_id})).scalar() or 0
            if age > _TIMEOUT_MINUTES:
                await db.execute(text(
                    "UPDATE review_reports SET status='failed', "
                    "error_msg='analysis timeout', updated_at=NOW() WHERE id=:rid"
                ), {"rid": report_id})
                await db.commit()
                row = (row[0], row[1], row[2], row[3], row[4], "failed",
                       row[6], "analysis timeout", row[8])
    return _row_to_dict(row, row[8])
