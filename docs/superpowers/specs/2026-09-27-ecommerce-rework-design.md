# EduAgent → 电商 AI Agent 平台改造设计

- 日期：2026-09-27
- 状态：设计已逐节确认，待书面审阅
- 决策路线：方案 A — 就地改造（保留现有架构与公共层，替换业务语义）

## 1. 背景与目标

将现有 EduAgent（教育场景 AI 多智能体平台）改造为电商场景的 AI Agent 平台，作为**真实产品原型 / MVP**，由**一人业余时间**实施。

**核心约束**（来自需求澄清）：

- 保留「4 个 LangGraph Agent + Orchestrator 编排 + RAG 公共层」架构，平移而非重写
- 四个电商能力全部要：商品导购问答、订单售后客服、评价分析报告、多轮导购推荐
- 商城功能做**轻量外壳**：可浏览商品、可生成模拟订单；不做购物车 / 支付 / 库存
- 商品数据来自 **Open Food Facts 公开 API**（真实中文商品、免鉴权、中国区 1600+）；**价格与评价由 LLM 生成补全**（OFF 无此字段）。〔2026-09-27 变更〕原定爬取 books.toscrape 英文书目，用户要求中文内容且经候选 API 实测后改定本方案；已入库的英文书目下架保留、不删除
- 实施资源：一个人兼职

**张力声明**：「真实产品原型」与「一人兼职」冲突，本设计通过「就地改造 + 里程碑增量交付」控制范围；M1~M3 为核心承诺，M4~M5 中的非核心项可在时间不足时裁剪。

## 2. 整体架构与 Agent 平移映射

架构分层不变：Vue3 前端 → FastAPI (:8000) → Orchestrator → 4 个 LangGraph Agent → 公共层（LLM Factory / BGE-M3 / Reranker / MemorySaver / 三层重试 / MCP）→ 数据层（PostgreSQL / Milvus / MinIO）。

| 现有 Agent | 电商 Agent | 平移方式 |
|-----------|-----------|---------|
| QA 智能问答 | 商品导购问答 | 改动最小：知识库换为商品详情/参数/FAQ，保留 RAG 混合检索 + Reranker + SSE |
| Exam 试卷批改 | 订单售后客服 | 复用「流程化 + 后台异步 + HitL」：按物流/退款/换货三轨分流，异常单人工确认 |
| Resume 简历审查 | 评价分析报告 | 复用「结构化抽取 + 六维并行评分」：输入评价集合，输出口碑评分报告 |
| Interview 模拟面试 | 多轮导购推荐 | 复用「状态机多轮对话 + 阶段推进」，五阶段改为导购流程 |

**编排层**：`Orchestrator` 保留；意图分类器（MiniLM）现按教育意图训练，**必须以电商语料微调或替换**，否则统一聊天入口会误路由。

**统一聊天入口**（`/api/v1/chat`，SSE）保留，作为产品主入口，由编排层分发到四个 Agent。

**命名**：对外名称定为 **ShopPilot**（在 M5 收尾时统一改 README、页面标题、docker-compose 注释；如需更名在 M5 前告知即可，不影响其余里程碑）；仓库目录名 `e-commerce` 保持不变。

## 3. 数据层与商品数据采集

### 3.1 表结构平移（PostgreSQL，`db/migrations.py` 幂等迁移）

| 现有表 | 电商表 | 说明 |
|--------|--------|------|
| users / auth | 原样保留 | JWT 登录体系不动 |
| courses / 知识库文档 | products | 标题、类目、价格、参数 JSON、详情、图片 |
| exam / 批改记录 | orders + service_tickets | 售后 Agent 的处理对象 |
| resume / 简历报告 | review_reports | 评价分析报告持久化 |
| interviews | recommendation_sessions + recommendation_results | 导购会话状态与结果 |
| 无对应 | reviews | 商品评价原文，爬虫入库 |
| 无对应 | faq_pending | 低置信度问题待补录（原知识待审） |

旧教育表在对应模块切换完成后分批删除，不在改造首日执行。

### 3.2 数据采集：Open Food Facts API + LLM 补全（2026-09-27 变更后）

