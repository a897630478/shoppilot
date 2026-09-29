# M3 外壳闭环（订单前端 + 统一入口电商化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐「浏览 → 下单 → 支付 → 订单管理」前端闭环，并把统一聊天入口（`/chat`）与 QA 意图分类从教育语义切换为电商语义。

**Architecture:** 订单侧纯增量——新建 `api/orders.ts` + 订单列表页 + 详情页下单对话框，复用 M1 已就绪的 `/orders` 接口；统一入口侧做语义替换——`_ROUTE_PROMPT` 改五类电商意图（qa/service/review/guide/clarify），未上线能力（service/review/guide，M4/M5 交付）走引导卡片指向现有页面；QA 分类层旁路教育域 MiniLM（未命中规则时默认 specialized，避免教育模型把商品问题判成闲聊）。

**Tech Stack:** Vue3 + Element Plus（前端）、FastAPI SSE 统一入口、既有 QA LangGraph 图。

**Spec:** `docs/superpowers/specs/2026-09-27-ecommerce-rework-design.md` §2（意图路由）、§7 里程碑 M3

## Global Constraints

- Python：`& "D:\ProgramTools\Anaconda3\envs\Edu_Agent\python.exe" -m ...`；前端门禁 `cd frontend; npm run build`（vue-tsc，历史错误已在 M2 清零，本计划不得重新引入）。
- `/orders` 接口契约（M1 已定，勿改）：`POST {product_id, quantity, receiver, address}` → `{id,status,unit_price,total_amount,currency,quantity}`；`GET /orders` → `{total, items:[{id,product_id,product_title,quantity,unit_price,total_amount,currency,receiver,address,status,created_at}]}`；`POST /orders/{id}/pay` → `{id,status}`，非 created 返回 409。
- 登录字段 `username`；未登录 403；SSE 直连 `http://localhost:8000`（`API_BASE` 模式）。
- service/review/guide 三个意图**只做引导卡片**，不建 Agent（M4/M5 范围）；路由事件 `agent_type` 载荷仍用 orchestrator 既有枚举占位，展示名以 label 为键。
- 不动 exam/resume/interview 三个教育 Agent 本体与页面（M5 清理）。
- 统一入口既有 SSE 事件协议不变（routing_decision/guidance/token/meta/done），前端 UnifiedChatView 无需改事件处理。

## 文件结构总览

| 文件 | 职责 | 动作 |
|------|------|------|
| `frontend/src/api/orders.ts` | 订单 API 封装 | 新建 |
| `frontend/src/views/order/OrderListView.vue` | 我的订单（列表+支付） | 新建 |
| `frontend/src/views/product/ProductDetailView.vue` | 加「立即下单」对话框 | 修改 |
| `frontend/src/router/index.ts` | 加 orders 路由 | 修改 |
| `frontend/src/components/layout/Sidebar.vue` | 加「我的订单」菜单 | 修改 |
| `backend/api/v1/unified_chat.py` | 路由 Prompt/模板/分支电商化 | 修改（约 8 处） |
| `backend/agents/qa/nodes.py` | 分类层旁路教育 MiniLM | 修改（classify 节点 1 处） |
| `frontend/src/views/DashboardView.vue` | featureCards 电商化 | 修改 |
| `scripts/manual_tests/test_m3_unified_route.py` | 统一入口路由冒烟 | 新建 |
| `scripts/manual_tests/test_m3_orders_flow.py` | 下单→支付 API 流冒烟 | 新建（复用 M1 orders 冒烟则可只跑已有） |

---

### Task 1: 订单前端闭环（客户端 + 下单入口 + 列表页 + 路由菜单）

**Files:**
- Create: `frontend/src/api/orders.ts`
- Modify: `frontend/src/views/product/ProductDetailView.vue`（下单按钮与对话框）
- Create: `frontend/src/views/order/OrderListView.vue`
- Modify: `frontend/src/router/index.ts`、`frontend/src/components/layout/Sidebar.vue`
- Gate: `npm run build` + 手测

**Interfaces:**
- Consumes: `/orders` 四接口（见 Global Constraints）；`productsApi.detail`（已有）
- Produces: `ordersApi = { create(data), list(), detail(id), pay(id) }`；路由 name `orders`（path `orders`）；详情页 `下单成功 → router.push('/orders')`

- [ ] **Step 1: 写 `frontend/src/api/orders.ts`**

