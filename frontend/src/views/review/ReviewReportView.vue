<!-- frontend/src/views/review/ReviewReportView.vue -->
<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reviewsApi, type ReviewReport } from '@/api/reviews'
import DimensionScoreCard from '@/components/resume/DimensionScoreCard.vue'

const route = useRoute()
const router = useRouter()

const report = ref<ReviewReport | null>(null)
const loading = ref(true)
const failedMsg = ref('')
let pollTimer: number | null = null
let disposed = false

function stopPoll() {
  if (pollTimer !== null) {
    window.clearTimeout(pollTimer)
    pollTimer = null
  }
}

async function fetchReport() {
  const reportId = String(route.params.reportId)
  if (!reportId) return
  try {
    const { data } = await reviewsApi.get(reportId)
    if (disposed) return
    report.value = data
    loading.value = false
    if (data.status === 'processing' || data.status === 'pending') {
      // 5s 递归轮询（平移自 ResumeReportView 模式）
      pollTimer = window.setTimeout(fetchReport, 5_000)
    } else if (data.status === 'failed') {
      failedMsg.value = data.error_msg || '分析失败，请稍后重试'
    }
  } catch {
    if (disposed) return
    loading.value = false
    ElMessage.error('报告加载失败')
  }
}

function reload() {
  stopPoll()
  loading.value = true
  report.value = null
  failedMsg.value = ''
  fetchReport()
}

onMounted(() => {
  disposed = false
  reload()
})

// 路由参数变化（如从报告 A 跳到报告 B）时重载；watch 不带 immediate，不会与 onMounted 重复
watch(() => route.params.reportId, reload)

onBeforeUnmount(() => {
  disposed = true
  stopPoll()
})

function backToProduct() {
  if (report.value) router.push(`/products/${report.value.product_id}`)
  else router.push('/products')
}
</script>

<template>
  <div class="review-report">
    <el-page-header content="口碑分析报告" @back="backToProduct" />

    <!-- 加载骨架 -->
    <div v-if="loading" class="state-block">
      <el-skeleton :rows="8" animated />
    </div>

    <!-- 失败 -->
    <el-result
      v-else-if="report?.status === 'failed'"
      icon="error"
      title="分析失败"
      :sub-title="failedMsg"
    >
      <template #extra>
        <el-button type="primary" @click="reload">重试</el-button>
      </template>
    </el-result>

    <!-- 处理中 -->
    <div v-else-if="report && (report.status === 'processing' || report.status === 'pending')" class="state-block">
      <el-result icon="info" title="AI 正在分析口碑" sub-title="通常需要 20~60 秒，页面会自动刷新">
        <template #extra>
          <el-skeleton :rows="3" animated />
        </template>
      </el-result>
    </div>

    <!-- 完成 -->
    <template v-else-if="report?.status === 'done'">
      <div class="head-card">
        <div class="head-left">
          <div class="product-title">{{ report.product_title }}</div>
          <div class="meta">六维口碑分析 · 基于买家真实评价</div>
        </div>
        <div class="score-block">
          <div class="score-num">{{ report.weighted_score }}</div>
          <div class="score-label">加权总分 / 100</div>
        </div>
      </div>

      <div class="dim-grid">
        <DimensionScoreCard
          v-for="d in report.dimensions"
          :key="d.key"
          :dimension="d.name"
          :score="d.score"
          :weight="d.weight"
          :issues="d.issues"
          :suggestions="d.suggestions"
        />
      </div>

      <el-row :gutter="16" class="pros-cons">
        <el-col :span="12">
          <el-card shadow="never">
            <template #header><span class="pros-title">👍 买家认可</span></template>
            <div v-for="(p, i) in report.pros" :key="i" class="pc-item">
              <el-tag type="success" size="small" effect="plain">优点</el-tag>
              <span>{{ p }}</span>
            </div>
            <div v-if="!report.pros.length" class="empty-tip">暂无</div>
          </el-card>
        </el-col>
        <el-col :span="12">
          <el-card shadow="never">
            <template #header><span class="cons-title">👎 买家吐槽</span></template>
            <div v-for="(c, i) in report.cons" :key="i" class="pc-item">
              <el-tag type="danger" size="small" effect="plain">缺点</el-tag>
              <span>{{ c }}</span>
            </div>
            <div v-if="!report.cons.length" class="empty-tip">暂无</div>
          </el-card>
        </el-col>
      </el-row>

      <el-card shadow="never" class="summary-card">
        <template #header><span>📝 分析总结</span></template>
        <p class="summary-text">{{ report.summary }}</p>
      </el-card>
    </template>
  </div>
</template>

<style scoped>
.review-report { max-width: 1000px; }
.state-block { margin-top: 24px; }
.head-card {
  display: flex; justify-content: space-between; align-items: center;
  background: #fff; border: 1px solid #ebeef5; border-radius: 8px;
  padding: 20px 24px; margin-top: 20px;
}
.product-title { font-size: 18px; font-weight: 600; }
.meta { color: #909399; font-size: 13px; margin-top: 6px; }
.score-block { text-align: center; }
.score-num { font-size: 40px; font-weight: 700; color: #f56c6c; line-height: 1; }
.score-label { font-size: 12px; color: #909399; margin-top: 4px; }
.dim-grid {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 16px; margin-top: 16px;
}
.pros-cons { margin-top: 16px; }
.pc-item { display: flex; gap: 8px; align-items: flex-start; margin-bottom: 10px; line-height: 1.5; font-size: 13px; }
.empty-tip { color: #c0c4cc; font-size: 13px; }
.pros-title { color: #67c23a; }
.cons-title { color: #f56c6c; }
.summary-card { margin-top: 16px; }
.summary-text { margin: 0; line-height: 1.8; color: #303133; }
</style>
