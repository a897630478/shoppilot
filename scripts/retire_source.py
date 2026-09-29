# scripts/retire_source.py
# 用法：python -m scripts.retire_source --source books_toscrape
# 软下架指定来源商品（is_active=FALSE），不删除行（订单/评价 FK 不受影响）。幂等。
import argparse
import asyncio

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)


async def retire_source(source: str) -> int:
    async with AsyncSessionLocal() as s:
        res = await s.execute(
            text("UPDATE products SET is_active = FALSE, updated_at = NOW() "
                 "WHERE source = :src AND is_active"),
            {"src": source},
        )
        await s.commit()
        n = res.rowcount or 0
    logger.info("retire.done", source=source, count=n)
    return n


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    args = parser.parse_args()
    print(f"✅ 下架 {asyncio.run(retire_source(args.source))} 个商品")


if __name__ == "__main__":
    main()