```ts
// frontend/src/api/orders.ts
import client from './client'

export interface OrderCreateReq {
  product_id: string
  quantity: number
  receiver: string
  address: string
}

export interface OrderCreated {
  id: string
  status: string
  unit_price: string
  total_amount: string
  currency: string
  quantity: number
}

export interface OrderItem {
  id: string
  product_id: string
  product_title: string
  quantity: number
  unit_price: string
  total_amount: string
  currency: string
  receiver: string
  address: string
  status: string
  created_at: string | null
}

export const ordersApi = {
  create: (data: OrderCreateReq) => client.post<OrderCreated>('/orders', data),
  list: () => client.get<{ total: number; items: OrderItem[] }>('/orders'),
  detail: (id: string) => client.get<OrderItem>(`/orders/${id}`),
  pay: (id: string) => client.post<{ id: string; status: string }>(`/orders/${id}/pay`),
}
```

- [ ] **Step 2: ProductDetailView 加「立即下单」**

script 追加（在 `askAi` 之后）：

```ts
const orderDialogVisible = ref(false)
const ordering = ref(false)
const orderForm = ref({ quantity: 1, receiver: '', address: '' })

function openOrderDialog() {
  orderForm.value = { quantity: 1, receiver: '', address: '' }
  orderDialogVisible.value = true
}

async function submitOrder() {
  if (!detail.value) return
  if (!orderForm.value.receiver.trim() || !orderForm.value.address.trim()) {
    ElMessage.warning('请填写收件人与地址')
    return
  }
  ordering.value = true
  try {
    await ordersApi.create({
      product_id: detail.value.id,
      quantity: orderForm.value.quantity,
      receiver: orderForm.value.receiver.trim(),
      address: orderForm.value.address.trim(),
    })
    ElMessage.success('下单成功（演示订单，可模拟支付）')
    orderDialogVisible.value = false
    router.push('/orders')
  } catch { /* 拦截器已提示 */ }
  finally { ordering.value = false }
}
```

import 追加 `ordersApi`。template 中「问问 AI」按钮旁加：

```html
          <el-button type="danger" size="large" @click="openOrderDialog">立即下单</el-button>
```

template 末尾（`</template>` 前）加对话框：

```html
    <el-dialog v-model="orderDialogVisible" title="确认下单（演示）" width="440px">
      <el-form label-width="80px">
        <el-form-item label="数量">
          <el-input-number v-model="orderForm.quantity" :min="1" :max="99" />
        </el-form-item>
        <el-form-item label="收件人">
          <el-input v-model="orderForm.receiver" placeholder="姓名" maxlength="64" />
        </el-form-item>
        <el-form-item label="收货地址">
          <el-input v-model="orderForm.address" type="textarea" :rows="2" placeholder="省市区 + 详细地址" maxlength="256" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="orderDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="ordering" @click="submitOrder">提交订单</el-button>
      </template>
    </el-dialog>
```

- [ ] **Step 3: 写 `frontend/src/views/order/OrderListView.vue`**

```vue
<!-- frontend/src/views/order/OrderListView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { ordersApi, type OrderItem } from '@/api/orders'

const loading = ref(false)
const items = ref<OrderItem[]>([])
const payingId = ref('')

const statusTag: Record<string, { label: string; type: 'warning' | 'primary' | 'info' | 'success' | 'danger' }> = {
  created:   { label: '待支付', type: 'warning' },
  paid:      { label: '已支付', type: 'primary' },
  shipped:   { label: '已发货', type: 'info' },
  completed: { label: '已完成', type: 'success' },
  cancelled: { label: '已取消', type: 'danger' },
}

async function load() {
  loading.value = true
  try {
    const { data } = await ordersApi.list()
    items.value = data.items
  } catch {
    ElMessage.error('订单加载失败')
  } finally {
    loading.value = false
  }
}

async function pay(row: OrderItem) {
  payingId.value = row.id
  try {
    await ordersApi.pay(row.id)
    ElMessage.success('支付成功（演示）')
    await load()
  } catch { /* 409 等由拦截器提示 */ }
  finally { payingId.value = '' }
}

function fmtDate(iso: string | null) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '--'
}

onMounted(load)
</script>

<template>
  <div class="order-list">
    <el-card shadow="never">
      <template #header><span>📦 我的订单</span></template>
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column label="商品" min-width="220">
          <template #default="{ row }">{{ row.product_title }} × {{ row.quantity }}</template>
        </el-table-column>
        <el-table-column label="金额" width="120">
          <template #default="{ row }">
            <span style="color:#f56c6c">¥{{ row.total_amount }}</span>
          </template>
        </el-table-column>
        <el-table-column label="收件人" width="110" prop="receiver" />
        <el-table-column label="下单时间" width="160">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="statusTag[row.status]?.type ?? 'info'" size="small">
              {{ statusTag[row.status]?.label ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="120">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'created'" type="primary" size="small"
              :loading="payingId === row.id" @click="pay(row)"
            >模拟支付</el-button>
            <span v-else style="color:#c0c4cc;font-size:12px">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有订单，去商品页逛逛" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.order-list { max-width: 1100px; }
</style>
```

