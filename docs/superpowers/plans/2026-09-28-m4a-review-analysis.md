# M4a 商品评价分析 Agent（Resume 平移）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付四个电商 Agent 中的第三个——**评价分析 Agent**：输入商品 ID，异步拉取该商品 30 条评价，六维并行评分 + 优缺点挖掘 + 总结，报告持久化到 `review_reports`，商品详情页一键触发并可视化查看。

**Architecture:** 新建 `backend/agents/review/`（复制 Resume 的线性图 + `asyncio.gather` 并行评分骨架，不就地改 Resume——教育页面保留到 M5）；API 用 `/api/v1/reviews` 前缀（Resume 平移位）；前端复制 ResumeReportView 四态轮询模式 + 复用 `DimensionScoreCard`；`review_reports.scores` JSONB 内嵌维度与 issues（**不加列**）。

**Tech Stack:** LangGraph 线性图（无 checkpointer，一次性任务）、`get_structured_llm` 结构化输出、FastAPI 后台任务 + 前端 5s 轮询、Vue3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §4.3、§5.1、§7 M4

## Global Constraints

- Python：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`；前端门禁 `npm run build`（0 错误）。
- 数据现状（实查）：`product_reviews` 3180 行 / 106 商品（**含已下架商品**）；分析只允许针对 `is_active=TRUE` 的商品；`review_reports` 0 行、列为 `id, tenant_id, product_id, triggered_by, scores, pros, cons, summary, status(pending|processing|done|failed), error_msg, created_at, updated_at`——**不改表结构**。
- `review_reports.scores` JSONB 结构固定为：`{"weighted_score": float, "dimensions": [{key, name, score, weight, issues: string[], suggestions: string[]}]}`；`pros`/`cons` 为 `string[]`；`summary` 为纯文本。
- LLM：`get_llm/get_structured_llm`；agent_type 新增 `"review"`（llm_factory 路由表追加，指向与 resume 相同的 chat 模型），失败兜底复用 `"resume"` 键。
- 异步模式照抄 resume.py：`asyncio.create_task` + `_background_tasks` 强引用 + done_callback 失败标 failed + 15min 超时兜底。
- **避开 resume/graph.py:49 的坑**：`build_review_graph` 保持可调用函数，返回 `builder.compile()`，不得把函数重赋值为实例。
- 教育 Resume/Exam/Interview Agent 与页面不动（M5 清理）。
- 详情页/评价数据在 M2/M1b 已就绪；不改 `/products` 契约。

## 复用/新建文件总览

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/agents/review/state.py` | ReviewState + Pydantic 伴生类 | 新建 |
| `backend/agents/review/prompts.py` | 6 维提示词 + 优缺点 + 总结 | 新建 |
| `backend/agents/review/nodes.py` | 5 节点线性图逻辑 | 新建 |
| `backend/agents/review/graph.py` | build_review_graph() | 新建 |
| `backend/core/llm_factory.py` | 路由表加 `"review"` 键 | 修改（1 行） |
| `backend/api/v1/reviews.py` | 触发/查询/最新报告三端点 | 新建 |
| `backend/api/router.py` | 挂 `/reviews` 前缀 | 修改（2 行） |
| `frontend/src/api/reviews.ts` | 报告 API 封装 | 新建 |
| `frontend/src/views/review/ReviewReportView.vue` | 报告页（四态+轮询） | 新建 |
| `frontend/src/views/product/ProductDetailView.vue` | 「AI 口碑分析」触发按钮 | 修改 |
| `frontend/src/router/index.ts` | 报告页路由 | 修改 |
| `backend/api/v1/unified_chat.py` | review 意图引导文案更新（指向详情页触发） | 修改（1 处） |
| `scripts/manual_tests/test_m4a_review_report.py` | 端到端冒烟（真实 LLM） | 新建 |

---

### Task 1: 评价分析 Agent（backend/agents/review/）

**Files:**
- Create: `backend/agents/review/__init__.py`（空）、`state.py`、`prompts.py`、`nodes.py`、`graph.py`
- Modify: `backend/core/llm_factory.py`（agent_type 路由表加 `"review"`）
- Test: `scripts/manual_tests/test_m4a_review_agent.py`（直接跑图的冒烟）

