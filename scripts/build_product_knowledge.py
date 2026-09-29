# scripts/build_product_knowledge.py
# 用法：python -m scripts.build_product_knowledge --limit 10
# 商品 → 文本 chunk → BGE-M3(dense+sparse) → 写入 product_knowledge（幂等覆盖）
import argparse
import asyncio
import time

from sqlalchemy import text

from backend.core.knowledge_base import BGEMEmbedder
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal
from pymilvus import MilvusClient

from backend.config import get_settings

logger = get_logger(__name__)
COLLECTION = "product_knowledge"


def _chunk_product(row) -> list[str]:
    """title/category/price 行 + 参数 + 描述段落 → chunk 列表。"""
    chunks = [
        f"{row['title']}｜类目：{row['category'] or '未分类'}｜价格：{row['price']} {row['currency']}"
    ]
    params = row["params"] or {}
    if params:
        # 参数按 6 个键一块切，避免超长
        items = list(params.items())
        for i in range(0, len(items), 6):
            part = "；".join(f"{k}：{v}" for k, v in items[i:i + 6])
            chunks.append(f"{row['title']} 规格参数：{part}")
    desc = (row["description"] or "").strip()
    if desc:
        step = 800
        for i in range(0, len(desc), step):
            chunks.append(f"{row['title']} 商品介绍：{desc[i:i + step]}")
    return chunks


async def build_for_products(limit: int | None = None, tenant_id: str = "tenant_default") -> int:
    embedder = BGEMEmbedder.get_instance()
    client = MilvusClient(uri=f"http://{get_settings().milvus_host}:{get_settings().milvus_port}")
    # MilvusClient.query 不自动 load；保证写入后按 product_id 查询可见（幂等）
    client.load_collection(COLLECTION)

    async with AsyncSessionLocal() as db:
        # 不加 ORDER BY：与冒烟测试的 `WHERE is_active LIMIT 1` 取同一物理行，
        # 否则 limit=1 时构建的商品与测试断言的商品不是同一个
        sql = """
            SELECT id, title, category, price, currency, description, params
            FROM products WHERE is_active = TRUE
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        res = await db.execute(text(sql))
        rows = res.mappings().all()

    count = 0
    for row in rows:
        pid = str(row["id"])
        chunks = _chunk_product(row)
        # encode 真实签名：encode(texts: list[str]) -> (dense_list, sparse_list)
        # 每商品一次批量编码（encode(texts, batch_size) 返回 (dense_list, sparse_list)）
        dense, sparse = embedder.encode(chunks)
        ids, contents = [], []
        for idx, content in enumerate(chunks):
            ids.append(f"prod_{pid}_{idx}")
            contents.append(content[:4096])
            # 同 id 重复插入会报错，先删后插（幂等重建）
            try:
                client.delete(COLLECTION, filter=f'id == "prod_{pid}_{idx}"')
            except Exception:
                pass
        # 批量插入
        now = int(time.time())
        client.insert(COLLECTION, data=[
            {
                "id": ids[i], "embedding": dense[i], "sparse_embedding": sparse[i],
                "content": contents[i], "tenant_id": tenant_id, "chunk_index": i,
                "product_id": pid, "source_name": row["title"][:256], "updated_at": now,
            }
            for i in range(len(ids))
        ])
        count += 1
        logger.info("kb.product_indexed", title=row["title"], chunks=len(chunks))
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    n = asyncio.run(build_for_products(args.limit))
    print(f"✅ 完成：{n} 个商品已入向量索引")


if __name__ == "__main__":
    main()