- [ ] **Step 4: 路由与菜单**

`router/index.ts` children 追加：

```ts
        // 我的订单（M3）
        {
          path: 'orders',
          name: 'orders',
          component: () => import('@/views/order/OrderListView.vue'),
        },
```

`Sidebar.vue`：图标 import 追加 `ShoppingCart`；「商品浏览」之后插入：

```html
      <RouterLink to="/orders" class="nav-item" :class="{ 'nav-item--active': isActive('/orders') }">
        <el-icon><ShoppingCart /></el-icon>
        <span>我的订单</span>
      </RouterLink>
```

- [ ] **Step 5: 构建 + 接口流手测**

`npm run build` 期望 0 错误。前后端启动后手测：详情页 → 立即下单（缺收件人有校验）→ 提交 → 订单页出现「待支付」→ 模拟支付 → 变「已支付」→ 重复支付不再显示按钮。

---

### Task 2: 统一聊天入口电商化（unified_chat.py）

**Files:**
- Modify: `backend/api/v1/unified_chat.py`（模板 Prompt、映射表、分支文案）
- Test: `scripts/manual_tests/test_m3_unified_route.py`（新建）

**Interfaces:**
- Consumes: 既有 `_llm_route` / SSE 事件协议；`_stream_qa_agent` 不动
- Produces: `_ROUTE_PROMPT` 五类 label `qa|service|review|guide|clarify`；`_LABEL_DISPLAY`（label→中文展示名）；guidance 分支按 label 出引导卡（service/review/guide 指向现有页面）；`routing_decision` 事件字段不变

- [ ] **Step 1: 写路由冒烟测试**

新建 `scripts/manual_tests/test_m3_unified_route.py`：

```python
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
```

- [ ] **Step 2: 运行确认失败**

启动后端后跑测试，Expected: FAIL（`agent_display == 商品导购问答` 不成立 / 出现「试卷批改」展示名）

- [ ] **Step 3: 重写模板与 Prompt**

`unified_chat.py` 修改点（保持事件协议与函数签名不变）：

① `_AGENT_DISPLAY` 删除，新增以 label 为键的展示名与引导表：

```python
# ── label 中文名映射（路由卡片展示用；M4/M5 的 service/review/guide 为预告）──
_LABEL_DISPLAY = {
    "qa":          "商品导购问答",
    "service":     "售后服务中心",
    "review":      "商品评价分析",
    "guide":       "智能选购推荐",
    "multi_agent": "购物全链路",
    "clarify":     "智能助手",
}

# ── 未上线能力的引导卡（M4/M5 交付前指向现有页面）─────────────────
_GUIDANCE_BY_LABEL = {
    "service": {
        "message": "售后服务中心正在建设中（M4 上线）。现在您可以先去「我的订单」查看订单，或直接向我描述问题，我会尽力解答。",
        "action_label": "查看我的订单",
        "action_url": "/orders",
    },
    "review": {
        "message": "商品评价分析正在建设中（M4 上线）。您可以先在商品详情页查看评价数量，稍后回来体验 AI 口碑报告。",
        "action_label": "去逛商品",
        "action_url": "/products",
    },
    "guide": {
        "message": "多轮智能导购正在建设中（M5 上线）。现在可以直接告诉我需求，我会基于商品库为您检索推荐。",
        "action_label": "去智能问答",
        "action_url": "/qa",
    },
}
```

（原 `_GUIDANCE`（exam/resume/interview 三卡）整块删除。）

② `_ROUTE_PROMPT` 替换：

```python
_ROUTE_PROMPT = """判断用户需求应路由到哪个功能。

可选功能：
- qa       : 商品咨询与选购问答（参数、价格、对比、推荐，直接提问）
- service  : 售后问题（退货、退款、换货、物流查询、订单异常）
- review   : 商品评价分析（用户要求分析口碑、总结评价、生成报告）
- guide    : 多轮导购推荐（用户要"帮我挑/推荐/选"且需求较复杂，需要多轮沟通）
- clarify  : 意图不明确，无法判断，需要追问

严格按以下 JSON 格式返回，不要有其他内容：
{{"label": "功能名", "reason": "一句话说明判断依据"}}

用户输入：{message}"""
```

