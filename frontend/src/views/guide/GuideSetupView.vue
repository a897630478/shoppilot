<!-- frontend/src/views/guide/GuideSetupView.vue -->
<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { guideApi } from '@/api/guide'

const router = useRouter()
const message = ref('')
const starting = ref(false)

async function start() {
  starting.value = true
  try {
    const { data } = await guideApi.create(message.value.trim())
    router.push({ path: `/guide/${data.session_id}`, state: { openingMessage: data.opening_message } })
  } catch {
    ElMessage.error('会话创建失败')
  } finally {
    starting.value = false
  }
}
</script>

<template>
  <div class="guide-setup">
    <el-card shadow="never" class="setup-card">
      <template #header><span>🛍️ 智能导购</span></template>
      <p class="hint">告诉我想买什么，AI 会通过几轮对话了解需求，最后给出商品推荐。</p>
      <el-input
        v-model="message"
        type="textarea"
        :rows="4"
        maxlength="500"
        show-word-limit
        placeholder="例如：想买瓶装水日常喝，预算 50 以内 / 想给朋友挑个礼物，不知道选什么"
        @keyup.enter.ctrl="start"
      />
      <div class="actions">
        <el-button type="primary" size="large" :loading="starting" @click="start">
          开始导购 →
        </el-button>
      </div>
      <p class="tip">也可以留空直接开始，AI 会主动询问您的需求</p>
    </el-card>
  </div>
</template>

<style scoped>
.guide-setup { max-width: 640px; }
.setup-card { margin-top: 8px; }
.hint { color: #606266; line-height: 1.6; }
.actions { margin-top: 16px; display: flex; justify-content: flex-end; }
.tip { color: #c0c4cc; font-size: 12px; margin-top: 12px; text-align: right; }
</style>
