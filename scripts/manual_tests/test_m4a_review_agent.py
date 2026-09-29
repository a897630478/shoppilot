# scripts/manual_tests/test_m4a_review_agent.py
# 直接跑评价分析图（真实 LLM 8 次调用，约 1~3 分钟；需 PG）
import asyncio
import uuid

from sqlalchemy import text

from backend.agents.review.graph import build_review_graph
from backend.dependencies import AsyncSessionLocal


def test_review_graph_end_to_end():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT p.id FROM products p "
            "JOIN product_reviews r ON r.product_id = p.id "
            "WHERE p.is_active GROUP BY p.id ORDER BY count(r.id) DESC LIMIT 1"
        ))).first()
        assert row, "no active product with reviews"
        product_id = str(row[0])
        rid = str(uuid.uuid4())
        # 造一行 processing 报告（API 层正式实现前的测试脚手架）
        await db.execute(text(
            "INSERT INTO review_reports (id, tenant_id, product_id, status) "
            "VALUES (:rid, 'tenant_default', :pid, 'processing')"
        ), {"rid": rid, "pid": product_id})
        await db.commit()

    graph = build_review_graph()
    await graph.ainvoke({
        "messages": [],
        "tenant_id": "tenant_default",
        "product_id": product_id,
        "report_id": rid,
        "triggered_by": None,
        "product_title": "", "product_category": None, "reviews": [],
        "dimension_scores": [], "weighted_score": 0.0,
        "pros": [], "cons": [], "summary": None, "fallback_used": False,
    })

    async with AsyncSessionLocal() as db:
        rep = (await db.execute(text(
            "SELECT status, scores, pros, cons, summary FROM review_reports WHERE id = :rid"
        ), {"rid": rid})).first()
    assert rep and rep[0] == "done", rep
    scores = rep[1]
    if isinstance(scores, str):
        import json
        scores = json.loads(scores)
    assert isinstance(scores, dict) and len(scores.get("dimensions", [])) == 6
    assert 0 < scores["weighted_score"] <= 100
    assert isinstance(rep[2], list) and isinstance(rep[3], list)
    assert rep[4] and len(rep[4]) >= 30
