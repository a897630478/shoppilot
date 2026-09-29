# scripts/manual_tests/test_product_knowledge.py
# 需要：PG 有商品、Milvus product_knowledge 已建、本地 bge-m3 权重可用
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.build_product_knowledge import build_for_products


def test_build_and_query():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT id FROM products WHERE is_active LIMIT 1"))
        row = res.fetchone()
        assert row, "no product in PG — run crawl first"
        product_id = str(row[0])

    n = await build_for_products(limit=1)
    assert n >= 1

    # 标量过滤 query 而非向量 search：只验证「写入成功」，不依赖嵌入质量
    from backend.config import get_settings
    from pymilvus import MilvusClient
    client = MilvusClient(uri=f"http://{get_settings().milvus_host}:{get_settings().milvus_port}")
    res = client.query(
        collection_name="product_knowledge",
        filter=f'product_id == "{product_id}"',
        output_fields=["chunk_index", "content"],
        limit=5,
    )
    assert len(res) >= 1
