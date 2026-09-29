# scripts/cleanup_education.py
# 用法：python -m scripts.cleanup_education          # dry-run，只打印将执行的 SQL
#       python -m scripts.cleanup_education --yes    # 真正执行
# M5b 数据清理：删除教育业务表与英文书目商品数据（spec §3.1「旧表分批删除」的执行入口）。
# 保持 migrations.py 无破坏性——本脚本是显式、可审阅的一次性清理。
import argparse

from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

# FK 依赖顺序：子表在前（注意 interview_sessions.resume_review_id → resume_reviews）
EDU_TABLES_DROP_ORDER = [
    "exam_reviews",        # → exam_submissions / questions
    "exam_submissions",    # → exams / users
    "scoring_points",      # → questions
    "questions",           # → exams
    "exams",
    "interview_sessions",  # → resume_reviews（必须先删）
    "resume_reviews",
    "interview_questions",
]


def build_statements() -> list[str]:
    stmts: list[str] = []
    # 1) 英文书目：先删引用它们的订单（测试订单），再级联清评价，最后删商品行
    stmts.append(
        "DELETE FROM orders WHERE product_id IN "
        "(SELECT id FROM products WHERE source = 'books_toscrape')"
    )
    stmts.append(
        "DELETE FROM product_reviews WHERE product_id IN "
        "(SELECT id FROM products WHERE source = 'books_toscrape')"
    )
    stmts.append("DELETE FROM products WHERE source = 'books_toscrape'")
    # 2) 教育表 DROP（IF EXISTS：可能部分已不存在）
    for t in EDU_TABLES_DROP_ORDER:
        stmts.append(f"DROP TABLE IF EXISTS {t}")
    return stmts


async def dry_run() -> None:
    async with AsyncSessionLocal() as db:
        books = (await db.execute(text(
            "SELECT count(id) FROM products WHERE source = 'books_toscrape'"
        ))).scalar()
        orders = (await db.execute(text(
            "SELECT count(o.id) FROM orders o JOIN products p ON p.id = o.product_id "
            "WHERE p.source = 'books_toscrape'"
        ))).scalar()
        print(f"== DRY-RUN（不会执行）==")
        print(f"英文书目商品：{books} 行；引用它们的订单：{orders} 行")
        print(f"将删除的教育表（按序）：{', '.join(EDU_TABLES_DROP_ORDER)}")
        for s in build_statements():
            print(f"  SQL> {s}")
    print("确认无误后加 --yes 执行。")


async def execute() -> None:
    stmts = build_statements()
    async with AsyncSessionLocal() as db:
        for s in stmts:
            try:
                await db.execute(text(s))
                await db.commit()
                logger.info("cleanup.statement_ok", sql=s[:80])
            except Exception as e:
                await db.rollback()
                logger.warning("cleanup.statement_failed", sql=s[:80], error=str(e))
                raise
    # 验证
    async with AsyncSessionLocal() as db:
        left = (await db.execute(text(
            "SELECT count(id) FROM products WHERE source = 'books_toscrape'"
        ))).scalar()
        for t in EDU_TABLES_DROP_ORDER:
            exists = (await db.execute(text(
                "SELECT to_regclass(:t) IS NOT NULL"
            ), {"t": t})).scalar()
            assert not exists, f"table still exists: {t}"
        active = (await db.execute(text(
            "SELECT count(id) FROM products WHERE is_active"
        ))).scalar()
    print(f"✅ 完成：英文书目残留 {left}（应为 0），active 商品 {active}（应为 94），教育表全部已删")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--yes", action="store_true", help="确认执行（默认 dry-run）")
    args = parser.parse_args()
    if args.yes:
        asyncio_run(execute())
    else:
        asyncio_run(dry_run())


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    main()
