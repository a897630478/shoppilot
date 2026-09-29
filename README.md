# ShopPilot — 电商场景的 AI 多智能体平台

> 面向电商购物场景的 AI 原生导购与服务系统。  
> 基于 **LangChain + LangGraph + FastAPI** 构建，核心大模型为 **DeepSeek**。

---

## 项目简介

ShopPilot 将电商场景的四类高频服务封装为独立 AI Agent，每个 Agent 融合商品知识库、内置完整业务流程、并配备工程化容错机制，由统一入口做意图路由。

| Agent | 业务能力 | 核心技术范式 |
|-------|---------|------------|
| **商品导购问答（QA）** | 基于商品知识库实时答疑 | RAG 混合检索 + BGE-M3 + Reranker 精排 + SSE 流式 |
| **售后客服（Service）** | 物流 / 退款 / 换货工单处理 | 条件边三轨分流 + 规则引擎 + 人工审批（HitL） |
| **评价分析（Review）** | 商品口碑六维评分报告 | 评价清洗 + 六维并行评分 + 优缺点挖掘 |
| **智能导购（Guide）** | 多轮对话精准推荐 | 五阶段状态机 + 向量选品 + 结构化推荐清单 |

四个 Agent 之上由 **Orchestrator / 统一入口（`/chat`）** 做意图路由；之下是商品/订单**轻量外壳**（浏览、模拟下单与支付）。

---

## 技术栈

| 层面 | 选型 |
|------|------|
| 开发语言 | Python 3.11（严格锁定） |
| Web 框架 | FastAPI + SSE-Starlette |
| Agent 框架 | LangChain 1.2.x + LangGraph 1.0.x |
| 大模型 | DeepSeek（经 LLM Factory 统一封装） |
| 向量数据库 | Milvus（`product_knowledge` 集合） |
| 关系数据库 | PostgreSQL + SQLAlchemy（全异步） |
| 对象存储 | MinIO（`product-images` 桶） |
| 嵌入/精排 | BGE-M3 + BGE-Reranker-large（进程内） |
| 前端 | Vue3 + TypeScript + Element Plus |

> BGE-M3、BGE-Reranker、MiniLM 三个本地模型均为**进程内调用**，启动时随后端并行预热。

---

## 系统架构

```
┌─────────────────────────────────────────────────┐
│          前端层   Vue3 SPA (:3000) ShopPilot      │
│   商品浏览 / 订单 / 售后 / 导购 / 问答 / 运营审批   │
└────────────────────┬────────────────────────────┘
                     │ HTTP / SSE
┌────────────────────▼────────────────────────────┐
│          API 层   FastAPI (:8000) /api/v1        │
│   auth · chat · qa · products · orders           │
│   reviews · service · guide · JWT 鉴权 · SSE      │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│     统一入口 /chat：规则前置 + LLM 意图路由        │
│   qa / service / review / guide / clarify        │
└──────┬───────────┬───────────┬───────────┬──────┘
       │           │           │           │
  ┌────▼───┐  ┌────▼────┐  ┌───▼────┐  ┌───▼─────┐
  │   QA   │  │ Service │  │ Review │  │  Guide  │ ← LangGraph × 4
  │ (RAG)  │  │ 三轨分流 │  │ 六维并行│  │ 五阶段机 │
  └────────┘  └─────────┘  └────────┘  └─────────┘
                    公共层
       ├── LLM Factory（DeepSeek 统一封装）
       ├── BGE-M3 混合检索 / BGE-Reranker 精排
       ├── MemorySaver 对话记忆 · 三层容错重试
       └── MCP（商品知识检索 / Web 搜索）
                     │
┌────────────────────▼────────────────────────────┐
│  数据层  PostgreSQL · Milvus · MinIO（Docker）    │
└─────────────────────────────────────────────────┘
```

---

## 环境要求

- Python **3.11**（严格锁定）+ Conda
- Node.js 18+（前端）
- Docker & Docker Compose
- DeepSeek API Key

---

## 快速开始

### 1. 创建环境

```bash
conda create -n shop_pilot python=3.11 -y
conda activate shop_pilot
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env.local   # 若无 example，复制现有 .env.local 模板
```

