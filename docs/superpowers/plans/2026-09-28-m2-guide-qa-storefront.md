# M2 首个链路（商品导购问答 + 商城页面）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通「浏览商品 → 详情页问 AI → 商品导购问答（RAG 检索 product_knowledge）」第一条完整电商链路：QA Agent 从教育语义切换为电商导购语义，前端新增商品列表/详情页并接入问答。

**Architecture:** 后端做**精确点位替换**——检索层换集合与过滤字段（`knowledge_domain`→`product_knowledge`、`course_id`→`product_id`）、QA 提示词与规则词全量电商化；前端按现有模式（axios 封装 / 懒加载路由 / Sidebar 硬编码菜单 / QAChatView 直连 SSE）新增两个页面，并让 QAChatView 支持从详情页携带 `product_id` 与预填问题。

**Tech Stack:** Vue3 + TS + Element Plus（前端）、FastAPI + LangGraph QA 图 + Milvus 混合检索 + BGE-Reranker（后端）。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §4.1、§5.2；里程碑 M2

## Global Constraints

- Python 解释器：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`；前端 `cd frontend` 后 `npm run build`（含 vue-tsc 类型检查）是唯一前端门禁。
- 检索切换必须**只改点位不改机制**：WeightedRanker(0.7,0.3)、RECALL/RERANK 常量、HyDE/多查询改写、三层容错全部保留。
- `product_knowledge` 集合 schema 无 `course_id/document_id/chunk_type` 字段——`output_fields` 必须同步删改，否则检索报错。
- QA 图结构（graph.py 节点路由）与 `knowledge_pending_queue` 写入逻辑不动。
- SSE 仍走前端直连 `http://localhost:8000`（QAChatView 现有 `API_BASE` 模式），不经 Vite proxy。
- 不动 exam/resume/interview 三个 Agent 与 `/chat` 统一入口的路由逻辑（M3/M4/M5 范围）。
- 已知环境：Docker 栈需运行；后端启动有 regex warmup warning 属正常。

## 现状关键事实（探索确认，直接引用）

- `backend/core/knowledge_base.py:181` `COLLECTION_NAME = "knowledge_domain"`（模块常量，`__init__:209` load、`:330` 检索均引用）；`:321-324` output_fields 含 `course_id`；`:363-374` `_build_filter(tenant_id, course_id)` 是 course_id 唯一拼接点。
- 检索入口：`backend/core/reranker.py:131` `retrieve(query, tenant_id, course_id=None, recall_top_k=10, rerank_top_k=3) -> (list[RankedDocument], float)`。
- QA state：`backend/agents/qa/state.py:23` `course_id: Optional[str]`；`nodes.py:402/417/448` 读取并透传；`:144-148` `_SPECIALIZED_KEYWORDS` 教育词；`:643/:505` 文案含「课程知识库/课程文档」。
- `backend/agents/qa/prompts.py` 7 个常量：`SYSTEM_PROMPT/RAG_STRATEGY_PROMPT/HYDE_PROMPT/MULTI_QUERY_REWRITE_PROMPT/RAG_ANSWER_PROMPT/DIRECT_ANSWER_PROMPT/GENERAL_ANSWER_PROMPT`。
- 分类器 `core/query_classifier.py` 是教育域微调模型（M3 才换），M2 只换规则关键词层，模型调用保持不动。
- `api/v1/qa.py:22` `ChatRequest.course_id`；`:62/:101` 注入 initial_state。`unified_chat.py:416` `"course_id": None` 硬编码。
- `mcp/knowledge_base_server.py:20/32/56` 带 `course_id` 参数。
- 前端：路由 children 懒加载模式；`api/client.ts` baseURL=`/api/v1`+token 注入；菜单硬编码在 `Sidebar.vue`；SSE 直连模式在 `QAChatView.vue:233-291`（body 现为 `{session_id, message, enable_web_search}`）；vite proxy `/api`→8000。

