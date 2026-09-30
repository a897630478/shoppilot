# scripts/import_shopping_reviews.py
# 用法：python -m scripts.import_shopping_reviews [--per-product 30]
# 数据源：data/online_shopping_10_cats.csv（真实中文购物评论，cat/label/review）
# 行为：清空现有评价（含 AI 生成的）→ 按类目规则为每个 active 商品灌真实评论
#       label 1→4/5星、0→1/2星；source='dataset'；结束后回填 rating
import argparse
import asyncio
import csv
import random
import uuid
from collections import defaultdict

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

CSV_PATH = "data/online_shopping_10_cats.csv"

# 数据集类目 → 商品匹配规则（title/category 关键词）；未命中走全库均衡池
CAT_RULES = {
    "蒙牛": ["蒙牛"],
    "水果": ["果", "汁", "水果", "零食", "饼干", "薯片"],
}


def load_dataset() -> dict[str, list[dict]]:
    pools: dict[str, list[dict]] = defaultdict(list)
    with open(CSV_PATH, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            cat = (row.get("cat") or "").strip()
            review = (row.get("review") or "").strip()
            label = (row.get("label") or "").strip()
            if not cat or not review:
                continue
            pools[cat].append({"label": label, "review": review, "cat": cat})
    return pools


def stars_for(label: str) -> int:
    """情感标签 → 星级（1 正 4/5★，0 负 1/2★，随机）"""
    return random.choice([4, 5]) if label == "1" else random.choice([1, 2])


def pick_pool(product: dict, pools: dict[str, list[dict]], fallback: list[dict]) -> list[dict]:
    title = (product.get("title") or "") + (product.get("category") or "")
    for cat, kws in CAT_RULES.items():
        if any(k in title for k in kws) and pools.get(cat):
            return pools[cat]
    return fallback


async def import_reviews(per_product: int = 30) -> int:
    pools = load_dataset()
    logger.info("dataset.loaded", cats={k: len(v) for k, v in pools.items()})
    fallback = [r for cat, rows in pools.items() if cat != "酒店" for r in rows]  # 酒店与商品语境差最远

    async with AsyncSessionLocal() as db:
        # 1) 清空旧评价（全是 AI 生成的演示数据）
        await db.execute(text("DELETE FROM product_reviews"))
        await db.commit()

        products = (await db.execute(text(
            "SELECT id, title, category FROM products WHERE is_active ORDER BY created_at"
        ))).fetchall()
        total = 0
        for p in products:
            pool = pick_pool({"title": p[1], "category": p[2]}, pools, fallback)
            if not pool:
                continue
            samples = random.sample(pool, k=min(per_product, len(pool)))
            for s in samples:
                await db.execute(text(
                    "INSERT INTO product_reviews (id, product_id, author, rating, content, source) "
                    "VALUES (:id, :pid, :author, :rating, :content, 'dataset')"
                ), {
                    "id": str(uuid.uuid4()), "pid": p[0],
                    "author": f"用户{random.randint(10000, 99999)}",
                    "rating": stars_for(s["label"]),
                    "content": s["review"][:500],
                })
                total += 1
            await db.commit()
            logger.info("import.product_done", title=p[1][:24], n=per_product)

        # 2) 回填星级
        res = await db.execute(text("""
            UPDATE products p SET rating = sub.avg_rating, updated_at = NOW()
            FROM (
                SELECT product_id, ROUND(AVG(rating))::int AS avg_rating
                FROM product_reviews WHERE source = 'dataset'
                GROUP BY product_id
            ) sub
            WHERE p.id = sub.product_id AND p.is_active
        """))
        await db.commit()
        logger.info("import.done", reviews=total, rating_backfilled=res.rowcount)
    return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-product", type=int, default=30)
    args = parser.parse_args()
    n = asyncio.run(import_reviews(args.per_product))
    print(f"✅ 已导入真实购物评论 {n} 条（source=dataset）")


if __name__ == "__main__":
    main()
