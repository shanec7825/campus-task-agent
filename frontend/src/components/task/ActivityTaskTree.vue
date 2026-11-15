<script setup lang="ts">
/**
 * 活动任务树（契约 C-SEMANTIC@1）。
 *
 * - 第一层任务用 `article` + `h3 > a` 表达，链接稳定指向 `/tasks/:id`；
 * - 子任务列表始终渲染（`v-show` 控制可见性），保证切换按钮的 `aria-controls`
 *   始终指向已存在的元素；
 * - 展开状态由父视图持有（`expanded` 为任务 id 列表），「展开全部 / 收起全部」
 *   与单节点切换共用同一份状态。
 */
import type { ActivityTaskNode } from '../../types/models'
import EmptyState from '../common/EmptyState.vue'
import StatusTag, { statusText } from './StatusTag.vue'

const props = defineProps<{
  tasks: ActivityTaskNode[]
  /** 当前处于展开状态的任务 id */
  expanded: number[]
}>()

const emit = defineEmits<{ (e: 'toggle', id: number): void }>()

function isExpanded(id: number): boolean {
  return props.expanded.includes(id)
}

function assigneeText(names: string[]): string {
  return names.length > 0 ? names.join('、') : '暂无负责人'
}

function deadlineText(value: string | null): string {
  if (!value) return '未设置截止'
  return value.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <EmptyState
    v-if="tasks.length === 0"
    title="暂无任务"
    description="该活动下还没有任务，可以先发布相关事务。"
  />

  <ul v-else class="activity-tree">
    <li v-for="task in tasks" :key="task.id" class="tree-node">
      <article class="tree-article">
        <h3 class="tree-title">
          <a :href="`/tasks/${task.id}`" class="tree-link">{{ task.title }}</a>
        </h3>
        <p class="tree-meta">
          <StatusTag :status="task.status" size="small" />
          <span>截止 {{ deadlineText(task.deadline) }}</span>
          <span>负责人 {{ assigneeText(task.assignee_names) }}</span>
        </p>
        <button
          v-if="task.children.length > 0"
          type="button"
          class="tree-toggle"
          :aria-expanded="isExpanded(task.id) ? 'true' : 'false'"
          :aria-controls="`subtasks-${task.id}`"
          @click="emit('toggle', task.id)"
        >
          {{ isExpanded(task.id) ? `收起「${task.title}」的子任务` : `展开「${task.title}」的子任务` }}
        </button>
      </article>

      <ul
        v-if="task.children.length > 0"
        v-show="isExpanded(task.id)"
        :id="`subtasks-${task.id}`"
        class="subtask-list"
      >
        <li v-for="child in task.children" :key="child.id" class="subtask-item">
          <a :href="`/tasks/${child.id}`" class="subtask-link">{{ child.title }}</a>
          <p class="subtask-meta">
            {{ statusText(child.status) }} · 截止 {{ deadlineText(child.deadline) }} · 负责人
            {{ assigneeText(child.assignee_names) }}
          </p>
        </li>
      </ul>
    </li>
  </ul>
</template>

<style scoped>
.activity-tree,
.subtask-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.activity-tree {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.tree-node {
  min-width: 0;
}

.tree-article {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 6px 12px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}

.tree-title {
  margin: 0;
  min-width: 0;
  flex: 1 1 220px;
  font-size: var(--app-font-body);
  font-weight: 600;
  line-height: 1.5;
}

.tree-link,
.subtask-link {
  color: var(--app-primary);
  text-decoration: none;
  word-break: break-word;
}

.tree-link:hover,
.tree-link:focus-visible,
.subtask-link:hover,
.subtask-link:focus-visible {
  text-decoration: underline;
}

.tree-meta,
.subtask-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  margin: 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-secondary);
  line-height: 1.6;
  word-break: break-word;
}

.tree-meta {
  flex: 1 1 100%;
}

.tree-toggle {
  flex: 0 0 auto;
  margin-left: auto;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  padding: 0 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.tree-toggle:hover,
.tree-toggle:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.subtask-list {
  margin-top: 6px;
  padding-left: 12px;
  border-left: 2px solid var(--app-border);
}

.subtask-item {
  padding: 6px 0;
}

.subtask-link {
  font-size: var(--app-font-aux-lg);
}

@media (max-width: 768px) {
  .tree-toggle {
    margin-left: 0;
    width: 100%;
  }
}
</style>