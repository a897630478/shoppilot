# scripts/manual_tests/test_ingest_off.py
# 需要：PG + MinIO 运行、网络可达 world.openfoodfacts.org（限速，3 个商品约 30s）
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.ingest_off import ingest_off


def test_ingest_three_chinese_products():
    asyncio.run(_run())


async def _run():
    n = await ingest_off(limit=3)
    assert n >= 3
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(
            "SELECT title, currency, image_object, price FROM products "
            "WHERE source='openfoodfacts' AND is_active LIMIT 5"
        ))).fetchall()
        assert len(rows) >= 3
        for title, currency, image_object, price in rows:
            assert any('一' <= ch <= '鿿' for ch in title), f"not Chinese: {title}"
            assert currency == "CNY"
            assert image_object and image_object.startswith("products/")
            assert price is None, "price must stay NULL until enrich (Task 3)"
