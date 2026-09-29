# scripts/ingest_off.py
# 用法：python -m scripts.ingest_off --limit 100
# Open Food Facts 中国区商品拉取入库（免鉴权 API；礼貌限速 ≥2s；价格留空由 enrich 补）
import argparse
import asyncio
import json
import random
import time
from urllib.parse import urlparse

import httpx
from sqlalchemy import text

from backend.core import storage
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal

logger = get_logger(__name__)

SEARCH_URL = "https://world.openfoodfacts.org/api/v2/search"
FIELDS = ("code,product_name,product_name_zh,brands,categories,quantity,product_quantity,"
          "ingredients_text_zh,nutriments,image_front_url")
USER_AGENT = "ShopPilotDemo/0.1 (local MVP; open data import)"
PAGE_SIZE = 50

_UPSERT = """
    INSERT INTO products
        (tenant_id, external_id, source, title, category, price, currency,
         description, params, image_object, rating, url)
    VALUES
        (:tenant_id, :external_id, 'openfoodfacts', :title, :category, NULL, 'CNY',
         NULL, :params, :image_object, NULL, :url)
    ON CONFLICT (source, external_id) DO UPDATE SET
        title = EXCLUDED.title,
        category = EXCLUDED.category,
        params = EXCLUDED.params,
        image_object = EXCLUDED.image_object,
        url = EXCLUDED.url,
        updated_at = NOW()
"""

_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def _throttle():
    time.sleep(2.0 + random.uniform(0.0, 1.0))


async def _fetch_page(client: httpx.AsyncClient, page: int) -> list[dict]:
    """拉取一页；对 429/5xx 与网络错误做 6 次退避重试（15s~90s），仍失败返回 [] 优雅收尾。"""
    for attempt in range(6):
        _throttle()
        try:
            resp = await client.get(SEARCH_URL, params={
                "countries_tags_en": "china",
                "page_size": PAGE_SIZE,
                "page": page,
                "fields": FIELDS,
            }, headers={"User-Agent": USER_AGENT}, timeout=30)
            if resp.status_code in (429, 500, 502, 503, 529):
                wait = 15 * (attempt + 1)
                logger.warning("off.retry", page=page, status=resp.status_code, wait=wait)
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json().get("products", [])
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            if attempt == 5:
                logger.warning("off.fetch_give_up", page=page, error=str(e))
                return []
            wait = 15 * (attempt + 1)
            logger.warning("off.retry", page=page, error=str(e)[:120], wait=wait)
            await asyncio.sleep(wait)
    return []


def _has_cjk(s: str) -> bool:
    return any('一' <= ch <= '鿿' for ch in s)


def _zh_title(p: dict) -> str | None:
    """标题必须含中文：优先 product_name_zh，其次含中文的 product_name（OFF 的 zh 字段可能是英文）。"""
    zh = (p.get("product_name_zh") or "").strip()
    if zh and _has_cjk(zh):
        return zh
    plain = (p.get("product_name") or "").strip()
    if plain and _has_cjk(plain):
        return plain
    return None


def _pick_category(raw: str | None) -> str | None:
    if not raw:
        return None
    # OFF categories 形如 "Waters, bottled"，取首段作大类
    return raw.split(",")[0].strip() or None


def _clean_params(p: dict) -> dict:
    out = {}
    if p.get("brands"):
        out["品牌"] = str(p["brands"])[:200]
    if p.get("quantity"):
        out["规格"] = str(p["quantity"])[:100]
    if p.get("ingredients_text_zh"):
        out["配料"] = str(p["ingredients_text_zh"])[:500]
    nutri = p.get("nutriments") or {}
    if isinstance(nutri, dict):
        keep = {k: v for k, v in nutri.items()
                if k.endswith("_100g") and isinstance(v, (int, float))}
        if keep:
            out["营养成分(每100g)"] = {k.replace("_100g", ""): round(float(v), 2)
                                       for k, v in list(keep.items())[:8]}
    return out


async def _download_image(client: httpx.AsyncClient, url: str, external_id: str) -> str | None:
    path = urlparse(url).path.lower()
    ext = next((e for e in _IMG_EXT if path.endswith(e)), None)
    if ext is None:
        return None
    _throttle()
    try:
        resp = await client.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        logger.warning("off.image_failed", code=external_id, error=str(e))
        return None
    object_name = f"products/{external_id}/0{ext}"
    ctype = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
             "png": "image/png", "webp": "image/webp"}[ext.lstrip(".")]
    await asyncio.to_thread(storage.upload_product_image, object_name, resp.content, ctype)
    return object_name


async def ingest_off(limit: int = 100, tenant_id: str = "tenant_default") -> int:
    storage.ensure_bucket()
    collected: list[dict] = []
    page = 1
    async with httpx.AsyncClient() as client:
        while len(collected) < limit:
            batch = await _fetch_page(client, page)
            if not batch:
                break
            for p in batch:
                title = _zh_title(p)
                if title and p.get("code"):
                    collected.append(p)
                if len(collected) >= limit:
                    break
            page += 1
        logger.info("off.fetched", count=len(collected), pages=page - 1)

        count = 0
        async with AsyncSessionLocal() as db:
            for p in collected:
                code = str(p["code"])
                image_object = None
                if p.get("image_front_url"):
                    image_object = await _download_image(client, p["image_front_url"], code)
                await db.execute(text(_UPSERT), {
                    "tenant_id": tenant_id,
                    "external_id": code,
                    "title": (_zh_title(p) or "未命名商品")[:500],
                    "category": _pick_category(p.get("categories")),
                    "params": json.dumps(_clean_params(p), ensure_ascii=False),
                    "image_object": image_object,
                    "url": f"https://world.openfoodfacts.org/product/{code}",
                })
                await db.commit()
                count += 1
                logger.info("off.ingested", code=code,
                            title=(_zh_title(p) or "")[:40], n=count)
    return count


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    n = asyncio.run(ingest_off(args.limit))
    print(f"✅ 完成：入库/更新 {n} 个中文商品（价格待 enrich）")


if __name__ == "__main__":
    main()
