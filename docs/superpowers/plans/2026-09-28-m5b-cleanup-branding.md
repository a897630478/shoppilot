# M5b 清理与品牌收尾（EduAgent → ShopPilot）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 改造收官——删除三个教育 Agent 及其 API/页面/数据，重构教师区菜单只留运营审批，全站品牌切换为 **ShopPilot**，README 重写，全套回归绿。

**Architecture:** 解耦顺序「先引用后本体」：orchestrator / router / 统一入口先摘除教育分支 → 删除教育模块 → 前端同步删路由页面 → 数据清理走**独立脚本**（不进 migrations，保持迁移链无破坏性）→ 品牌替换为纯文本/配置级修改。

**Tech Stack:** 现有栈不变；清理用 `scripts/cleanup_education.py`（显式、可审阅、可先 dry-run）。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §3.1（旧表分批删除）、§5.2（教师端→运营端）、§7 M5、§2 命名 ShopPilot

## Global Constraints

- Python：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`；前端门禁 `npm run build`（0 错误）。
- **保留**（有活引用）：`agents/qa`、`api/v1/qa.py`、`qa_sessions` 表、`knowledge_pending_queue`（FAQ 语义）、`users`（含三角色）、`query_classifier.py`（启动预热仍加载）、`scripts/crawl/`（适配器参考，spec §3.2 明确保留）、`memory/llm_factory/retry` 等公共层。
- **删除范围**：后端 `agents/{exam,resume,interview}`、`api/v1/{exam,resume,interview}.py`、`api/v1/verify_*.py / veriry_*.py`、前端 exam/resume/interview 视图与 api、教师区两个教育菜单项、教育数据表（见 T3）、29 英文书目数据。
- `AgentType` 枚举成员 **保留**（unified_chat 的 routing_decision 载荷前端按字符串消费），仅删除 orchestrator 里构建教育图的分支（命中时返回清晰报错而非 ImportError）。
- docker-compose 仅改 `container_name`/注释文案（运行中栈不受影响，下次自本仓库 up 才生效）；**不动** `.env.local` 与运行中容器。
- 删除文件前先全局 `rg` 确认无残余引用；每步删除后后端能 import、前端能构建。
- 意图分类器微调：**不做**（M3 规则+LLM 路由已覆盖），本计划收尾时在 README「已知限制」注明。

## 文件结构（动作清单）

| 对象 | 动作 |
|------|------|
| `backend/core/orchestrator.py` | `_get_agent_graph` 摘除 exam/resume/interview 构建（返回报错提示） |
| `backend/api/router.py` | 摘除 exam/resume/interview include |
| `backend/api/v1/` 教育三件 + verify* | 删除 |
| `backend/agents/{exam,resume,interview}` | 删除（含 manual_tests） |
| `backend/core/llm_factory.py` | 路由表删 `exam_subjective/exam_code/interview` 键（`resume` 键保留？→ **删**，review/guide 已独立） |
| `backend/main.py` | 标题无关（FastAPI title 在 main.py）改 ShopPilot；MCP name 同步 |
| `frontend` 教育 views/api/router/Sidebar | 删除/重构 |
| `scripts/cleanup_education.py` | 新建（dry-run + 执行教育表/英文书目清理） |
| `README.md` | 重写为 ShopPilot |
| `docker-compose.yml` | container_name/注释 ShopPilot 化 |

---

### Task 1: 后端解耦与删除

**Steps:**

- [ ] **Step 1: orchestrator 摘除教育图构建**

`orchestrator.py:107-116` 三段 import+build 改为：

```python
            elif agent_type == AgentType.EXAM:
                raise RuntimeError("教育考试 Agent 已在 M5b 移除，请使用售后客服（/service）")
            elif agent_type == AgentType.RESUME:
                raise RuntimeError("教育简历 Agent 已在 M5b 移除，请使用评价分析（/reviews）")
            elif agent_type == AgentType.INTERVIEW:
                raise RuntimeError("教育面试 Agent 已在 M5b 移除，请使用智能导购（/guide）")
