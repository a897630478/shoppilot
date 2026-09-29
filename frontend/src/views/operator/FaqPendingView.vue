<!-- frontend/src/views/operator/FaqPendingView.vue -->
<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { faqApi, type FaqPendingItem } from '@/api/faq'

const loading = ref(false)
const items = ref<FaqPendingItem[]>([])
const actingId = ref('')

// 补录对话框
const dialogVisible = ref(false)
const answering = ref(false)
const current = ref<FaqPendingItem | null>(null)
const answerText = ref('')

function openResolve(row: FaqPendingItem) {
  current.value = row
  answerText.value = row.answer ?? ''
  dialogVisible.value = true
}

async function submitResolve() {
  const ans = answerText.value.trim()
  if (ans.length < 10) {
    ElMessage.warning('答案至少 10 个字')
    return
  }
  if (!current.value) return
  answering.value = true
  try {
    await faqApi.resolve(current.value.id, ans)
    ElMessage.success('已补录，答案已进入商品知识库')
    dialogVisible.value = false
    await fetchList()
  } catch { /* 拦截器提示 */ }
  finally { answering.value = false }
}

async function dismiss(row: FaqPendingItem) {
  try {
    await ElMessageBox.confirm(`确定忽略「${row.question.slice(0, 20)}…」？`, '忽略问题', {
      confirmButtonText: '忽略', cancelButtonText: '取消', type: 'warning',
    })
  } catch { return }
  actingId.value = row.id
  try {
    await faqApi.dismiss(row.id)
    ElMessage.success('已忽略')
    await fetchList()
  } catch { /* 拦截器提示 */ }
  finally { actingId.value = '' }
}

async function fetchList() {
  loading.value = true
  try {
    const { data } = await faqApi.listPending()
    items.value = data.items
  } catch {
    ElMessage.error('队列加载失败')
  } finally {
    loading.value = false
  }
}

function fmtDate(iso: string | null) {
  return iso ? iso.replace('T', ' ').slice(0, 16) : '--'
}

onMounted(fetchList)
</script>

<template>
  <div class="faq-pending">
    <el-card shadow="never">
      <template #header>
        <span>📝 FAQ 待补录</span>
        <span class="header-tip">低置信度问题 · 补录后进入商品知识库供 AI 检索</span>
      </template>
      <el-table v-loading="loading" :data="items" size="small">
        <el-table-column label="用户问题" min-width="320" prop="question" show-overflow-tooltip />
        <el-table-column label="置信度" width="100">
          <template #default="{ row }">
            <el-tag :type="row.confidence < 0.5 ? 'danger' : 'warning'" size="small">
              {{ Math.round((row.confidence ?? 0) * 100) }}%
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="入队时间" width="150">
          <template #default="{ row }">{{ fmtDate(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="180">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="openResolve(row)">补录答案</el-button>
            <el-button
              size="small" plain :disabled="actingId === row.id"
              @click="dismiss(row)"
            >忽略</el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无待补录问题" :image-size="80" />
        </template>
      </el-table>
    </el-card>

    <el-dialog v-model="dialogVisible" title="补录标准答案" width="560px">
      <div class="question-box">{{ current?.question }}</div>
      <el-input
        v-model="answerText" type="textarea" :rows="5"
        placeholder="写出可被 AI 直接引用的标准答案（10 字以上，客观准确）"
        maxlength="2000" show-word-limit
      />
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="answering" @click="submitResolve">
          补录并入库
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.faq-pending { max-width: 1100px; }
.header-tip { margin-left: 12px; color: #909399; font-size: 12px; }
.question-box {
  background: #f5f7fa; border-radius: 6px; padding: 10px 12px;
  margin-bottom: 12px; color: #303133; line-height: 1.6; font-size: 13px;
}
</style>
