# backend/api/v1/faq.py
# FAQ 补录 API（收尾补全）：运营端查看低置信度问题队列 → 补录答案 → 答案入向量库
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.knowledge_base import BGEMEmbedder, COLLECTION_NAME
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)


class ResolveRequest(BaseModel):
    answer: str = Field(..., min_length=10, max_length=2000, description="标准答案，10~2000 字")


def _require_operator(current_user: dict) -> None:
    if current_user.get("role") not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="operator only")


@router.get("/pending")
async def list_pending(current_user: dict = Depends(get_current_user)):
    """低置信度问题队列（运营端）。"""
    _require_operator(current_user)
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT id, question, confidence, answer, created_at "
            "FROM knowledge_pending_queue WHERE status = 'pending' "
            "ORDER BY created_at DESC LIMIT 100"
        ))).fetchall()
    items = [{
        "id": str(r[0]),
        "question": r[1],
        "confidence": r[2],
        "answer": r[3],
        "created_at": r[4].isoformat() if r[4] else None,
    } for r in rows]
    return {"total": len(items), "items": items}


async def _upsert_faq_chunk(queue_id: str, tenant_id: str, question: str, answer: str) -> None:
    """把补录的 FAQ 写入 product_knowledge（同 id 先删后插，幂等）。"""
    from pymilvus import MilvusClient
    from backend.config import get_settings

    content = f"{question}\n答案：{answer}"
    loop = asyncio.get_running_loop()
    dense, sparse = await loop.run_in_executor(
        None, lambda: BGEMEmbedder.get_instance().encode([content]))
    chunk_id = f"faq_{queue_id}_0"
    client = MilvusClient(uri=f"http://{get_settings().milvus_host}:{get_settings().milvus_port}")
    try:
        client.load_collection(COLLECTION_NAME)
    except Exception:
        pass  # 已 load 时的告警可忽略
    try:
        client.delete(COLLECTION_NAME, filter=f'id == "{chunk_id}"')
    except Exception:
        pass
    client.insert(COLLECTION_NAME, data=[{
        "id": chunk_id,
        "embedding": dense[0],
        "sparse_embedding": sparse[0],
        "content": content[:4096],
        "tenant_id": tenant_id,
        "chunk_index": 0,
        "product_id": "",
        "source_name": f"FAQ · {question[:40]}",
        "updated_at": int(__import__("time").time()),
    }])
    logger.info("faq.chunk_upserted", chunk_id=chunk_id)


@router.post("/{queue_id}/resolve")
async def resolve_faq(queue_id: str, req: ResolveRequest,
                      current_user: dict = Depends(get_current_user)):
    """补录答案：先写向量库，再落库（向量失败则不改状态，可重试）。"""
    _require_operator(current_user)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT status, question, tenant_id FROM knowledge_pending_queue WHERE id = :qid"
        ), {"qid": queue_id})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="queue item not found")
        if row[0] != "pending":
            raise HTTPException(status_code=409, detail=f"item already {row[0]}")

        await _upsert_faq_chunk(queue_id, row[2], row[1], req.answer)

        await db.execute(text(
            "UPDATE knowledge_pending_queue SET answer = :a, status = 'resolved', "
            "resolved_by = :uid, resolved_at = NOW() WHERE id = :qid"
        ), {"a": req.answer, "uid": current_user["user_id"], "qid": queue_id})
        await db.commit()
    logger.info("faq.resolved", queue_id=queue_id, by=current_user["user_id"])
    return {"id": queue_id, "status": "resolved"}


@router.post("/{queue_id}/dismiss")
async def dismiss_faq(queue_id: str, current_user: dict = Depends(get_current_user)):
    """忽略该问题（不入库向量）。"""
    _require_operator(current_user)
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT status FROM knowledge_pending_queue WHERE id = :qid"
        ), {"qid": queue_id})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="queue item not found")
        if row[0] != "pending":
            raise HTTPException(status_code=409, detail=f"item already {row[0]}")
        await db.execute(text(
            "UPDATE knowledge_pending_queue SET status = 'dismissed', "
            "resolved_by = :uid, resolved_at = NOW() WHERE id = :qid"
        ), {"uid": current_user["user_id"], "qid": queue_id})
        await db.commit()
    logger.info("faq.dismissed", queue_id=queue_id)
    return {"id": queue_id, "status": "dismissed"}
