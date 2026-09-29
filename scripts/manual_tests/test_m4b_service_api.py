# scripts/manual_tests/test_m4b_service_api.py
# 需后端 :8000：下单→售后工单→轮询→审批闭环（真实 LLM 1~2 次）
import time

import httpx

BASE = "http://localhost:8000"


def _login(username: str, password: str) -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": username, "password": password,
    })
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def test_ticket_and_approval_flow():
    student = _login("student01@shoppilot.local", "Student@123456")

    # 1) 造单：下单 + 模拟支付（quantity=1 取首个商品；金额不足 100 时工单走自动 resolved，测试兼容）
    p = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=student).json()
    pid = p["items"][0]["id"]
    o = httpx.post(f"{BASE}/api/v1/orders", json={
        "product_id": pid, "quantity": 5, "receiver": "测试", "address": "地址",
    }, headers=student, timeout=30)
    assert o.status_code == 200, o.text
    order_id = o.json()["id"]
    httpx.post(f"{BASE}/api/v1/orders/{order_id}/pay", headers=student, timeout=30)

    # 2) 发起退款工单
    t = httpx.post(f"{BASE}/api/v1/service/tickets", json={
        "order_id": order_id, "ticket_type": "refund", "reason": "商品质量问题，要求退款",
    }, headers=student, timeout=30)
    assert t.status_code == 202, t.text
    tid = t.json()["ticket_id"]

    # 2b) 同一订单重复提交 → 409（每单一个未完结工单）
    dup = httpx.post(f"{BASE}/api/v1/service/tickets", json={
        "order_id": order_id, "ticket_type": "refund", "reason": "重复提交测试工单",
    }, headers=student, timeout=30)
    assert dup.status_code == 409, f"expected 409 for duplicate open ticket, got {dup.status_code}"

    # 3) 轮询至终态
    deadline = time.time() + 180
    body = {}
    while time.time() < deadline:
        g = httpx.get(f"{BASE}/api/v1/service/tickets/{tid}", headers=student, timeout=30)
        assert g.status_code == 200, g.text
        body = g.json()
        if body["status"] in ("resolved", "pending", "rejected"):
            break
        time.sleep(4)
    assert body["status"] in ("resolved", "pending"), body
    assert body["ai_result"]["reply"], "missing reply"

    # 4) 若 pending → 运营审批
    if body["status"] == "pending":
        teacher = _login("teacher01@shoppilot.local", "Teacher@123456")
        pending = httpx.get(f"{BASE}/api/v1/service/pending-reviews",
                            headers=teacher, timeout=30)
        assert pending.status_code == 200, pending.text
        assert any(x["id"] == tid for x in pending.json()["items"]), "not in pending list"
        rv = httpx.post(f"{BASE}/api/v1/service/tickets/{tid}/review", json={
            "action": "approve", "comment": "情况属实，同意退款",
        }, headers=teacher, timeout=30)
        assert rv.status_code == 200, rv.text
        after = httpx.get(f"{BASE}/api/v1/service/tickets/{tid}",
                          headers=student, timeout=30)
        assert after.json()["status"] == "resolved"
        assert after.json()["ai_result"]["operator_comment"] == "情况属实，同意退款"
        # 学员无权审批
        forbidden = httpx.post(f"{BASE}/api/v1/service/tickets/{tid}/review",
                               json={"action": "approve"}, headers=student, timeout=30)
        assert forbidden.status_code == 403
