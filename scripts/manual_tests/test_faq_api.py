# scripts/manual_tests/test_faq_api.py
# FAQ 补录闭环：造 pending 行 → 运营补录 → 向量库可检索 → 队列 resolved（需后端+Milvus）
import time
import uuid

import httpx

BASE = "http://localhost:8000"


def _login(username: str, password: str) -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def test_faq_resolve_and_searchable():
    teacher = _login("teacher01@shoppilot.local", "Teacher@123456")

    # 1) 直接造一条 pending（低置信度入队的等价数据）
    import asyncio
    from sqlalchemy import text
    from backend.dependencies import AsyncSessionLocal

    question = f"你们家的矿泉水保质期是多久？（测试 {uuid.uuid4().hex[:6]}）"
    queue_id = str(uuid.uuid4())

    async def _seed():
        from backend.dependencies import engine
        await engine.dispose()  # 清掉前序异步测试留在池里的旧事件循环连接
        async with AsyncSessionLocal() as db:
            await db.execute(text(
                "INSERT INTO knowledge_pending_queue "
                "(id, tenant_id, question, confidence, status) "
                "VALUES (:id, 'tenant_default', :q, 0.42, 'pending')"
            ), {"id": queue_id, "q": question})
            await db.commit()
    asyncio.run(_seed())

    # 2) 队列可见
    lst = httpx.get(f"{BASE}/api/v1/faq/pending", headers=teacher, timeout=30)
    assert lst.status_code == 200, lst.text
    assert any(x["id"] == queue_id for x in lst.json()["items"]), "not in pending list"

    # 3) 学员无权
    student = _login("student01@shoppilot.local", "Student@123456")
    forbidden = httpx.get(f"{BASE}/api/v1/faq/pending", headers=student, timeout=30)
    assert forbidden.status_code == 403

    # 4) 补录答案
    answer = "我们售卖的瓶装水保质期通常为 12 个月，具体以瓶身标注为准，请在商品详情页查看规格。"
    rv = httpx.post(f"{BASE}/api/v1/faq/{queue_id}/resolve",
                    json={"answer": answer}, headers=teacher, timeout=60)
    assert rv.status_code == 200, rv.text
    assert rv.json()["status"] == "resolved"

    # 5) 向量库可检索到 FAQ 正文（唯一短语）
    from backend.core.reranker import retrieve
    docs, _ = retrieve("瓶装水保质期多久", tenant_id="tenant_default",
                       recall_top_k=8, rerank_top_k=5)
    joined = "".join(d.content for d in docs)
    assert "12 个月" in joined or "保质期" in joined, f"FAQ not retrievable: {joined[:200]}"

    # 6) 重复补录 → 409
    again = httpx.post(f"{BASE}/api/v1/faq/{queue_id}/resolve",
                       json={"answer": answer}, headers=teacher, timeout=30)
    assert again.status_code == 409
