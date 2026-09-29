# M5a 多轮导购 Agent（Interview 平移）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付最后一个电商能力——**多轮导购 Agent**：五阶段状态机对话（需求探询→预算确认→商品匹配→对比答疑→推荐收尾），结束时生成结构化推荐清单（写 `recommendation_results`），前端独立导购会话页 + 统一入口 `guide` 意图接通。

**Architecture:** 新建 `backend/agents/guide/`（保留 Interview 供 M5b 清理）：拓扑照抄 Interview——`load_context → check_stage →(条件边: finished→报告) → generate_response / generate_report → save_memory`，**砍掉**评估双轨 Think 节点（导购无需质量打分，spec §4.4 只要求状态机+阶段推进）；商品匹配用既有 `retrieve()` 向量检索 + PG 价格过滤；`recommendation_sessions` 补 `summary` 列（幂等迁移）；API/前端照抄 interview 五端点与三事件 SSE 协议。

**Tech Stack:** LangGraph 状态机 + MemorySaver、BGE-M3 混合检索、DeepSeek（新增 `"guide"` 路由键）、Vue3 + Element Plus。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §4.4、§5.1、§7 M5

## Global Constraints

- Python：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`；前端门禁 `npm run build`（0 错误）。
- 表：`recommendation_sessions`（已有 `stage/status/result/thread_id UNIQUE`）补一列 `summary TEXT`（`_MIGRATIONS` 幂等追加 `ADD COLUMN IF NOT EXISTS`）；`recommendation_results (session_id FK, product_id FK, rank INT, reason TEXT)` 存推荐行。
- 五阶段枚举值（= `stage` 列与 State 值）：`needs_discovery → budget_confirm → matching → compare_qa → recommend_close → finished`。
- 轮次上限（`STAGE_MIN/MAX_TURNS`）：discovery 1-4、budget 1-3、matching 2-6、compare 0-8、close 1-2；`max_turns=16`；**强制结束关键词**：`["直接推荐", "结束选购", "不用问了", "就这些", "结束吧"]`（发关键词同轮跳 finished 生成推荐——复用 Interview 提前结束机制）。
- LLM：`llm_factory` 加 `"guide": "deepseek-chat"`；agent 对话用 `get_llm("guide", 0.5~0.7)`，结构化抽取用 `get_structured_llm("guide", Schema)`。
- `get_memory_saver("guide")`；thread_id 用 `build_thread_id(user_id, session_id)`（与既有 `student_{id}_session_{sid}` 格式一致）。
- 商品匹配：`retrieve(query, tenant_id, top_k=8)` → 取 `product_id` 元数据 → PG 查 active 商品 → 若 State 有预算则 `price <= budget` 过滤 → 前 3 个进 State；检索空时 PG `ILIKE` 关键词兑底。
- SSE 三事件协议不变（`token`/`done`/`error`）；`done` 携带 `current_stage/total_turns/is_finished/report`。
- 教育 Interview 不动（M5b 删）；统一入口 guide 引导最后更新。

## 文件结构总览

| 文件 | 职责 | 动作 |
|------|------|------|
| `backend/db/migrations.py` | `recommendation_sessions.summary` 加列 | 修改 1 条 |
| `backend/agents/guide/{__init__,state,prompts,nodes,graph}.py` | 导购 Agent | 新建 |
| `backend/core/llm_factory.py` | 加 `"guide"` | 修改 1 行 |
| `backend/api/v1/guide.py` | 五端点（setup/chat/sse/report/list） | 新建 |
| `backend/api/router.py` | 挂 `/guide` | 修改 2 行 |
| `frontend/src/api/guide.ts` | 会话 API + SSE | 新建 |
| `frontend/src/views/guide/GuideSetupView.vue` / `GuideChatView.vue` | 设页 + 对话页 | 新建 |
| `frontend/src/components/interview/StageProgressBar.vue` | 加 `stages` 可选 prop（默认原数组） | 修改 |
| `frontend/src/router/index.ts` / `Sidebar.vue` | 2 路由 + 「智能导购」菜单 | 修改 |
| `backend/api/v1/unified_chat.py` | guide 引导上线文案 | 修改 1 处 |
| `scripts/manual_tests/test_m5a_guide_agent.py` / `test_m5a_guide_api.py` | 端到端 | 新建 |

---

### Task 1: 数据列 + Agent（state/prompts/nodes/graph）

**Files:**
- Modify: `backend/db/migrations.py`、`backend/core/llm_factory.py`
- Create: `backend/agents guide/` 五文件
- Test: `scripts/manual_tests/test_m5a_guide_agent.py`

**Interfaces:**
- Produces: `build_guide_graph()`（可调用函数）；initial_state = `{"user_id","tenant_id","session_id","initial_message","...stage 字段"}`；终态 `recommendation_sessions.status='finished'`、`result` 含 `{"summary","recommendations":[{product_id,title,price,reason}]}`、`recommendation_results` 落行
- Pydantic：`NeedsInfo {needs: str, budget: float|None, preferences: list[str]}`、`GuideReport {summary: str, recommendations: list[Recommendation]}`、`Recommendation {product_id: str, reason: str}`

- [ ] **Step 1: 迁移加列 + llm 键**

`_MIGRATIONS` 追加：

```python
    (
        "recommendation_sessions.summary",
        "ALTER TABLE recommendation_sessions ADD COLUMN IF NOT EXISTS summary TEXT",
    ),