## 文件结构总览

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/core/knowledge_base.py` | 集合名/output_fields/过滤字段 | 修改（3 个点位） |
| `backend/core/reranker.py` | `retrieve` 参数 course_id→product_id | 修改（2 个点位） |
| `backend/mcp/knowledge_base_server.py` | MCP 检索参数同步 | 修改 |
| `backend/agents/qa/state.py` | `course_id`→`product_id` | 修改（1 行） |
| `backend/agents/qa/nodes.py` | 读取字段/规则关键词/文案 | 修改（约 6 处） |
| `backend/agents/qa/prompts.py` | 7 个提示词常量全量重写 | 修改（整体替换） |
| `backend/api/v1/qa.py` | `ChatRequest.product_id` + 注入 | 修改 |
| `backend/api/v1/unified_chat.py` | `_stream_qa_agent` 字段占位 | 修改（1 行） |
| `scripts/manual_tests/test_m2_retrieval.py` | 检索切换断言 | 新建 |
| `scripts/manual_tests/test_m2_qa_chat.py` | QA 对话冒烟（真实 LLM） | 新建 |
| `frontend/src/api/products.ts` | 商品 API 封装 | 新建 |
| `frontend/src/views/product/ProductListView.vue` | 商品列表页 | 新建 |
| `frontend/src/views/product/ProductDetailView.vue` | 商品详情页 + 问 AI | 新建 |
| `frontend/src/router/index.ts` | 挂 2 条路由 | 修改 |
| `frontend/src/components/layout/Sidebar.vue` | 「商品浏览」菜单 | 修改 |
| `frontend/src/views/qa/QAChatView.vue` | 读取 route.query 预填+自动发送+带 product_id | 修改 |

---

### Task 1: 检索层切换到 product_knowledge

**Files:**
- Modify: `backend/core/knowledge_base.py`（`:181` 常量、`:321-324` output_fields、`:363-374` `_build_filter`、`:209` 注释无需动）
- Modify: `backend/core/reranker.py`（`:131-164` `retrieve` 签名与调用）
- Modify: `backend/mcp/knowledge_base_server.py`（`course_id` 参数 3 处）
- Test: `scripts/manual_tests/test_m2_retrieval.py`（新建）

**Interfaces:**
- Consumes: Milvus 集合 `product_knowledge`（字段 `tenant_id, product_id, source_name, content, chunk_index`；已存 94 商品向量）
- Produces（后续任务依赖的精确签名）:
  - `retrieve(query: str, tenant_id: str, product_id: str | None = None, recall_top_k: int = 10, rerank_top_k: int = 3) -> tuple[list[RankedDocument], float]`
  - `KnowledgeBaseClient._build_filter(tenant_id: str, product_id: str | None = None) -> str`，表达式 `tenant_id == "..." [and product_id == "..."]`
  - `RankedDocument`（沿用 reranker 既有类）的 metadata 含 `source_name/chunk_index/product_id`

- [ ] **Step 1: 写失败测试**

新建 `scripts/manual_tests/test_m2_retrieval.py`：

```python
# scripts/manual_tests/test_m2_retrieval.py
# 断言 QA 检索链路已切到 product_knowledge（需 Milvus 运行 + 已建商品索引）
import asyncio


def test_retrieval_targets_product_knowledge():
    asyncio.run(_run())


async def _run():
    from backend.core.knowledge_base import COLLECTION_NAME, KnowledgeBaseClient
    from backend.core.reranker import retrieve

    # 1. 集合常量已切换
    assert COLLECTION_NAME == "product_knowledge", COLLECTION_NAME

    # 2. 全库检索返回商品 chunk（中文查询「矿泉水」应命中饮用水类商品）
    # 注意：retrieve 是同步函数（nodes 里经 run_in_executor 调用）
    docs, score = retrieve("矿泉水", tenant_id="tenant_default",
                           recall_top_k=10, rerank_top_k=3)
    assert docs, "no docs retrieved from product_knowledge"
    for d in docs:
        meta = getattr(d, "metadata", {}) or {}
        assert "product_id" in meta or d.content, "chunk must carry content"
    # 命中内容应含中文（商品文案）
    joined = "".join(d.content for d in docs)
    assert any('一' <= ch <= '鿿' for ch in joined), "expected Chinese product content"

    # 3. product_id 过滤：取一个真实 product_id，限定后结果全部属于它
    from sqlalchemy import text
    from backend.dependencies import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        pid = (await s.execute(text(
            "SELECT id FROM products WHERE is_active LIMIT 1"))).scalar()
    docs2, _ = retrieve("牛奶", tenant_id="tenant_default",
                        product_id=str(pid), recall_top_k=10, rerank_top_k=3)
    for d in docs2:
        meta = getattr(d, "metadata", {}) or {}
        if "product_id" in meta:
            assert str(meta["product_id"]) == str(pid)