必填：`DB_USER`、`DB_PASSWORD`、`DEEPSEEK_API_KEY`、`JWT_SECRET_KEY`。

### 3. 启动基础设施

```bash
docker-compose --env-file .env.local up -d postgres minio etcd milvus
```

### 4. 初始化数据（首次）

```bash
python -m scripts.init_milvus_product          # 商品向量集合
python -m scripts.ingest_off --limit 100       # 中文商品入库（Open Food Facts）
python -m scripts.enrich_off_products          # LLM 补价格与详情
python -m scripts.seed_product_reviews --per-product 30   # 生成评价
python -m scripts.backfill_product_rating      # 回填星级
python -m scripts.build_product_knowledge      # 商品知识入向量索引
python scripts/seed_data.py                    # 测试账号
```

### 5. 一键启动（推荐）

```bash
conda activate shop_pilot
python start.py
```

`start.py` 会自动：检查/拉起 Docker 基建 → 清理 8000/3000 旧进程 → 同时启动后端与前端 → **在当前终端实时显示两侧日志**（`[后端]`/`[前端]` 前缀）→ 健康检查通过后打印访问地址。**Ctrl+C** 一键停止全部服务。

也可手动分步启动：

```bash
# 后端（项目根目录）
uvicorn backend.main:app --host 0.0.0.0 --port 8000

# 前端
cd frontend && npm install && npm run dev
```

---

## 服务端口

| 服务 | 端口 |
|------|------|
| FastAPI 后端 | **8000**（`/docs` 查看 Swagger） |
| Vue3 前端 | **3000** |
| PostgreSQL | 5433 |
| MinIO API | 9002 |
| Milvus | 19531 |

> 连接配置统一从 `.env.local` 读取，禁止硬编码端口号。

---

## 测试账号

| 角色 | 账号 | 密码 |
|------|------|------|
| 学员（顾客） | student01@shoppilot.local | Student@123456 |
| 教师（运营） | teacher01@shoppilot.local | Teacher@123456 |
| 管理员 | admin@shoppilot.local | 123456 |

> 账号由 `scripts/seed_data.py` 写入；运营角色（teacher/admin）可访问侧边栏「售后审批」「FAQ 补录」。

---

## 目录结构

```
ShopPilot/
├── backend/
│   ├── main.py                  # FastAPI 入口（模型预热 + DB 迁移）
│   ├── config.py                # pydantic-settings 配置
│   ├── api/v1/                  # auth/chat/qa/products/orders/reviews/service/guide
│   ├── agents/
│   │   ├── qa/                  # 商品导购问答（RAG）
│   │   ├── review/              # 评价分析（M4a）
│   │   ├── service/             # 售后客服（M4b）
│   │   └── guide/               # 多轮导购（M5a）
│   ├── core/                    # llm_factory / knowledge_base / reranker / memory / retry
│   ├── db/migrations.py         # 启动时幂等 DDL（含电商 7 表）
│   └── mcp/                     # MCP Server（商品知识检索 + Web 搜索）
├── frontend/src/
│   ├── views/                   # product/order/service/guide/qa/review/operator 等
│   ├── api/                     # axios 封装 + 各能力 API
│   └── components/              # 布局/聊天/阶段条等
├── scripts/                     # 数据流水线与运维脚本（见下）
├── docs/superpowers/            # 设计规格与实施计划
├── docker-compose.yml
└── requirements.txt
```

**数据流水线脚本**：`ingest_off`（商品入库）→ `enrich_off_products`（价格文案）→ `seed_product_reviews`（评价）→ `backfill_product_rating`（星级）→ `init_milvus_product` + `build_product_knowledge`（向量索引）；`cleanup_education.py` 为历史清理工具。

---

## 容错机制

| 层级 | 触发条件 | 处理方式 |
|------|---------|---------|
| 第一层：自动重试 | 网络抖动 / LLM 超时 | 间隔退避重试（各 Agent 内置 3 次） |
| 第二层：Agent 降级 | 重试仍失败 | 问答直答 / 售后转人工 / 报告默认值 / 导购兜底话术 |
| 第三层：系统兜底 | 全部失败 | 友好提示 + 已完成结果持久化 + 错误记录 |

**数据约束**：价格与商品参数**以库内数据为准**，LLM 生成内容不覆盖库字段。

---


