# scripts/manual_tests/test_seed_reviews.py
# 需要：PG 已有商品（跑过 run_crawl）、.env.local 有 DEEPSEEK_API_KEY
import asyncio

import pytest
from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.seed_product_reviews import seed_reviews_for_all


@pytest.mark.asyncio
async def test_seed_creates_reviews():
    await seed_reviews_for_all(per_product=3, limit=1)
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            text("""
                SELECT count(*) FROM product_reviews r
                JOIN products p ON p.id = r.product_id
                WHERE r.source = 'generated'
            """)
        )
        assert res.fetchone()[0] >= 3
