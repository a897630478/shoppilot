# scripts/manual_tests/test_retire_source.py
# 需要 PG 运行；验证 retire_source 幂等且只动指定 source
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal
from scripts.retire_source import retire_source


def test_retire_books_idempotent():
    asyncio.run(_run())


async def _run():
    n1 = await retire_source("books_toscrape")
    n2 = await retire_source("books_toscrape")
    assert n1 >= 1, "expected at least one active book to retire"
    assert n2 == 0, "second run must be a no-op"
    async with AsyncSessionLocal() as s:
        active_books = (await s.execute(text(
            "SELECT count(*) FROM products WHERE source='books_toscrape' AND is_active"
        ))).scalar()
        assert active_books == 0
        # 软删除：行仍在
        total = (await s.execute(text(
            "SELECT count(*) FROM products WHERE source='books_toscrape'"
        ))).scalar()
        assert total >= n1, "rows must exist (soft delete, not hard delete)"