**Interfaces:**
- Consumes: `product_reviews` / `products` / `review_reports` 表；`get_llm/get_structured_llm`；`AsyncSessionLocal`
- Produces（后续任务依赖）:
  - `build_review_graph()` → 编译后的 CompiledStateGraph（**可调用函数**）
  - `initial_state = {"report_id": str, "tenant_id": str, "product_id": str, "triggered_by": str, ...}`
  - 图终态：`review_reports` 行 `status='done'`，`scores/pros/cons/summary` 填充
  - 六维 key 固定：`quality, logistics, service, value, fit, repurchase`（权重 0.30/0.10/0.15/0.20/0.10/0.15）

- [ ] **Step 1: 写 state**

`backend/agents/review/state.py`：

```python
# backend/agents/review/state.py
from typing import Annotated, Optional
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class DimensionResult(BaseModel):
    """单维度评分结果（结构化输出用）"""
    score: int = Field(..., ge=0, le=100, description="0-100 分")
    issues: list[str] = Field(default_factory=list, description="该维度发现的问题，最多3条")
    suggestions: list[str] = Field(default_factory=list, description="改进建议，最多3条")


class ProsCons(BaseModel):
    """优缺点挖掘结果"""
    pros: list[str] = Field(..., description="优点清单，2~4条，每条15~40字")
    cons: list[str] = Field(..., description="缺点清单，2~4条，每条15~40字")


class ReviewSummary(BaseModel):
    """报告总结"""
    summary: str = Field(..., description="120~200字的中文总结，客观中立")


class ReviewState(TypedDict):
    """评价分析 Agent 状态（一次性线性图，无 checkpointer）"""
    messages: Annotated[list[BaseMessage], add_messages]
    tenant_id: str
    product_id: str
    report_id: str
    triggered_by: str
    product_title: str                 # 商品名（提示词上下文）
    product_category: Optional[str]
    reviews: list[dict]                # [{author, rating, content}] 最多30条
    dimension_scores: list[dict]       # [{key,name,score,weight,issues,suggestions}]
    weighted_score: float
    pros: list[str]
    cons: list[str]
    summary: Optional[str]
    fallback_used: bool
```

- [ ] **Step 2: 写 prompts**

`backend/agents/review/prompts.py`（占位符与 nodes 的 format 严格一致）：

```python
# backend/agents/review/prompts.py
# 商品评价分析提示词（M4a：由简历审查六维评分平移）

SYSTEM_PROMPT = (
    "你是电商平台的口碑分析专家，基于真实买家评价产出客观、可执行的分析结论。"
    "要求：结论必须由评价证据支撑，不编造；语言中文、简洁、无营销腔。"
)

# 六维定义与权重（与 nodes.SIX_DIMENSIONS 保持一致，此处仅提示词侧重）
DIMENSION_REVIEW_PROMPTS = {
    "quality": """分析买家评价中关于【商品质量】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0-100 整数, "issues": ["问题", ...], "suggestions": ["建议", ...]}}
评分标准：差评集中于质量/耐用/做工 → 低分；好评质量反馈多 → 高分。issues/suggestions 各最多3条，每条15~40字。""",
    "logistics": """分析买家评价中关于【物流配送】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0-100 整数, "issues": [...], "suggestions": [...]}}
关注：发货速度、包装完好、到货时效。评价未提及物流时按中性60分处理。""",
    "service": """分析买家评价中关于【商家服务】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0-100 整数, "issues": [...], "suggestions": [...]}}
关注：客服响应、售后态度。未提及时按中性60分处理。""",
    "value": """分析买家评价中关于【性价比】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0-100 整数, "issues": [...], "suggestions": [...]}}
关注：值不值、划算、贵/便宜的主观反馈。""",
    "fit": """分析买家评价中关于【适配性/符合预期】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0-100 整数, "issues": [...], "suggestions": [...]}}
关注：与描述相符程度、使用场景是否匹配、规格是否合适。""",
    "repurchase": """分析买家评价中关于【复购意愿/推荐意愿】的表现。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"score": 0-100 整数, "issues": [...], "suggestions": [...]}}
关注：会回购、推荐给朋友、已回购等正向信号；差评中的劝退表达为负向信号。""",
}

MINE_PROS_CONS_PROMPT = """从买家评价中提炼该商品的优缺点。
商品：{product_title}
评价样本：
{reviews_text}
只输出 JSON：{{"pros": ["优点", ...], "cons": ["缺点", ...]}}
pros/cons 各 2~4 条，每条 15~40 字，必须能在评价样本中找到依据。"""

GENERATE_SUMMARY_PROMPT = """为该商品生成口碑分析总结。
商品：{product_title}（类目：{product_category}）
加权总分：{weighted_score}（0-100）
六维得分：{scores_summary}
优点：{pros}
缺点：{cons}
输出 120~200 字中文总结：先给整体结论，再点出最突出的优缺点，最后给一句选购建议。只输出总结正文。"""
```

