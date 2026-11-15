<script lang="ts">
import type { ActivityTaskNode } from '../../types/models'

/**
 * 活动任务分组（契约 `C-TASK-GROUPS@1`）。
 *
 * 固定顺序：进行中 → 待验收 → 待开始 → 已完成 → 已取消；空分组不渲染。
 * 本组件只读，不请求、不写入、不改变任务状态。
 */
export type TaskGroupKey = 'active' | 'review' | 'pending' | 'done' | 'cancelled'

export interface TaskGroupMeta {
  key: TaskGroupKey
  label: string
}

export const TASK_GROUPS: TaskGroupMeta[] = [
  { key: 'active', label: '进行中' },
  { key: 'review', label: '待验收' },
  { key: 'pending', label: '待开始' },
  { key: 'done', label: '已完成' },
  { key: 'cancelled', label: '已取消' }
]

/** 后端任务状态字符串（与 `ActivityTaskNode.status` 同域） */
export type TaskStatus = ActivityTaskNode['status']

const STATUS_GROUP_MAP: Record<string, TaskGroupKey> = {
  in_progress: 'active',
  claimed: 'active',
  overdue: 'active',
  submitted: 'review',
  todo: 'pending',
  verified: 'done',
  cancelled: 'cancelled'
}

/** 未知状态归入「待开始」，避免任务在分组视图中丢失 */
export function taskGroupOf(status: TaskStatus): TaskGroupKey {
  return STATUS_GROUP_MAP[status] ?? 'pending'
}
</script>

<script setup lang="ts">
import { computed } from 'vue'

import EmptyState from '../common/EmptyState.vue'
import UserAvatar from '../common/UserAvatar.vue'
import NavIcon from '../nav/NavIcon.vue'
import StatusTag from './StatusTag.vue'

interface TaskGroupView extends TaskGroupMeta {
  tasks: ActivityTaskNode[]
}

const props = withDefaults(
  defineProps<{
    tasks: ActivityTaskNode[]
    expanded: number[]
    emptyTitle?: string
    emptyDescription?: string
  }>(),
  { emptyTitle: '暂无任务', emptyDescription: '该活动下还没有任务，可以先发布相关事务。' }
)

const emit = defineEmits<{ (e: 'toggle', id: number): void }>()

const groups = computed<TaskGroupView[]>(() =>
  TASK_GROUPS.map((meta) => ({
    ...meta,
    tasks: props.tasks.filter((task) => taskGroupOf(task.status) === meta.key)
  })).filter((group) => group.tasks.length > 0)
)

function isExpanded(id: number): boolean {
  return props.expanded.includes(id)
}

function todayText(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

function deadlineText(value: string | null): string {
  if (!value) return '未设置'
  return value.slice(0, 10)
}

/** 截止日早于今天且未完成 */
function isOverdue(status: string, deadline: string | null): boolean {
  if (!deadline) return false
  if (taskGroupOf(status) === 'done') return false
  return deadline.slice(0, 10) < todayText()
}

function leadUserId(task: ActivityTaskNode): number | null {
  return task.assignees[0]?.user_id ?? null
}

function leadName(task: ActivityTaskNode): string {
  return task.assignees[0]?.name ?? task.assignee_names[0] ?? '待分配'
}

function childLeadName(names: string[]): string {
  return names[0] ?? '待分配'
}
</script>

<template>
  <EmptyState
    v-if="groups.length === 0"
    :title="emptyTitle"
    :description="emptyDescription"
  />

  <div v-else class="task-group-list">
    <section
      v-for="group in groups"
      :key="group.key"
      class="task-group"
      :aria-labelledby="`task-group-${group.key}-heading`"
    >
      <h3 :id="`task-group-${group.key}-heading`" class="task-group__heading">
        {{ group.label }}
        <span class="task-group__count">{{ group.tasks.length }}</span>
      </h3>

      <ul class="task-group__list">
        <li v-for="task in group.tasks" :key="task.id" class="task-group__item">
          <div class="task-group__row">
            <StatusTag :status="task.status" size="small" />
            <router-link
              class="task-group__title"
              :to="{ name: 'detail', params: { id: task.id } }"
            >
              {{ task.title }}
            </router-link>

            <span class="task-group__meta">
              <span v-if="leadUserId(task) !== null" class="task-group__owner">
                <UserAvatar :user-id="leadUserId(task)" :name="leadName(task)" size="xs" />
              </span>
              <span
                class="task-group__deadline"
                :class="{ 'is-overdue': isOverdue(task.status, task.deadline) }"
              >
                <NavIcon name="calendar" :size="16" />
                截止 {{ deadlineText(task.deadline) }}
              </span>
              <span v-if="task.total_children > 0" class="task-group__subtask-count">
                {{ task.completed_children }}/{{ task.total_children }} 子任务
              </span>
            </span>

            <button
              v-if="task.children.length > 0"
              type="button"
              class="task-group__toggle"
              :aria-expanded="isExpanded(task.id) ? 'true' : 'false'"
              :aria-controls="`task-group-subtasks-${task.id}`"
              :aria-label="`${isExpanded(task.id) ? '收起' : '展开'}「${task.title}」的子任务`"
              @click="emit('toggle', task.id)"
            >
              <NavIcon
                :name="isExpanded(task.id) ? 'chevron-down' : 'chevron-right'"
                :size="16"
              />
            </button>
          </div>

          <ul
            v-if="task.children.length > 0 && isExpanded(task.id)"
            :id="`task-group-subtasks-${task.id}`"
            class="task-group__subtasks"
          >
            <li v-for="child in task.children" :key="child.id" class="task-group__subtask">
              <span class="task-group__subtask-badge">子任务</span>
              <router-link
                class="task-group__title"
                :to="{ name: 'detail', params: { id: child.id } }"
              >
                {{ child.title }}
              </router-link>
              <StatusTag :status="child.status" size="small" />
              <span
                class="task-group__deadline"
                :class="{ 'is-overdue': isOverdue(child.status, child.deadline) }"
              >
                截止 {{ deadlineText(child.deadline) }}
              </span>
              <span class="task-group__subtask-owner">
                <UserAvatar :user-id="null" :name="childLeadName(child.assignee_names)" size="xs" />
              </span>
            </li>
          </ul>
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.task-group-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-5);
}