```

`llm_factory.py` 路由表追加：`"guide": "deepseek-chat",   # 多轮导购（M5a）`

- [ ] **Step 2: state.py**

```python
# backend/agents/guide/state.py
# 多轮导购 Agent 状态（M5a：由 Interview 五阶段状态机平移）
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field


class GuideStage:
    NEEDS_DISCOVERY = "needs_discovery"
    BUDGET_CONFIRM  = "budget_confirm"
    MATCHING        = "matching"
    COMPARE_QA      = "compare_qa"
    RECOMMEND_CLOSE = "recommend_close"
    FINISHED        = "finished"


class NeedsInfo(BaseModel):
    """需求抽取（每阶段结构化输出）"""
    needs: str = Field(..., description="用户需求一句话概括，中文")
    budget: Optional[float] = Field(None, description="预算上限（元），未提及为 null")
    preferences: list[str] = Field(default_factory=list, description="偏好标签，如 送礼/便携/低糖")


class Recommendation(BaseModel):
    product_id: str = Field(..., description="推荐商品的 UUID")
    reason: str = Field(..., description="推荐理由，20~50字，结合用户需求")


class GuideReport(BaseModel):
    """结束时的推荐报告"""
    summary: str = Field(..., description="整体推荐总结，80~150字")
    recommendations: list[Recommendation] = Field(..., description="1~5 条推荐，按优先级")


class GuideState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    user_id: str
    tenant_id: str
    session_id: str
    initial_message: str                # 首轮用户输入（可为空字符串）
    current_stage: str
    stage_turn_count: int
    total_turn_count: int
    max_turns: int
    needs: str
    budget: Optional[float]
    preferences: list[str]
    candidates: list[dict]              # [{product_id,title,price,category,rating}]
    existing_summary: Optional[str]
    report: Optional[dict]              # {summary, recommendations}
    fallback_used: bool
    structured_output: Optional[dict]
```

- [ ] **Step 3: prompts.py**（占位符与 nodes format 严格一致；关键常量）

