# scripts/enrich_off_products.py
# 用法：python -m scripts.enrich_off_products [--limit N]
# 为 OFF 商品生成演示价格（CNY）与中文详情文案；只处理 price IS NULL 的行，幂等。
import argparse
import asyncio
import json
import re

from sqlalchemy import text

from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

_PROMPT = """你是电商平台的商品编辑。为下面这件真实商品生成演示用售价与详情文案。
商品：{title}
品牌/规格/配料/营养：{params}
类目：{category}

只输出 JSON，格式：{{"price": 数字, "description": "60~120字中文详情文案"}}
要求：
1. price 为人民币演示价，按类目常识在 3.0~199.0 之间（饮料零食取低端，礼盒/粮油取中高端），保留两位小数
2. description 口吻为电商详情页，客观介绍卖点，不编造功效/认证
3. 不要输出 JSON 以外的任何内容
"""


def _clamp(price: float) -> float:
    return round(max(3.0, min(199.0, price)), 2)


async def enrich(limit: int | None = None) -> int:
    llm = LLMFactory.get_llm("summarize")
    async with AsyncSessionLocal() as db:
        sql = """
            SELECT id, title, category, params FROM products
            WHERE source = 'openfoodfacts' AND is_active AND price IS NULL
            ORDER BY created_at
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = (await db.execute(text(sql))).mappings().all()

        done = 0
        for row in rows:
            prompt = _PROMPT.format(
                title=row["title"],
                params=json.dumps(row["params"] or {}, ensure_ascii=False, default=str)[:800],
                category=row["category"] or "日用百货",
            )
            try:
                resp = await llm.ainvoke(prompt)
                raw = resp.content if hasattr(resp, "content") else str(resp)
                match = re.search(r"\{.*\}", raw, re.S)
                if not match:
                    raise ValueError(f"no JSON object: {raw[:150]}")
                data = json.loads(match.group(0))
                price = _clamp(float(data["price"]))
                desc = str(data["description"]).strip()
                if len(desc) < 10:
                    raise ValueError("description too short")
            except Exception as e:
                logger.warning("enrich.failed", title=row["title"], error=str(e))
                continue
            await db.execute(
                text("UPDATE products SET price = :p, description = :d, updated_at = NOW() "
                     "WHERE id = :id"),
                {"p": price, "d": desc, "id": row["id"]},
            )
            await db.commit()
            done += 1
            logger.info("enrich.done", title=row["title"][:30], price=price, n=done)
        return done


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    print(f"✅ 完成：{asyncio.run(enrich(args.limit))} 个商品补全价格与文案")


if __name__ == "__main__":
    main()
