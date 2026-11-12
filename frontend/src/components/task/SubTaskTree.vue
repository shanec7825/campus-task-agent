<script setup lang="ts">
/**
 * 子任务依赖树（计划 T6 实现要点 2 / R2.4-AC4）。
 *
 * - 按 `depends_on` 绘制「前置 → 当前」箭头；
 * - 前置任务未 `verified` 时，当前节点加 `disabled` 样式并标注原因；
 * - 前置任务可能不在 `tasks`（兄弟列表）中，此时通过 `predecessor` 补齐展示。
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
    /** 当前任务的前置任务（可能不在 tasks 中） */
    predecessor?: TaskBrief | null
  }>(),
  { current: null, predecessor: null }
)

const emit = defineEmits<{ (e: 'open', id: number): void }>()

interface TreeNode {
  task: TaskBrief
  /** 前置任务；null 表示无依赖或信息缺失 */
  dependency: TaskBrief | null
  /** 前置任务是否已完成（verified） */
  dependencyDone: boolean
  blocked: boolean
}

const taskMap = computed<Map<number, TaskBrief>>(() => {
  const map = new Map<number, TaskBrief>()
  for (const item of props.tasks) map.set(item.id, item)
  if (props.current) map.set(props.current.id, props.current)
  if (props.predecessor) map.set(props.predecessor.id, props.predecessor)
  return map
})

function buildNode(task: TaskBrief): TreeNode {
  const dependency = task.depends_on === null ? null : (taskMap.value.get(task.depends_on) ?? null)
  const dependencyDone = dependency ? dependency.status === 'verified' : false
  return {
    task,
    dependency,
    dependencyDone,
    blocked: task.depends_on !== null && !dependencyDone
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
        v-if="currentNode && currentNode.task.depends_on !== null"
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
              <span class="chain-title">前置任务 #{{ currentNode.task.depends_on }}（信息缺失）</span>
            </template>
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
              ? '前置任务尚未完成，当前任务暂不可认领/推进'
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
            <template v-if="node.task.depends_on !== null">
              <template v-if="node.dependency">
                <span class="chain-title">{{ node.dependency.title }} #{{ node.dependency.id }}</span>
                <span class="chain-arrow" aria-hidden="true">→</span>
                <span class="chain-title">当前 #{{ node.task.id }}</span>
                <span class="dependency-state" :class="{ done: node.dependencyDone }">
                  {{ node.dependencyDone ? '前置已完成' : '前置未完成' }}
                </span>
              </template>
              <span v-else class="dependency-state">
                前置任务 #{{ node.task.depends_on }}（信息缺失）→ 当前不可推进
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
  border: 1px solid #dcdfe6;
  border-left: 4px solid #409eff;
  border-radius: 8px;
  padding: 10px 12px;
  background: #f5f9ff;
}

.current-node.is-blocked {
  border-left-color: #f56c6c;
  background: #fef6f6;
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
  color: #909399;
  font-weight: 700;
}

.chain-title {
  font-size: 14px;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
  white-space: nowrap;
}

.blocked-tip {
  margin: 6px 0 0;
  font-size: 13px;
  color: #f56c6c;
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
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #ffffff;
}

.node-item.is-blocked {
  opacity: 0.7;
  background: #fafafa;
  border-style: dashed;
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
  color: #303133;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.node-id {
  font-size: 13px;
  color: #c0c4cc;
}

.node-dependency {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #606266;
}

.dependency-state {
  font-size: 13px;
  color: #f56c6c;
}

.dependency-state.done {
  color: #67c23a;
}

.node-actions {
  margin-left: auto;
}
</style>