（实现时若 `DIMENSION_REVIEW_PROMPTS` 的键与 nodes `SIX_DIMENSIONS` 不一致，以 `SIX_DIMENSIONS` 为准对齐。）

- [ ] **Step 3: 写 nodes（5 节点线性图）**

`backend/agents/review/nodes.py` 核心结构：

```python
# backend/agents/review/nodes.py
import asyncio
import json
from langchain_core.messages import HumanMessage
from sqlalchemy import text

from backend.core.llm_factory import get_llm, get_structured_llm
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal
from backend.agents.review.prompts import (
    SYSTEM_PROMPT, DIMENSION_REVIEW_PROMPTS, MINE_PROS_CONS_PROMPT, GENERATE_SUMMARY_PROMPT,
)
from backend.agents.review.state import (
    ReviewState, DimensionResult, ProsCons, ReviewSummary,
)

logger = get_logger(__name__)

# 六维定义（key 与 prompts.DIMENSION_REVIEW_PROMPTS 对齐；权重和=1.0）
SIX_DIMENSIONS = [
    {"key": "quality",    "name": "商品质量", "weight": 0.30},
    {"key": "logistics",  "name": "物流配送", "weight": 0.10},
    {"key": "service",    "name": "商家服务", "weight": 0.15},
    {"key": "value",      "name": "性价比",   "weight": 0.20},
    {"key": "fit",        "name": "符合预期", "weight": 0.10},
    {"key": "repurchase", "name": "复购意愿", "weight": 0.15},
]

MAX_REVIEWS = 30
_REVIEW_CHARS = 60          # 单条评价进提示词的截断长度


def _reviews_block(reviews: list[dict]) -> str:
    lines = []
    for i, r in enumerate(reviews[:MAX_REVIEWS], 1):
        stars = r.get("rating") or "?"
        content = (r.get("content") or "")[:_REVIEW_CHARS]
        lines.append(f"{i}. [{stars}星] {content}")
    return "\n".join(lines)


async def load_reviews_node(state: ReviewState) -> dict:
    """按 product_id 拉取商品信息与评价（只取 active 商品）。"""
    async with AsyncSessionLocal() as db:
        prod = (await db.execute(text(
            "SELECT title, category FROM products WHERE id = :pid AND is_active"
        ), {"pid": state["product_id"]})).first()
        if prod is None:
            raise ValueError(f"product not found or inactive: {state['product_id']}")
        rows = (await db.execute(text(
            "SELECT author, rating, content FROM product_reviews "
            "WHERE product_id = :pid ORDER BY created_at DESC LIMIT 30"
        ), {"pid": state["product_id"]})).fetchall()
    reviews = [{"author": r[0], "rating": r[1], "content": r[2]} for r in rows]
    if not reviews:
        raise ValueError("no reviews for product")
    logger.info("review.load_done", product=prod[0], n=len(reviews))
    return {"product_title": prod[0], "product_category": prod[1], "reviews": reviews}


async def run_dimensions_node(state: ReviewState) -> dict:
    """六维并行评分（asyncio.gather，平移自 Resume 六维骨架）。"""
    block = _reviews_block(state["reviews"])

    async def review_one(dim: dict) -> dict:
        prompt = DIMENSION_REVIEW_PROMPTS[dim["key"]].format(
            product_title=state["product_title"], reviews_text=block,
        )
        for attempt in range(3):
            try:
                result = await get_structured_llm("review", DimensionResult).ainvoke(
                    [HumanMessage(content=SYSTEM_PROMPT + "\n\n" + prompt)]
                )
                return {**dim, "score": result.score,
                        "issues": result.issues, "suggestions": result.suggestions}
            except Exception as e:
                if attempt == 2:
                    logger.warning("review.dimension_failed", dim=dim["key"], error=str(e))
                    return {**dim, "score": 60, "issues": [], "suggestions": []}  # 降级中性分
                await asyncio.sleep(1)

    results = await asyncio.gather(*[review_one(d) for d in SIX_DIMENSIONS])
    weighted = round(sum(r["score"] * r["weight"] for r in results), 1)
    return {"dimension_scores": list(results), "weighted_score": weighted}


async def mine_pros_cons_node(state: ReviewState) -> dict:
    """优缺点挖掘。"""
    prompt = MINE_PROS_CONS_PROMPT.format(
        product_title=state["product_title"], reviews_text=_reviews_block(state["reviews"]),
    )
    try:
        result = await get_structured_llm("review", ProsCons).ainvoke(
            [HumanMessage(content=SYSTEM_PROMPT + "\n\n" + prompt)]
        )
        return {"pros": result.pros, "cons": result.cons, "fallback_used": False}
    except Exception as e:
        logger.warning("review.mine_failed", error=str(e))
        return {"pros": [], "cons": [], "fallback_used": True}


async def generate_summary_node(state: ReviewState) -> dict:
    scores_summary = "、".join(
        f"{d['name']} {d['score']}" for d in state["dimension_scores"]
    )
    prompt = GENERATE_SUMMARY_PROMPT.format(
        product_title=state["product_title"],
        product_category=state.get("product_category") or "未分类",
        weighted_score=state["weighted_score"],
        scores_summary=scores_summary,
        pros="；".join(state.get("pros") or []) or "无",
        cons="；".join(state.get("cons") or []) or "无",
    )
    try:
        result = await get_structured_llm("review", ReviewSummary).ainvoke(
            [HumanMessage(content=prompt)]
        )
        return {"summary": result.summary}
    except Exception as e:
        logger.warning("review.summary_failed", error=str(e))
        return {"summary": f"加权总分 {state['weighted_score']} 分，详见各维度得分。"}


async def save_results_node(state: ReviewState) -> dict:
    """报告持久化到 review_reports（status=done；失败由 API 层 done_callback 标 failed）。"""
    scores = {
        "weighted_score": state["weighted_score"],
        "dimensions": state["dimension_scores"],
    }
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE review_reports SET scores = :scores, pros = :pros, cons = :cons, "
            "summary = :summary, status = 'done', updated_at = NOW() WHERE id = :rid"
        ), {
            "scores": json.dumps(scores, ensure_ascii=False),
            "pros": json.dumps(state.get("pros") or [], ensure_ascii=False),
            "cons": json.dumps(state.get("cons") or [], ensure_ascii=False),
            "summary": state.get("summary"),
            "rid": state["report_id"],
        })
        await db.commit()
    logger.info("review.saved", report_id=state["report_id"], score=state["weighted_score"])
    return {}
```

