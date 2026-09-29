# scripts/manual_tests/test_enrich_off.py
# 需要：PG 有 OFF 商品（Task 2）、DEEPSEEK_API_KEY 可用；真实 LLM 调用 1 次
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.enrich_off_products import enrich


def test_enrich_one_product():
    asyncio.run(_run())


async def _run():
    n = await enrich(limit=1)
    assert n >= 1
    async with AsyncSessionLocal() as s:
        row = (await s.execute(text(
            "SELECT price, description FROM products "
            "WHERE source='openfoodfacts' AND price IS NOT NULL LIMIT 1"
        ))).fetchone()
        assert row is not None, "no enriched product"
        assert row[0] is not None and 3.0 <= float(row[0]) <= 199.0
        assert row[1] and len(row[1]) >= 20
