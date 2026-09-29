# backend/api/v1/products.py
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import text

from backend.core import storage
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)


@router.get("")
async def list_products(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: str | None = None,
    keyword: str | None = None,
    current_user: dict = Depends(get_current_user),
):
    """商品列表：类目筛选 + 关键词搜索 + 分页。"""
    filters, params = ["is_active = TRUE"], {}
    if category:
        filters.append("category = :category")
        params["category"] = category
    if keyword:
        filters.append("(title ILIKE :kw OR description ILIKE :kw)")
        params["kw"] = f"%{keyword}%"
    where = " AND ".join(filters)

    async with AsyncSessionLocal() as db:
        total = (await db.execute(
            text(f"SELECT count(*) FROM products WHERE {where}"), params
        )).scalar()
        rows = (await db.execute(
            text(f"""
                SELECT id, title, category, price, currency, rating, image_object
                FROM products WHERE {where}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            {**params, "limit": page_size, "offset": (page - 1) * page_size},
        )).mappings().all()

    return {
        "total": total,
        "items": [
            {
                "id": str(r["id"]),
                "title": r["title"],
                "category": r["category"],
                "price": str(r["price"]),
                "currency": r["currency"],
                "rating": r["rating"],
                "image_url": storage.presign_image_url(r["image_object"]),
            }
            for r in rows
        ],
    }


@router.get("/{product_id}")
async def get_product(product_id: str, current_user: dict = Depends(get_current_user)):
    """商品详情（含参数、评价数）。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("""
                SELECT id, title, category, price, currency, description, params,
                       rating, url, source, image_object,
                       (SELECT count(*) FROM product_reviews r WHERE r.product_id = p.id) AS review_count
                FROM products p
                WHERE id = :pid AND is_active = TRUE
            """),
            {"pid": product_id},
        )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="product not found")

    params = row["params"]
    if isinstance(params, str):
        params = json.loads(params)
    return {
        "id": str(row["id"]),
        "title": row["title"],
        "category": row["category"],
        "price": str(row["price"]),
        "currency": row["currency"],
        "description": row["description"],
        "params": params or {},
        "rating": row["rating"],
        "url": row["url"],
        "source": row["source"],
        "image_url": storage.presign_image_url(row["image_object"]),
        "review_count": row["review_count"],
    }


@router.get("/{product_id}/image")
async def get_product_image(product_id: str, current_user: dict = Depends(get_current_user)):
    """商品主图代理（鉴权透传；列表/详情已改用预签名 URL，本端点保留兼容）。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT image_object FROM products WHERE id = :pid"), {"pid": product_id}
        )).first()
    if row is None or not row[0]:
        raise HTTPException(status_code=404, detail="image not found")
    try:
        data, content_type = storage.download_product_image(row[0])
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="image object missing")
    return Response(content=data, media_type=content_type)
