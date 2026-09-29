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
        # 找一个 paid/shipped/completed 且金额 >100 的订单；没有就造一个
        row = (await db.execute(text(
            "SELECT id, user_id FROM orders "
            "WHERE status IN ('paid','shipped','completed') AND total_amount > 100 "
            "LIMIT 1"
        ))).first()
        if row:
            order_id, user_id = str(row[0]), str(row[1])
        else:
            prod = (await db.execute(text(
                "SELECT id, price FROM products WHERE is_active LIMIT 1"))).fetchone()
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