- [ ] **Step 4: 写 graph（保持可调用函数）**

`backend/agents/review/graph.py`：

```python
# backend/agents/review/graph.py
# 一次性线性图（无 checkpointer）——build_review_graph 必须保持为函数，
# 不要写成 build_review_graph = build_review_graph()（resume/graph.py 的历史坑）
from langgraph.graph import StateGraph, START, END

from backend.agents.review.state import ReviewState
from backend.agents.review.nodes import (
    load_reviews_node,
    run_dimensions_node,
    mine_pros_cons_node,
    generate_summary_node,
    save_results_node,
)


def build_review_graph():
    builder = StateGraph(ReviewState)
    builder.add_node("load_reviews",     load_reviews_node)
    builder.add_node("run_dimensions",   run_dimensions_node)
    builder.add_node("mine_pros_cons",   mine_pros_cons_node)
    builder.add_node("generate_summary", generate_summary_node)
    builder.add_node("save_results",     save_results_node)

    builder.add_edge(START, "load_reviews")
    builder.add_edge("load_reviews", "run_dimensions")
    builder.add_edge("run_dimensions", "mine_pros_cons")
    builder.add_edge("mine_pros_cons", "generate_summary")
    builder.add_edge("generate_summary", "save_results")
    builder.add_edge("save_results", END)
    return builder.compile()
```

- [ ] **Step 5: llm_factory 加 `"review"` 路由**

读 `backend/core/llm_factory.py` 找 agent_type 路由表（约 :36），追加与 `"resume"` 同值的一行：

```python
        "review":   "deepseek-chat",     # M4a 评价分析
```

（若 `get_structured_llm` 对未知 agent_type 有校验，必须加；若实现为透传可跳过，报告说明。）

