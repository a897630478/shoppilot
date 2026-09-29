# scripts/seed_product_reviews.py
# 用法：python -m scripts.seed_product_reviews --per-product 30 --limit 10
# 为商品生成模拟评价（source='generated'），供 M4 评价分析 Agent 使用。
# 注意：生成的评价是演示数据，价格/参数类信息若出现在评价中以库内为准。
import argparse
import asyncio
import json
import re

from sqlalchemy import text

from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

_PROMPT = """你是电商平台的真实买家。请为下面这件商品写 {n} 条中文买家评价。
商品：{title}
类目：{category}
简介：{desc}

要求：
1. 每条 30~80 字，口吻各异（满意/中性/不满都要有，比例约 6:3:1）
2. rating 字段 1~5 星，与口吻一致
3. author 用化名
4. 只输出 JSON 数组，格式：[{{"author":"...","rating":4,"content":"..."}}]
5. 不要编造具体价格数字与规格参数，只谈主观体验
"""


async def _gen_reviews(llm, product: dict) -> list[dict]:
    prompt = _PROMPT.format(
        n=product["n"],
        title=product["title"],
        category=product.get("category") or "通用",
        desc=(product.get("description") or "")[:300],
    )
    resp = await llm.ainvoke(prompt)
    text_out = resp.content if hasattr(resp, "content") else str(resp)
    match = re.search(r"\[.*\]", text_out, re.S)
    if not match:
        raise ValueError(f"no JSON array in LLM reply: {text_out[:200]}")
    items = json.loads(match.group(0))
    return [
        {
            "author": str(it.get("author") or "匿名"),
            "rating": max(1, min(5, int(it.get("rating") or 5))),
            "content": str(it.get("content") or ""),
        }
        for it in items
        if it.get("content")
    ]


async def seed_reviews_for_all(per_product: int = 30, limit: int | None = None) -> int:
    llm = LLMFactory.get_llm("summarize")
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("""
            SELECT p.id, p.title, p.category, p.description,
                   (SELECT count(*) FROM product_reviews r
                    WHERE r.product_id = p.id AND r.source='generated') AS existing
            FROM products p
            WHERE p.is_active = TRUE
            ORDER BY p.created_at
        """))
        rows = res.fetchall()
        total = 0
        for row in rows:
            product = {
                "id": row[0], "title": row[1], "category": row[2],
                "description": row[3], "existing": row[4],
                "n": per_product - int(row[4]),
            }
            if limit is not None and total >= limit:
                break
            if product["n"] <= 0:
                logger.info("seed.skip", title=product["title"], reason="enough reviews")
                continue
            try:
                items = await _gen_reviews(llm, product)
            except Exception as e:
                logger.warning("seed.llm_failed", title=product["title"], error=str(e))
                continue
            for it in items:
                await db.execute(
                    text("""
                        INSERT INTO product_reviews (product_id, author, rating, content, source)
                        VALUES (:pid, :author, :rating, :content, 'generated')
                    """),
                    {"pid": product["id"], "author": it["author"],
                     "rating": it["rating"], "content": it["content"]},
                )
            await db.commit()
            total += 1
            logger.info("seed.done", title=product["title"], added=len(items))
        return total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-product", type=int, default=30)
    parser.add_argument("--limit", type=int, default=None, help="最多处理几个商品")
    args = parser.parse_args()
    n = asyncio.run(seed_reviews_for_all(args.per_product, args.limit))
    print(f"✅ 完成：{n} 个商品生成评价")


if __name__ == "__main__":
    main()
