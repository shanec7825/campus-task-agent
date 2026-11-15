<script setup lang="ts">
/**
 * 活动字段区块（`C-NAV-SHARED-ACTIVITY@2` / `C-ACTIVITY-FACTS@1`）。
 *
 * 发布活动预览与活动详情共用同一组字段与顺序：名称 → 介绍 → 负责人 / 举办时间 /
 * 截止 / 地点 / 组织 / 状态。只做展示，不持有数据、不发请求；编辑仍由发布页表单负责。
 * `variant="facts"` 供详情侧栏复用字段，只输出字段 `dl`，不套卡片、不渲染标题与描述。
 */
import { computed } from 'vue'

import type { Activity } from '../../types/models'

const props = withDefaults(
  defineProps<{
    activity: Activity
    titleTag?: 'h1' | 'h2' | 'h3'
    showProgress?: boolean
    variant?: 'card' | 'facts'
  }>(),
  { titleTag: 'h1', showProgress: false, variant: 'card' }
)

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.slice(0, 16).replace('T', ' ')
}

function activityStatusText(status: string): string {
  if (status === 'published') return '进行中'
  if (status === 'closed') return '已结束'
  return '未知'
}

const facts = computed<{ label: string; value: string }[]>(() => [
  { label: '负责人', value: props.activity.owner_name || '—' },
  { label: '举办开始', value: dateText(props.activity.start_time) },
  { label: '截止', value: dateText(props.activity.deadline) },
  { label: '地点', value: props.activity.location || '未设置' },
  { label: '组织', value: props.activity.org || '未加入组织' },
  { label: '状态', value: activityStatusText(props.activity.status) }
])
</script>

<template>
  <dl
    v-if="variant === 'facts'"
    class="activity-info__facts"
    data-variant="facts"
    aria-label="活动信息"
  >
    <div v-for="fact in facts" :key="fact.label" class="activity-info__fact">
      <dt>{{ fact.label }}</dt>
      <dd>{{ fact.value }}</dd>
    </div>
  </dl>

  <section v-else class="activity-info app-section-card" aria-label="活动信息">
    <component :is="titleTag" class="activity-info__title">{{ activity.title }}</component>
    <p v-if="activity.description" class="activity-info__desc">{{ activity.description }}</p>

    <dl class="activity-info__facts">
      <div v-for="fact in facts" :key="fact.label" class="activity-info__fact">
        <dt>{{ fact.label }}</dt>
        <dd>{{ fact.value }}</dd>
      </div>
    </dl>

    <p v-if="showProgress" class="activity-info__progress">
      整体进度 {{ activity.progress.percent }}% ·
      {{ activity.progress.completed_tasks }}/{{ activity.progress.total_tasks }} 个任务已完成
    </p>
  </section>
</template>

<style scoped>
.activity-info {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.activity-info__title {
  margin: 0;
  font-size: var(--app-font-page-title);
  font-weight: 700;
  line-height: 1.3;
  color: var(--app-text);
  word-break: break-word;
}

.activity-info__desc {
  margin: 0;
  font-size: var(--app-font-body);
  line-height: 1.7;
  color: var(--app-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.activity-info__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--app-space-2);
  margin: 0;
}

/* 侧栏事实模式：无卡片外框，字段按单列行式排列 */
.activity-info__facts[data-variant='facts'] {
  grid-template-columns: 1fr;
}

.activity-info__facts[data-variant='facts'] .activity-info__fact {
  padding: 0;
  border: 0;
  background: transparent;
}

.activity-info__fact {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: var(--app-space-2) var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.activity-info__fact dt {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.activity-info__fact dd {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.activity-info__progress {
  margin: 0;
  font-size: var(--app-font-body);
  color: var(--app-text);
  word-break: break-word;
}

@media (max-width: 768px) {
  .activity-info__facts {
    grid-template-columns: 1fr;
  }
}
</style>