- [ ] **Step 6: 写 Agent 级冒烟（真实 LLM，直接跑图）**

`scripts/manual_tests/test_m4a_review_agent.py`：

```python
# scripts/manual_tests/test_m4a_review_agent.py
# 直接跑评价分析图（真实 LLM 8 次调用，约 1~3 分钟；需 PG）
import asyncio
import uuid

from sqlalchemy import text

from backend.agents.review.graph import build_review_graph
from backend.dependencies import AsyncSessionLocal


def test_review_graph_end_to_end():
    asyncio.run(_run())


async def _run():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT p.id FROM products p "
            "JOIN product_reviews r ON r.product_id = p.id "
            "WHERE p.is_active GROUP BY p.id ORDER BY count(r.id) DESC LIMIT 1"
        ))).first()
        assert row, "no active product with reviews"
        product_id = str(row[0])
        rid = str(uuid.uuid4())
        # 造一行 processing 报告（API 层正式实现前的测试脚手架）
        await db.execute(text(
            "INSERT INTO review_reports (id, tenant_id, product_id, status) "
            "VALUES (:rid, 'tenant_default', :pid, 'processing')"
        ), {"rid": rid, "pid": product_id})
        await db.commit()

    graph = build_review_graph()
    await graph.ainvoke({
        "messages": [],
        "tenant_id": "tenant_default",
        "product_id": product_id,
        "report_id": rid,
        "triggered_by": None,
        "product_title": "", "product_category": None, "reviews": [],
        "dimension_scores": [], "weighted_score": 0.0,
        "pros": [], "cons": [], "summary": None, "fallback_used": False,
    })

    async with AsyncSessionLocal() as db:
        rep = (await db.execute(text(
            "SELECT status, scores, pros, cons, summary FROM review_reports WHERE id = :rid"
        ), {"rid": rid})).first()
    assert rep and rep[0] == "done", rep
    scores = rep[1]
    assert isinstance(scores, dict) and len(scores.get("dimensions", [])) == 6
    assert 0 < scores["weighted_score"] <= 100
    assert isinstance(rep[2], list) and isinstance(rep[3], list)
    assert rep[4] and len(rep[4]) >= 30
```

- [ ] **Step 7: 运行确认通过**

Run: `& $py -m pytest scripts/manual_tests/test_m4a_review_agent.py -v`（超时 10 分钟）
Expected: PASS（status=done、6 维、总结非空）
若 `triggered_by` 列 NOT NULL 报错：改为插入实际 user id（查 users 表取一个）——以 DDL 为准最小调整。

---

### Task 2: `/reviews` API 与路由挂载

**Files:**
- Create: `backend/api/v1/reviews.py`
- Modify: `backend/api/router.py`（import + include，共 2 行）
- Test: `scripts/manual_tests/test_m4a_review_api.py`

**Interfaces:**
- Consumes: `build_review_graph`（Task 1）、resume.py 的后台任务模式（`_background_tasks`/done_callback/15min 超时——**抄结构，不 import 教育模块**）
- Produces:
  - `POST /api/v1/reviews/reports` body `{"product_id": str}` → 202 `{"report_id", "status": "processing"}`；404 商品不存在/下架；409 可选（同商品已有 processing 报告时直接返回该报告）
  - `GET /api/v1/reviews/reports/{report_id}` → `{"report_id","product_id","product_title","status","weighted_score","dimensions","pros","cons","summary","error_msg"}`（processing 时分数字段为 null；failed 带 error_msg）
  - `GET /api/v1/reviews/reports/latest?product_id=` → 同上结构；无记录 404
  - 全端点 `Depends(get_current_user)`

- [ ] **Step 1: 写冒烟测试**

`scripts/manual_tests/test_m4a_review_api.py`：

```python
# scripts/manual_tests/test_m4a_review_api.py
# 需后端 :8000 运行；触发真实分析并轮询至 done（超时给 5 分钟）
import time

import httpx

BASE = "http://localhost:8000"


def _headers() -> dict:
    r = httpx.post(f"{BASE}/api/v1/auth/login", json={
        "username": "student01@eduagent.local", "password": "Student@123456",
    })
    assert r.status_code == 200
    tok = r.json().get("access_token") or r.json().get("token")
    return {"Authorization": f"Bearer {tok}"}


def test_report_lifecycle():
    headers = _headers()
    # 找一个评价最多的 active 商品
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
```

