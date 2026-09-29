# scripts/manual_tests/test_orders_api.py
# 运行前置：后端运行中 + 有商品 + student 账号
# 注：登录体字段为 username（auth.LoginRequest 契约），账号取 seed_data.py 的 student01。
import httpx
import pytest

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@shoppilot.local", "password": "Student@123456",
    })
    if r.status_code != 200:
        pytest.skip(f"login failed: {r.status_code}")
    token = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {token}"}


def _first_product_id(headers: dict) -> str:
    r = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=headers)
    items = r.json().get("items", [])
    if not items:
        pytest.skip("no products — run crawler first")
    return items[0]["id"]


def test_order_lifecycle():
    headers = _headers()
    pid = _first_product_id(headers)

    # 1) 下单
    r = httpx.post(f"{BASE}/api/v1/orders", json={
        "product_id": pid, "quantity": 2,
        "receiver": "测试用户", "address": "上海市测试路 1 号",
    }, headers=headers)
    assert r.status_code == 200, r.text
    order = r.json()
    assert order["status"] == "created"
    assert order["quantity"] == 2
    # total = unit_price * 2（价格来自库，非请求）
    assert float(order["total_amount"]) == float(order["unit_price"]) * 2
    order_id = order["id"]

    # 2) 模拟支付
    r = httpx.post(f"{BASE}/api/v1/orders/{order_id}/pay", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paid"

    # 3) 重复支付 → 409
    r = httpx.post(f"{BASE}/api/v1/orders/{order_id}/pay", headers=headers)
    assert r.status_code == 409

    # 4) 列表含该订单
    r = httpx.get(f"{BASE}/api/v1/orders", headers=headers)
    assert r.status_code == 200
    ids = [o["id"] for o in r.json()["items"]]
    assert order_id in ids

    # 5) 详情
    r = httpx.get(f"{BASE}/api/v1/orders/{order_id}", headers=headers)
    assert r.status_code == 200
    assert r.json()["status"] == "paid"


def test_order_price_cannot_be_tampered():
    headers = _headers()
    pid = _first_product_id(headers)
    r = httpx.post(f"{BASE}/api/v1/orders", json={
        "product_id": pid, "quantity": 1,
        "receiver": "x", "address": "y",
        "unit_price": 0.01,   # 恶意字段应被忽略（pydantic 不含此字段）
    }, headers=headers)
    assert r.status_code == 200, r.text
    # 单价必须来自库：与商品列表价格一致
    p = httpx.get(f"{BASE}/api/v1/products/{pid}", headers=headers).json()
    assert float(r.json()["unit_price"]) == float(p["price"])