```

- [ ] **Step 2: 运行确认失败**

Run: `& $py -m pytest scripts/manual_tests/test_m2_retrieval.py -v`
Expected: FAIL，`AssertionError: knowledge_domain`（常量未切换）

- [ ] **Step 3: 切换 knowledge_base.py 三个点位**

① `:181` 常量：

```python
COLLECTION_NAME = "product_knowledge"   # M2：商品导购问答检索集合（原 knowledge_domain 教育库已弃用）
```

② `_hybrid_search` 内 `output_fields`（原 `["content", "score", "source_name", "chunk_type", "course_id", "document_id", "chunk_index"]` 一类列表）改为仅保留集合真实存在的字段：

```python
        output_fields=["content", "source_name", "chunk_index", "product_id"],
```

（同时确认返回组装处 `metadata` 的键与之对应：`course_id`→`product_id`，`chunk_type/document_id` 相关引用一并删除或置 None——以文件实际代码为准做最小改。）

③ `_build_filter`：

```python
def _build_filter(self, tenant_id: str, product_id: str | None = None) -> str:
    expr = f'tenant_id == "{tenant_id}"'
    if product_id:
        expr += f' and product_id == "{product_id}"'
    return expr
```

- [ ] **Step 4: 切换 reranker.retrieve**

签名 `course_id: str | None = None` → `product_id: str | None = None`；内部 `_build_filter(tenant_id, course_id)` → `_build_filter(tenant_id, product_id)`（`:134` 与 `:163` 两处，函数内如有同名透传变量一并改名）。

- [ ] **Step 5: 同步 MCP server**

`backend/mcp/knowledge_base_server.py` 中 3 处 `course_id` 参数/透传改为 `product_id`（工具签名、内部调用 retrieve 的传参）。

- [ ] **Step 6: 运行测试确认通过**

Run: `& $py -m pytest scripts/manual_tests/test_m2_retrieval.py -v`
Expected: PASS（全库检索命中中文商品 chunk + product_id 过滤生效）
若第 3 段 `docs2` 为空允许通过（目标商品可能无「牛奶」相关 chunk，过滤语义已由元数据断言覆盖）。

- [ ] **Step 7: 回归教育残留引用**

Run: `& $py -m pytest tests/ -q` → 7 passed（不动 DB 结构）
Run: `& $py -c "import backend.agents.qa.nodes, backend.mcp.knowledge_base_server, backend.api.v1.qa, backend.api.v1.unified_chat; print('imports ok')"`
Expected: `imports ok`（此步只验 import；nodes 里 `course_id` 读取在 Task 2 改——若此时 import 报错说明误动了文件）

---

### Task 2: QA state 与 API 字段切换（course_id → product_id）

**Files:**
- Modify: `backend/agents/qa/state.py`（`:23`）
- Modify: `backend/agents/qa/nodes.py`（`:402`、`:417`、`:448` 读取与透传）
- Modify: `backend/api/v1/qa.py`（`ChatRequest:22`、initial_state `:62/:101`）
- Modify: `backend/api/v1/unified_chat.py`（`:416` 一行）
- Test: `scripts/manual_tests/test_m2_qa_chat.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 `retrieve(..., product_id=...)`
- Produces:
  - QA `initial_state` 键：`"product_id": str | None`（原 `course_id` 键**移除**，graph 的 TypedDict 不再声明 course_id）
  - `POST /api/v1/qa/chat` body 新增可选 `"product_id": str`（旧 `course_id` 字段删除——前端 M2 之前无页面传该字段，检查 `unified_chat`/手动测试脚本引用后统一改）
  - SSE `/qa/chat/stream` body 同样接受 `product_id`

- [ ] **Step 1: 写失败测试（需后端运行 + DeepSeek 可用）**

