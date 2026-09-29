<!-- frontend/src/views/guide/GuideChatView.vue -->
<script setup lang="ts">
import { ref, onMounted, nextTick, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { guideApi, type GuideReportResponse } from '@/api/guide'
import { useAuthStore } from '@/stores/auth'
import ChatBubble from '@/components/chat/ChatBubble.vue'
import MarkdownRenderer from '@/components/chat/MarkdownRenderer.vue'
import StageProgressBar from '@/components/interview/StageProgressBar.vue'

const GUIDE_STAGES = [
  { key: 'needs_discovery', label: '需求探询' },
  { key: 'budget_confirm', label: '预算确认' },
  { key: 'matching', label: '商品匹配' },
  { key: 'compare_qa', label: '对比答疑' },
  { key: 'recommend_close', label: '最终推荐' },
  { key: 'finished', label: '完成' },
]

interface Message { role: 'user' | 'assistant'; content: string }

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const sessionId = String(route.params.sessionId)

const messages = ref<Message[]>([])
const inputText = ref('')
const isStreaming = ref(false)
const streamingText = ref('')
const currentStage = ref('needs_discovery')
const isFinished = ref(false)
const report = ref<GuideReportResponse | null>(null)
const messagesEl = ref<HTMLElement>()

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
}

async function sendMessage() {
  const text = inputText.value.trim()
  if (!text || isStreaming.value || isFinished.value) return
  inputText.value = ''
  messages.value.push({ role: 'user', content: text })
  await scrollToBottom()
  isStreaming.value = true
  streamingText.value = ''

  await guideApi.chatStream(sessionId, text, auth.token ?? '', {
    onToken: (t) => { streamingText.value += t; scrollToBottom() },
    onDone: async (done) => {
      if (streamingText.value) {
        messages.value.push({ role: 'assistant', content: streamingText.value })
      }
      streamingText.value = ''
      if (done.current_stage) currentStage.value = done.current_stage
      if (done.is_finished) {
        isFinished.value = true
        await fetchReport()
      }
      isStreaming.value = false
      scrollToBottom()
    },
    onError: (msg) => {
      streamingText.value = ''
      isStreaming.value = false
      ElMessage.error(msg)
    },
  })
}

function recommendNow() {
  if (isFinished.value) return
  inputText.value = '直接推荐'
  sendMessage()
}

async function fetchReport() {
  try {
    const { data } = await guideApi.report(sessionId)
    report.value = data
    if (data.status !== 'finished') {
      setTimeout(fetchReport, 2000)
    }
  } catch { /* 下次再试 */ }
}

function goDetail(productId: string) {
  router.push(`/products/${productId}`)
}

onMounted(async () => {
  const opening = (history.state as { openingMessage?: string })?.openingMessage
  if (opening) {
    messages.value.push({ role: 'assistant', content: opening })
    await scrollToBottom()
  }
  // 已结束的会话重进 → 直接拉报告
  try {
    const { data } = await guideApi.report(sessionId)
    if (data.status === 'finished') {
      isFinished.value = true
      currentStage.value = 'finished'
      report.value = data
    }
  } catch { /* 新会话无报告 */ }
})

onBeforeUnmount(() => { isStreaming.value = false })
</script>

<template>
  <div class="guide-chat">
    <StageProgressBar :current="currentStage" :stages="GUIDE_STAGES" />

    <div class="chat-panel">
      <div ref="messagesEl" class="chat-messages">
        <ChatBubble
          v-for="(m, i) in messages"
          :key="i"
          :role="m.role"
        >
          <MarkdownRenderer :content="m.content" />
        </ChatBubble>
        <ChatBubble v-if="streamingText" role="assistant">
          <MarkdownRenderer :content="streamingText" />
        </ChatBubble>
      </div>

      <!-- 推荐面板（结束后展示） -->
      <div v-if="isFinished && report" class="report-panel">
        <div class="report-title">🎯 为您推荐</div>
        <p class="report-summary">{{ report.summary }}</p>
        <div class="rec-list">
          <div
            v-for="rec in report.recommendations"
            :key="rec.product_id"
            class="rec-card"
            @click="goDetail(rec.product_id)"
          >
            <div class="rec-title">{{ rec.title }}</div>
            <div class="rec-price">¥{{ rec.price }}</div>
            <div class="rec-reason">{{ rec.reason }}</div>
            <el-button size="small" type="primary" plain>查看详情 →</el-button>
          </div>
        </div>
      </div>

      <div v-if="!isFinished" class="chat-input-area">
        <el-input
          v-model="inputText"
          :disabled="isStreaming"
          placeholder="描述您的需求…（Enter 发送）"
          @keyup.enter="sendMessage"
        />
        <el-button type="primary" :disabled="isStreaming" @click="sendMessage">发送</el-button>
        <el-button type="warning" plain :disabled="isStreaming" @click="recommendNow">
          🎯 直接出推荐
        </el-button>
      </div>
      <div v-else class="finished-tip">选购结束 · 点击推荐卡片查看商品详情</div>
    </div>
  </div>
</template>

<style scoped>
.guide-chat { max-width: 900px; }
.chat-panel {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #ebeef5;
  display: flex;
  flex-direction: column;
  height: calc(100vh - 56px - 48px - 80px);
  min-height: 420px;
}
.chat-messages { flex: 1; overflow-y: auto; padding: 16px; }
.chat-input-area { display: flex; gap: 8px; padding: 12px; border-top: 1px solid #f0f2f5; }
.finished-tip { text-align: center; color: #909399; font-size: 13px; padding: 14px; border-top: 1px solid #f0f2f5; }
.report-panel { border-top: 1px solid #f0f2f5; padding: 14px; background: #fafbfc; max-height: 40%; overflow-y: auto; }
.report-title { font-weight: 600; margin-bottom: 6px; }
.report-summary { color: #606266; font-size: 13px; line-height: 1.6; margin: 0 0 10px; }
.rec-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 10px; }
.rec-card { background: #fff; border: 1px solid #ebeef5; border-radius: 8px; padding: 12px; cursor: pointer; transition: border-color .2s; }
.rec-card:hover { border-color: #409eff; }
.rec-title { font-weight: 600; font-size: 13px; line-height: 1.4; }
.rec-price { color: #f56c6c; font-weight: 700; margin: 6px 0; }
.rec-reason { color: #909399; font-size: 12px; line-height: 1.5; margin-bottom: 8px; }
</style>
