<!-- frontend/src/views/order/OrderListView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ordersApi, type OrderItem } from '@/api/orders'
import { serviceApi, type TicketType } from '@/api/service'

const router = useRouter()
const loading = ref(false)
const items = ref<OrderItem[]>([])
const payingId = ref('')

// ── 申请售后（M4b）──
const afterSaleVisible = ref(false)
const submittingTicket = ref(false)
const afterSaleForm = ref({ orderId: '', type: 'refund' as TicketType, reason: '' })

function openAfterSale(row: OrderItem) {
  afterSaleForm.value = { orderId: row.id, type: 'refund', reason: '' }
  afterSaleVisible.value = true
}

async function submitAfterSale() {
  const reason = afterSaleForm.value.reason.trim()
  if (reason.length < 5) {
    ElMessage.warning('请填写至少 5 个字的诉求说明')
    return
  }
  submittingTicket.value = true
  try {
    await serviceApi.create({
      order_id: afterSaleForm.value.orderId,
      ticket_type: afterSaleForm.value.type,
      reason,
    })
    ElMessage.success('工单已提交，AI 正在处理')
    afterSaleVisible.value = false
    router.push('/service')
  } catch { /* 拦截器提示 */ }
  finally { submittingTicket.value = false }
}

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
        <el-table-column label="金额" width="130">
          <template #default="{ row }">
            <span class="price-tag price-tag--sm">
              <span class="yen">¥</span>
              <span class="num">{{ row.total_amount }}</span>
            </span>
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
        <el-table-column label="操作" width="210">
          <template #default="{ row }">
            <el-button
              v-if="row.status === 'created'" type="primary" size="small"
              :loading="payingId === row.id" @click="pay(row)"
            >模拟支付</el-button>
            <el-button
              v-if="['paid','shipped','completed'].includes(row.status)"
              size="small" @click="openAfterSale(row)"
            >申请售后</el-button>
            <span v-if="!['created','paid','shipped','completed'].includes(row.status)"
                  style="color:#c0c4cc;font-size:12px">—</span>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="还没有订单，去商品页逛逛" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <el-dialog v-model="afterSaleVisible" title="申请售后" width="460px">
      <el-form label-width="80px">
        <el-form-item label="类型">
          <el-radio-group v-model="afterSaleForm.type">
            <el-radio value="logistics">物流查询</el-radio>
            <el-radio value="refund">退款</el-radio>
            <el-radio value="exchange">换货</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="诉求说明">
          <el-input
            v-model="afterSaleForm.reason" type="textarea" :rows="3"
            placeholder="请描述遇到的问题（至少 5 个字）" maxlength="300" show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="afterSaleVisible = false">取消</el-button>
        <el-button type="primary" :loading="submittingTicket" @click="submitAfterSale">提交工单</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.order-list { max-width: 1100px; }
</style>