```python
# backend/agents/guide/prompts.py
# 多轮导购提示词（M5a：由模拟面试平移）

SYSTEM_PROMPT = (
    "你是 ShopPilot 商城的资深导购顾问。通过自然的多轮对话了解顾客需求，"
    "基于真实商品数据给出推荐。要求：价格与商品名以你拿到的数据为准，绝不编造；"
    "每轮只问 1 个问题或给出一条回应，保持对话节奏；语气热情但不啰嗦。"
)

NEEDS_EXTRACT_PROMPT = """从顾客最新发言抽取需求信息。
已有需求：{needs}；已有预算：{budget}
顾客最新发言：{answer}
只输出 JSON：{{"needs": "更新后的需求概括", "budget": 数字或null, "preferences": ["标签"]}}"""

OPENING_PROMPT = """基于顾客的开场白生成导购开场回应（60~100字）：先复述理解的需求，再问出第一个关键问题（品类/使用场景）。
顾客开场：{answer}"""

STAGE_PROMPTS = {
    "needs_discovery": """当前阶段：需求探询。已知信息：{needs}
顾客最新发言：{answer}
生成回应：确认已知信息，追问仍缺的关键维度（用途/品类/特殊要求），只问一个问题，40~80字。""",
    "budget_confirm": """当前阶段：预算与偏好确认。已知需求：{needs}，预算：{budget}
顾客最新发言：{answer}
生成回应：确认预算是否已明确；若明确则说明将据此筛选并进入选品，40~80字。""",
    "matching": """当前阶段：商品匹配。需求：{needs}，预算：{budget}
候选商品：
{candidates_block}
顾客最新发言：{answer}
生成回应：介绍最匹配的 2~3 个候选（名称+价格+一句卖点），并问顾客想先看哪个或还需要什么条件，80~150字。""",
    "compare_qa": """当前阶段：对比答疑。需求：{needs}
候选商品：
{candidates_block}
顾客最新发言：{answer}
基于候选与商品知识如实回答对比/疑问，必要时给出倾向性建议，60~120字。""",
    "recommend_close": """当前阶段：推荐收尾。需求：{needs}，预算：{budget}
候选商品：
{candidates_block}
顾客最新发言：{answer}
生成最终推荐语（60~100字）：明确给出 1~3 个推荐及理由，引导顾客查看商品详情。""",
}

REPORT_PROMPT = """生成最终推荐报告。
需求：{needs}，预算：{budget}，偏好：{preferences}
候选商品（product_id|标题|价格）：
{candidates_block}
对话摘要：{history_summary}
只输出 JSON：{{"summary": "80~150字总结", "recommendations": [{{"product_id": "...", "reason": "20~50字理由"}}]}}
recommendations 只能引用上面出现过的 product_id，1~5 条，按契合度排序。"""

TRANSITION_PROMPT = "（进入新阶段：{stage}）"
```

- [ ] **Step 4: nodes.py**（6 节点；匹配/抽取/报告核心逻辑）

关键实现要点（完整代码按此写）：
- `load_context_node`：**只读**——查 `recommendation_sessions.summary WHERE thread_id=:tid` 填 `existing_summary`（会话行由 API 的 POST /sessions 负责插入，图不建行）。
- `check_stage_node`：纯逻辑——①强制结束关键词命中或 `total_turns >= max_turns-2` → `FINISHED`；②按 `STAGE_ORDER=[discovery,budget,matching,compare,close]` 与 `STAGE_MIN/MAX_TURNS`（discovery 1-4 / budget 1-3 / matching 2-6 / compare 0-8 / close 1-2）+ 内容条件（budget 阶段 `budget is not None` 或轮次到 max 才进 matching）推进 `current_stage`；每轮 `total_turn_count+=1`，阶段切换时 `stage_turn_count` 归 1。
- `generate_response_node`：按 stage 分派——`needs_discovery/budget_confirm` 先 `get_structured_llm("guide", NeedsInfo)` 抽取更新 `needs/budget/preferences` 再套 `STAGE_PROMPTS`；`matching` 调 `_search_candidates(state)`（见 Global Constraints 检索规则）填 `candidates`，格式化 `candidates_block = "\n".join(f"{i+1}. {c['product_id']} | {c['title']} | ¥{c['price']} | {c['category'] or ''}" ...)`；全部 `get_llm("guide", 0.6)` 流式前的单次生成（token 流由 API 层 astream_events 捕 `generate_response` 节点）。
- `generate_report_node`：`get_structured_llm("guide", GuideReport)`，candidates 过滤出报告引用的 product_id；LLM 返回缺失 product_id 时截断到合法集合；失败兜底 `{summary: needs+候选清单文本, recommendations: candidates 全部 + reason="基于需求匹配"}`。
- `save_report_node`：`UPDATE recommendation_sessions SET result=:r, stage='finished', status='finished', summary=:s, finished_at=NOW() WHERE thread_id=:tid`；`INSERT recommendation_results` **先 DELETE 本 session 行再插入**（幂等），rank=序号、reason。
- `save_memory_node`：`UPDATE recommendation_sessions SET summary=:s, updated_at=NOW() WHERE thread_id=:tid`（UPSERT 语义按 UNIQUE(thread_id)，与 Interview 同款）。
- `_search_candidates`：`retrieve(query, tenant_id, top_k=8)`（同步放 executor）→ metadata['product_id'] 去重 → PG 批查 `is_active`（+ `price <= budget` 若有）→ 前 3；空结果时 PG `title ILIKE '%{词}%'` 兜底（词 = needs 首 6 字）。

