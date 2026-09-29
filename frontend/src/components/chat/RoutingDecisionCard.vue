<template>
  <div class="routing-card">
    <div class="routing-header">
      <el-icon class="routing-icon"><Connection /></el-icon>
      <span class="routing-title">路由决策</span>
      <el-tag :type="confidenceTagType" size="small" class="confidence-tag">
        {{ Math.round(confidence * 100) }}% 置信度
      </el-tag>
    </div>
    <div class="routing-body">
      <div class="routing-agent">
        <span class="label">识别意图</span>
        <el-tag :type="agentTagType" size="small">
          {{ icon }} {{ agentDisplay || agentType }}
        </el-tag>
      </div>
      <div class="routing-reason">
        <span class="label">判断依据</span>
        <span class="reason-text">{{ reason }}</span>
      </div>
      <div class="routing-mode">
        <span class="label">执行模式</span>
        <span class="mode-text">{{ modeDisplay }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Connection } from '@element-plus/icons-vue'

const props = defineProps<{
  agentType: string
  agentDisplay: string
  confidence: number
  reason: string
  executionMode: string
}>()

// 展示名优先（后端 _LABEL_DISPLAY 已是电商语义）；图标按展示名/占位载荷映射
const displayIcon: Record<string, string> = {
  '商品导购问答': '💬',
  '售后服务中心': '🎧',
  '商品评价分析': '📊',
  '智能选购推荐': '🛍️',
  '智能助手': '✨',
}
// 占位载荷兼容：review 走 RESUME、guide 走 INTERVIEW、service 走 EXAM
const typeIcon: Record<string, string> = {
  qa: '💬', exam: '🎧', resume: '📊', interview: '🛍️',
}

const icon = computed(() => displayIcon[props.agentDisplay] ?? typeIcon[props.agentType] ?? '💬')

const agentTagType = computed(() => {
  if (props.agentDisplay === '商品导购问答' || props.agentType === 'qa') return 'success'
  if (props.agentDisplay === '售后服务中心') return 'warning'
  if (props.agentDisplay === '商品评价分析') return 'info'
  return 'success'
})

const confidenceTagType = computed(() => {
  if (props.confidence >= 0.85) return 'success'
  if (props.confidence >= 0.65) return 'warning'
  return 'danger'
})

const modeDisplay = computed(() => {
  const map: Record<string, string> = {
    single:   '单 Agent 直达',
    clarify:  '需要澄清',
  }
  return map[props.executionMode] ?? props.executionMode
})
</script>

<style scoped>
.routing-card {
  background: var(--sp-primary-soft, #e7f0ec);
  border: 1px solid var(--sp-primary-light-7, #bbd5cd);
  border-radius: 10px;
  padding: 10px 14px;
  margin-bottom: 4px;
  font-size: 13px;
}
.routing-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-weight: 600;
  color: var(--sp-primary, #2f6f5e);
}
.routing-icon {
  font-size: 14px;
}
.routing-title {
  flex: 1;
}
.confidence-tag {
  font-size: 11px;
}
.routing-body {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.routing-agent,
.routing-reason,
.routing-mode {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.label {
  color: var(--sp-ink-3, #8a968f);
  min-width: 52px;
  flex-shrink: 0;
}
.reason-text,
.mode-text {
  color: var(--sp-ink, #1c2420);
  line-height: 1.5;
}
</style>
