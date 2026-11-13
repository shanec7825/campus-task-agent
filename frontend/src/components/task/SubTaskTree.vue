<script setup lang="ts">
/**
 * 子任务依赖树（计划 T6 实现要点 2 / R2.4-AC4）。
 *
 * - 按 `depends_on_ids`（缺省回退 `depends_on`）绘制「前置 → 当前」箭头；
 * - 任一前置未 `verified` 时，当前节点加 `disabled` 样式并标注原因；
 * - 前置任务可能不在 `tasks`（兄弟列表）中，此时通过 `predecessor` 补齐展示；
 * - 多个前置时箭头只展示首个，同时标注总项数与信息缺失数量。
 */
import { computed } from 'vue'

import type { TaskBrief } from '../../types/models'
import EmptyState from '../common/EmptyState.vue'
import StatusTag from './StatusTag.vue'

const props = withDefaults(
  defineProps<{
    /** 子任务列表（兄弟节点） */
    tasks: TaskBrief[]
    /** 当前任务节点（用于绘制它的前置依赖） */
    current?: TaskBrief | null
    /** 当前任务的前置任务全集（可能不在 tasks 中） */
    predecessors?: TaskBrief[]
    /** 单个前置（兼容旧调用） */
    predecessor?: TaskBrief | null
  }>(),
  { current: null, predecessors: () => [], predecessor: null }
)

const emit = defineEmits<{ (e: 'open', id: number): void }>()

interface TreeNode {
  task: TaskBrief
  /** 前置 id 全集（边表 ∪ 旧 `depends_on` 的去重结果） */
  dependencyIds: number[]
  /** 已在兄弟列表 / predecessor 中找到的前置 */
  dependencies: TaskBrief[]
  /** 首个前置；null 表示无依赖或信息缺失 */
  dependency: TaskBrief | null
  /** 无法解析出前置信息的数量（不可见或不在本列表） */
  missingCount: number
  hasDependencies: boolean
  /** 全部前置是否均已完成（verified） */
  dependencyDone: boolean
  blocked: boolean
}

const taskMap = computed<Map<number, TaskBrief>>(() => {
  const map = new Map<number, TaskBrief>()
  for (const item of props.tasks) map.set(item.id, item)
  if (props.current) map.set(props.current.id, props.current)
  for (const item of props.predecessors) map.set(item.id, item)
  if (props.predecessor) map.set(props.predecessor.id, props.predecessor)
  return map
})

function buildNode(task: TaskBrief): TreeNode {
  const dependencyIds =
    task.depends_on_ids && task.depends_on_ids.length > 0
      ? task.depends_on_ids
      : task.depends_on === null
        ? []
        : [task.depends_on]
  const dependencies = dependencyIds
    .map((id) => taskMap.value.get(id))
    .filter((item): item is TaskBrief => Boolean(item))
  const missingCount = dependencyIds.length - dependencies.length
  const dependencyDone = dependencies.every((item) => item.status === 'verified')
  return {
    task,
    dependencyIds,
    dependencies,
    dependency: dependencies[0] ?? null,
    missingCount,
    hasDependencies: dependencyIds.length > 0,
    dependencyDone,
    blocked: dependencyIds.length > 0 && (!dependencyDone || missingCount > 0)
  }
}

const nodes = computed<TreeNode[]>(() => props.tasks.map(buildNode))
const currentNode = computed<TreeNode | null>(() => (props.current ? buildNode(props.current) : null))
const hasContent = computed<boolean>(() => nodes.value.length > 0 || currentNode.value !== null)
</script>