- [ ] **Step 5: graph.py**

```python
# backend/agents/guide/graph.py
# 多轮导购图（M5a：平移自 Interview 拓扑）——条件边只分流「继续/生成报告」
from langgraph.graph import StateGraph, START, END

from backend.agents.guide.state import GuideState, GuideStage
from backend.agents.guide.nodes import (
    load_context_node, check_stage_node, generate_response_node,
    generate_report_node, save_report_node, save_memory_node,
)


def _route_after_check_stage(state):
    if state.get("current_stage") == GuideStage.FINISHED:
        return "generate_report"
    return "generate_response"


def build_guide_graph():
    builder = StateGraph(GuideState)
    builder.add_node("load_context",     load_context_node)
    builder.add_node("check_stage",      check_stage_node)
    builder.add_node("generate_response", generate_response_node)
    builder.add_node("generate_report",  generate_report_node)
    builder.add_node("save_report",      save_report_node)
    builder.add_node("save_memory",      save_memory_node)

    builder.add_edge(START, "load_context")
    builder.add_edge("load_context", "check_stage")
    builder.add_conditional_edges(
        "check_stage", _route_after_check_stage,
        {"generate_report": "generate_report", "generate_response": "generate_response"},
    )
    builder.add_edge("generate_response", "save_memory")
    builder.add_edge("generate_report",   "save_report")
    builder.add_edge("save_report",       "save_memory")
    builder.add_edge("save_memory", END)

    from backend.core.memory import get_memory_saver
    return builder.compile(checkpointer=get_memory_saver("guide"))
```

- [ ] **Step 6: Agent 端到端测试**

`scripts/manual_tests/test_m5a_guide_agent.py`：
1. PG 造 `recommendation_sessions` 行（thread_id=build_thread_id、stage='needs_discovery'）
2. 跑图 3 轮（初始消息「想买瓶装水日常喝」→ 追加「预算 50 以内」→ 追加「直接推荐」强制结束）
3. 断言：`status='finished'`、`result.recommendations` 非空且 `product_id` 均存在于 active 商品、`recommendation_results` 行数 = len(recommendations)、`summary` 非空
4. 每轮 `config={"configurable":{"thread_id": ...}}`

Run: `& $py -m pytest scripts/manual_tests/test_m5a_guide_agent.py -v`（3 轮 ≈ 6~9 次 LLM，超时 8 分钟）
Expected: PASS

---

### Task 2: `/guide` API

**Files:**
- Create: `backend/api/v1/guide.py`
- Modify: `backend/api/router.py`（2 行）
- Test: `scripts/manual_tests/test_m5a_guide_api.py`

**Interfaces（照抄 interview.py 五端点语义）:**
- `POST /api/v1/guide/sessions` body `{"message": str(可空)}` → 同步跑首轮图 → `{"session_id", "opening_message", "stage"}`
- `POST /api/v1/guide/sessions/{id}/chat/stream` body `{"message"}` → SSE：`token`（generate_response 节点流）/ `done`（含 `current_stage,total_turns,is_finished,report`）/ `error`
- `GET /api/v1/guide/sessions/{id}/report` → `{"status","result":{summary,recommendations[{product_id,title,price,reason}]}}`（title/price join products）
- `GET /api/v1/guide/sessions` → 当前用户会话列表（stage/status/created_at）
- `POST /api/v1/guide/sessions/{id}/chat`（同步版，可选保留——有 stream 可不实现；**实现 stream + sessions + report + list 四个即可**）
- 权限：session 归属校验（user_id）；`get_current_user` 全端点

- [ ] **Step 1: 冒烟测试**（需后端）：创建会话 → chat/stream 消费至 done（发「直接推荐」强制结束）→ report 有 recommendations → list 命中
- [ ] **Step 2: 确认 404 失败 → Step 3 实现**（SSE 段逐段对照 `interview.py:253-310` 改表名/字段名：`aget_state(config)` 取 `current_stage/total_turns/report` 组装 done）
- [ ] **Step 4: 挂路由** prefix `/guide`, tag `智能导购`
- [ ] **Step 5: 重启跑冒烟** Expected: PASS（3 轮流式，超时 5 分钟）

