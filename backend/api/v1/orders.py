# backend/api/v1/orders.py
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)


class OrderCreateRequest(BaseModel):
    product_id: str
    quantity: int = Field(..., ge=1, le=99)
    receiver: str = Field(..., min_length=1, max_length=128)
    address: str = Field(..., min_length=1, max_length=512)


def _order_row_to_dict(r) -> dict:
    return {
        "id": str(r["id"]),
        "product_id": str(r["product_id"]),
        "product_title": r["product_title"],
        "quantity": r["quantity"],
        "unit_price": str(r["unit_price"]),
        "total_amount": str(r["total_amount"]),
        "currency": r["currency"],
        "receiver": r["receiver"],
        "address": r["address"],
        "status": r["status"],
        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
    }


_ORDER_SELECT = """
    SELECT o.id, o.product_id, p.title AS product_title, o.quantity,
           o.unit_price, o.total_amount, o.currency, o.receiver, o.address,
           o.status, o.created_at
    FROM orders o
    JOIN products p ON p.id = o.product_id
"""


@router.post("")
async def create_order(req: OrderCreateRequest, current_user: dict = Depends(get_current_user)):
    """模拟下单：单价从库读取（不接受请求价格），status=created。"""
    async with AsyncSessionLocal() as db:
        product = (await db.execute(
            text("SELECT price, currency FROM products WHERE id = :pid AND is_active"),
            {"pid": req.product_id},
        )).first()
        if product is None:
            raise HTTPException(status_code=404, detail="product not found")
        unit_price, currency = product[0], product[1]
        total = round(float(unit_price) * req.quantity, 2)
        row = (await db.execute(
            text("""
                INSERT INTO orders
                    (tenant_id, user_id, product_id, quantity, unit_price, total_amount,
                     currency, receiver, address, status)
                VALUES (:tenant, :uid, :pid, :qty, :unit, :total, :cur, :recv, :addr, 'created')
                RETURNING id, status, unit_price, total_amount, currency
            """),
            {
                "tenant": current_user["tenant_id"],
                "uid": current_user["user_id"],
                "pid": req.product_id,
                "qty": req.quantity,
                "unit": unit_price,
                "total": total,
                "cur": currency,
                "recv": req.receiver,
                "addr": req.address,
            },
        )).mappings().first()
        await db.commit()
    logger.info("order.created", order_id=str(row["id"]), qty=req.quantity)
    return {
        "id": str(row["id"]),
        "status": row["status"],
        "quantity": req.quantity,
        "unit_price": str(row["unit_price"]),
        "total_amount": str(row["total_amount"]),
        "currency": row["currency"],
    }


@router.get("")
async def list_orders(
    current_user: dict = Depends(get_current_user),
):
    """当前用户的订单列表（新→旧）。"""
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            text(_ORDER_SELECT + " WHERE o.user_id = :uid ORDER BY o.created_at DESC LIMIT 100"),
            {"uid": current_user["user_id"]},
        )).mappings().all()
    return {"total": len(rows), "items": [_order_row_to_dict(r) for r in rows]}


@router.get("/{order_id}")
async def get_order(order_id: str, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text(_ORDER_SELECT + " WHERE o.id = :oid AND o.user_id = :uid"),
            {"oid": order_id, "uid": current_user["user_id"]},
        )).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="order not found")
    return _order_row_to_dict(row)


@router.post("/{order_id}/pay")
async def pay_order(order_id: str, current_user: dict = Depends(get_current_user)):
    """模拟支付：created → paid；重复/非法状态 409。"""
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            text("SELECT status FROM orders WHERE id = :oid AND user_id = :uid"),
            {"oid": order_id, "uid": current_user["user_id"]},
        )).first()
        if row is None:
            raise HTTPException(status_code=404, detail="order not found")
        if row[0] != "created":
            raise HTTPException(status_code=409, detail=f"cannot pay order in status {row[0]}")
        await db.execute(
            text("UPDATE orders SET status = 'paid' WHERE id = :oid"),
            {"oid": order_id},
        )
        await db.commit()
    logger.info("order.paid", order_id=order_id)
    return {"id": order_id, "status": "paid"}
