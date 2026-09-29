# scripts/manual_tests/test_m5a_guide_api.py
# 需后端 :8000：创建会话 → SSE 流式对话 → 强制结束 → 报告（真实 LLM 多次）
import json
import time

import httpx

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@shoppilot.local", "password": "Student@123456",
    })
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def _stream_chat(session_id: str, message: str, headers: dict, max_events: int = 400) -> list[dict]:
    events = []
    with httpx.stream("POST", f"{BASE}/api/v1/guide/sessions/{session_id}/chat/stream",
                      json={"message": message}, headers=headers, timeout=120) as resp:
        assert resp.status_code == 200, resp.read()
        for line in resp.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[5:].strip()))
                if events[-1].get("type") in ("done", "error") or len(events) >= max_events:
                    break
    return events


def test_guide_session_flow():
    headers = _headers()

    # 1) 创建会话（同步首轮）
    r = httpx.post(f"{BASE}/api/v1/guide/sessions",
                   json={"message": "想买瓶装水日常喝"}, headers=headers, timeout=90)
    assert r.status_code == 201, r.text
    sid = r.json()["session_id"]
    assert r.json()["opening_message"], "no opening"

    # 2) 追一轮预算
    events = _stream_chat(sid, "预算 50 以内，要矿泉水", headers)
    assert any(e.get("type") == "token" for e in events), events[:3]
    done = next(e for e in events if e.get("type") == "done")
    assert done["current_stage"] in ("needs_discovery", "budget_confirm",
                                     "matching", "compare_qa", "recommend_close")

    # 3) 强制结束 → 报告
    events = _stream_chat(sid, "直接推荐", headers)
    done = next((e for e in events if e.get("type") == "done"), {})
    assert done.get("is_finished"), done

    # 4) 报告端点
    deadline = time.time() + 30
    report = {}
    while time.time() < deadline:
        g = httpx.get(f"{BASE}/api/v1/guide/sessions/{sid}/report",
                      headers=headers, timeout=30)
        assert g.status_code == 200, g.text
        report = g.json()
        if report["status"] == "finished":
            break
        time.sleep(2)
    assert report["status"] == "finished", report
    assert report["recommendations"], report
    assert report["recommendations"][0]["title"]

    # 5) 列表命中
    lst = httpx.get(f"{BASE}/api/v1/guide/sessions", headers=headers, timeout=30)
    assert any(x["session_id"] == sid for x in lst.json()["items"])
