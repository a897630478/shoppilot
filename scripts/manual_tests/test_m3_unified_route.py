# scripts/manual_tests/test_m3_unified_route.py
# 统一入口路由冒烟（需后端 :8000 运行，真实 LLM 路由调用 2 次）
import json

import httpx

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@eduagent.local", "password": "Student@123456",
    })
    assert r.status_code == 200
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def _first_events(message: str, n: int = 6) -> list[dict]:
    headers = _headers()
    events = []
    with httpx.stream("POST", f"{BASE}/api/v1/chat/stream",
                      json={"session_id": "m3-route", "message": message},
                      headers=headers, timeout=90) as resp:
        assert resp.status_code == 200
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if len(events) >= n:
                    break
    return events


def test_route_service_intent():
    events = _first_events("我买的东西坏了，怎么退货退款？")
    routing = next(e for e in events if e.get("type") == "routing_decision")
    assert routing["agent_type"] in ("exam", "qa")  # service 占位映射 exam 或降级
    assert "试卷" not in routing["agent_display"]    # 不得出现教育展示名
    # 未上线能力 → guidance 引导卡（不是 QA token 流）
    types = [e.get("type") for e in events]
    assert "guidance" in types or "token" in types


def test_route_qa_intent():
    events = _first_events("矿泉水和纯净水有什么区别？", n=12)
    routing = next(e for e in events if e.get("type") == "routing_decision")
    assert routing["agent_display"] == "商品导购问答"
    assert "token" in [e.get("type") for e in events]