- [ ] **Step 2: 确认失败**

Run（后端运行中）: `& $py -m pytest scripts/manual_tests/test_m4a_review_api.py -v`
Expected: FAIL（404，路由未挂）

- [ ] **Step 3: 实现 `backend/api/v1/reviews.py`**

结构（完整实现，后台任务段照抄 resume.py :21-131 的模式）：

```python
# backend/api/v1/reviews.py
# 评价分析报告 API（M4a：由 /resume 平移）——异步触发 + 轮询查询
import asyncio
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.agents.review.graph import build_review_graph
from backend.core.logger import get_logger
from backend.dependencies import AsyncSessionLocal, get_current_user

router = APIRouter()
logger = get_logger(__name__)

_graph = build_review_graph()            # 模块级编译一次
_background_tasks: set = set()           # 强引用防 GC（平移自 resume.py）
_TIMEOUT_MINUTES = 15


class ReportCreateRequest(BaseModel):
    product_id: str = Field(..., description="商品 ID")


def _track(task: asyncio.Task, report_id: str) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    def _on_done(t: asyncio.Task) -> None:
        if t.exception():
            logger.error("review.report_failed", report_id=report_id,
                         error=str(t.exception()))
            asyncio.ensure_future(_mark_failed(report_id, str(t.exception())[:500]))
    task.add_done_callback(_on_done)


async def _mark_failed(report_id: str, msg: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(text(
            "UPDATE review_reports SET status='failed', error_msg=:e, updated_at=NOW() "
            "WHERE id=:rid AND status='processing'"
        ), {"e": msg, "rid": report_id})
        await db.commit()


@router.post("/reports", status_code=202)
async def create_report(req: ReportCreateRequest, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        prod = (await db.execute(text(
            "SELECT id FROM products WHERE id=:pid AND is_active"
        ), {"pid": req.product_id})).first()
        if prod is None:
            raise HTTPException(status_code=404, detail="product not found")
        # 同商品已有 processing 报告 → 直接复用（幂等）
        existing = (await db.execute(text(
            "SELECT id FROM review_reports WHERE product_id=:pid AND status='processing'"
        ), {"pid": req.product_id})).first()
        if existing:
            return {"report_id": str(existing[0]), "status": "processing"}
        report_id = str(uuid.uuid4())
        await db.execute(text(
            "INSERT INTO review_reports (id, tenant_id, product_id, triggered_by, status) "
            "VALUES (:rid, :tid, :pid, :uid, 'processing')"
        ), {"rid": report_id, "tid": current_user["tenant_id"],
            "pid": req.product_id, "uid": current_user["user_id"]})
        await db.commit()

    task = asyncio.create_task(_graph.ainvoke({
        "messages": [],
        "tenant_id": current_user["tenant_id"],
        "product_id": req.product_id,
        "report_id": report_id,
        "triggered_by": current_user["user_id"],
        "product_title": "", "product_category": None, "reviews": [],
        "dimension_scores": [], "weighted_score": 0.0,
        "pros": [], "cons": [], "summary": None, "fallback_used": False,
    }))
    _track(task, report_id)
    logger.info("review.report_created", report_id=report_id)
    return {"report_id": report_id, "status": "processing"}


def _row_to_dict(row, title: str | None) -> dict:
    import json as _json
    scores = row[2]
    if isinstance(scores, str):
        scores = _json.loads(scores or "{}")
    scores = scores or {}
    pros, cons = row[3], row[4]
    if isinstance(pros, str):
        pros = _json.loads(pros or "[]")
    if isinstance(cons, str):
        cons = _json.loads(cons or "[]")
    return {
        "report_id": row[0], "product_id": row[1], "product_title": title,
        "status": row[5],
        "weighted_score": scores.get("weighted_score"),
        "dimensions": scores.get("dimensions", []),
        "pros": pros or [], "cons": cons or [],
        "summary": row[6], "error_msg": row[7],
    }


@router.get("/reports/latest")
async def get_latest_report(product_id: str, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        rid = (await db.execute(text(
            "SELECT id FROM review_reports WHERE product_id = :pid "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"pid": product_id})).scalar()
    if not rid:
        raise HTTPException(status_code=404, detail="no report")
    return await get_report(str(rid), current_user)


@router.get("/reports/{report_id}")
async def get_report(report_id: str, current_user: dict = Depends(get_current_user)):
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text(
            "SELECT r.id, r.product_id, r.scores, r.pros, r.cons, r.status, "
            "r.summary, r.error_msg, p.title "
            "FROM review_reports r JOIN products p ON p.id = r.product_id "
            "WHERE r.id = :rid"
        ), {"rid": report_id})).first()
        if row is None:
            raise HTTPException(status_code=404, detail="report not found")
        # 15min 超时兜底（平移自 resume.py）
        if row[5] == "processing":
            age = (await db.execute(text(
                "SELECT EXTRACT(EPOCH FROM (NOW() - created_at))/60 "
                "FROM review_reports WHERE id = :rid"
            ), {"rid": report_id})).scalar() or 0
            if age > _TIMEOUT_MINUTES:
                await db.execute(text(
                    "UPDATE review_reports SET status='failed', "
                    "error_msg='analysis timeout', updated_at=NOW() WHERE id=:rid"
                ), {"rid": report_id})
                await db.commit()
                row = (row[0], row[1], row[2], row[3], row[4], "failed",
                       row[6], "analysis timeout", row[8])
    return _row_to_dict(row, row[8])
```

