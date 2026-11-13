<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import ThemeToggle from '../components/common/ThemeToggle.vue'
import { resolveSafeRedirect } from '../router'
import { useUserStore } from '../stores/user'

/**
 * 登录页（契约 C-FE-AUTH@1）。
 *
 * 账号 + 密码登录，成功后跳转 `redirect` 指向的站内页面，缺省工作台。
 * 登录失败统一提示，不区分「账号不存在」与「密码错误」。
 */
const LOGIN_FAILED_MESSAGE = '账号或密码错误，请重新输入'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

const notice = computed<string>(() => {
  const raw = route.query.notice
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' ? value : ''
})

async function submit(): Promise<void> {
  const name = username.value.trim()
  if (!name || !password.value) {
    errorMessage.value = '请输入账号和密码'
    return
  }

  loading.value = true
  errorMessage.value = ''
  try {
    await userStore.login({ username: name, password: password.value })
    await router.replace(resolveSafeRedirect(route.query.redirect))
  } catch (error) {
    if (error instanceof ApiError && error.code === 4010) {
      errorMessage.value = LOGIN_FAILED_MESSAGE
    } else if (error instanceof ApiError) {
      errorMessage.value = error.message
    } else {
      errorMessage.value = '登录失败，请稍后重试'
    }
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section class="auth-page">
    <div class="auth-topbar">
      <ThemeToggle />
    </div>

    <el-card class="auth-card app-section-card" shadow="never">
      <div class="auth-header">
        <div class="auth-logo" aria-hidden="true">校</div>
        <h1 class="auth-title">校园任务协同</h1>
        <p class="auth-subtitle">使用账号与密码登录</p>
      </div>

      <el-alert
        v-if="notice"
        :title="notice"
        type="success"
        show-icon
        :closable="false"
        class="auth-notice"
      />

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        role="alert"
        class="auth-error"
      />

      <el-form class="auth-form" label-position="top" @submit.prevent>
        <el-form-item label="账号">
          <el-input
            v-model="username"
            placeholder="请输入账号"
            size="large"
            clearable
            maxlength="64"
            autocomplete="username"
            :disabled="loading"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            placeholder="请输入密码"
            size="large"
            show-password
            maxlength="200"
            autocomplete="current-password"
            :disabled="loading"
            @keyup.enter="submit"
          />
        </el-form-item>
      </el-form>

      <el-button
        type="primary"
        size="large"
        class="auth-submit"
        :loading="loading"
        :disabled="loading"
        @click="submit"
      >
        登录
      </el-button>

      <p class="auth-footnote">没有账号？请联系组织管理员获取邀请链接后注册。</p>
    </el-card>
  </section>
</template>

<style scoped>
.auth-page {
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

.auth-topbar {
  position: absolute;
  top: 16px;
  right: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.auth-card {
  width: 100%;
  max-width: 420px;
  box-sizing: border-box;
}

.auth-card :deep(.el-card__body) {
  padding: 28px 24px 24px;
}

.auth-header {
  margin-bottom: 20px;
  text-align: center;
}

.auth-logo {
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

.auth-title {
  margin: 0 0 6px;
  font-size: 24px;
  font-weight: 600;
  line-height: 1.3;
  color: var(--app-text);
}

.auth-subtitle {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
}

.auth-notice,
.auth-error {
  margin-bottom: 16px;
}

.auth-form :deep(.el-form-item__label) {
  color: var(--app-text-secondary);
}

.auth-submit {
  width: 100%;
  min-height: var(--app-touch);
  margin-top: 4px;
}

.auth-footnote {
  margin: 16px 0 0;
  font-size: var(--app-font-aux);
  line-height: 1.6;
  color: var(--app-text-muted);
  text-align: center;
}

@media (max-width: 768px) {
  .auth-page {
    align-items: flex-start;
    padding: 64px 16px calc(24px + var(--app-safe-bottom));
  }

  .auth-card :deep(.el-card__body) {
    padding: 24px 18px 20px;
  }
}

@media (max-width: 430px) {
  .auth-topbar {
    top: 12px;
    right: 12px;
  }

  .auth-card {
    max-width: none;
  }

  .auth-title {
    font-size: 22px;
  }
}
</style>