```

（保留 `AgentType.QA` 分支与 `_agent_graphs` 缓存结构；具体行号以现实为准——`rg "build_exam_graph" backend/core/orchestrator.py`。）

- [ ] **Step 2: router 摘除三行 include + import**

- [ ] **Step 3: 统一入口残留核查**

`rg "exam|resume|interview" backend/api/v1/unified_chat.py` —— 仅允许 label 占位映射与注释；如有教育文案残留（grep「试卷|简历|面试」的**面向用户字符串**）改掉；`_LABEL_TO_AGENT` 占位保留（枚举成员未删）。

- [ ] **Step 4: llm_factory 删教育键**

删 `exam_subjective/exam_code/interview/resume` 四键（`rg` 确认无 `get_llm("resume"` 残留——review/prompts 已用 review 键；resume 模块删除后无人引用）。

- [ ] **Step 5: 删除教育模块**

```powershell
Remove-Item -Recurse backend/agents/exam, backend/agents/resume, backend/agents/interview
Remove-Item backend/api/v1/exam.py, backend/api/v1/resume.py, backend/api/v1/interview.py,
  backend/api/v1/verify_interview_e2e.py, backend/api/v1/verify_qa_e2e.py,
  backend/api/v1/verify_resume_e2e.py, backend/api/v1/veriry_exam_e2e.py
```

（`verify_qa_e2e` 也删——它验证的旧 QA course_id 契约已变。）

- [ ] **Step 6: 后端 import 冒烟**

```powershell
& $py -c "import backend.main, backend.api.router, backend.core.orchestrator; print('ok')"
rg "agents.exam|agents.resume|agents.interview" backend/ --glob '!**/__pycache__/**'   # 期望无输出
```

并清理 `__pycache__` 中教育 pyc：`Get-ChildItem -Recurse -Filter *.pyc backend/agents |` 删除 exam/resume/interview 目录下残留（目录已删则跳过）。

- [ ] **Step 7: 重启后端 + 旧接口回归**

`/health` 200、`/docs` 不再含 /exam /resume /interview 路径、`/api/v1/qa/chat` 与 /products /orders /reviews /service /guide 均在。

---

### Task 2: 前端解耦与删除

**Steps:**

- [ ] **Step 1: 摘路由**（router/index.ts）：删除 `exam`、`exam/:submissionId`、`resume`、`resume/:reviewId`、`interview`、`interview/:sessionId`（如有）、`teacher/exam-review`、`teacher/knowledge-pending` 共 8 条左右；逐一 `rg` 对应 name 引用清零。
- [ ] **Step 2: 摘菜单**（Sidebar.vue）：删「试卷批改/简历审查/模拟面试」三项与教师区 `<template v-if="auth.isTeacher">` 中两个教育项；**保留**「售后审批」并包进新的运营区模板（`v-if="auth.isTeacher"`，只含售后审批，标题注释改为「运营端」）；删除不再使用的图标 import（Document/Postcard/Microphone/EditPen/Collection，保留 Check 用到的——以 vue-tsc 未使用报错为准）。
- [ ] **Step 3: 删文件**

```powershell
Remove-Item -Recurse frontend/src/views/exam, frontend/src/views/resume, frontend/src/views/interview, frontend/src/views/teacher
Remove-Item frontend/src/api/exam.ts, frontend/src/api/resume.ts, frontend/src/api/interview.ts
```

- [ ] **Step 4: 全局引用清扫**

`rg "examApi|resumeApi|interviewApi|ExamSubmit|ExamResult|ResumeUpload|ResumeReport|InterviewSetup|InterviewChat|StageProgressBar 引用残留" frontend/src`——`StageProgressBar` 仅 GuideChatView 引用（组件本体保留）。UnifiedChatView / Dashboard / AppLayout 若有教育字样（试卷/简历/面试）同步改写。
- [ ] **Step 5: `npm run build`** → 0 错误

---

### Task 3: 数据清理脚本

**Files:** Create `scripts/cleanup_education.py`；Test 手测 dry-run + 执行

**Steps:**

- [ ] **Step 1: 实现（dry-run 默认，`--yes` 才执行）**

清理内容（顺序遵守 FK）：
1. `orders` 中引用 `source='books_toscrape'` 商品的行（先查有无；测试订单一并清）
2. `product_reviews` 中这些商品的评价（或依赖 CASCADE）
3. `products WHERE source='books_toscrape'`（含 6 个 inactive OFF 不动——只清 books 来源；inactive OFF 保留做「下架」演示）
4. 教育表 DROP（有 FK 依赖按序）：`exam_reviews → exam_submissions → scoring_points → questions → exams → resume_reviews → interview_sessions → interview_questions`
5. **不删**：`users/qa_sessions/knowledge_pending_queue/products/product_reviews/orders/service_tickets/review_reports/recommendation_*`

```python
# 核心结构
EDU_TABLES_DROP_ORDER = [
    "exam_reviews", "exam_submissions", "scoring_points",
    "questions", "exams", "resume_reviews",
    "interview_sessions", "interview_questions",
]
def collect(conn) -> list[str]   # 返回将执行的 SQL（dry-run 打印）
def execute(conn) -> None        # 逐条执行 + 提交
# CLI: python -m scripts.cleanup_education [--yes]
```

- [ ] **Step 2: dry-run 打印核对** → **Step 3: `--yes` 执行** → **Step 4: 验证**

`to_regclass` 查 8 张教育表 = NULL；`books_toscrape` 商品 = 0；`products active = 94`；M1b 整链路测试 `test_off_pipeline` 仍 passed（它只查 active 商品）。

- [ ] **Step 5: 旧测试清理**

删 `scripts/manual_tests/test_exam.py`、`test_all_agents_health.py`（健康检查含教育 Agent 断言——若其断言可裁剪则改为只查 qa/guide，**优先裁剪保留文件**，失败再删）；`test_unified_chat` 若断言教育路由则裁剪为 qa/guide 用例。

---

### Task 4: 品牌收尾 + 全量回归

**Steps:**

- [ ] **Step 1: 品牌点位替换**（rg `EduAgent|edu-agent|edu_agent` 全仓逐处决策）：

| 位置 | 改为 |
|------|------|
| `Sidebar.vue` logo「🎓 EduAgent」 | 「🛍️ ShopPilot」 |
| `AppLayout.vue` header 标题（若为 EduAgent） | ShopPilot |
| `LoginView.vue` 标题/副标语（若有） | ShopPilot 智能商城 |
| `backend/main.py` FastAPI title/description | `title="ShopPilot API"` / 电商描述 |
| `mcp/knowledge_base_server.py` FastMCP name | `ShopPilot-KnowledgeBase` |
| `docker-compose.yml` container_name×4 + 顶部注释 | `shop_pilot_*`（仅文件级；运行栈不动） |
| `frontend/package.json` name（可选） | `shoppilot-frontend` |
| localStorage key `edu-agent-token` | **不改**（改了会让现有登录态失效且需全文件替换，收益低——README 注明遗留） |

- [ ] **Step 2: README 重写**

新 README 结构：ShopPilot 定位（电商 AI 多智能体平台）→ 四大能力表 → 技术栈（沿用原表，模型/Agent 行更新）→ 架构图（文本版更新为电商语义）→ 快速开始（端口/测试账号沿用）→ 目录结构（更新后的真实结构）→ 已知限制（教育数据已清理、分类器为规则+LLM 路由未微调、演示数据免责声明）→ License。

- [ ] **Step 3: 全量回归**

```powershell
& $py -m pytest tests/ scripts/manual_tests/test_m2_retrieval.py scripts/manual_tests/test_m2_qa_chat.py scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py scripts/manual_tests/test_off_pipeline.py scripts/manual_tests/test_m3_unified_route.py scripts/manual_tests/test_m4a_review_api.py scripts/manual_tests/test_m4b_service_api.py scripts/manual_tests/test_m5a_guide_api.py -q
npm run build   # frontend
```
Expected: pytest 全绿（约 22）+ 构建 0 错误

- [ ] **Step 4: 终验清单**

1. 后端启动无 ImportError；`/docs` 路径 = auth/chat/qa/products/orders/reviews/service/guide/health/mcp
2. 前端侧边栏：首页/商品浏览/我的订单/售后服务/智能导购/智能问答 + 运营区（售后审批，teacher 可见）
3. 黄金路径抽查：登录→商品→问答→下单→售后→口碑→导购 全通
4. `rg -i "试卷|简历|模拟面试" frontend/src backend/api` 无用户可见残留
5. 教育表已删、英文书目已清、active 商品 94

## M5b 完成定义（DoD）= 整个改造收官

- [ ] 三个教育 Agent 与页面/路由/菜单全删，后端 import 无残留、前端 0 类型错误
- [ ] 8 张教育表与 29 英文书目数据清理完成（脚本 dry-run 可复现）
- [ ] 全站品牌 ShopPilot（README/标题/logo）；运行中基础设施不受影响
- [ ] 全套回归绿；黄金路径七步终验通过

## 明确不做

- 意图分类器电商语料微调（README「已知限制」注明）
- localStorage key 改名（兼容性代价大于收益）
- 运行中 docker 栈的容器/网络重构
- 根目录教学遗留文件（a.py、review/、understant_sse/ 等）——非业务代码，不动