.task-group {
  min-width: 0;
}

.task-group__heading {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  margin: 0 0 var(--app-space-2);
  font-size: var(--app-font-body);
  font-weight: 600;
  line-height: 1.5;
  color: var(--app-text);
}

.task-group__count {
  padding: 0 var(--app-space-2);
  font-size: var(--app-font-label);
  font-weight: 500;
  line-height: 1.6;
  text-align: center;
  color: var(--app-text-muted);
  background: var(--app-surface-sunken);
  border-radius: var(--app-radius-pill);
}

.task-group__list,
.task-group__subtasks {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.task-group__item {
  min-width: 0;
}

.task-group__row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2) var(--app-space-3);
  padding: var(--app-space-3);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.task-group__title {
  flex: 1 1 200px;
  min-width: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  line-height: 1.5;
  color: var(--app-text);
  text-decoration: none;
  word-break: break-word;
}

.task-group__title:hover {
  color: var(--app-primary);
  text-decoration: underline;
}

.task-group__meta {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2) var(--app-space-3);
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.task-group__owner,
.task-group__subtask-owner {
  display: inline-flex;
  align-items: center;
}

.task-group__deadline {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
}

.task-group__deadline.is-overdue {
  font-weight: 500;
  color: var(--el-color-danger);
}

.task-group__subtask-count {
  white-space: nowrap;
}

.task-group__toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  color: var(--app-text-secondary);
  cursor: pointer;
  background: transparent;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-xs);
  width: var(--app-icon-lg);
  height: var(--app-icon-lg);
}

.task-group__toggle:hover {
  color: var(--app-primary);
  border-color: var(--app-primary);
}

.task-group__subtasks {
  margin-top: var(--app-space-2);
  padding-left: var(--app-space-4);
}

.task-group__subtask {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2) var(--app-space-3);
  padding: var(--app-space-2) var(--app-space-3);
  font-size: var(--app-font-aux);
  background: var(--app-surface-sunken);
  border-radius: var(--app-radius-xs);
}

.task-group__subtask .task-group__title {
  font-size: var(--app-font-aux-lg);
  font-weight: 500;
}

.task-group__subtask-badge {
  flex: none;
  padding: 0 var(--app-space-1);
  font-size: var(--app-font-label);
  line-height: 1.6;
  color: var(--app-text-secondary);
  background: var(--app-primary-soft);
  border-radius: var(--app-radius-xs);
}

@media (max-width: 768px) {
  .task-group__row {
    padding: var(--app-space-3) var(--app-space-2);
  }

  .task-group__toggle {
    min-width: var(--app-touch);
    min-height: var(--app-touch);
  }

  .task-group__subtasks {
    padding-left: 0;
  }
}
</style>