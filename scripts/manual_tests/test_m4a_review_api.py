# scripts/manual_tests/test_m4a_review_api.py
# 需后端 :8000 运行；触发真实分析并轮询至 done（超时给 5 分钟）
import time

import httpx

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@shoppilot.local", "password": "Student@123456",
    })
    assert r.status_code == 200
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def test_report_lifecycle():
    headers = _headers()
    p = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=headers)
    pid = p.json()["items"][0]["id"]

    r = httpx.post(f"{BASE}/api/v1/reviews/reports", json={"product_id": pid},
                   headers=headers, timeout=30)
    assert r.status_code == 202, r.text
    report_id = r.json()["report_id"]
    assert r.json()["status"] == "processing"

    # 轮询至 done
    deadline = time.time() + 300
    body = {}
    while time.time() < deadline:
        g = httpx.get(f"{BASE}/api/v1/reviews/reports/{report_id}",
                      headers=headers, timeout=30)
        assert g.status_code == 200, g.text
        body = g.json()
        if body["status"] in ("done", "failed"):
            break
        time.sleep(5)
    assert body["status"] == "done", body
    assert len(body["dimensions"]) == 6
    assert 0 < body["weighted_score"] <= 100
    assert body["summary"]

    # latest 端点
    latest = httpx.get(f"{BASE}/api/v1/reviews/reports/latest",
                       params={"product_id": pid}, headers=headers, timeout=30)
    assert latest.status_code == 200
    assert latest.json()["report_id"] == report_id
