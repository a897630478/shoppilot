# backend/api/v1/guide.py
# 多轮导购 API（M5a：由 /interview 平移）——创建会话 / SSE 对话 / 报告 / 列表
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from langchain_core.messages import HumanMessage
from sqlalchemy import text

from backend.agents.guide.graph import build_guide_graph
from backend.core.memory import build_thread_id
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)

_graph = build_guide_graph()          # 模块级编译一次


class SessionCreateRequest(BaseModel):
    message: str = Field("", max_length=500, description="开场需求（可空）")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


def _sse(data: dict) -> dict:
    return {"data": json.dumps(data, ensure_ascii=False)}


def _initial_state(user: dict, session_id: str, message: str) -> dict:
    return {
        "user_id": user["user_id"],
        "tenant_id": user["tenant_id"],
        "session_id": session_id,
        "initial_message": message,
        "current_stage": "needs_discovery",
        "stage_turn_count": 0,
        "total_turn_count": 0,
        "max_turns": 16,
        "needs": "", "budget": None, "preferences": [],
        "candidates": [], "existing_summary": None,
        "report": None, "fallback_used": False, "structured_output": None,
    }


@router.post("/sessions", status_code=201)
async def create_session(req: SessionCreateRequest, current_user: dict = Depends(get_current_user)):
    """创建导购会话并同步跑首轮（返回开场白）。"""
    session_id = f"gd-{uuid.uuid4().hex[:12]}"
    thread_id = build_thread_id(current_user["user_id"], session_id)
    opening = req.message.strip() or "你好，我想挑选商品"

    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO recommendation_sessions "
            "(id, tenant_id, user_id, session_id, thread_id, stage, status) "
            "VALUES (:id, :tenant, :uid, :sid, :tid, 'needs_discovery', 'in_progress')"
        ), {"id": str(uuid.uuid4()), "tenant": current_user["tenant_id"],
            "uid": current_user["user_id"], "sid": session_id, "tid": thread_id})
        await db.commit()

    state = _initial_state(current_user, session_id, opening)
    config = {"configurable": {"thread_id": thread_id}}
    result = await _graph.ainvoke(
        {**state, "messages": [HumanMessage(content=opening)]}, config=config)

    # 取最后一条 AI 回复作为开场白
    opening_message = ""
    for msg in reversed(result.get("messages", [])):
        if not isinstance(msg, HumanMessage):
            content = msg.content
            opening_message = content if isinstance(content, str) else str(content)
            break
    logger.info("guide.session_created", session_id=session_id)
    return {"session_id": session_id, "opening_message": opening_message,
            "stage": result.get("current_stage", "needs_discovery")}


@router.get("/sessions")
async def list_sessions(current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text(
            "SELECT session_id, stage, status, created_at, finished_at "
            "FROM recommendation_sessions WHERE user_id = :uid "
            "ORDER BY created_at DESC LIMIT 50"
        ), {"uid": current_user["user_id"]})).fetchall()
    return {"total": len(rows), "items": [{
        "session_id": r[0], "stage": r[1], "status": r[2],
        "created_at": r[3].isoformat() if r[3] else None,
        "finished_at": r[4].isoformat() if r[4] else None,
    } for r in rows]}


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str, current_user: dict = Depends(get_current_user)):
    """推荐报告（含商品标题/价格 join）。"""
    async with AsyncSessionLocal() as db:
        sess = (await db.execute(text(
            "SELECT id, status, result, summary FROM recommendation_sessions "
            "WHERE session_id = :sid AND user_id = :uid"
        ), {"sid": session_id, "uid": current_user["user_id"]})).first()
        if sess is None:
            raise HTTPException(status_code=404, detail="session not found")
        result = sess[2]
        if isinstance(result, str):
            result = json.loads(result or "{}")
        result = result or {}
        recs = result.get("recommendations") or []
        enriched = []
        for rec in recs:
            p = (await db.execute(text(
                "SELECT title, price FROM products WHERE id = :pid"
            ), {"pid": rec.get("product_id")})).first()
            enriched.append({
                "product_id": rec.get("product_id"),
                "title": p[0] if p else "（商品已下架）",
                "price": str(p[1]) if p else None,
                "reason": rec.get("reason", ""),
            })
    return {"session_id": session_id, "status": sess[1],
            "summary": sess[3], "recommendations": enriched}


@router.post("/sessions/{session_id}/chat/stream")
async def chat_stream(session_id: str, req: ChatRequest, current_user: dict = Depends(get_current_user)):
    """SSE 流式对话（token / done / error 三事件，平移自 interview）。"""
    thread_id = build_thread_id(current_user["user_id"], session_id)
    async with AsyncSessionLocal() as db:
        exists = (await db.execute(text(
            "SELECT status FROM recommendation_sessions "
            "WHERE session_id = :sid AND user_id = :uid"
        ), {"sid": session_id, "uid": current_user["user_id"]})).first()
    if exists is None:
        raise HTTPException(status_code=404, detail="session not found")
    if exists[0] == "finished":
        raise HTTPException(status_code=409, detail="session already finished")

    config = {"configurable": {"thread_id": thread_id}}
    user_msg = req.message

    async def event_generator():
        state_update = {"messages": [HumanMessage(content=user_msg)]}
        try:
            async for event in _graph.astream_events(state_update, config, version="v2"):
                evt = event["event"]
                node = event.get("metadata", {}).get("langgraph_node", "")
                if evt == "on_chat_model_stream" and node == "generate_response":
                    chunk = event["data"].get("chunk")
                    if chunk and chunk.content:
                        content = chunk.content
                        if not isinstance(content, str):
                            content = str(content)
                        yield _sse({"type": "token", "content": content})
                elif evt == "on_chat_model_stream" and node == "generate_report":
                    pass  # 报告不流式

            snapshot = await _graph.aget_state(config)
            values = snapshot.values if snapshot else {}
            report = values.get("report")
            done = {
                "type": "done",
                "current_stage": values.get("current_stage"),
                "total_turns": values.get("total_turn_count"),
                "is_finished": values.get("current_stage") == "finished",
            }
            if report:
                done["report"] = report
            yield _sse(done)
        except Exception as e:
            logger.error("guide.stream_error", error=str(e), exc_info=True)
            yield _sse({"type": "error", "message": "导购服务异常，请稍后重试"})

    return EventSourceResponse(event_generator())
