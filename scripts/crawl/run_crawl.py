# scripts/crawl/run_crawl.py
# 用法：python -m scripts.crawl.run_crawl --limit 10 [--skip-images]
# 流程：适配器产出 URL → 限速抓取 → 解析 → 下载图片入 MinIO → upsert PG products
import argparse
import asyncio
from urllib.parse import urlparse

import requests
from sqlalchemy import text

from backend.core import storage
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal
from scripts.crawl.adapters.books_toscrape import BooksToscrapeAdapter

logger = get_logger(__name__)

_UPSERT_SQL = """
    INSERT INTO products
        (tenant_id, external_id, source, title, category, price, currency,
         description, params, image_object, rating, url)
    VALUES
        (:tenant_id, :external_id, :source, :title, :category, :price, :currency,
         :description, :params, :image_object, :rating, :url)
    ON CONFLICT (source, external_id) DO UPDATE SET
        title = EXCLUDED.title,
        category = EXCLUDED.category,
        price = EXCLUDED.price,
        description = EXCLUDED.description,
        params = EXCLUDED.params,
        image_object = EXCLUDED.image_object,
        rating = EXCLUDED.rating,
        url = EXCLUDED.url,
        updated_at = NOW()
"""

_IMAGE_EXT = {".jpg": ".jpg", ".jpeg": ".jpg", ".png": ".png", ".webp": ".webp"}


def _content_type(ext: str) -> str:
    return {".jpg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(
        ext, "application/octet-stream"
    )


async def _download_image(url: str, external_id: str, index: int, session: requests.Session) -> str | None:
    path = urlparse(url).path
    ext = next((e for e in _IMAGE_EXT if path.lower().endswith(e)), None)
    if ext is None:
        return None
    html_bytes = await asyncio.to_thread(_sync_get_bytes, url, session)
    if html_bytes is None:
        return None
    object_name = f"products/{external_id}/{index}{_IMAGE_EXT[ext]}"
    await asyncio.to_thread(
        storage.upload_product_image, object_name, html_bytes, _content_type(_IMAGE_EXT[ext])
    )
    return object_name


def _sync_get_bytes(url: str, session: requests.Session) -> bytes | None:
    from scripts.crawl.base_adapter import USER_AGENT, MIN_INTERVAL_SECONDS
    import random
    import time

    time.sleep(MIN_INTERVAL_SECONDS + random.uniform(0.0, 1.0))
    try:
        resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning("crawl.image_failed", url=url, error=str(e))
        return None


async def ingest_products(adapter, limit: int, skip_images: bool = False, tenant_id: str = "tenant_default") -> int:
    """爬取并入库；返回成功条数。幂等（ON CONFLICT UPDATE）。"""
    storage.ensure_bucket()
    session = requests.Session()
    count = 0
    urls = []
    for url in adapter.iter_product_urls():
        urls.append(url)
        if len(urls) >= limit:
            break

    async with AsyncSessionLocal() as db:
        for url in urls:
            # 单商品失败（如 external_id 超长/网络抖动）不中断整批，记日志后继续
            try:
                html = await asyncio.to_thread(adapter.throttled_get, url, session)
                rec = adapter.parse_product(html, url)
                image_object = None
                if not skip_images and rec.image_urls:
                    image_object = await _download_image(
                        rec.image_urls[0], rec.external_id, 0, session
                    )
                import json
                await db.execute(
                    text(_UPSERT_SQL),
                    {
                        "tenant_id": tenant_id,
                        "external_id": rec.external_id,
                        "source": adapter.site_name,
                        "title": rec.title,
                        "category": rec.category,
                        "price": rec.price,
                        "currency": rec.currency,
                        "description": rec.description,
                        "params": json.dumps(rec.params, ensure_ascii=False),
                        "image_object": image_object,
                        "rating": rec.rating,
                        "url": rec.url,
                    },
                )
                await db.commit()
                count += 1
                logger.info("crawl.ingested", title=rec.title, price=rec.price, n=count)
            except Exception as e:
                await db.rollback()
                logger.warning("crawl.item_failed", url=url, error=str(e))
                continue
    return count


def main():
    parser = argparse.ArgumentParser(description="商品爬虫入库")
    parser.add_argument("--limit", type=int, default=10, help="最多爬取商品数")
    parser.add_argument("--skip-images", action="store_true", help="跳过图片下载")
    args = parser.parse_args()

    adapter = BooksToscrapeAdapter()
    n = asyncio.run(ingest_products(adapter, args.limit, args.skip_images))
    print(f"✅ 完成：入库/更新 {n} 个商品")


if __name__ == "__main__":
    main()