---

### Task 3: 前端导购页

**Files:**
- Create: `frontend/src/api/guide.ts`、`views/guide/GuideSetupView.vue`、`views/guide/GuideChatView.vue`
- Modify: `components/interview/StageProgressBar.vue`（加 `stages` 可选 prop）
- Modify: `router/index.ts`（2 路由）、`Sidebar.vue`（菜单，图标 `ShoppingBag`）
- Gate: `npm run build` + 手测

**Interfaces:**
- `guideApi = { create(message), chatStream(sessionId, message, {onToken,onDone,onError}), report(sessionId), list() }`（chatStream 用 `fetch+ReadableStream` 直连 `API_BASE`，照抄 `interview.ts:115-160` 的 data: 行解析）
- 路由：`guide`（Setup）、`guide/:sessionId`（Chat）
- StageProgressBar：`defineProps<{ current: string; stages?: Array<{key,label}> }>()`，默认值 = 现有面试数组；导购页传 `GUIDE_STAGES = [needs_discovery 需求探询, budget_confirm 预算确认, matching 商品匹配, compare_qa 对比答疑, recommend_close 最终推荐, finished 已完成]`
- SetupView：单输入框「想买什么？（可选，一句话即可）」→ `guideApi.create` → `router.push('/guide/'+id, {state:{openingMessage}})`
- ChatView：照抄 InterviewChatView 骨架——StageProgressBar（传 GUIDE_STAGES）、消息流、结束按钮文案「🎯 直接出推荐」发送 `直接推荐`；`onDone` 更新 stage，`is_finished` → `guideApi.report` 渲染**推荐面板**（卡片：标题/价格/理由，`router.push('/products/'+product_id)` 跳详情）；挂载时拉 report 判已结束

- [ ] 各文件按上述实现 → `npm run build` → 手测黄金路径：侧边栏「智能导购」→ 输入需求 → 多轮问答推进阶段条 → 点「直接出推荐」→ 推荐面板 → 点卡片进详情

---

### Task 4: 统一入口 guide 上线 + 全量回归

- [ ] **Step 1: unified_chat guide 引导**

```python
    "guide": {
        "message": "智能选购推荐已上线：点击下方按钮开始多轮导购，我会了解您的需求并给出商品推荐。",
        "action_label": "开始智能导购",
        "action_url": "/guide",
    },
```

（`_LABEL_TO_AGENT` 的 guide 占位不变——routing_decision 载荷无需改。）

- [ ] **Step 2: 全量回归**

```powershell
& $py -m pytest tests/ scripts/manual_tests/test_m2_retrieval.py scripts/manual_tests/test_m2_qa_chat.py scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py scripts/manual_tests/test_off_pipeline.py scripts/manual_tests/test_m3_unified_route.py scripts/manual_tests/test_m4a_review_api.py scripts/manual_tests/test_m4b_service_api.py scripts/manual_tests/test_m5a_guide_api.py -q
```
Expected: 全 passed（约 22 个）

- [ ] **Step 3: M5a 黄金路径手测**：导购会话五阶段推进+结束推荐+报告重进；`/chat` 「帮我挑个礼物」→ guide 引导新文案；教育 Interview 页仍可访问（M5b 才删）

## M5a 完成定义（DoD）

- [ ] 五阶段状态机可推进，强制结束关键词同轮生成推荐报告；`recommendation_results` 落行
- [ ] SSE 流式对话 + done 携带阶段/报告；重进会话显示已结束报告
- [ ] 前端 Setup/Chat/阶段条/推荐面板可用；`npm run build` 0 错误
- [ ] `/chat` guide 引导上线；全套 pytest 绿

## 明确不做（M5a 范围外）

- 教育代码清理与品牌改名（M5b）
- Think Tool 双轨评估（导购场景裁掉，spec §4.4 未要求）
- 推荐结果页独立路由（对话页内嵌面板即可）
- 意图分类器微调（可选项，M5b 决定）
- Interview 五端点中的同步 chat（只做 stream/report/list/create）