- **数据源**：Open Food Facts 搜索 API（`world.openfoodfacts.org/api/v2/search`，免鉴权、公开数据），筛选 `countries_tags_en=china` 且有 `product_name_zh` 的商品；首批 100 个
- **字段映射**：`product_name_zh`→title、`categories`→category、`brands`/`ingredients_text_zh`/`nutriments`/`quantity`→params、`code`→external_id、`image_front_url`→图片
- **LLM 补全**（OFF 缺失字段，DeepSeek 生成，入库后以库为准）：
  - 价格：按类目/规格生成合理人民币价，`currency='CNY'`
  - 商品详情文案：基于品名/配料/营养成分生成中文简介
  - 评价：每商品 30 条中文评价（`source='generated'`，沿用种子脚本机制）；商品 rating 取评价均分回填
- **图片**：`image_front_url` 下载入 MinIO 桶 `product-images`，前端经后端代理引用
- **礼貌约束（硬性）**：API 请求间隔 ≥2s 随机抖动、显式 UA、失败重试、增量幂等（`UNIQUE(source, external_id)` upsert）
- **英文书目处置**：`source='books_toscrape'` 商品 `is_active=FALSE` 下架（不删除、级联评价保留），列表/详情/向量索引均只取 active；其 Milvus chunk 一并清理
- **旧爬虫代码**：`scripts/crawl/`（books 适配器）保留不删，作为站点适配器模式的参考实现

### 3.3 向量层（Milvus）

- 商品知识库集合 `product_knowledge`：商品详情 + 参数切块，BGE-M3 编码（dense + sparse），检索链路不变
- 数据源切换后全量重建：重建集合 → `build_product_knowledge.py` 只索引 active 商品
- 评价数据不入向量：PG 存原文，评价分析 Agent 运行时读取 → LLM 结构化分析 → 报告入库

## 4. 四个 Agent 内部改造

每个 Agent 保持 `state.py / graph.py / nodes.py / prompts.py` 四件套。

### 4.1 商品导购问答（QA 平移，改动最小）

- 图结构不变：`classify → HyDE/多查询改写 → retrieve → RAG生成/联网搜索/直答 → save_memory`
- `state.py` 增加可选 `product_id`：详情页进入时检索限定该商品范围
- `prompts.py` 全部重写为电商语气
- `enqueue_pending` 语义改为「低置信度问题 → FAQ 待补录队列」（管理端处理）

### 4.2 订单售后客服（Exam 平移，改动中等）

- 三轨并行从「选择/简答/编程」改为「物流类 / 退款类 / 换货类」；后台异步任务机制保留
- 新增订单读取节点：Agent 通过工具查 PG 订单，**不给 LLM 写库权限**
- HitL 保留：退款超阈值或规则无法判断 → 生成待确认工单 → 运营端确认页审批
- 输入 = 轻量外壳生成的模拟订单 + 用户自然语言描述

### 4.3 评价分析报告（Resume 平移，改动中等）

- 「PDF 解析」→ 「批量评价清洗」（分页截断、去重、无效过滤）
- 六维并行评分 → 口碑六维：质量、物流、服务、性价比、适配、复购意愿
- 输出结构不变（总分 + 维度分 + 优缺点引用 + 建议），前端复用 `DimensionScoreCard` 布局

### 4.4 多轮导购推荐（Interview 平移，改动最大）

- 五阶段：需求探询 → 预算/偏好确认 → 商品匹配检索 → 对比答疑 → 推荐清单收尾
- 阶段工具：`products.search`（PG + 向量）、`reviews.summary`（读评价分析结果）
- 「结束面试」按钮 → 「直接出推荐」，复用现有跳阶段逻辑
- MemorySaver 对话记忆保留

### 4.5 提示词总策略

集中重写；统一注入约束：**不编造商品参数、价格以库内为准、超出类目范围礼貌拒答**。

## 5. API 层与前端改造

### 5.1 路由

| 现有 | 电商 | 变更 |
|------|------|------|
| `/auth` | `/auth` | 不动 |
| `/chat` | `/chat` | 保留；意图分发改电商分类器 |
| `/qa` | `/qa` | 入参增加可选 `product_id` |
| `/exam` | `/service` | 批改提交 → 售后工单创建/查询；异步机制保留 |
| `/resume` | `/reviews` | 改为按商品 ID 触发分析 |
| `/interview` | `/guide` | 会话 SSE 流式复用 |
| 无 | `/products` **新增** | 商品列表/详情/搜索 |
| 无 | `/orders` **新增** | 模拟下单、订单查询 |

