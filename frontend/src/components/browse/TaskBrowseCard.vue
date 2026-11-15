<script lang="ts">
import type { TaskItem } from '../../types/models'
import { statusText } from '../task/StatusTag.vue'
import { formatDeadline, quotaText } from '../task/TaskCard.vue'
</script>

<script setup lang="ts">
/**
 * 任务短卡片（契约 `C-BROWSE-CARD@2`，承接 `C-BROWSE-SPLIT@1` 的交互面）。
 *
 * 整卡即主操作：点击/回车/空格选中并在右侧打开摘要，卡内不放按钮或链接；
 * 报名、验收等写入仍只在独立详情页，避免第二套写入路径。
 */
import { computed } from 'vue'

import UserAvatar from '../common/UserAvatar.vue'

const props = withDefaults(
  defineProps<{ task: TaskItem; activityTitle?: string; selected?: boolean }>(),
  { activityTitle: '', selected: false }
)

const emit = defineEmits<{ (e: 'select', id: number): void }>()

const toneClass = computed<string>(() => `browse-card--tone-${props.task.id % 4}`)

/** 主行最多展示 3 名成员，其余折叠为 `+n` */
const leadMembers = computed(() => props.task.members.slice(0, 3))

const extraMembers = computed<number>(() => Math.max(props.task.members.length - 3, 0))

const statusLine = computed<string>(
  () => `${statusText(props.task.status)} · 截止 ${formatDeadline(props.task.deadline)}`
)

const quotaLine = computed<string>(() => {
  const parts: string[] = [quotaText(props.task)]
  if (props.task.credit_reward !== null) parts.push(`+${props.task.credit_reward} 积分`)
  return parts.join(' · ')
})

const activityLine = computed<string>(() => {
  if (props.activityTitle) return `所属活动 · ${props.activityTitle}`
  return props.task.activity_id === null ? '独立任务' : `所属活动 #${props.task.activity_id}`
})

function handleSelect(): void {
  emit('select', props.task.id)
}
</script>

<template>
  <article
    class="browse-card browse-card--task"
    :class="[toneClass, { 'browse-card--selected': selected }]"
    role="button"
    tabindex="0"
    :aria-pressed="selected"
    :aria-label="`查看任务：${task.title}`"
    @click="handleSelect"
    @keydown.enter.prevent="handleSelect"
    @keydown.space.prevent="handleSelect"
  >
    <span class="browse-card__main">
      <span class="browse-card__avatars">
        <UserAvatar
          v-for="member in leadMembers"
          :key="member.user_id"
          :user-id="member.user_id"
          :name="member.user_name"
          size="md"
        />
        <UserAvatar v-if="!leadMembers.length" :user-id="null" name="" size="md" />
        <span v-if="extraMembers > 0" class="browse-card__avatar-extra">+{{ extraMembers }}</span>
      </span>
      <span class="browse-card__title">{{ task.title }}</span>
    </span>

    <span class="browse-card__meta browse-card__meta--muted">{{ activityLine }}</span>
    <span class="browse-card__meta">{{ statusLine }}</span>
    <span class="browse-card__meta browse-card__meta--muted">{{ quotaLine }}</span>
  </article>
</template>

<style scoped>
.browse-card {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  padding: var(--app-space-4);
  text-align: left;
  background: var(--browse-tone-bg, var(--app-surface));
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  cursor: pointer;
}

.browse-card--tone-0 {
  --browse-tone-bg: var(--el-color-primary-light-9);
}

.browse-card--tone-1 {
  --browse-tone-bg: var(--el-color-success-light-9);
}

.browse-card--tone-2 {
  --browse-tone-bg: var(--el-color-warning-light-9);
}

.browse-card--tone-3 {
  --browse-tone-bg: var(--el-color-danger-light-9);
}

.browse-card:hover {
  border-color: var(--app-border-strong);
}

.browse-card:focus-visible {
  border-color: var(--app-primary);
  outline: none;
}

.browse-card--selected {
  border-color: var(--el-color-primary);
  box-shadow: inset 0 0 0 1px var(--el-color-primary);
}

.browse-card__main {
  display: flex;
  align-items: flex-start;
  gap: var(--app-space-2);
  min-width: 0;
}

.browse-card__avatars {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: var(--app-space-1);
}

.browse-card__avatar-extra {
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux, 13px);
  line-height: 1;
}

.browse-card__title {
  display: -webkit-box;
  overflow: hidden;
  flex: 1 1 auto;
  min-width: 0;
  /* 固定两行标题高度：同列表内标题长短不影响卡片高度（R-06） */
  min-height: 2.75em;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  color: var(--app-text);
  font-size: var(--app-font-card-title, 16px);
  font-weight: 400;
  line-height: 22px;
  word-break: break-word;
}

/* 元信息固定单行，超出以省略号收尾（R-06） */
.browse-card__meta {
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux, 13px);
  line-height: 20px;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.browse-card__meta--muted {
  color: var(--app-text-muted);
}
</style>