# scripts/manual_tests/test_crawl_ingest.py
# 运行前置：PG + MinIO 已启动，且已跑过 Task 1 迁移
# 运行：python -m pytest scripts/manual_tests/test_crawl_ingest.py -v -s
import asyncio

import pytest
from sqlalchemy import text

from backend.db.migrations import run_migrations
from backend.dependencies import AsyncSessionLocal
from scripts.crawl.adapters.books_toscrape import BooksToscrapeAdapter
from scripts.crawl.run_crawl import ingest_products


@pytest.mark.asyncio
async def test_ingest_two_products():
    await run_migrations()
    adapter = BooksToscrapeAdapter()
    await ingest_products(adapter, limit=2, skip_images=False)
    async with AsyncSessionLocal() as session:
        res = await session.execute(
            text("SELECT count(*) FROM products WHERE source = 'books_toscrape'")
        )
        count = res.fetchone()[0]
        assert count >= 1
        res = await session.execute(
            text("SELECT image_object FROM products WHERE source='books_toscrape' LIMIT 1")
        )
        obj = res.fetchone()[0]
        assert obj and obj.startswith("products/")
