# scripts/manual_tests/test_m5a_guide_agent.py
# 导购图端到端：3 轮对话 + 强制结束 → 推荐报告与 results 落库（真实 LLM 约 6~9 次）
import asyncio
import uuid

from langchain_core.messages import HumanMessage
from sqlalchemy import text

from backend.agents.guide.graph import build_guide_graph
from backend.core.memory import build_thread_id
from backend.dependencies import AsyncSessionLocal


def test_guide_graph_end_to_end():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as db:
        uid = str((await db.execute(text("SELECT id FROM users LIMIT 1"))).scalar())
    session_id = f"m5a-{uuid.uuid4().hex[:8]}"
    thread_id = build_thread_id(uid, session_id)
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "INSERT INTO recommendation_sessions "
            "(id, tenant_id, user_id, session_id, thread_id, stage, status) "
            "VALUES (:id, 'tenant_default', :uid, :sid, :tid, 'needs_discovery', 'in_progress')"
        ), {"id": str(uuid.uuid4()), "uid": uid, "sid": session_id, "tid": thread_id})
        await db.commit()

    graph = build_guide_graph()
    config = {"configurable": {"thread_id": thread_id}}
    initial_state = {
        "user_id": uid, "tenant_id": "tenant_default", "session_id": session_id,
        "initial_message": "想买瓶装水日常喝",
        "current_stage": "needs_discovery", "stage_turn_count": 0,
        "total_turn_count": 0, "max_turns": 16,
        "needs": "", "budget": None, "preferences": [],
        "candidates": [], "existing_summary": None,
        "report": None, "fallback_used": False, "structured_output": None,
    }

    # 轮1：开场
    await graph.ainvoke(
        {**initial_state, "messages": [HumanMessage(content="想买瓶装水日常喝")]},
        config=config)
    # 轮2：给预算（推进 budget→matching）
    await graph.ainvoke(
        {"messages": [HumanMessage(content="预算 50 以内，喜欢矿泉水")]},
        config=config)
    # 轮3：强制结束 → 报告
    await graph.ainvoke(
        {"messages": [HumanMessage(content="直接推荐")]},
        config=config)

    async with AsyncSessionLocal() as db:
        sess = (await db.execute(text(
            "SELECT id, status, stage, result, summary FROM recommendation_sessions "
            "WHERE thread_id = :tid"
        ), {"tid": thread_id})).first()
        assert sess[1] == "finished", sess
        assert sess[2] == "finished", sess
        import json
        result = sess[3] if isinstance(sess[3], dict) else json.loads(sess[3] or "{}")
        recs = result.get("recommendations") or []
        assert recs, result
        rows = (await db.execute(text(
            "SELECT product_id, rank FROM recommendation_results "
            "WHERE session_id = :sid ORDER BY rank"
        ), {"sid": sess[0]})).fetchall()
        assert len(rows) == len(recs), (rows, recs)
        # 推荐商品必须存在且 active
        for pid, _rank in rows:
            ok = (await db.execute(text(
                "SELECT count(id) FROM products WHERE id = :pid AND is_active"
            ), {"pid": pid})).scalar()
            assert ok == 1, f"invalid product {pid}"
        assert sess[4] and len(sess[4]) >= 10, "summary missing"