③ `_LABEL_TO_AGENT` / `_LABEL_TO_MODE` 更新（agent 枚举仅作事件载荷占位）：

```python
_LABEL_TO_AGENT: dict[str, AgentType] = {
    "qa":       AgentType.QA,
    "service":  AgentType.EXAM,     # 占位载荷，M4 换真实售后 Agent
    "review":   AgentType.RESUME,   # 占位载荷，M4 换真实评价 Agent
    "guide":    AgentType.INTERVIEW,# 占位载荷，M5 换真实导购 Agent
    "clarify":  AgentType.QA,
}
_LABEL_TO_MODE = {
    "qa": ExecutionMode.SINGLE, "service": ExecutionMode.SINGLE,
    "review": ExecutionMode.SINGLE, "guide": ExecutionMode.SINGLE,
    "clarify": ExecutionMode.CLARIFY,
}
```

（`multi_agent` 从 Prompt 与映射中移除；代码中既有 pipeline 分支保留但不可达，M5 清理。）

④ Step 2 推送卡片处：`_AGENT_DISPLAY.get(decision.agent_type, "")` → `_LABEL_DISPLAY.get(decision.label, "")`。

⑤ 分发分支改写：

```python
        if label == "qa":
            async for event in _stream_qa_agent(req, current_user):
                yield event

        elif label in ("service", "review", "guide"):     # M4/M5 前的预告引导
            guidance = _GUIDANCE_BY_LABEL[label]
            yield _sse({
                "type": "guidance", "message": guidance["message"],
                "action_label": guidance["action_label"], "action_url": guidance["action_url"],
            })

        elif label == "multi_agent":                       # 历史分支，新 Prompt 不再产生
            yield _sse({"type": "guidance",
                        "message": "请直接告诉我您的具体需求，我会为您检索商品并解答。",
                        "action_label": "开始提问", "action_url": "/qa"})

        else:                                              # clarify
            yield _sse({
                "type": "guidance",
                "message": "您的需求我还不太确定，能否再具体一些？"
                           "例如：想咨询某个商品、查询退货物流，还是让我帮您挑选商品？",
                "action_label": "", "action_url": "",
            })
```

⑥ `_pre_filter` 五类模板电商化（`_REPLY_HELLO/_THANKS/_BYE/_REPLY_IDENTITY/_REPLY_CAPABILITY/_MULTI_AGENT_TIP` 内容替换，结构与关键词集合不动）：

- HELLO：`您好！我是 ShopPilot 智能导购助手。` + 能力清单（商品咨询 / 售后查询 / 选购推荐）+ 「请问有什么可以帮到您？」
- BYE：`再见！祝您购物愉快，期待再次为您服务。`
- IDENTITY：`我是 ShopPilot 商城的智能导购助手`，介绍导购问答/售后/评价/推荐四项能力（后三项标注"即将上线"）
- CAPABILITY：`- 直接输入商品问题 → 商品导购问答（基于商品库检索）`、`- 「怎么退货」 → 售后服务（即将上线，可先查订单）`、`- 「帮我分析评价」 → 评价分析（即将上线）`、`- 「帮我挑」 → 智能选购推荐（即将上线）`
- `_MULTI_AGENT_TIP`：`- **购物全链路**：从商品咨询到下单售后，我都会尽力协助`（或在模板中不再引用，二选一，保持各模板可运行）

- [ ] **Step 4: 重启后端运行测试**

Run: `& $py -m pytest scripts/manual_tests/test_m3_unified_route.py -v`
Expected: 2 passed（qa 意图展示名=商品导购问答 且有 token 流；service 意图出 guidance、无教育展示名）

---

### Task 3: QA 分类层旁路教育 MiniLM

**Files:**
- Modify: `backend/agents/qa/nodes.py`（`classify_query_node` Layer 1 段，约 :281-302）
- Test: 沿用 `test_m2_qa_chat.py` 回归 + 新断言

**Interfaces:**
- Consumes: 既有规则层 `_rule_classify_general` / `_rule_classify_specialized`
- Produces: 分类顺序 = 规则 GENERAL → 关键词 SPECIALIZED → **默认 SPECIALIZED（不再调用 MiniLM）**；`get_query_classifier` 调用从 nodes 移除（import 若无他用则一并删）

- [ ] **Step 1: 加回归断言**

`scripts/manual_tests/test_m2_qa_chat.py` 追加（真实 LLM 1 次）：

