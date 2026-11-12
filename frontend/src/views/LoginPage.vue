<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import { useUserStore } from '../stores/user'

/**
 * 登录页（契约 C-AUTH@1 / C-FEAPI@1）。
 *
 * 用户名登录：用户名以 teacher 开头为发布者、admin 开头为管理员、其余为学生（后端建号）。
 * 成功后跳转 `redirect` 参数指定页面，缺省 `/tasks`。
 */
const DEMO_ACCOUNTS = ['teacher01', 'student01', 'student02', 'student03']

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const username = ref('')
const loading = ref(false)
const errorMessage = ref('')

function redirectTarget(): string {
  const raw = route.query.redirect
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('/login')) return value
  return '/tasks'
}

async function goAfterLogin(): Promise<void> {
  await router.replace(redirectTarget())
}

async function submit(): Promise<void> {
  const name = username.value.trim()
  if (!name) {
    errorMessage.value = '请输入用户名'
    return
  }

  loading.value = true
  errorMessage.value = ''
  try {
    await userStore.login(name)
    await goAfterLogin()
  } catch (error) {
    errorMessage.value =
      error instanceof ApiError ? error.message : '登录失败，请检查后端服务后重试'
  } finally {
    loading.value = false
  }
}

function loginAs(name: string): void {
  username.value = name
  void submit()
}

onMounted(() => {
  // 已登录直接进入目标页（守卫也会兜底）
  if (userStore.isLoggedIn) void goAfterLogin()
})
</script>

<template>
  <section class="login-page">
    <el-card class="login-card" shadow="never">
      <div class="login-header">
        <h2 class="login-title">校园任务协同</h2>
        <p class="login-subtitle">用演示账号登录，体验 AI 发布与任务流转</p>
      </div>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        class="login-error"
      />

      <el-form label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input
            v-model="username"
            placeholder="如 teacher01 / student01"
            clearable
            maxlength="32"
            @keyup.enter="submit"
          />
        </el-form-item>
      </el-form>

      <el-button
        type="primary"
        class="login-submit"
        :loading="loading"
        :disabled="loading"
        @click="submit"
      >
        登录
      </el-button>

      <div class="demo-accounts">
        <span class="demo-label">演示账号</span>
        <el-button
          v-for="account in DEMO_ACCOUNTS"
          :key="account"
          size="small"
          text
          type="primary"
          :disabled="loading"
          @click="loginAs(account)"
        >
          {{ account }}
        </el-button>
      </div>
    </el-card>
  </section>
</template>

<style scoped>
.login-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #eef2ff 0%, #f5f7fa 55%, #ecfdf5 100%);
  padding: 24px;
  box-sizing: border-box;
}

.login-card {
  width: 100%;
  max-width: 420px;
  border-radius: 12px;
  padding: 8px 12px;
}

.login-header {
  margin-bottom: 16px;
  text-align: center;
}

.login-title {
  margin: 0 0 6px;
  font-size: 22px;
  color: #303133;
}

.login-subtitle {
  margin: 0;
  font-size: 14px;
  color: #909399;
}

.login-error {
  margin-bottom: 16px;
}

.login-submit {
  width: 100%;
  margin-top: 4px;
}

.demo-accounts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
  margin-top: 16px;
}

.demo-label {
  font-size: 13px;
  color: #909399;
  margin-right: 4px;
}
</style>