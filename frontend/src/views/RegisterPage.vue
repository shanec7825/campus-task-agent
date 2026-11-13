<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { register } from '../api/auth'
import { ApiError } from '../api/client'
import ThemeToggle from '../components/common/ThemeToggle.vue'
import { useUserStore } from '../stores/user'

/**
 * 邀请注册页（契约 C-FE-AUTH@1 / C-ORG@1）。
 *
 * 邀请凭据从 query 的 `invite` 读取；注册成功后服务端直接建立会话，进入 AI 助手。
 */
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const inviteToken = computed<string>(() => {
  const raw = route.query.invite
  const value = Array.isArray(raw) ? raw[0] : raw
  return typeof value === 'string' ? value : ''
})

const form = reactive({
  username: '',
  display_name: '',
  password: '',
  confirm_password: ''
})
const loading = ref(false)
const errorMessage = ref('')

function validate(): string {
  if (!inviteToken.value) return '缺少邀请凭据，请使用组织管理员发放的邀请链接注册'
  if (!/^[A-Za-z0-9_]{3,32}$/.test(form.username.trim())) {
    return '账号需为 3-32 位字母、数字或下划线'
  }
  const displayName = form.display_name.trim()
  if (!displayName) return '请输入姓名'
  if (displayName.length > 40) return '姓名不能超过 40 个字符'
  if (form.password.length < 8) return '密码至少 8 位'
  if (form.password !== form.confirm_password) return '两次输入的密码不一致'
  return ''
}

async function submit(): Promise<void> {
  const message = validate()
  if (message) {
    errorMessage.value = message
    return
  }

  loading.value = true
  errorMessage.value = ''
  try {
    const result = await register({
      username: form.username.trim(),
      display_name: form.display_name.trim(),
      password: form.password,
      confirm_password: form.confirm_password,
      invite_token: inviteToken.value
    })
    userStore.setSession(result.user, result.orgs)
    await router.replace({ name: 'ai' })
  } catch (error) {
    errorMessage.value = error instanceof ApiError ? error.message : '注册失败，请稍后重试'
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
        <h1 class="auth-title">邀请注册</h1>
        <p class="auth-subtitle">填写账号信息，加入所在组织</p>
      </div>

      <el-alert
        v-if="!inviteToken"
        title="邀请链接无效或已过期，请联系组织管理员重新获取"
        type="warning"
        show-icon
        :closable="false"
        class="auth-alert"
      />

      <el-alert
        v-if="errorMessage"
        :title="errorMessage"
        type="error"
        show-icon
        :closable="false"
        role="alert"
        class="auth-alert"
      />

      <el-form class="auth-form" label-position="top" @submit.prevent>
        <el-form-item label="账号">
          <el-input
            v-model="form.username"
            placeholder="3-32 位字母、数字或下划线"
            size="large"
            clearable
            maxlength="32"
            autocomplete="username"
            :disabled="loading"
          />
        </el-form-item>
        <el-form-item label="姓名">
          <el-input
            v-model="form.display_name"
            placeholder="用于任务与消息展示"
            size="large"
            clearable
            maxlength="40"
            autocomplete="name"
            :disabled="loading"
          />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="至少 8 位"
            size="large"
            show-password
            maxlength="200"
            autocomplete="new-password"
            :disabled="loading"
          />
        </el-form-item>
        <el-form-item label="确认密码">
          <el-input
            v-model="form.confirm_password"
            type="password"
            placeholder="再次输入密码"
            size="large"
            show-password
            maxlength="200"
            autocomplete="new-password"
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
        :disabled="loading || !inviteToken"
        @click="submit"
      >
        注册并登录
      </el-button>

      <p class="auth-footnote">
        已有账号？<router-link class="auth-link" :to="{ name: 'login' }">返回登录</router-link>
      </p>
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

.auth-alert {
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

.auth-link {
  color: var(--app-primary);
  text-decoration: none;
}

.auth-link:hover,
.auth-link:focus-visible {
  text-decoration: underline;
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