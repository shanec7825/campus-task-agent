<script setup lang="ts">
/**
 * 活动 / 后台共用任务表格（契约 `C-ACTIVITY-TABLE@1`）。
 *
 * - 只读组件：不发起请求、不新增写入路径；操作列由消费方通过 `actions` 插槽注入；
 * - 展开状态由父视图持有，`aria-controls` 指向每个任务自己的 `<tbody>`，
 *   即使收起该元素仍然存在；
 * - 容器横向滚动，窄栏与移动端不产生页面级横向溢出。
 */
import { computed, useSlots } from 'vue'

import type { ActivitySubtaskNode, ActivityTaskNode } from '../../types/models'
import EmptyState from '../common/EmptyState.vue'
import UserAvatar from '../common/UserAvatar.vue'
import StatusTag, { statusText } from './StatusTag.vue'

/** 成员列内联展示上限，超出只显示计数 */
const VISIBLE_ASSIGNEES = 2

const props = withDefaults(
  defineProps<{
    tasks: ActivityTaskNode[]
    /** 当前处于展开状态的任务 id */
    expanded: number[]
    showActivity?: boolean
    activityTitles?: Record<number, string>
  }>(),
  { showActivity: false, activityTitles: () => ({}) }
)

const emit = defineEmits<{ (e: 'toggle', id: number): void }>()

const slots = useSlots()

/** 任务、[所属活动]、状态、执行成员、开始、截止、完成情况、[操作] */
const columnCount = computed<number>(
  () => 6 + (props.showActivity ? 1 : 0) + (slots.actions ? 1 : 0)
)

function isExpanded(id: number): boolean {
  return props.expanded.includes(id)
}

function dateText(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 16) : value
}

function activityLabel(task: ActivityTaskNode): string {
  if (task.activity_id === null || task.activity_id === undefined) return '独立任务'
  return props.activityTitles[task.activity_id] ?? `#${task.activity_id}`
}

function visibleAssignees(task: ActivityTaskNode | ActivitySubtaskNode): ActivitySubtaskNode['assignees'] {
  return task.assignees.slice(0, VISIBLE_ASSIGNEES)
}

function hiddenAssigneeCount(task: ActivityTaskNode | ActivitySubtaskNode): number {
  return Math.max(0, task.assignees.length - VISIBLE_ASSIGNEES)
}

function completionText(task: ActivityTaskNode): string {
  return task.total_children > 0
    ? `${task.completed_children}/${task.total_children} 子任务`
    : statusText(task.status)
}
</script>