新建 `scripts/manual_tests/test_m2_qa_chat.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

启动后端后 Run: `& $py -m pytest scripts/manual_tests/test_m2_qa_chat.py::test_qa_chat_product_question -v`
Expected: FAIL（`answer_mode != rag` 或 422——字段/集合未切换导致检索空走 LLM 直答）

- [ ] **Step 3: 改 state 与 nodes**

① `state.py:23`：`course_id: Optional[str]` → `product_id: Optional[str]`（注释同步：「商品 ID，限定检索范围；None=全库检索」）。
② `nodes.py` retrieve_node 三处：`state.get("course_id")` → `state.get("product_id")`；`retrieve(sub_query, tenant_id, course_id, ...)` → `retrieve(sub_query, tenant_id, product_id, ...)`（`414-420` BROAD 并行与 `443-451` 单路的**所有** retrieve 调用位，变量名统一为 `product_id`）。
③ 全文件 `rg "course_id" backend/agents/qa/` 确认无残留（prompts 无该词，graph 无）。

- [ ] **Step 4: 改 API 注入**

① `api/v1/qa.py` `ChatRequest`：

```python
class ChatRequest(BaseModel):
    session_id:        str        = Field(..., description="会话 ID")
    product_id:        str | None = Field(None, description="商品 ID（可选，限定检索范围）")
    message:           str        = Field(..., min_length=1, max_length=2000)
    enable_web_search: bool       = Field(False, description="低置信度时是否先走 Web Search 再给 LLM")
```

（原 `course_id` 字段删除。）`/chat` 与 `/chat/stream` 两处 initial_state：`"course_id": req.course_id` → `"product_id": req.product_id`。
② `unified_chat.py:416`：`"course_id": None` → `"product_id": None`。
③ `rg "course_id" backend/` 全库确认仅剩 M5 外无关引用（exam/resume 等业务表字段属正常，勿动）；`backend/agents/qa/` 与 `backend/api/v1/qa.py` 内必须为 0。

- [ ] **Step 5: 重启后端运行测试确认通过**

Run: `& $py -m pytest scripts/manual_tests/test_m2_qa_chat.py -v`（2 次真实 LLM 调用，超时 5 分钟）
Expected: 2 passed（`answer_mode == "rag"`）

---

### Task 3: QA 提示词与规则词电商化

**Files:**
- Modify: `backend/agents/qa/prompts.py`（7 个常量整体替换）
- Modify: `backend/agents/qa/nodes.py`（`:144-148` `_SPECIALIZED_KEYWORDS`、`:643/:505` 文案）
- Test: 沿用 `scripts/manual_tests/test_m2_qa_chat.py`（重跑断言行为不回归）

**Interfaces:**
- Consumes: 无新依赖
- Produces: 提示词常量名**保持不变**（nodes.py 引用不动），仅内容替换；`_SPECIALIZED_KEYWORDS` 变为商品词表

- [ ] **Step 1: 重写 prompts.py 七个常量**

`backend/agents/qa/prompts.py` 整体替换为（变量名与现有完全一致，format 占位符仅保留原文件已使用的那些——改写前先读原文件核对每个常量的 `.format()` 参数，保持入参兼容）：

```python
# backend/agents/qa/prompts.py
# 商品导购问答提示词（M2：由教育助教语义整体切换为电商导购语义）

SYSTEM_PROMPT = (
    "你是「ShopPilot」商城的智能导购助手，为顾客提供商品咨询与选购建议。"
    "回答要求：基于检索到的商品信息作答，绝不编造商品参数与价格；"
    "价格与库存以你拿到的数据为准；超出商品与购物范畴的问题礼貌说明并引导回商品话题。"
)

RAG_STRATEGY_PROMPT = (
    "顾客问题：{query}\n\n"
    "判断该问题类型并只输出 JSON：\n"
    '{{"query_type": "product" 或 "general", "needs_hyde": true/false, "needs_multi_query": true/false}}\n'
    "product = 与具体商品/参数/价格/选购/对比相关（走商品库检索）；"
    "general = 寒暄或与商品无关（走通用回答）。"
)

HYDE_PROMPT = (
    "顾客问题：{query}\n"
    "假设一个商城商品详情页会直接回答该问题，写出那段最可能的详情页文字（中文，2 句以内，只输出正文）："
)

MULTI_QUERY_REWRITE_PROMPT = (
    "顾客问题：{query}\n"
    "改写为 3 个不同角度的中文检索式（同义替换/上下位词/场景词），每行一个，只输出 3 行："
)

RAG_ANSWER_PROMPT = (
    "你是商城导购助手。以下是检索到的商品资料：\n{context}\n\n"
    "顾客问题：{query}\n\n"
    "要求：只依据资料回答，可引用商品名与规格；资料不足以回答时明确告知并给出选购建议方向；"
    "语言自然热情，60~150 字，输出中文。"
)

DIRECT_ANSWER_PROMPT = (
    "你是商城导购助手。顾客问题无需检索即可回答：{query}\n"
    "只回答与购物/商品常识相关的内容；不涉及具体商品参数或价格，不要编造；60~120 字，输出中文。"
)