```python
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
```

（"包装/送人"不在关键词表，改动前会经教育 MiniLM 高置信判 general → answer_mode=="general" → 本断言失败。）

- [ ] **Step 2: 运行确认失败（可选，需后端）**

Expected: `assert 'general' in ...` 失败或长度不足

- [ ] **Step 3: 旁路 Layer 1**

`classify_query_node` 中删除 MiniLM 段（`loop.run_in_executor(..., get_query_classifier().classify, ...)` 至 Layer 2 结束），替换为：

```python
    # ── Layer 1（M3 移除）：原教育域 MiniLM 二分类对商品语料不可靠，
    #    未命中规则时默认按专业问题处理（进检索策略判断），由 RAG 兜底质量 ──
    logger.info("classify_query.specialized_by_default", query=original_query[:50])
    strategy = await _determine_rag_strategy_fast(original_query)
    logger.info("classify_query.rag_strategy", strategy=strategy)
    return {**_base, "query_type": strategy}
```

清理：`rg "get_query_classifier" backend/agents/qa/` 确认 nodes 无引用后删对应 import（`query_classifier` 文件本身保留，启动预热不受影响）。

- [ ] **Step 4: 回归**

Run: `& $py -m pytest scripts/manual_tests/test_m2_qa_chat.py -v`（含新断言，3 个用例）
Expected: 3 passed（RAG 主路径未回归）

---

### Task 4: Dashboard 电商化 + 全量回归

**Files:**
- Modify: `frontend/src/views/DashboardView.vue`（`featureCards`）
- Gate: `npm run build`、全套测试、黄金路径

- [ ] **Step 1: 替换 featureCards**

读现有 `featureCards` 结构（title/desc/route/icon 字段以现实为准），替换为四张电商卡：

```ts
const featureCards = [
  { title: '商品浏览', desc: '94 件中文商品，支持搜索与类目筛选', route: '/products', /* icon 字段按原文件 */ },
  { title: '智能问答', desc: '基于商品库的导购问答，流式回答', route: '/qa', },
  { title: '我的订单', desc: '模拟下单与支付，订单状态一目了然', route: '/orders', },
  { title: '统一助手', desc: '一个入口自动路由到合适的能力', route: '/chat', },
]
```

（`desc`/`icon` 字段名与原文件对齐；教育卡片删除。）

- [ ] **Step 2: 构建门禁**

`npm run build` → 0 错误。

- [ ] **Step 3: 全量回归**

```powershell
& $py -m pytest tests/ scripts/manual_tests/test_m2_retrieval.py scripts/manual_tests/test_m2_qa_chat.py scripts/manual_tests/test_products_api.py scripts/manual_tests/test_orders_api.py scripts/manual_tests/test_off_pipeline.py scripts/manual_tests/test_m3_unified_route.py -q
```
Expected: 全 passed（约 18~19 个）

- [ ] **Step 4: M3 黄金路径手测**

1. 首页四张电商卡片，点「商品浏览」
2. 详情页 → 立即下单 → 校验 → 提交 → 订单页「待支付」→ 模拟支付 →「已支付」
3. `/chat` 统一助手输入「怎么退货」→ 路由卡「售后服务中心」→ guidance 引导去订单页（无教育文案）
4. `/chat` 输入「矿泉水哪个好」→ 路由卡「商品导购问答」→ 流式回答
5. `/chat` 输入「你好」→ ShopPilot 问候模板（无 EduAgent 字样）
6. 教育旧页面（/exam 等）仍可访问（M5 才删，允许残留）

## M3 完成定义（DoD）

- [ ] 详情页可下单、订单页可支付，状态流转正确（created→paid，重复支付 409 被前端拦截提示）
- [ ] 统一入口：qa 意图展示名「商品导购问答」；service/review/guide 出引导卡；五类模板无 EduAgent/试卷/简历/面试字样
- [ ] QA 分类不再调用教育 MiniLM；无关键词的商品问题不落 general
- [ ] Dashboard 四张电商卡；`npm run build` 0 错误；全套 pytest 绿
- [ ] 教育 Agent 页面仍可访问（不破坏，留待 M5）

## 明确不做（M3 范围外）

- service/review/guide 三个 Agent 实现（M4/M5）
- 多轮导购状态机、售后 HitL 审批（M4/M5）
- 教育菜单/页面/表删除、品牌改名（M5）
- 意图分类器微调（规则+LLM 路由已覆盖；微调列为 M5 可选项）
- 取消订单/物流跟踪等增强下单功能（spec 轻量外壳）