<template>
  <EmptyState
    v-if="tasks.length === 0"
    title="暂无任务"
    description="该活动下还没有任务，可以先发布相关事务。"
  />

  <div v-else class="task-table__scroll">
    <table class="task-table">
      <thead>
        <tr>
          <th scope="col">任务</th>
          <th v-if="showActivity" scope="col">所属活动</th>
          <th scope="col">状态</th>
          <th scope="col">执行成员</th>
          <th scope="col">开始时间</th>
          <th scope="col">截止时间</th>
          <th scope="col">完成情况</th>
          <th v-if="slots.actions" scope="col">操作</th>
        </tr>
      </thead>

      <tbody
        v-for="task in tasks"
        :id="`task-table-subtasks-${task.id}`"
        :key="task.id"
        class="task-table__group"
      >
        <tr class="task-table__row">
          <td class="task-table__cell task-table__cell--title">
            <div class="task-table__title">
              <div class="task-table__title-row">
                <button
                  v-if="task.children.length > 0"
                  type="button"
                  class="task-table__toggle"
                  :aria-expanded="isExpanded(task.id) ? 'true' : 'false'"
                  :aria-controls="`task-table-subtasks-${task.id}`"
                  :aria-label="`${isExpanded(task.id) ? '收起' : '展开'}「${task.title}」的子任务`"
                  @click="emit('toggle', task.id)"
                >
                  <span aria-hidden="true">{{ isExpanded(task.id) ? '▾' : '▸' }}</span>
                </button>
                <router-link
                  :to="{ name: 'detail', params: { id: task.id } }"
                  class="task-table__link"
                >
                  {{ task.title }}
                </router-link>
              </div>
              <span v-if="slots.meta" class="task-table__meta">
                <slot name="meta" :task="task" />
              </span>
            </div>
          </td>
          <td v-if="showActivity" class="task-table__cell">{{ activityLabel(task) }}</td>
          <td class="task-table__cell">
            <StatusTag :status="task.status" size="small" />
          </td>
          <td class="task-table__cell task-table__cell--members">
            <template v-if="task.assignees.length > 0">
              <span
                v-for="member in visibleAssignees(task)"
                :key="member.user_id"
                class="task-table__member"
              >
                <UserAvatar :user-id="member.user_id" :name="member.name" size="xs" />
                <span class="task-table__member-name">{{ member.name }}</span>
              </span>
              <span v-if="hiddenAssigneeCount(task) > 0" class="task-table__more">
                +{{ hiddenAssigneeCount(task) }}
              </span>
            </template>
            <span v-else class="task-table__member task-table__member--vacant">
              <UserAvatar :user-id="null" :name="''" size="xs" />
              <span class="task-table__member-name">待分配</span>
            </span>
          </td>
          <td class="task-table__cell task-table__cell--time">{{ dateText(task.start_time) }}</td>
          <td class="task-table__cell task-table__cell--time">{{ dateText(task.deadline) }}</td>
          <td class="task-table__cell">{{ completionText(task) }}</td>
          <td v-if="slots.actions" class="task-table__cell task-table__cell--actions">
            <slot name="actions" :task="task" />
          </td>
        </tr>

        <tr
          v-for="child in task.children"
          v-show="isExpanded(task.id)"
          :key="child.id"
          class="task-table__row task-table__row--sub"
        >
          <td class="task-table__cell task-table__cell--title">
            <div class="task-table__title">
              <div class="task-table__title-row">
                <span class="task-table__badge">子任务</span>
                <router-link
                  :to="{ name: 'detail', params: { id: child.id } }"
                  class="task-table__link"
                >
                  {{ child.title }}
                </router-link>
              </div>
            </div>
          </td>
          <td v-if="showActivity" class="task-table__cell">{{ activityLabel(task) }}</td>
          <td class="task-table__cell">
            <StatusTag :status="child.status" size="small" />
          </td>
          <td class="task-table__cell task-table__cell--members">
            <template v-if="child.assignees.length > 0">
              <span
                v-for="member in visibleAssignees(child)"
                :key="member.user_id"
                class="task-table__member"
              >
                <UserAvatar :user-id="member.user_id" :name="member.name" size="xs" />
                <span class="task-table__member-name">{{ member.name }}</span>
              </span>
              <span v-if="hiddenAssigneeCount(child) > 0" class="task-table__more">
                +{{ hiddenAssigneeCount(child) }}
              </span>
            </template>
            <span v-else class="task-table__member task-table__member--vacant">
              <UserAvatar :user-id="null" :name="''" size="xs" />
              <span class="task-table__member-name">待分配</span>
            </span>
          </td>
          <td class="task-table__cell task-table__cell--time">{{ dateText(child.start_time) }}</td>
          <td class="task-table__cell task-table__cell--time">{{ dateText(child.deadline) }}</td>
          <td class="task-table__cell">{{ statusText(child.status) }}</td>
          <td v-if="slots.actions" class="task-table__cell task-table__cell--actions"></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<style scoped>
.task-table__scroll {
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.task-table {
  width: 100%;
  min-width: 680px;
  border-collapse: collapse;
  font-size: var(--app-font-aux);
  color: var(--app-text);
}

.task-table th {
  height: 30px;
  padding: 0 var(--app-space-2);
  text-align: left;
  font-size: var(--app-font-aux);
  font-weight: 600;
  white-space: nowrap;
  color: var(--app-text-muted);
  background: var(--app-surface-sunken);
  border-bottom: 1px solid var(--app-border);
}

.task-table td {
  padding: 5px var(--app-space-2);
  line-height: 1.4;
  vertical-align: middle;
  border-bottom: 1px solid var(--app-border);
}

.task-table__row--sub td {
  background: var(--app-surface-sunken);
}

.task-table__row--sub .task-table__cell--title {
  padding-left: var(--app-space-5);
}

.task-table__cell--title {
  min-width: 180px;
  word-break: break-word;
}

.task-table__title {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.task-table__title-row {
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  min-width: 0;
}

.task-table__meta {
  font-size: var(--app-font-aux);
  line-height: 1.5;
  color: var(--app-text-muted);
  word-break: break-word;
}

.task-table__badge {
  flex-shrink: 0;
  padding: 0 6px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
  line-height: 1.5;
  white-space: nowrap;
}

.task-table__cell--time {
  white-space: nowrap;
}

.task-table__link {
  color: var(--app-primary);
  text-decoration: none;
}

.task-table__link:hover,
.task-table__link:focus-visible {
  text-decoration: underline;
}

.task-table__toggle {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  padding: 0;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-family: inherit;
  font-size: var(--app-font-aux);
  line-height: 1;
  cursor: pointer;
}

.task-table__toggle:hover,
.task-table__toggle:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.task-table__cell--members {
  min-width: 130px;
}

.task-table__member {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-right: var(--app-space-2);
  white-space: nowrap;
}

.task-table__member-name {
  max-width: 90px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-table__member--vacant .task-table__member-name {
  color: var(--app-text-muted);
}

.task-table__more {
  color: var(--app-text-muted);
  white-space: nowrap;
}

.task-table__cell--actions {
  white-space: nowrap;
}

@media (max-width: 768px) {
  .task-table {
    min-width: 560px;
  }

  .task-table td {
    padding: var(--app-space-2);
  }

  .task-table__toggle {
    min-width: var(--app-touch);
    min-height: var(--app-touch);
    font-size: var(--app-font-body);
  }
}
</style>