### 5.2 前端（Vue3，骨架保留）

- **新增**：`ProductListView`（列表 + 类目/关键词筛选）、`ProductDetailView`（详情 + 右下角「问问 AI」直达问答并带 `product_id`）
- **对话主入口**：`UnifiedChatView` 保留，推荐结果以商品卡片组件展示，可跳详情
- **换皮复用**：
  - `ExamSubmit/Result` → 售理工单提交与进度
  - `ResumeUpload/Report` → 评价分析触发与报告页
  - `InterviewSetup/Chat` → `GuideSetup/Chat`（复用 `StageProgressBar`）
- **教师端 `teacher/` → 运营端 `operator/`**：试卷审核 → 售后工单审批（HitL）；知识待审 → FAQ 待补录（对应角色 teacher 改名 operator，与超管 admin 区分）
- **导航**：`Dashboard` 改商品浏览首页；Sidebar 改「首页 / 导购问答 / 售后服务 / 评价分析 / 智能导购」
- **SSE**：`useSSEChat` 直连 8000 不经 Vite proxy 的设计不变
- 主题色后定，布局组件（AppLayout/Sidebar/ChatBubble）全部复用

## 6. 容错、测试与质量约束

### 6.1 三层兜底（继承，调整降级行为）

| 层级 | 电商降级表现 |
|------|-------------|
| 一层自动重试 | 不变（1s/3s，最多 2 次） |
| 二层 Agent 降级 | 问答 → 库内关键词直搜；售后 → 通用流程话术；评价 → 已清洗的部分结果；导购 → 列 3 个热销商品 |
| 三层系统兜底 | 不变（友好提示 + 已完成结果持久化） |

新增硬性约束：

1. LLM 输出的价格/参数与 PG 不一致时**以库为准**（生成后字段校验）
2. 爬虫失败不影响已入库数据（增量、幂等）

### 6.2 测试策略（一人兼职，不追求覆盖率）

- 每个 Agent 2~3 个手动脚本测试（延续 `manual_tests` 模式），断言输出结构
- 售后工单状态流转（待审 → 通过/驳回）写**自动化测试**（HitL 最易回归）
- 爬虫：小批量试跑 + 人工抽检，不写自动化测试
- 提交前核心链路手测清单：登录 → 浏览商品 → 问答 → 下单 → 售后 → 评价分析

## 7. 里程碑（一人业余时间，14 日历周）

| 里程碑 | 内容 | 周次 |
|--------|------|------|
| M1 数据地基 | 表迁移、爬虫跑通、商品入库、Milvus 商品集合、`/products` `/orders` 接口 | W1~W3 |
| M2 首个链路 | 导购问答全通 + 商品列表/详情页 + 详情页「问 AI」 | W4~W5 |
| M3 外壳闭环 | 模拟下单、订单页、意图分类器电商化、统一聊天路由 | W6~W7 |
| M4 售后+评价 | 售后客服 Agent（含审批环）、评价分析 Agent | W8~W11 |
| M5 导购+收尾 | 多轮导购 Agent、旧教育代码清理、全链路手测 | W12~W14 |

- M2 结束即可演示核心链路；每个里程碑增量可用
- 时间不足时优先保 M1~M3，M4/M5 非核心项可裁剪

## 8. 明确不做（YAGNI）

- 购物车、支付、库存、优惠券、物流跟踪集成
- 多租户、权限细分（沿用现有 student/teacher/admin 三角色语义，仅改名为 user/operator/admin）
- 生产级高可用（多副本、监控告警）——MVP 目标不含
- 实时商品价格同步（价格为爬取时快照）
- 移动端适配（桌面 Web 优先）

## 9. 风险与应对

| 风险 | 应对 |
|------|------|
| 目标站点反爬升级导致爬虫失效 | 适配器结构支持换源；M1 内先小批量验证 |
| 意图分类器迁移后误路由 | M3 专门安排电商语料微调；统一聊天入口保留关键词规则兜底 |
| 一人时间中断导致改造半途悬空 | 里程碑设计保证每个 M 结束系统可运行；按模块分批提交 |
| LLM 生成商品信息与库不一致 | 生成后字段校验，以库为准（6.1 硬性约束） |
