<template>
  <div class="login-page">
    <!-- 左：品牌面板（买手店橱窗感） -->
    <aside class="brand-panel">
      <div class="brand-mark">
        <el-icon :size="28" color="#7fbfaa"><Shop /></el-icon>
        <span class="brand-name">ShopPilot</span>
      </div>
      <div class="brand-copy">
        <h1>逛得明白<br />买得放心</h1>
        <p>商品导购 · 售后服务 · 口碑分析 · 多轮选购<br />一个入口，四种 AI 能力</p>
      </div>
      <ul class="brand-points">
        <li><span class="dot" />基于商品库的实时检索回答</li>
        <li><span class="dot" />退款售后自动处理或转人工</li>
        <li><span class="dot" />六维口碑报告一目了然</li>
      </ul>
    </aside>

    <!-- 右：登录表单 -->
    <main class="form-panel">
      <el-card class="login-card" shadow="never">
        <div class="login-header">
          <h2>欢迎回来</h2>
          <p>登录后即可浏览商品、咨询 AI、管理订单</p>
        </div>
        <el-form
          ref="formRef"
          :model="form"
          :rules="rules"
          label-position="top"
          @submit.prevent="handleLogin"
        >
          <el-form-item label="用户名" prop="username">
            <el-input
              v-model="form.username"
              placeholder="请输入用户名"
              size="large"
              :prefix-icon="User"
            />
          </el-form-item>
          <el-form-item label="密码" prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="请输入密码"
              size="large"
              :prefix-icon="Lock"
              show-password
              @keyup.enter="handleLogin"
            />
          </el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="login-btn"
            @click="handleLogin"
          >
            登录
          </el-button>
        </el-form>
        <p class="demo-hint">演示账号：student01@eduagent.local / Student@123456</p>
      </el-card>
    </main>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { User, Lock, Shop } from '@element-plus/icons-vue'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = reactive({ username: '', password: '' })

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin() {
  await formRef.value?.validate()
  loading.value = true
  try {
    const { data } = await authApi.login({
      username: form.username,
      password: form.password,
    })
    auth.login(data.access_token, {
      userId: data.user_id,
      role: data.role as 'student' | 'teacher' | 'admin',
      tenantId: '',
      username: form.username,
    })
    router.push('/dashboard')
  } catch {
    ElMessage.error('用户名或密码错误')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  background: var(--sp-bg, #f5f7f6);
}

/* 左品牌面板：墨绿黑 + 青瓷绿点缀 */
.brand-panel {
  flex: 1.1;
  background:
    radial-gradient(1200px 500px at 20% -10%, #2f6f5e44 0%, transparent 60%),
    var(--sp-ink, #1c2420);
  color: #fff;
  padding: 56px 64px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}
.brand-mark {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
}
.brand-copy h1 {
  margin: 0 0 16px;
  font-size: 44px;
  font-weight: 700;
  letter-spacing: -0.03em;
  line-height: 1.2;
  color: #fff;
}
.brand-copy p {
  margin: 0;
  font-size: 14px;
  line-height: 1.8;
  color: #ffffffa6;
}
.brand-points {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
  color: #ffffffcc;
}
.brand-points .dot {
  display: inline-block;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #7fbfaa;
  margin-right: 10px;
  vertical-align: middle;
}

/* 右表单 */
.form-panel {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
}
.login-card {
  width: 400px;
  border-radius: 16px;
  border: 1px solid var(--sp-line, #e2e8e4);
}
.login-header {
  margin-bottom: 20px;
}
.login-header h2 {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--sp-ink, #1c2420);
}
.login-header p {
  margin: 0;
  color: var(--sp-ink-2, #5c6b64);
  font-size: 13px;
}
.login-btn {
  width: 100%;
  margin-top: 8px;
}
.demo-hint {
  margin: 16px 0 0;
  text-align: center;
  font-size: 12px;
  color: var(--sp-ink-3, #8a968f);
}

@media (max-width: 860px) {
  .brand-panel { display: none; }
  .form-panel { padding: 24px; }
  .login-card { width: 100%; max-width: 400px; }
}
</style>
