# scripts/manual_tests/test_products_api.py
# 运行前置：后端 uvicorn 运行中 + 已爬取商品 + 已有登录账号（seed_data.py 的 student）
# 运行：python -m pytest scripts/manual_tests/test_products_api.py -v -s
# 注：登录体字段为 username（auth.LoginRequest 契约），账号取 seed_data.py 的 student01。
import httpx
import pytest

BASE = "http://localhost:8000"


def _token() -> str:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@shoppilot.local", "password": "Student@123456",
    })
    if r.status_code != 200:
        pytest.skip(f"login failed: {r.status_code} {r.text[:200]}")
    body = r.json()
    return body.get("access_token") or body.get("token")


def _headers():
    return {"Authorization": f"Bearer {_token()}"}


def test_product_list():
    r = httpx.get(f"{BASE}/api/v1/products", params={"page": 1, "page_size": 5}, headers=_headers())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "total" in body and "items" in body
    if body["items"]:
        item = body["items"][0]
        for key in ("id", "title", "price", "currency", "image_url"):
            assert key in item


def test_product_detail_and_image():
    r = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=_headers())
    items = r.json()["items"]
    if not items:
        pytest.skip("no products — run crawler first")
    pid = items[0]["id"]
    r = httpx.get(f"{BASE}/api/v1/products/{pid}", headers=_headers())
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["params"] is None or isinstance(detail["params"], dict)
    assert "review_count" in detail

    if detail["image_url"]:
        # image_url 为 MinIO 预签名 URL：签名已内嵌，不能再带 Authorization 头
        r = httpx.get(detail["image_url"], timeout=30)
        assert r.status_code == 200, f"presigned image fetch failed: {r.status_code}"
        assert r.headers["content-type"].startswith("image/")


def test_product_not_found():
    r = httpx.get(
        f"{BASE}/api/v1/products/00000000-0000-0000-0000-000000000000",
        headers=_headers(),
    )
    assert r.status_code == 404
