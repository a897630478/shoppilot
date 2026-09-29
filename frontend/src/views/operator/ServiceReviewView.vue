<!-- frontend/src/views/operator/ServiceReviewView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { serviceApi, type TicketItem } from '@/api/service'

const loading = ref(false)
const items = ref<TicketItem[]>([])
const actingId = ref('')

const typeLabel: Record<string, string> = {
  logistics: '物流查询', refund: '退款', exchange: '换货',
}

async function fetchList() {
  loading.value = true
  try {
    const { data } = await serviceApi.listPending()
    items.value = data.items
  } catch {
    ElMessage.error('审批列表加载失败')
  } finally {
    loading.value = false
  }
}

async function approve(row: TicketItem) {
  actingId.value = row.id
  try {
    await serviceApi.review(row.id, 'approve')
    ElMessage.success('已批准，工单转为已解决')
    await fetchList()
  } catch { /* 拦截器提示 */ }
  finally { actingId.value = '' }
}

async function reject(row: TicketItem) {
  try {
    const { value } = await ElMessageBox.prompt(
      '请填写驳回理由（会展示给用户）', '驳回工单',
      { confirmButtonText: '驳回', cancelButtonText: '取消', inputPattern: /\S{2,}/, inputErrorMessage: '理由不能为空' },
    )
    actingId.value = row.id
    await serviceApi.review(row.id, 'reject', value)
    ElMessage.success('已驳回')
    await fetchList()
  } catch { /* 用户取消或接口错误 */ }
  finally { actingId.value = '' }
}

function fmtDate(iso: string | null) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '--'
}

onMounted(fetchList)
</script>

<template>
  <div class="service-review">
    <el-card shadow="never">
      <template #header><span>✅ 售后工单审批</span></template>
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column label="商品" min-width="160" prop="product_title" />
        <el-table-column label="类型" width="90">
          <template #default="{ row }">
            <el-tag size="small">{{ typeLabel[row.ticket_type] ?? row.ticket_type }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="用户诉求" min-width="180" prop="reason" show-overflow-tooltip />
        <el-table-column label="AI 建议" min-width="220">
          <template #default="{ row }">
            {{ row.ai_result?.suggestion || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="发起时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170">
          <template #default="{ row }">
            <el-button
              type="primary" size="small" :loading="actingId === row.id"
              @click="approve(row)"
            >批准</el-button>
            <el-button
              type="danger" size="small" plain
              :disabled="actingId === row.id" @click="reject(row)"
            >驳回</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无待审批工单" :image-size="80" />
        </template>
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.service-review { max-width: 1100px; }
</style>
