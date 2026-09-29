<template>
  <div class="dashboard">
    <!-- 门面区 -->
    <header class="hero">
      <div class="hero-copy">
        <span class="sp-eyebrow">SHOPPILOT 智能商城</span>
        <h1 class="hero-title">欢迎回来，{{ auth.user?.username ?? auth.user?.userId }}</h1>
        <p class="hero-sub">逛商品、问 AI、管订单——需要拿主意的时候，让导购助手来。</p>
      </div>
      <div class="hero-actions">
        <el-button type="primary" size="large" @click="router.push('/products')">浏览商品</el-button>
        <el-button size="large" @click="router.push('/chat')">问 AI 助手</el-button>
      </div>
    </header>

    <!-- AI 统一入口（墨绿深色主卡） -->
    <section
      class="ai-card sp-hover"
      @click="router.push('/chat')"
    >
      <div class="ai-card-main">
        <div class="ai-badge">
          <el-icon :size="22" color="#7fbfaa"><MagicStick /></el-icon>
        </div>
        <div>
          <div class="ai-title">AI 导购助手</div>
          <div class="ai-desc">一句话描述需求，自动识别意图并路由到问答、售后、口碑分析或选购推荐。</div>
        </div>
      </div>
      <el-button type="primary" class="ai-cta">开始对话 →</el-button>
    </section>

    <!-- 能力陈列 -->
    <section class="capabilities">
      <div class="cap-head">
        <h2 class="sp-page-title" style="margin: 0">能做什么</h2>
        <p class="sp-page-sub" style="margin: 0">四个入口，对应商城里的四件正事</p>
      </div>
      <div class="cap-grid">
        <article
          v-for="card in featureCards"
          :key="card.route"
          class="cap-card sp-hover"
          @click="router.push(card.route)"
        >
          <div class="cap-icon" :style="{ background: card.tint }">
            <el-icon :size="22" :color="card.color"><component :is="card.icon" /></el-icon>
          </div>
          <h3 class="cap-title">{{ card.title }}</h3>
          <p class="cap-desc">{{ card.desc }}</p>
          <div class="cap-foot">
            <span class="cap-action">{{ card.action }}</span>
            <el-icon :size="14" color="#8a968f"><ArrowRight /></el-icon>
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ArrowRight, MagicStick } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const featureCards = [
  {
    icon: 'Shop',
    title: '商品浏览',
    desc: '中文商品库，支持搜索与类目筛选',
    action: '去逛逛',
    route: '/products',
    tint: '#e7f0ec',
    color: '#2f6f5e',
  },
  {
    icon: 'ChatDotRound',
    title: '智能问答',
    desc: '基于商品库的导购问答，流式回答',
    action: '开始问答',
    route: '/qa',
    tint: '#fbede2',
    color: '#e07b39',
  },
  {
    icon: 'ShoppingCart',
    title: '我的订单',
    desc: '下单与支付，状态一目了然',
    action: '查看订单',
    route: '/orders',
    tint: '#e7f0ec',
    color: '#2f6f5e',
  },
  {
    icon: 'ShoppingBag',
    title: '智能导购',
    desc: '多轮对话，按需求给出推荐清单',
    action: '开始选购',
    route: '/guide',
    tint: '#fbede2',
    color: '#e07b39',
  },
]
</script>

<style scoped>
.dashboard {
  max-width: 1100px;
}

/* 门面 */
.hero {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}
.hero-title {
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.03em;
  color: var(--sp-ink);
}
.hero-sub {
  margin: 0;
  font-size: 14px;
  color: var(--sp-ink-2);
  line-height: 1.6;
}
.hero-actions {
  display: flex;
  gap: 12px;
  flex-shrink: 0;
}

/* AI 主卡：墨绿深色，整页视觉重心 */
.ai-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  padding: 28px 32px;
  border-radius: 16px;
  cursor: pointer;
  color: #fff;
  background:
    radial-gradient(600px 200px at 100% 0%, #2f6f5e55 0%, transparent 55%),
    var(--sp-ink);
  border: 1px solid #2f6f5e66;
  margin-bottom: 32px;
}
.ai-card-main {
  display: flex;
  align-items: center;
  gap: 20px;
}
.ai-badge {
  width: 52px;
  height: 52px;
  border-radius: 14px;
  background: #ffffff14;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.ai-title {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin-bottom: 6px;
}
.ai-desc {
  font-size: 13px;
  color: #ffffffb3;
  line-height: 1.6;
  max-width: 520px;
}
.ai-cta {
  flex-shrink: 0;
}

/* 能力陈列 */
.cap-head {
  margin-bottom: 16px;
}
.cap-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}
.cap-card {
  background: var(--sp-surface);
  border: 1px solid var(--sp-line);
  border-radius: 14px;
  padding: 20px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
}
.cap-icon {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 14px;
}
.cap-title {
  margin: 0 0 6px;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: var(--sp-ink);
}
.cap-desc {
  margin: 0;
  font-size: 12.5px;
  color: var(--sp-ink-2);
  line-height: 1.6;
  flex: 1;
}
.cap-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--sp-line);
}
.cap-action {
  font-size: 13px;
  font-weight: 600;
  color: var(--sp-primary);
}

@media (max-width: 960px) {
  .cap-grid { grid-template-columns: repeat(2, 1fr); }
  .hero { flex-direction: column; align-items: flex-start; }
  .ai-card { flex-direction: column; align-items: flex-start; }
}
@media (max-width: 560px) {
  .cap-grid { grid-template-columns: 1fr; }
}
</style>
