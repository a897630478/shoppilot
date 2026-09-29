# scripts/backfill_product_rating.py
# 用法：python -m scripts.backfill_product_rating
# 用 generated 评价均分回填 active 商品的 rating（1~5 整数）。幂等可重复跑。
import asyncio

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)


async def backfill_rating() -> int:
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            UPDATE products p SET rating = sub.avg_rating, updated_at = NOW()
            FROM (
                SELECT product_id, ROUND(AVG(rating))::int AS avg_rating
                FROM product_reviews WHERE source = 'generated'
                GROUP BY product_id
            ) sub
            WHERE p.id = sub.product_id AND p.is_active
              AND (p.rating IS NULL OR p.rating <> sub.avg_rating)
        """))
        await db.commit()
        n = res.rowcount or 0
    logger.info("rating.backfilled", count=n)
    return n


def main():
    print(f"✅ 回填 {asyncio.run(backfill_rating())} 个商品 rating")


if __name__ == "__main__":
    main()
