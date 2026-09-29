<!-- frontend/src/views/product/ProductDetailView.vue -->
<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ChatDotRound } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { productsApi, type ProductDetail } from '@/api/products'
import { ordersApi } from '@/api/orders'
import { reviewsApi } from '@/api/reviews'

const route = useRoute()
const router = useRouter()
const detail = ref<ProductDetail | null>(null)
const loading = ref(false)

async function load() {
  loading.value = true
  existingReportId.value = null
  try {
    const { data } = await productsApi.detail(String(route.params.id))
    detail.value = data
    checkLatestReport()
  } catch {
    ElMessage.error('商品加载失败')
    router.push('/products')
  } finally {
    loading.value = false
  }
}

// ── 口碑分析（M4a）──
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
  // 已有报告 → 直接查看；没有 → 新建
  if (existingReportId.value) {
    router.push(`/reviews/reports/${existingReportId.value}`)
    return
  }
  analyzing.value = true
  try {
    const { data } = await reviewsApi.create(detail.value.id)
    router.push(`/reviews/reports/${data.report_id}`)
  } catch { /* 拦截器提示 */ }
  finally { analyzing.value = false }
}

function askAi() {
  if (!detail.value) return
  const q = `介绍一下「${detail.value.title}」，适合我吗？`
  router.push({ path: '/qa', query: { q, product_id: detail.value.id } })
}

// ── 模拟下单（M3）──
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
          <img v-if="detail.image_url" :src="detail.image_url" :alt="detail.title" class="image" />
          <div v-else class="image placeholder">暂无图片</div>
        </div>
        <div class="info">
          <h1 class="title">{{ detail.title }}</h1>
          <div class="sub">
            <el-tag v-if="detail.category" size="small">{{ detail.category }}</el-tag>
            <span v-if="detail.rating" class="rating">★ {{ detail.rating }}</span>
            <span class="reviews">{{ detail.review_count }} 条评价</span>
          </div>
          <div class="price-tag price-tag--lg">
            <span class="yen">¥</span>
            <span class="num">{{ detail.price }}</span>
          </div>
          <p class="desc">{{ detail.description || '暂无详情介绍' }}</p>
          <el-button type="primary" size="large" :icon="ChatDotRound" @click="askAi">
            问问 AI · 了解是否适合我
          </el-button>
          <el-button type="danger" size="large" @click="openOrderDialog">立即下单</el-button>
          <el-button size="large" :loading="analyzing" @click="analyzeReviews">
            {{ existingReportId ? '查看口碑报告' : 'AI 口碑分析' }}
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
  </div>
</template>

<style scoped>
.product-detail { max-width: 1000px; }
.main { display: flex; gap: 32px; margin-top: 20px; }
.media { flex: 0 0 320px; }
.image { width: 320px; height: 320px; object-fit: cover; border-radius: 8px; border: 1px solid #ebeef5; }
.placeholder { display: flex; align-items: center; justify-content: center; color: #c0c4cc; background: #f5f7fa; }
.info { flex: 1; }
.title { font-size: 22px; margin: 0 0 12px; letter-spacing: -0.02em; }
.sub { display: flex; gap: 12px; align-items: center; color: var(--sp-ink-2); font-size: 13px; margin-bottom: 16px; }
.rating { color: var(--sp-accent); }
.price-tag { margin-bottom: 16px; }
.desc { color: var(--sp-ink-2); line-height: 1.7; margin-bottom: 24px; }
.params-card { margin-top: 24px; }
</style>