（**注意注册顺序**：`/reports/latest` 必须定义在 `/reports/{report_id}` 之前——上面的顺序即为正确顺序，否则 `latest` 会被路径参数吞掉。实现后自测两个 GET 都通。）

- [ ] **Step 4: 挂路由**

`backend/api/router.py`：import 追加 `reviews`；include 追加：

```python
api_router.include_router(reviews.router, prefix="/reviews", tags=["评价分析"])  # M4a
```

- [ ] **Step 5: 重启后端跑冒烟**

Expected: `test_report_lifecycle` PASS（202 → 轮询 done → latest 命中）

---

### Task 3: 前端触发与报告页

**Files:**
- Create: `frontend/src/api/reviews.ts`、`frontend/src/views/review/ReviewReportView.vue`
- Modify: `frontend/src/views/product/ProductDetailView.vue`（触发按钮 + latest 检测）
- Modify: `frontend/src/router/index.ts`（1 条路由）
- Gate: `npm run build` + 手测

**Interfaces:**
- Consumes: Task 2 三端点；`DimensionScoreCard`（props: `dimension/score/weight/issues/suggestions`）
- Produces: 路由 name `review-report`（path `reviews/reports/:reportId`）；详情页按钮流程

- [ ] **Step 1: 写 `frontend/src/api/reviews.ts`**

```ts
// frontend/src/api/reviews.ts
import client from './client'

export interface ReviewDimension {
  key: string
  name: string
  score: number
  weight: number
  issues: string[]
  suggestions: string[]
}

export interface ReviewReport {
  report_id: string
  product_id: string
  product_title: string
  status: 'pending' | 'processing' | 'done' | 'failed'
  weighted_score: number | null
  dimensions: ReviewDimension[]
  pros: string[]
  cons: string[]
  summary: string | null
  error_msg: string | null
}

export const reviewsApi = {
  create: (productId: string) =>
    client.post<{ report_id: string; status: string }>('/reviews/reports', { product_id: productId }),
  get: (reportId: string) => client.get<ReviewReport>(`/reviews/reports/${reportId}`),
  latest: (productId: string) => client.get<ReviewReport>('/reviews/reports/latest', { params: { product_id: productId } }),
}
```

- [ ] **Step 2: 写报告页 `ReviewReportView.vue`**

四态渲染（skeleton / processing+5s 递归轮询 / failed / done），done 视图：

- 顶部总分卡（`weighted_score` 大数字 + 商品名 + 返回按钮回 `/products/:id`）
- `DimensionScoreCard` 六卡（el-row span=8，props 直接映射 dimensions 数组：`dimension=d.name, score, weight, issues, suggestions`）
- 优点（`el-tag type=success` 列表）/ 缺点（`el-tag type=danger` 列表）
- 总结段落

轮询与 mounted 竞态防护**照抄** `ResumeReportView.vue:110-152` 的模式（`mounted` 标志 + `setTimeout` 递归 + `route.params.reportId` 变化重载）。完整文件实现时参考该文件逐段改字段名，此处不重复贴全量代码——**字段映射**：`weighted_score/dimensions/pros/cons/summary/error_msg/status`（见 Step 1 接口）。

- [ ] **Step 3: 挂路由**

