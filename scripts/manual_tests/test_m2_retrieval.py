# scripts/manual_tests/test_m2_retrieval.py
# 断言 QA 检索链路已切到 product_knowledge（需 Milvus 运行 + 已建商品索引）
import asyncio


def test_retrieval_targets_product_knowledge():
    asyncio.run(_run())


async def _run():
    from backend.core.knowledge_base import COLLECTION_NAME
    from backend.core.reranker import retrieve
    from backend.dependencies import engine

    # 先前的异步测试可能在已关闭的事件循环上缓存了连接（Windows Proactor）——清池重建
    await engine.dispose()

    # 1. 集合常量已切换
    assert COLLECTION_NAME == "product_knowledge", COLLECTION_NAME

    # 2. 全库检索返回商品 chunk（中文查询「矿泉水」应命中饮用水类商品）
    # 注意：retrieve 是同步函数（nodes 里经 run_in_executor 调用）
    docs, score = retrieve("矿泉水", tenant_id="tenant_default",
                           recall_top_k=10, rerank_top_k=3)
    assert docs, "no docs retrieved from product_knowledge"
    for d in docs:
        meta = getattr(d, "metadata", {}) or {}
        assert "product_id" in meta or d.content, "chunk must carry content"
    # 命中内容应含中文（商品文案）
    joined = "".join(d.content for d in docs)
    assert any('一' <= ch <= '鿿' for ch in joined), "expected Chinese product content"

    # 3. product_id 过滤：取一个真实 product_id，限定后结果全部属于它
    from sqlalchemy import text
    from backend.dependencies import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        pid = (await s.execute(text(
            "SELECT id FROM products WHERE is_active LIMIT 1"))).scalar()
    docs2, _ = retrieve("牛奶", tenant_id="tenant_default",
                        product_id=str(pid), recall_top_k=10, rerank_top_k=3)
    for d in docs2:
        meta = getattr(d, "metadata", {}) or {}
        if "product_id" in meta:
            assert str(meta["product_id"]) == str(pid)
