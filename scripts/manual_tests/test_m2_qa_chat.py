# scripts/manual_tests/test_m2_qa_chat.py
# QA 对话冒烟：商品问题应走 RAG 且来源为商品内容（需后端 :8000 运行，真实 LLM 调用 1~2 次）
import httpx
import pytest

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@eduagent.local", "password": "Student@123456",
    })
    assert r.status_code == 200, r.text
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def test_qa_chat_product_question():
    headers = _headers()
    r = httpx.post(f"{BASE}/api/v1/qa/chat", json={
        "session_id": "m2-smoke",
        "message": "有没有适合日常喝的矿泉水？",
    }, headers=headers, timeout=90)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"], "empty answer"
    assert body["answer_mode"] in ("rag", "web_augmented", "llm_direct", "general")
    # 商品类问题在 94 商品库下应优先走 rag
    assert body["answer_mode"] == "rag", f"expected rag, got {body['answer_mode']}: {body['answer'][:120]}"
    assert any('一' <= ch <= '鿿' for ch in body["answer"])


def test_qa_chat_with_product_filter():
    headers = _headers()
    # 取一个商品 id 带过滤提问
    p = httpx.get(f"{BASE}/api/v1/products", params={"page_size": 1}, headers=headers)
    pid = p.json()["items"][0]["id"]
    r = httpx.post(f"{BASE}/api/v1/qa/chat", json={
        "session_id": "m2-smoke-pid",
        "product_id": pid,
        "message": "这个商品的规格和价格是多少？",
    }, headers=headers, timeout=90)
    assert r.status_code == 200, r.text
    assert r.json()["answer"]


def test_qa_chat_no_keyword_product_question():
    """不含商品关键词的问题也不得被教育分类器判成闲聊（应走 RAG 或直答，而非 general 敷衍）"""
    headers = _headers()
    r = httpx.post(f"{BASE}/api/v1/qa/chat", json={
        "session_id": "m2-nokw",
        "message": "这个适合送人吗，包装好看吗",
    }, headers=headers, timeout=90)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer_mode"] in ("rag", "llm_direct"), body["answer_mode"]
    assert len(body["answer"]) >= 20
