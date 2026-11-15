<script lang="ts">
/**
 * 统一用户头像（契约 `C-USER-AVATAR@1` / `C-AVATAR-UI@1`）。
 *
 * 本地生成、按 `user_id` 稳定取色，不请求外部头像服务；`userId === null`
 * 表示尚未分配负责人/成员，用中性形象区分。`avatar` 非空时渲染自定义图片。
 */
export type UserAvatarSize = 'xs' | 'md'
</script>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    userId: number | null
    name: string
    size?: UserAvatarSize
    avatar?: string | null
  }>(),
  { size: 'xs', avatar: null }
)

const isVacant = computed<boolean>(() => props.userId === null)

/** 四组柔和色，按 `userId % 4` 稳定落位，避免同一用户换色 */
const toneClass = computed<string>(() => {
  if (isVacant.value) return 'avatar--vacant'
  return `avatar--tone-${(Math.abs(props.userId ?? 0) % 4) + 1}`
})

const displayName = computed<string>(() => props.name?.trim() || '待分配')

const initial = computed<string>(() => {
  const text = props.name?.trim() ?? ''
  if (!text) return '待'
  const first = Array.from(text)[0] ?? ''
  return /[\u4e00-\u9fa5]/.test(first) ? first : first.toUpperCase()
})
</script>

<template>
  <span
    class="avatar"
    :class="[toneClass, `avatar--${size}`]"
    role="img"
    :title="displayName"
    :aria-label="displayName"
  >
    <img v-if="avatar" class="avatar__image" :src="avatar" alt="" />
    <span v-else class="avatar__initial" aria-hidden="true">{{ initial }}</span>
  </span>
</template>

<style scoped>
.avatar {
  --avatar-bg: var(--app-surface-sunken);
  --avatar-fg: var(--app-text-secondary);

  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  border-radius: 50%;
  background: var(--avatar-bg);
  color: var(--avatar-fg);
  font-weight: 600;
  line-height: 1;
  user-select: none;
}

.avatar__image {
  width: 100%;
  height: 100%;
  border-radius: 50%;
  object-fit: cover;
}

.avatar--xs {
  width: 18px;
  height: 18px;
  font-size: var(--app-font-aux);
}

.avatar--md {
  width: 32px;
  height: 32px;
  font-size: 14px;
}

/* 深色主题由 Element Plus 同名变量自动降明度，保持同色相 */
.avatar--tone-1 {
  --avatar-bg: var(--el-color-primary-light-9);
  --avatar-fg: var(--el-color-primary-dark-2);
}

.avatar--tone-2 {
  --avatar-bg: var(--el-color-success-light-9);
  --avatar-fg: var(--el-color-success-dark-2);
}

.avatar--tone-3 {
  --avatar-bg: var(--el-color-warning-light-9);
  --avatar-fg: var(--el-color-warning-dark-2);
}

.avatar--tone-4 {
  --avatar-bg: var(--el-color-danger-light-9);
  --avatar-fg: var(--el-color-danger-dark-2);
}

.avatar--vacant {
  --avatar-bg: var(--app-surface-sunken);
  --avatar-fg: var(--app-text-muted);
}
</style>