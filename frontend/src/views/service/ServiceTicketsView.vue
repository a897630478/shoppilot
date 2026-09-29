<!-- frontend/src/views/service/ServiceTicketsView.vue -->
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage } from 'element-plus'
import { serviceApi, type TicketItem } from '@/api/service'

const loading = ref(false)
const items = ref<TicketItem[]>([])
let pollTimer: number | null = null
let disposed = false

const typeLabel: Record<string, string> = {
  logistics: '物流查询', refund: '退款', exchange: '换货',
}
const statusTag: Record<string, { label: string; type: 'warning' | 'primary' | 'info' | 'success' | 'danger' }> = {
  pending:    { label: '人工审核中', type: 'warning' },
  processing: { label: 'AI 处理中',  type: 'info' },
  resolved:   { label: '已解决',     type: 'success' },
  rejected:   { label: '已驳回',     type: 'danger' },
}

function stopPoll() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

async function load() {
  loading.value = true
  try {
    const { data } = await serviceApi.listMine()
    if (disposed) return
    items.value = data.items
    // 有处理中的工单 → 4s 后刷新
    if (data.items.some((t) => t.status === 'processing')) {
      pollTimer = window.setTimeout(load, 4_000)
    }
  } catch {
    ElMessage.error('工单加载失败')
  } finally {
    loading.value = false
  }
}

function fmtDate(iso: string | null) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '--'
}

onMounted(() => { disposed = false; load() })
onBeforeUnmount(() => { disposed = true; stopPoll() })
</script>

<template>
  <div class="service-tickets">
    <el-card shadow="never">
      <template #header><span>🎧 我的售后服务</span></template>
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column label="商品" min-width="180" prop="product_title" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ typeLabel[row.ticket_type] ?? row.ticket_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="诉求" min-width="200" prop="reason" show-overflow-tooltip />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTag[row.status]?.type ?? 'info'" size="small">
              {{ statusTag[row.status]?.label ?? row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="发起时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="AI 回复" min-width="260">
          <template #default="{ row }">
            <template v-if="row.ai_result?.reply">
              <div>{{ row.ai_result.reply }}</div>
              <div v-if="row.status === 'pending'" class="review-hint">
                ⏳ 已转人工审核<template v-if="row.ai_result.suggestion">：{{ row.ai_result.suggestion }}</template>
              </div>
              <div v-if="row.ai_result.operator_comment" class="operator-hint">
                🧑‍💼 审批意见：{{ row.ai_result.operator_comment }}
              </div>
            </template>
            <span v-else-if="row.status === 'processing'" class="muted">处理中…</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有售后工单，可在「我的订单」发起" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.service-tickets { max-width: 1100px; }
.review-hint { color: #e6a23c; font-size: 12px; margin-top: 4px; }
.operator-hint { color: #409eff; font-size: 12px; margin-top: 4px; }
.muted { color: #c0c4cc; font-size: 12px; }
</style>
