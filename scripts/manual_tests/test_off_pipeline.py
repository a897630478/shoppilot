# scripts/manual_tests/test_off_pipeline.py
# M1b 收官断言：中文商品/价格/评价/rating/英文下架 全链路
# 需要：Task 1~4 步骤全部跑完后执行（不依赖后端进程）
import asyncio

from sqlalchemy import text

from backend.dependencies import AsyncSessionLocal, engine


def test_off_pipeline_ready():
    asyncio.run(_run())


async def _run():
    # 先前的异步测试可能在已关闭的事件循环上缓存了连接（Windows Proactor）——清池重建
    await engine.dispose()
    async with AsyncSessionLocal() as s:
        # 1. active 商品全部是中文 OFF 商品
        active = (await s.execute(text(
            "SELECT source, count(id) FROM products WHERE is_active GROUP BY source"
        ))).fetchall()
        sources = {r[0]: r[1] for r in active}
        assert sources.get("books_toscrape", 0) == 0, "books must be retired"
        assert sources.get("openfoodfacts", 0) >= 80, sources

        # 2. 价格与文案覆盖率 ≥95%
        total = sources["openfoodfacts"]
        priced = (await s.execute(text(
            "SELECT count(id) FROM products WHERE source='openfoodfacts' AND is_active "
            "AND price IS NOT NULL AND description IS NOT NULL"
        ))).scalar()
        assert priced / total >= 0.95, f"enrich coverage {priced}/{total}"

        # 3. 每个 active 商品 rating 已回填
        weak = (await s.execute(text(
            "SELECT count(id) FROM products WHERE is_active AND rating IS NULL"
        ))).scalar()
        assert weak == 0, f"{weak} products missing rating"

        # 4. 每个 active 商品评价 ≥30（真实数据集 source='dataset'）
        short = (await s.execute(text(
            "SELECT count(id) FROM (SELECT p.id FROM products p "
            "LEFT JOIN product_reviews r ON r.product_id = p.id "
            "WHERE p.is_active GROUP BY p.id HAVING count(r.id) < 30) t"
        ))).scalar()
        assert short == 0, f"{short} products with <30 reviews"

        # 5. 评价内容为中文
        sample = (await s.execute(text(
            "SELECT r.content FROM product_reviews r JOIN products p ON p.id=r.product_id "
            "WHERE p.source='openfoodfacts' ORDER BY r.created_at DESC LIMIT 1"
        ))).scalar()
        assert sample and any('一' <= ch <= '鿿' for ch in sample)