`router/index.ts` children 追加：

```ts
        // 口碑报告（M4a）
        {
          path: 'reviews/reports/:reportId',
          name: 'review-report',
          component: () => import('@/views/review/ReviewReportView.vue'),
        },
```

- [ ] **Step 4: 详情页触发按钮**

`ProductDetailView.vue` script 追加：

```ts
import { reviewsApi } from '@/api/reviews'

const existingReportId = ref<string | null>(null)
const analyzing = ref(false)

async function checkLatestReport() {
  if (!detail.value) return
  try {
    const { data } = await reviewsApi.latest(detail.value.id)
    if (data.status === 'done') existingReportId.value = data.report_id
  } catch { /* 404 = 无报告，忽略 */ }
}

async function analyzeReviews() {
  if (!detail.value) return
  analyzing.value = true
  try {
    const { data } = await reviewsApi.create(detail.value.id)
    router.push(`/reviews/reports/${data.report_id}`)
  } catch { /* 拦截器提示 */ }
  finally { analyzing.value = false }
}
```

`onMounted`/`watch` 的 `load()` 成功后调 `checkLatestReport()`；template 中「立即下单」旁：

```html
          <el-button size="large" :loading="analyzing" @click="analyzeReviews">
            {{ existingReportId ? '查看口碑报告' : 'AI 口碑分析' }}
          </el-button>
```

点击时若 `existingReportId` 存在且按钮文案为「查看」语义 → 直接 `router.push(/reviews/reports/${existingReportId})`（在 `analyzeReviews` 开头判断：`if (existingReportId.value && !analyzing.value) { router.push(...); return }`——注意与「重新分析」区分：**M4a 简化为有报告看报告，无报告才新建**；后端 202 幂等复用 processing 也兜底）。

- [ ] **Step 5: 构建 + 手测**

`npm run build` → 0 错误。手测：详情页点「AI 口碑分析」→ 跳报告页 processing 骨架 → 5s 轮询 → 六维卡+优缺点+总结渲染 → 返回详情页按钮变「查看口碑报告」→ 再点直达报告。

---

### Task 4: 统一入口 review 引导更新 + 全量回归

**Files:**
- Modify: `backend/api/v1/unified_chat.py`（`_GUIDANCE_BY_LABEL["review"]` 文案）
- Gate: 全套测试

- [ ] **Step 1: 更新 review 引导卡**

```python
    "review": {
        "message": "商品口碑报告已上线：请打开具体商品详情页，点击「AI 口碑分析」即可生成六维口碑报告。",
        "action_label": "去商品列表",
        "action_url": "/products",
    },
```

（service/guide 两张卡保留 M3 文案不变。）

- [ ] **Step 2: 全量回归**

重启后端：

```powershell
& $py -m pytest tests/ scripts/manual_tests/test_m2_retrieval.py scripts/manual_tests/test_m2_qa_chat.py scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py scripts/manual_tests/test_off_pipeline.py scripts/manual_tests/test_m3_unified_route.py scripts/manual_tests/test_m4a_review_api.py -q
```

Expected: 全 passed（约 20 个；`test_m4a_review_agent` 已在 Task 1 跑过，可不重复——若重复跑会在同商品再建一条报告，允许）

- [ ] **Step 3: 黄金路径手测**

1. 商品详情 → AI 口碑分析 → 报告页 processing → done 六维渲染
2. 返回详情 → 按钮变「查看口碑报告」→ 直达
3. `/chat` 输入「帮我分析一下这个商品的口碑」→ review 引导卡（新文案）
4. 教育 Resume 页面仍可访问（不破坏）

## M4a 完成定义（DoD）

- [ ] `POST /reviews/reports` 202 异步出报告，六维+优缺点+总结落库，15min 超时兜底
- [ ] 报告页四态渲染 + 轮询，详情页触发/查看闭环
- [ ] `/chat` review 意图引导更新；service/guide 引导不变
- [ ] `npm run build` 0 错误；全套 pytest 绿；教育页面无破坏

## 明确不做（M4a 范围外）

- 售后客服 Agent 与工单审批（M4b，本计划的姊妹篇）
- 多轮导购（M5）、教育代码清理（M5）
- 报告列表页 / 导出 PDF（YAGNI）
- 评价原文分页阅读页（报告页不展示 30 条原文）
- 表结构变更（scores JSONB 内嵌维度，已显式约定）