<template>
  <div class="sub-task-tree">
    <EmptyState v-if="!hasContent" title="暂无子任务" description="该任务未拆解出子任务，或未设置依赖关系。" />

    <template v-else>
      <!-- 当前任务的依赖链：前置 → 当前 -->
      <div
        v-if="currentNode && currentNode.hasDependencies"
        class="current-node"
        :class="{ 'is-blocked': currentNode.blocked }"
      >
        <div class="dependency-chain">
          <span class="chain-node dependency">
            <template v-if="currentNode.dependency">
              <StatusTag :status="currentNode.dependency.status" size="small" />
              <span class="chain-title">{{ currentNode.dependency.title }}</span>
              <span class="chain-id">#{{ currentNode.dependency.id }}</span>
            </template>
            <template v-else>
              <span class="chain-title">前置任务 #{{ currentNode.dependencyIds[0] }}（信息缺失）</span>
            </template>
          </span>
          <span v-if="currentNode.dependencyIds.length > 1" class="chain-extra">
            等 {{ currentNode.dependencyIds.length }} 项前置
          </span>
          <span class="chain-arrow" aria-hidden="true">→</span>
          <span class="chain-node current">
            <StatusTag :status="currentNode.task.status" size="small" />
            <span class="chain-title">当前任务：{{ currentNode.task.title }}</span>
          </span>
        </div>
        <p class="blocked-tip">
          {{
            currentNode.blocked
              ? currentNode.missingCount > 0
                ? '部分前置任务信息缺失，当前任务暂不可认领/推进'
                : '前置任务尚未完成，当前任务暂不可认领/推进'
              : '前置任务已完成，当前任务可以推进'
          }}
        </p>
      </div>

      <ul v-if="nodes.length > 0" class="node-list">
        <li
          v-for="node in nodes"
          :key="node.task.id"
          class="node-item"
          :class="{ 'is-blocked': node.blocked }"
        >
          <div class="node-main">
            <StatusTag :status="node.task.status" size="small" />
            <span class="node-title" :title="node.task.title">{{ node.task.title }}</span>
            <span class="node-id">#{{ node.task.id }}</span>
            <el-tag v-if="node.task.quota !== null" size="small" effect="plain">需求 {{ node.task.quota }} 人</el-tag>
          </div>

          <div class="node-dependency">
            <template v-if="node.hasDependencies">
              <template v-if="node.dependency">
                <span class="chain-title">{{ node.dependency.title }} #{{ node.dependency.id }}</span>
                <span v-if="node.dependencyIds.length > 1" class="chain-extra">
                  等 {{ node.dependencyIds.length }} 项前置
                </span>
                <span class="chain-arrow" aria-hidden="true">→</span>
                <span class="chain-title">当前 #{{ node.task.id }}</span>
                <span class="dependency-state" :class="{ done: node.dependencyDone && node.missingCount === 0 }">
                  {{ node.dependencyDone && node.missingCount === 0 ? '前置已完成' : '前置未完成' }}
                </span>
                <span v-if="node.missingCount > 0" class="dependency-state">
                  另有 {{ node.missingCount }} 项前置信息缺失，当前不可推进
                </span>
              </template>
              <span v-else class="dependency-state">
                前置任务 #{{ node.dependencyIds[0] }}（信息缺失）→ 当前不可推进
              </span>
            </template>
            <span v-else class="dependency-state done">无前置依赖</span>
          </div>

          <div class="node-actions">
            <el-button size="small" text type="primary" @click="emit('open', node.task.id)">
              查看
            </el-button>
          </div>
        </li>
      </ul>
    </template>
  </div>
</template>

<style scoped>
.sub-task-tree {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.current-node {
  border: 1px solid var(--app-border);
  border-left: 4px solid var(--app-primary);
  border-radius: var(--app-radius-sm);
  padding: 10px 12px;
  background: var(--app-primary-soft);
}

.current-node.is-blocked {
  border-left-color: var(--el-color-danger);
  background: var(--el-color-danger-light-9);
}

.dependency-chain {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.chain-node {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.chain-arrow {
  color: var(--app-text-muted);
  font-weight: 700;
}

.chain-title {
  font-size: 14px;
  color: var(--app-text);
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
  white-space: nowrap;
}

.chain-id {
  font-size: 13px;
  color: var(--app-text-muted);
}

.chain-extra {
  font-size: 13px;
  color: var(--app-text-muted);
}

.blocked-tip {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-color-danger);
}

.node-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.node-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}

.node-item.is-blocked {
  background: var(--app-surface-sunken);
  border-style: dashed;
}

.node-item.is-blocked .node-title {
  color: var(--app-text-muted);
}

.node-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 220px;
  flex: 1;
}

.node-title {
  font-size: 15px;
  color: var(--app-text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-id {
  font-size: 13px;
  color: var(--app-text-muted);
}

.node-dependency {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--app-text-secondary);
}

.dependency-state {
  font-size: 13px;
  color: var(--el-color-danger);
}

.dependency-state.done {
  color: var(--el-color-success);
}

.node-actions {
  margin-left: auto;
}

@media (max-width: 768px) {
  .chain-title {
    max-width: 100%;
    white-space: normal;
    word-break: break-word;
  }

  .node-main {
    min-width: 0;
    width: 100%;
    flex-wrap: wrap;
  }

  .node-title {
    white-space: normal;
    word-break: break-word;
  }

  .node-dependency {
    width: 100%;
  }

  .node-actions {
    margin-left: 0;
    width: 100%;
  }

  .node-actions :deep(.el-button) {
    width: 100%;
    min-height: var(--app-touch);
  }
}
</style>