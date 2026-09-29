import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
      meta: { public: true },
    },
    {
      path: '/',
      component: () => import('@/components/layout/AppLayout.vue'),
      meta: { requiresAuth: true },
      children: [
        {
          path: '',
          redirect: '/dashboard',
        },
        {
          path: 'dashboard',
          name: 'dashboard',
          component: () => import('@/views/DashboardView.vue'),
        },
        // AI 助手（统一入口）
        {
          path: 'chat',
          name: 'chat',
          component: () => import('@/views/UnifiedChatView.vue'),
        },
        // QA 问答
        {
          path: 'qa',
          name: 'qa',
          component: () => import('@/views/qa/QAChatView.vue'),
        },
        // 商品浏览（M2）
        {
          path: 'products',
          name: 'products',
          component: () => import('@/views/product/ProductListView.vue'),
        },
        {
          path: 'products/:id',
          name: 'product-detail',
          component: () => import('@/views/product/ProductDetailView.vue'),
        },
        // 我的订单（M3）
        {
          path: 'orders',
          name: 'orders',
          component: () => import('@/views/order/OrderListView.vue'),
        },
        // 口碑报告（M4a）
        {
          path: 'reviews/reports/:reportId',
          name: 'review-report',
          component: () => import('@/views/review/ReviewReportView.vue'),
        },
        // 我的售后（M4b）
        {
          path: 'service',
          name: 'service-tickets',
          component: () => import('@/views/service/ServiceTicketsView.vue'),
        },
        // 售后审批（M4b，运营端）
        {
          path: 'operator/service-review',
          name: 'operator-service-review',
          component: () => import('@/views/operator/ServiceReviewView.vue'),
          meta: { requiresTeacher: true },
        },
        // FAQ 补录（收尾补全，运营端）
        {
          path: 'operator/faq-pending',
          name: 'operator-faq-pending',
          component: () => import('@/views/operator/FaqPendingView.vue'),
          meta: { requiresTeacher: true },
        },
        // 智能导购（M5a）
        {
          path: 'guide',
          name: 'guide-setup',
          component: () => import('@/views/guide/GuideSetupView.vue'),
        },
        {
          path: 'guide/:sessionId',
          name: 'guide-chat',
          component: () => import('@/views/guide/GuideChatView.vue'),
        },
      ],
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/dashboard',
    },
  ],
})

router.beforeEach((to, _from, next) => {
  const auth = useAuthStore()

  if (to.meta.public) {
    if (auth.isLoggedIn && to.name === 'login') return next('/dashboard')
    return next()
  }

  if (!auth.isLoggedIn) return next('/login')

  if (to.meta.requiresTeacher && !auth.isTeacher) return next('/dashboard')

  next()
})

export default router
