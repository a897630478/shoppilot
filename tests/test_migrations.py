# tests/test_migrations.py
# 需要本地 PG 已启动（docker-compose postgres healthy）
import asyncio

import pytest
from sqlalchemy import text

from backend.db.migrations import run_migrations
from backend.dependencies import AsyncSessionLocal

EXPECTED_TABLES = [
    "products", "product_reviews", "orders", "service_tickets",
    "review_reports", "recommendation_sessions", "recommendation_results",
]


@pytest.mark.asyncio
async def test_ecommerce_tables_exist():
    await run_migrations()
    async with AsyncSessionLocal() as session:
        for table in EXPECTED_TABLES:
            res = await session.execute(
                text(
                    "SELECT to_regclass(:t) IS NOT NULL AS exists"
                ),
                {"t": table},
            )
            row = res.fetchone()
            assert row[0] is True, f"missing table: {table}"