GENERAL_ANSWER_PROMPT = (
    "你是商城导购助手，与顾客闲聊：{query}\n"
    "友好简短地回应，并自然引导顾客咨询商品选购问题；40~80 字，输出中文。"
)
```

注意：若原文件某常量含 `.format()` 之外的占位（如 `{context}` 以外参数），改写时必须保留同名占位符；以「改写后用原 nodes 调用方式跑通测试」为准。

- [ ] **Step 2: 换规则关键词与残留文案**

① `nodes.py:144-148`：

```python
_SPECIALIZED_KEYWORDS = (
    "商品", "价格", "多少钱", "优惠", "参数", "规格", "库存", "发货", "物流",
    "退换", "保修", "推荐", "对比", "哪个好", "值得买", "评价", "销量",
    "矿泉水", "饮料", "零食", "牛奶", "粮油", "调味",
)
```

② `nodes.py` 文案替换（`rg "课程" backend/agents/qa/` 找全）：
- `:643` 附近「课程知识库」→「商品库」
- `:505` 附近默认 source「课程文档」→「商品资料」
- 其他「学员/助教/课程」字样按同一语义替换（注释也换，避免误导）。

- [ ] **Step 3: 回归测试**

重启后端，Run: `& $py -m pytest scripts/manual_tests/test_m2_qa_chat.py scripts/manual_tests/test_m2_retrieval.py -v`
Expected: 全 passed（RAG 路径未被提示词改动破坏）
人工抽查一次非流式回答文案：应为导购口吻、无「课程/学员」字样。

---

### Task 4: 前端商品列表页（API 封装 + 列表页 + 路由 + 菜单）

**Files:**
- Create: `frontend/src/api/products.ts`
- Create: `frontend/src/views/product/ProductListView.vue`
- Modify: `frontend/src/router/index.ts`（children 加 1 条）
- Modify: `frontend/src/components/layout/Sidebar.vue`（菜单加 1 项）
- Gate: `cd frontend && npm run build`（vue-tsc 类型检查）

**Interfaces:**
- Consumes: `GET /api/v1/products?page&page_size&category&keyword` → `{total, items:[{id,title,category,price,currency,rating,image_url}]}`（M1 Task 9 契约）；`client.ts` 既有 axios 实例
- Produces（Task 5 依赖）:
  - `frontend/src/api/products.ts`：`export interface ProductListItem { id: string; title: string; category: string | null; price: string; currency: string; rating: number | null; image_url: string | null }`；`export interface ProductDetail extends ProductListItem { description: string | null; params: Record<string, unknown>; url: string; source: string; review_count: number }`；`export const productsApi = { list(params: { page?: number; page_size?: number; category?: string | null; keyword?: string | null }): Promise<{ data: { total: number; items: ProductListItem[] } }>; detail(id: string): Promise<{ data: ProductDetail }> }`
  - 路由 name：`products`（path `products`）、`product-detail`（path `products/:id`，Task 5 挂）

- [ ] **Step 1: 写 API 封装**

新建 `frontend/src/api/products.ts`：

```ts
// frontend/src/api/products.ts
import client from './client'

export interface ProductListItem {
  id: string
  title: string
  category: string | null
  price: string
  currency: string
  rating: number | null
  image_url: string | null
}

export interface ProductDetail extends ProductListItem {
  description: string | null
  params: Record<string, unknown>
  url: string
  source: string
  review_count: number
}

export interface ProductListResponse {
  total: number
  items: ProductListItem[]
}

export const productsApi = {
  list: (params: { page?: number; page_size?: number; category?: string | null; keyword?: string | null }) =>
    client.get<ProductListResponse>('/products', { params }),
  detail: (id: string) => client.get<ProductDetail>(`/products/${id}`),
}
```

- [ ] **Step 2: 写列表页**

新建 `frontend/src/views/product/ProductListView.vue`（沿用 Dashboard 卡片网格 + ExamSubmit 搜索条模式；图片用 `image_url` 直连后端需带 token——**图片接口要 Authorization，`<img>` 无法带头**，故列表图用 `v-if` 判断后经 `fetch→blob` 或直接省略缩略图；M2 决策：**列表不显示图片，详情页显示**——详情图由前端 fetch blob 创建 objectURL，见 Task 5。本页纯文字卡片）：

```vue
<!-- frontend/src/views/product/ProductListView.vue -->
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { productsApi, type ProductListItem } from '@/api/products'

