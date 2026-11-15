<script lang="ts">
import type { Activity } from '../../types/models'
</script>

<script setup lang="ts">
/**
 * 活动短卡片（契约 `C-BROWSE-CARD@2`，承接 `C-BROWSE-SPLIT@1` 的交互面）。
 *
 * 整卡即主操作：点击/回车/空格选中并在右侧打开摘要，卡内不放按钮或链接，
 * 避免嵌套交互冲突；打开完整详情由右侧面板与独立详情页承担。
 */
import { computed } from 'vue'

import UserAvatar from '../common/UserAvatar.vue'

const props = withDefaults(defineProps<{ activity: Activity; selected?: boolean }>(), {
  selected: false
})

const emit = defineEmits<{ (e: 'select', id: number): void }>()

const toneClass = computed<string>(() => `browse-card--tone-${props.activity.id % 4}`)

function formatStartTime(value: string | null): string {
  if (!value) return '时间待定'
  return value.slice(0, 16).replace('T', ' ')
}

const scheduleText = computed<string>(
  () => `${formatStartTime(props.activity.start_time)} · ${props.activity.location || '地点待定'}`
)

const progressText = computed<string>(
  () =>
    `负责人 ${props.activity.owner_name || '待分配'} · ${props.activity.progress.completed_tasks}/${props.activity.progress.total_tasks} 个任务完成`
)

function handleSelect(): void {
  emit('select', props.activity.id)
}
</script>

<template>
  <article
    class="browse-card browse-card--activity"
    :class="[toneClass, { 'browse-card--selected': selected }]"
    role="button"
    tabindex="0"
    :aria-pressed="selected"
    :aria-label="`查看活动：${activity.title}`"
    @click="handleSelect"
    @keydown.enter.prevent="handleSelect"
    @keydown.space.prevent="handleSelect"
  >
    <span class="browse-card__main">
      <UserAvatar :user-id="activity.owner_id" :name="activity.owner_name" size="md" />
      <span class="browse-card__title">{{ activity.title }}</span>
    </span>

    <span class="browse-card__meta">{{ scheduleText }}</span>
    <span class="browse-card__meta browse-card__meta--muted">{{ progressText }}</span>
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