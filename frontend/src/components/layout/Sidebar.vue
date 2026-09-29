<template>
  <div class="sidebar">
    <div class="logo">
      <el-icon :size="20" color="#7fbfaa"><Shop /></el-icon>
      <span>ShopPilot</span>
    </div>
    <nav class="nav-list">
      <RouterLink to="/dashboard" class="nav-item" :class="{ 'nav-item--active': isActive('/dashboard') }">
        <el-icon><House /></el-icon>
        <span>首页</span>
      </RouterLink>

      <RouterLink to="/products" class="nav-item" :class="{ 'nav-item--active': isActive('/products') }">
        <el-icon><Shop /></el-icon>
        <span>商品浏览</span>
      </RouterLink>

      <RouterLink to="/orders" class="nav-item" :class="{ 'nav-item--active': isActive('/orders') }">
        <el-icon><ShoppingCart /></el-icon>
        <span>我的订单</span>
      </RouterLink>

      <RouterLink to="/service" class="nav-item" :class="{ 'nav-item--active': isActive('/service') }">
        <el-icon><Headset /></el-icon>
        <span>售后服务</span>
      </RouterLink>

      <RouterLink to="/guide" class="nav-item" :class="{ 'nav-item--active': isActive('/guide') }">
        <el-icon><ShoppingBag /></el-icon>
        <span>智能导购</span>
      </RouterLink>

      <RouterLink to="/qa" class="nav-item" :class="{ 'nav-item--active': isActive('/qa') }">
        <el-icon><ChatDotRound /></el-icon>
        <span>智能问答</span>
      </RouterLink>

      <!-- 运营端菜单（仅 teacher/admin 可见） -->
      <template v-if="auth.isTeacher">
        <div class="nav-divider" />
        <RouterLink to="/operator/service-review" class="nav-item" :class="{ 'nav-item--active': isActive('/operator/service-review') }">
          <el-icon><Checked /></el-icon>
          <span>售后审批</span>
        </RouterLink>
        <RouterLink to="/operator/faq-pending" class="nav-item" :class="{ 'nav-item--active': isActive('/operator/faq-pending') }">
          <el-icon><EditPen /></el-icon>
          <span>FAQ 补录</span>
        </RouterLink>
      </template>
    </nav>
  </div>
</template>

<script setup lang="ts">
import { useRoute } from 'vue-router'
import {
  House, ChatDotRound, Shop, ShoppingCart, Headset, Checked, ShoppingBag, EditPen,
} from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const route = useRoute()

// 仅用于子路由高亮（纯视觉反馈，不参与导航逻辑）
// RouterLink 的 active-class 基于路由记录层级，不覆盖平级子路由（如 /resume/:id）
function isActive(prefix: string) {
  return route.path === prefix || route.path.startsWith(prefix + '/')
}
</script>

<style scoped>
.sidebar {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: -0.02em;
  border-bottom: 1px solid #ffffff1a;
  flex-shrink: 0;
}

.nav-list {
  display: flex;
  flex-direction: column;
  padding: 8px 0;
  flex: 1;
}

.nav-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 20px;
  color: #ffffffb3;
  text-decoration: none;
  font-size: 14px;
  cursor: pointer;
  transition: background-color 0.18s, color 0.18s;
  user-select: none;
}

.nav-item:hover {
  background-color: #ffffff14;
  color: #fff;
}

.nav-item--active {
  background-color: #2f6f5e33;
  color: #fff;
  font-weight: 600;
}
/* 青瓷绿指示条：侧栏的定位锚点 */
.nav-item--active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 8px;
  bottom: 8px;
  width: 3px;
  border-radius: 0 2px 2px 0;
  background: #7fbfaa;
}

.nav-item .el-icon {
  font-size: 16px;
  flex-shrink: 0;
}

.nav-divider {
  border: none;
  border-top: 1px solid #ffffff1a;
  margin: 8px 0;
}
</style>