const router = useRouter()
const loading = ref(false)
const items = ref<ProductListItem[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = 12
const keyword = ref('')
const category = ref<string | null>(null)
const categories = ref<string[]>([])

async function load() {
  loading.value = true
  try {
    const { data } = await productsApi.list({
      page: page.value,
      page_size: pageSize,
      keyword: keyword.value || null,
      category: category.value,
    })
    items.value = data.items
    total.value = data.total
    // 类目选项：从当前页聚合（M2 轻量做法，避免后端加接口）
    const set = new Set(categories.value)
    data.items.forEach((it) => { if (it.category) set.add(it.category) })
    categories.value = [...set].sort()
  } catch (e) {
    ElMessage.error('商品列表加载失败')
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}
function goDetail(id: string) {
  router.push(`/products/${id}`)
}
watch(page, load)
onMounted(load)
</script>

<template>
  <div class="product-list">
    <div class="toolbar">
      <el-input
        v-model="keyword" placeholder="搜索商品名称/简介" clearable
        style="width: 280px" :prefix-icon="Search" @keyup.enter="search" @clear="search"
      />
      <el-select v-model="category" placeholder="全部类目" clearable style="width: 160px" @change="search">
        <el-option v-for="c in categories" :key="c" :label="c" :value="c" />
      </el-select>
      <el-button type="primary" @click="search">搜索</el-button>
    </div>

    <div v-loading="loading" class="grid">
      <el-card
        v-for="p in items" :key="p.id" shadow="hover" class="card"
        @click="goDetail(p.id)"
      >
        <div class="card-title">{{ p.title }}</div>
        <div class="card-meta">
          <span v-if="p.category" class="tag">{{ p.category }}</span>
          <span v-if="p.rating" class="rating">★ {{ p.rating }}</span>
        </div>
        <div class="card-price">
          <span class="currency">{{ p.currency === 'CNY' ? '¥' : p.currency }}</span>
          <span class="price">{{ p.price }}</span>
        </div>
      </el-card>
      <el-empty v-if="!loading && items.length === 0" description="没有匹配的商品" />
    </div>

    <el-pagination
      v-model:current-page="page" :page-size="pageSize" :total="total"
      layout="prev, pager, next, total" class="pager"
    />
  </div>
</template>

<style scoped>
.product-list { max-width: 1100px; }
.toolbar { display: flex; gap: 12px; margin-bottom: 16px; }
.grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; min-height: 200px; }
.card { cursor: pointer; }
.card :deep(.el-card__body) { padding: 16px; }
.card-title { font-size: 15px; font-weight: 600; line-height: 1.4; height: 42px; overflow: hidden; }
.card-meta { display: flex; justify-content: space-between; margin: 8px 0; color: #909399; font-size: 12px; }
.tag { background: #f0f2f5; border-radius: 4px; padding: 2px 8px; }
.rating { color: #e6a23c; }
.card-price { color: #f56c6c; }
.currency { font-size: 12px; margin-right: 2px; }
.price { font-size: 20px; font-weight: 700; }
.pager { margin-top: 20px; justify-content: center; }
</style>
```

- [ ] **Step 3: 挂路由**

`frontend/src/router/index.ts` 的 children 中（`qa` 路由旁）追加：

```ts
    {
      path: 'products',
      name: 'products',
      component: () => import('@/views/product/ProductListView.vue'),
    },
```

- [ ] **Step 4: 加侧边栏菜单**

`Sidebar.vue`：import `Shop`（或 `Goods`、`Menu` 任一 Element 图标，确认 `@element-plus/icons-vue` 有导出）；在「智能问答」菜单项之前插入：

```html
    <RouterLink to="/products" class="nav-item" :class="{ 'nav-item--active': isActive('/products') }">
      <el-icon><Shop /></el-icon><span>商品浏览</span>
    </RouterLink>
```

- [ ] **Step 5: 构建门禁**

Run: `cd frontend; npm run build`
Expected: vue-tsc 无类型错误、构建成功。若既有项目 build 本就有历史报错，先 `git status` 确认非本次引入（本仓库无 git 则记录报错清单比对），只修本页新增问题。

- [ ] **Step 6: 页面手测**

前后端都启动（前端 `npm run dev`），登录后点「商品浏览」：
Expected: 94 商品分页展示、关键词「牛奶」能筛出相关商品、点类目筛选生效、点卡片进详情（404 由 Task 5 补齐——本步允许详情 404，但列表必须正常）。

---

### Task 5: 商品详情页 + 「问 AI」打通

**Files:**
- Create: `frontend/src/views/product/ProductDetailView.vue`
- Modify: `frontend/src/router/index.ts`（再加 1 条）
- Modify: `frontend/src/views/qa/QAChatView.vue`（route.query 读取 + 自动发送 + body 带 product_id）
- Gate: `npm run build` + 黄金路径手测

**Interfaces:**
- Consumes: `GET /api/v1/products/{id}`（ProductDetail）；图片经 `fetch` 带 Authorization 取 blob；QAChatView 既有 SSE 直连（body 将新增 `product_id` 可选字段，后端 Task 2 已支持）
- Produces: 详情页「问问 AI」→ `router.push({ path: '/qa', query: { q, product_id } })`；QAChatView 支持 `route.query.q`（预填并自动发送）与 `route.query.product_id`（透传进每次 `/qa/chat/stream` body）

- [ ] **Step 1: 写详情页**

新建 `frontend/src/views/product/ProductDetailView.vue`：

```vue
<!-- frontend/src/views/product/ProductDetailView.vue -->
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { productsApi, type ProductDetail } from '@/api/products'
import { useAuthStore } from '@/stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const detail = ref<ProductDetail | null>(null)
const loading = ref(false)
const imageUrl = ref('')

async function loadImage(productId: string) {
  const token = localStorage.getItem('edu-agent-token')
  try {
    const resp = await fetch(
      `${import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}/api/v1/products/${productId}/image`,
      { headers: { Authorization: `Bearer ${token}` } },
    )
    if (!resp.ok) return
    const blob = await resp.blob()
    imageUrl.value = URL.createObjectURL(blob)
  } catch { /* 无图不阻断 */ }
}

async function load() {
  loading.value = true
  imageUrl.value = ''
  try {
    const { data } = await productsApi.detail(String(route.params.id))
    detail.value = data
    if (data.image_url) await loadImage(data.id)
  } catch {
    ElMessage.error('商品加载失败')
    router.push('/products')
  } finally {
    loading.value = false
  }
}

function askAi() {
  if (!detail.value) return
  const q = `介绍一下「${detail.value.title}」，适合我吗？`
  router.push({ path: '/qa', query: { q, product_id: detail.value.id } })
}

function paramEntries(p: Record<string, unknown> | null | undefined): Array<[string, string]> {
  if (!p) return []
  return Object.entries(p).map(([k, v]) => [k, typeof v === 'object' ? JSON.stringify(v) : String(v)])
}

watch(() => route.params.id, load)
onMounted(load)
</script>

<template>
  <div v-loading="loading" class="product-detail">
    <el-page-header content="商品详情" @back="router.push('/products')" />
    <template v-if="detail">
      <div class="main">
        <div class="media">
          <img v-if="imageUrl" :src="imageUrl" :alt="detail.title" class="image" />
          <div v-else class="image placeholder">暂无图片</div>
        </div>
        <div class="info">
          <h1 class="title">{{ detail.title }}</h1>
          <div class="sub">
            <el-tag v-if="detail.category" size="small">{{ detail.category }}</el-tag>
            <span v-if="detail.rating" class="rating">★ {{ detail.rating }}</span>
            <span class="reviews">{{ detail.review_count }} 条评价</span>
          </div>
          <div class="price-row">
            <span class="currency">{{ detail.currency === 'CNY' ? '¥' : detail.currency }}</span>
            <span class="price">{{ detail.price }}</span>
          </div>
          <p class="desc">{{ detail.description || '暂无详情介绍' }}</p>
          <el-button type="primary" size="large" :icon="ChatDotRound" @click="askAi">
            问问 AI · 了解是否适合我
          </el-button>
        </div>
      </div>

      <el-card shadow="never" class="params-card">
        <template #header><span>规格参数</span></template>
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item v-for="[k, v] in paramEntries(detail.params)" :key="k" :label="k">
            {{ v }}
          </el-descriptions-item>
          <el-descriptions-item v-if="paramEntries(detail.params).length === 0" label="参数">
            暂无
          </el-descriptions-item>
        </el-descriptions>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.product-detail { max-width: 1000px; }
.main { display: flex; gap: 32px; margin-top: 20px; }
.media { flex: 0 0 320px; }
.image { width: 320px; height: 320px; object-fit: cover; border-radius: 8px; border: 1px solid #ebeef5; }
.placeholder { display: flex; align-items: center; justify-content: center; color: #c0c4cc; background: #f5f7fa; }
.info { flex: 1; }
.title { font-size: 22px; margin: 0 0 12px; }
.sub { display: flex; gap: 12px; align-items: center; color: #909399; font-size: 13px; margin-bottom: 16px; }
.rating { color: #e6a23c; }
.price-row { color: #f56c6c; margin-bottom: 16px; }
.currency { font-size: 14px; }
.price { font-size: 32px; font-weight: 700; }
.desc { color: #606266; line-height: 1.7; margin-bottom: 24px; }
.params-card { margin-top: 24px; }
</style>
```

- [ ] **Step 2: 挂详情路由**

`router/index.ts` children 追加：

```ts
    {
      path: 'products/:id',
      name: 'product-detail',
      component: () => import('@/views/product/ProductDetailView.vue'),
    },
```

- [ ] **Step 3: QAChatView 支持 query 预填与 product_id**

在 `QAChatView.vue` script 中：

① 增加 import：`import { useRoute } from 'vue-router'`（已有 useRouter），声明 `const route = useRoute()`。
② 新增 ref：`const productContextId = ref<string | null>(null)`。
③ 在 `onMounted`（或现有初始化函数）末尾追加：

```ts
  // 从商品详情页「问问 AI」进入：携带商品上下文与预填问题
  const q = route.query.q
  const pid = route.query.product_id
  if (typeof pid === 'string' && pid) productContextId.value = pid
  if (typeof q === 'string' && q.trim()) {
    await sendMessage(q.trim())   // 复用既有发送函数（含 SSE 逻辑）；若发送函数名不同按现实改
  }
```

④ SSE fetch 的 body JSON 中追加字段（`:233` 附近 `JSON.stringify({...})`）：

```ts
        ...(productContextId.value ? { product_id: productContextId.value } : {}),
```

⑤ `route.query` 变化时重置（从另一个商品再次进入同一页面）：`watch(() => route.query, ...)`——若 keep-alive 缓存 `QAChatView`（AppLayout include 中有），需在 `onActivated` 里重复 ③ 的读取逻辑；**最小实现：同时挂 onMounted 与 onActivated**。

- [ ] **Step 4: 构建门禁**

Run: `cd frontend; npm run build`
Expected: 类型检查与构建通过

- [ ] **Step 5: 黄金路径手测（M2 验收）**

前后端启动后完整走一遍：
1. 登录 → 侧边栏「商品浏览」→ 列表 94 商品、分页/搜索正常
2. 点「农夫山泉 饮用天然水」进详情 → 价格/参数/评价数正确、图片显示、无图则占位
3. 点「问问 AI」→ 跳 `/qa` 且自动发送「介绍一下…」→ 流式回答为导购口吻、提到该商品信息（RAG）
4. 问答页手动问「有没有便宜的零食」→ 回答基于商品库内容
5. 回到详情页换一个商品再点「问问 AI」→ 新会话/新问题携带的是新 product_id（重进页面生效）
6. `/docs` 与 `tests/` 单测回归无破坏

Expected: 6 步全部通过即 M2 完成。

---

## M2 完成定义（DoD）

- [ ] `retrieve` 打到 `product_knowledge`，`product_id` 过滤生效（test_m2_retrieval 通过）
- [ ] `/qa/chat` 商品问题 `answer_mode == "rag"`，带 `product_id` 可限定（test_m2_qa_chat 2 passed）
- [ ] QA 提示词/规则/文案无教育残留（`rg "课程|学员|助教" backend/agents/qa/` 无业务残留，注释除外可选清理）
- [ ] 商品列表页/详情页上线，`npm run build` 通过
- [ ] 黄金路径 6 步手测通过
- [ ] `tests/` 7 passed、旧 exam/resume/interview 路由 import 无破坏

## 明确不做（M2 范围外）

- 意图分类器/`/chat` 统一入口电商化（M3）
- 售后/评价分析/导购 Agent（M4/M5）
- 详情页评价列表展示（评价分析是 M4，M2 只显示 `review_count` 数字）
- 商品图片列表缩略图（需 token 的 img 方案，M2 列表纯文字卡片）
- 旧教育页面删除、旧 `knowledge_domain` 集合清理（M5）
- 前端主题/视觉重设计（换皮在各里程碑顺带做，M2 只求功能通）

