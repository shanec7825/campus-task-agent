<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ThemeToggle from '../components/common/ThemeToggle.vue'
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
    <div class="login-topbar">
      <ThemeToggle />
    </div>

    <el-card class="login-card app-section-card" shadow="never">
      <div class="login-header">
        <div class="login-logo" aria-hidden="true">校</div>
        <h1 class="login-title">校园任务协同</h1>
        <p class="login-subtitle">用演示账号登录，体验 AI 发布与任务流转</p>
      </div>

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        role="alert"
        class="login-error"
      />

      <el-form class="login-form" label-position="top" @submit.prevent>
        <el-form-item label="用户名">
          <el-input
            v-model="username"
            placeholder="如 teacher01 / student01"
            size="large"
            clearable
            maxlength="32"
            autocomplete="username"
            :disabled="loading"
            @keyup.enter="submit"
          />
        </el-form-item>
      </el-form>

      <el-button
        type="primary"
        size="large"
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
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  min-height: 100dvh;
  box-sizing: border-box;
  padding: 64px 24px 32px;
  background: var(--app-bg);
  background-image:
    radial-gradient(
      circle at 12% 6%,
      color-mix(in srgb, var(--app-primary) 16%, transparent),
      transparent 46%
    ),
    radial-gradient(
      circle at 88% 94%,
      color-mix(in srgb, var(--app-primary) 10%, transparent),
      transparent 50%
    );
}

.login-topbar {
  position: absolute;
  top: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.login-card {
  width: 100%;
  max-width: 420px;
  box-sizing: border-box;
}

.login-card :deep(.el-card__body) {
  padding: 28px 24px 24px;
}

.login-header {
  margin-bottom: 20px;
  text-align: center;
}

.login-logo {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  margin-bottom: 12px;
  border-radius: var(--app-radius-lg);
  background: var(--app-primary-soft);
  color: var(--app-primary);
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}

.login-title {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--app-text);
}

.login-subtitle {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--app-text-secondary);
}

.login-error {
  margin-bottom: 16px;
}

.login-form :deep(.el-form-item__label) {
  color: var(--app-text-secondary);
}

.login-submit {
  width: 100%;
  min-height: var(--app-touch);
  margin-top: 4px;
}

.demo-accounts {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 16px;
}

.demo-accounts :deep(.el-button + .el-button) {
  margin-left: 0;
}

.demo-label {
  margin-right: 4px;
  font-size: 13px;
  color: var(--app-text-muted);
}

@media (max-width: 768px) {
  .login-page {
    align-items: flex-start;
    padding: 64px 16px calc(24px + var(--app-safe-bottom));
  }

  .login-card :deep(.el-card__body) {
    padding: 24px 18px 20px;
  }

  .demo-accounts :deep(.el-button) {
    flex: 1 1 auto;
    justify-content: center;
  }
}

@media (max-width: 430px) {
  .login-topbar {
    top: 12px;
    right: 12px;
  }

  .login-card {
    max-width: none;
  }

  .login-title {
    font-size: 22px;
  }
}
</style>