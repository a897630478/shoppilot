# scripts/manual_tests/test_all_agents_health.py
# 四大电商能力 + 外壳接口健康冒烟（M5b 改写，教育版已废弃）
# 运行前提：后端已启动（uvicorn backend.main:app --port 8000）

import httpx

BASE_URL = "http://localhost:8000/api/v1"


def login():
    resp = httpx.post(
        f"{BASE_URL}/auth/login",
        json={"username": "student01@shoppilot.local", "password": "Student@123456"},
        trust_env=False,
    )
    resp.raise_for_status()
    body = resp.json()
    return body.get("access_token") or body.get("token")


if __name__ == "__main__":
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    results = []

    # 能力清单：名称 → GET 端点
    checks = [
        ("商品外壳 /products",  f"{BASE_URL}/products?page_size=1"),
        ("订单外壳 /orders",     f"{BASE_URL}/orders"),
        ("评价分析 /reviews",    f"{BASE_URL}/reviews/reports/latest?product_id=00000000-0000-0000-0000-000000000000"),
        ("售后客服 /service",    f"{BASE_URL}/service/tickets"),
        ("智能导购 /guide",      f"{BASE_URL}/guide/sessions"),
    ]
    for name, url in checks:
        try:
            resp = httpx.get(url, headers=headers, trust_env=False, timeout=10.0)
            # latest 可能 404（无报告），接口存活即可
            ok = resp.status_code in (200, 404)
            results.append((name, "✅" if ok else f"❌ HTTP {resp.status_code}"))
        except Exception as e:
            results.append((name, f"❌ {e}"))

    # QA SSE 流式
    try:
        chunks = []
        with httpx.stream(
            "POST",
            f"{BASE_URL}/qa/chat/stream",
            headers={**headers, "Content-Type": "application/json"},
            json={"session_id": "health001", "message": "矿泉水和纯净水的区别"},
            timeout=60.0,
        ) as r:
            for line in r.iter_lines():
                if line.startswith("data:"):
                    chunks.append(line)
        results.append(("商品问答 SSE", "✅" if chunks else "❌ 无事件"))
    except Exception as e:
        results.append(("商品问答 SSE", f"❌ {e}"))

    print("\n电商能力健康检查结果：")
    for name, status in results:
        print(f"  {name}: {status}")
