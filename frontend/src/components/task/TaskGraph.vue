<script lang="ts">
/**
 * 模块级实例计数器：`<script setup>` 顶层绑定是每个实例的局部变量，
 * 放在 setup 内会令每个实例都从 0 开始（第二轮审查 I6）。
 */
let graphSequence = 0

export function nextGraphId(): string {
  graphSequence += 1
  return `task-graph-${graphSequence}`
}
</script>

<script setup lang="ts">
/**
 * 活动与任务共用依赖 / 时间图谱（契约 `C-FE-TASK-GRAPH@1`）。
 *
 * - 数据唯一来源是服务端 `graph`（活动全图或任务局部图），图与列表同源；
 * - 依赖按层级分列展示，边同时以文字关系列出，避免只靠颜色表达；
 * - 只有 `start_time` 与 `deadline` 都存在才进入工作区间视图；任一缺失进入「未排期」，
 *   不补默认时间、不画虚构位置；
 * - 节点使用稳定链接 `/tasks/:id`，状态同时有文字（`StatusTag`）；
 * - 桌面横向分列，移动端纵向堆叠；横向滚动只发生在时间轴容器内。
 */
import { computed } from 'vue'

import type { TaskGraphEdge, TaskGraphNode } from '../../types/models'
import StatusTag from './StatusTag.vue'

const props = withDefaults(
  defineProps<{
    nodes: TaskGraphNode[]
    edges: TaskGraphEdge[]
    /** `full` = 活动全图；`local` = 当前任务与直接前后节点 */
    mode?: 'full' | 'local'
    currentId?: number | null
  }>(),
  { mode: 'full', currentId: null }
)

/** 同一页面可能同时渲染局部图与活动全图；实例级唯一 id 避免重复 DOM id（审查 I6）。 */
const graphId = nextGraphId()

const nodeMap = computed<Map<number, TaskGraphNode>>(
  () => new Map(props.nodes.map((node) => [node.id, node]))
)

const incoming = computed<Map<number, number[]>>(() => {
  const result = new Map<number, number[]>()
  for (const edge of props.edges) {
    const list = result.get(edge.to_id) ?? []
    list.push(edge.from_id)
    result.set(edge.to_id, list)
  }
  return result
})

/** 依赖层级：无前置为 0，其余为前置最大层级 + 1；脏数据成环时按 0 防御。 */
const levels = computed<number[]>(() => {
  const memo = new Map<number, number>()
  const visiting = new Set<number>()
  const inEdges = incoming.value
  const resolve = (id: number): number => {
    const cached = memo.get(id)
    if (cached !== undefined) return cached
    if (visiting.has(id)) return 0
    visiting.add(id)
    const deps = (inEdges.get(id) ?? []).filter((dep) => nodeMap.value.has(dep))
    const value = deps.length === 0 ? 0 : Math.max(...deps.map(resolve)) + 1
    visiting.delete(id)
    memo.set(id, value)
    return value
  }
  return props.nodes.map((node) => resolve(node.id))
})

const maxLevel = computed<number>(() => (levels.value.length === 0 ? 0 : Math.max(...levels.value)))

const columns = computed<Array<{ level: number; nodes: TaskGraphNode[] }>>(() => {
  const groups: TaskGraphNode[][] = []
  props.nodes.forEach((node, index) => {
    const level = levels.value[index] ?? 0
    groups[level] = groups[level] ?? []
    groups[level].push(node)
  })
  return groups
    .map((nodes, level) => ({ level, nodes }))
    .filter((column) => column.nodes.length > 0)
})

function nodeTitle(id: number): string {
  return nodeMap.value.get(id)?.title ?? `任务 #${id}`
}

function predecessorText(id: number): string {
  const deps = (incoming.value.get(id) ?? []).filter((dep) => nodeMap.value.has(dep))
  return deps.length === 0 ? '无前置' : deps.map(nodeTitle).join('、')
}

function shortTime(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 16) : value
}

function rangeText(node: TaskGraphNode): string {
  if (node.start_time && node.deadline) {
    return `${shortTime(node.start_time)} → ${shortTime(node.deadline)}`
  }
  if (node.start_time) return `开始 ${shortTime(node.start_time)}，截止未设置`
  if (node.deadline) return `开始未设置，截止 ${shortTime(node.deadline)}`
  return '未设置工作区间'
}

/** 完整区间的节点才进入时间轴；缺任一日期一律进入「未排期」。 */
const scheduled = computed<TaskGraphNode[]>(() =>
  props.nodes
    .filter((node) => Boolean(node.start_time) && Boolean(node.deadline))
    .sort((a, b) => String(a.start_time).localeCompare(String(b.start_time)))
)

const unscheduled = computed<TaskGraphNode[]>(() =>
  props.nodes.filter((node) => !node.start_time || !node.deadline)
)

function toTimestamp(value: string | null): number {
  if (!value) return Number.NaN
  const parsed = Date.parse(value.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : Number.NaN
}

const timeBounds = computed<{ min: number; max: number } | null>(() => {
  const starts = scheduled.value.map((node) => toTimestamp(node.start_time))
  const ends = scheduled.value.map((node) => toTimestamp(node.deadline))
  const values = [...starts, ...ends].filter((value) => Number.isFinite(value))
  if (values.length === 0) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  return max > min ? { min, max } : null
})

function barStyle(node: TaskGraphNode): Record<string, string> {
  const bounds = timeBounds.value
  if (!bounds) return { left: '0%', width: '100%' }
  const start = toTimestamp(node.start_time)
  const end = toTimestamp(node.deadline)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return { left: '0%', width: '100%' }
  const span = bounds.max - bounds.min
  const left = Math.min(100, Math.max(0, ((start - bounds.min) / span) * 100))
  const width = Math.min(100 - left, Math.max(2, ((end - start) / span) * 100))
  return { left: `${left}%`, width: `${width}%` }
}

function nodeClass(node: TaskGraphNode): Record<string, boolean> {
  return {
    'is-current': props.currentId !== null && node.id === props.currentId,
    'is-cancelled': node.status === 'cancelled',
    'is-verified': node.status === 'verified'
  }
}

function formatTimestamp(value: number): string {
  if (!Number.isFinite(value)) return '—'
  const date = new Date(value)
  const pad = (count: number): string => String(count).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

const boundsText = computed<string>(() => {
  const bounds = timeBounds.value
  if (!bounds) return '全部任务尚未形成完整工作区间'
  // 直接使用条形的真实上下界，避免按 start_time 排序后取末行 deadline 导致上界偏小（审查 I7）
  return `${formatTimestamp(bounds.min)} — ${formatTimestamp(bounds.max)}`
})
</script>

<template>
  <section
    class="task-graph"
    :class="`task-graph--${mode}`"
    aria-label="任务依赖与时间图"
    :data-node-count="nodes.length"
    :data-edge-count="edges.length"
  >
    <header class="task-graph__header">
      <h3 class="task-graph__title">{{ mode === 'full' ? '任务全景' : '当前任务与前后依赖' }}</h3>
      <span class="task-graph__hint">
        {{ nodes.length }} 个任务 · {{ edges.length }} 条依赖；层级按「前置 → 当前」表达
      </span>
    </header>

    <p v-if="nodes.length === 0" class="task-graph__empty">暂无任务可展示。</p>

    <div v-else class="task-graph__lanes" :aria-label="`依赖层级，共 ${maxLevel + 1} 层`">
      <section v-for="column in columns" :key="column.level" class="task-graph__lane">
        <h4 class="task-graph__lane-title">第 {{ column.level + 1 }} 层</h4>
        <ul class="task-graph__list">
          <li
            v-for="node in column.nodes"
            :key="node.id"
            class="task-graph__node"
            :class="nodeClass(node)"
          >
            <div class="task-graph__node-head">
              <a
                :href="`/tasks/${node.id}`"
                class="task-graph__node-link"
                :aria-current="node.id === currentId ? 'page' : undefined"
              >
                {{ node.title }}
              </a>
              <StatusTag :status="node.status" size="small" />
            </div>
            <p class="task-graph__meta">负责人：{{ node.assignee_names.join('、') || '暂无' }}</p>
            <p class="task-graph__meta">前置：{{ predecessorText(node.id) }}</p>
            <p class="task-graph__meta">工作区间：{{ rangeText(node) }}</p>
          </li>
        </ul>
      </section>
    </div>

    <section v-if="edges.length > 0" class="task-graph__relations" :aria-labelledby="`${graphId}-edges`">
      <h4 :id="`${graphId}-edges`" class="task-graph__subtitle">依赖关系</h4>
      <ul class="task-graph__edge-list">
        <li v-for="edge in edges" :key="`${edge.from_id}-${edge.to_id}`" class="task-graph__edge">
          <span>{{ nodeTitle(edge.from_id) }}</span>
          <span class="task-graph__arrow" aria-hidden="true">→</span>
          <span>{{ nodeTitle(edge.to_id) }}</span>
        </li>
      </ul>
    </section>

    <section class="task-graph__timeline" :aria-labelledby="`${graphId}-time`">
      <div class="task-graph__timeline-head">
        <h4 :id="`${graphId}-time`" class="task-graph__subtitle">工作区间</h4>
        <span class="task-graph__scale-text">{{ boundsText }}</span>
      </div>

      <div v-if="scheduled.length === 0" class="task-graph__empty">
        暂无完整起止时间；以下任务全部进入未排期，系统不会补默认时间。
      </div>
      <ul v-else class="task-graph__timeline-list">
        <li v-for="node in scheduled" :key="node.id" class="task-graph__timeline-item">
          <div class="task-graph__timeline-labels">
            <a :href="`/tasks/${node.id}`" class="task-graph__node-link">{{ node.title }}</a>
            <span class="task-graph__meta">{{ rangeText(node) }}</span>
          </div>
          <div class="task-graph__bar-track" aria-hidden="true">
            <span class="task-graph__bar" :style="barStyle(node)"></span>
          </div>
        </li>
      </ul>

      <div class="task-graph__unscheduled">
        <h5 class="task-graph__unscheduled-title">未排期（{{ unscheduled.length }}）</h5>
        <p v-if="unscheduled.length === 0" class="task-graph__meta">所有任务都有完整工作区间。</p>
        <ul v-else class="task-graph__unscheduled-list">
          <li v-for="node in unscheduled" :key="node.id" class="task-graph__unscheduled-item">
            <a :href="`/tasks/${node.id}`" class="task-graph__node-link">{{ node.title }}</a>
            <span class="task-graph__meta">{{ rangeText(node) }}</span>
          </li>
        </ul>
      </div>
    </section>
  </section>
</template>

<style scoped>
.task-graph {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.task-graph__header {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px 12px;
}

.task-graph__title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
}

.task-graph__hint,
.task-graph__meta,
.task-graph__scale-text {
  margin: 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-secondary);
  line-height: 1.5;
  word-break: break-word;
}

.task-graph__empty {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-muted);
  line-height: 1.6;
}

.task-graph__lanes {
  display: flex;
  gap: 12px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.task-graph__lane {
  flex: 1 0 min(240px, 100%);
  min-width: 0;
  padding: 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-sunken);
}

.task-graph__lane-title {
  margin: 0 0 8px;
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  color: var(--app-text-muted);
}

.task-graph__list,
.task-graph__edge-list,
.task-graph__timeline-list,
.task-graph__unscheduled-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-graph__node {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px;
  border: 1px solid var(--app-border);
  border-left: 3px solid var(--app-border-strong);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}

.task-graph__node.is-current {
  border-color: var(--app-primary);
  background: var(--el-color-primary-light-9);
}

.task-graph__node.is-verified {
  border-left-color: var(--el-color-success);
}

.task-graph__node.is-cancelled {
  border-left-color: var(--el-color-info);
  background: var(--app-surface-sunken);
}

.task-graph__node-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}

.task-graph__node-link {
  color: var(--app-primary);
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  text-decoration: none;
  word-break: break-word;
}

.task-graph__node-link:hover,
.task-graph__node-link:focus-visible {
  text-decoration: underline;
}

.task-graph__subtitle {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  color: var(--app-text);
}

.task-graph__relations,
.task-graph__timeline {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid var(--app-border);
}

.task-graph__edge-list {
  flex-direction: row;
  flex-wrap: wrap;
}

.task-graph__edge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 8px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-sunken);
  font-size: var(--app-font-aux);
  color: var(--app-text);
  word-break: break-word;
}

.task-graph__arrow {
  color: var(--app-text-muted);
}

.task-graph__timeline-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
}

.task-graph__timeline-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(120px, 2fr);
  align-items: center;
  gap: 10px;
}

.task-graph__timeline-labels {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.task-graph__bar-track {
  position: relative;
  height: 10px;
  border-radius: 999px;
  background: var(--app-surface-sunken);
  border: 1px solid var(--app-border);
}

.task-graph__bar {
  position: absolute;
  top: 0;
  bottom: 0;
  border-radius: 999px;
  background: var(--app-primary);
}

.task-graph__unscheduled {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 8px;
  border-top: 1px dashed var(--app-border);
}

.task-graph__unscheduled-title {
  margin: 0;
  font-size: var(--app-font-aux);
  font-weight: 600;
  color: var(--app-text-muted);
}

.task-graph__unscheduled-item {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 10px;
  padding: 6px 8px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

@media (max-width: 768px) {
  .task-graph__lanes {
    flex-direction: column;
    overflow-x: visible;
  }

  .task-graph__lane {
    flex: 0 0 auto;
    width: 100%;
    box-sizing: border-box;
  }

  .task-graph__timeline-item {
    grid-template-columns: minmax(0, 1fr);
    gap: 6px;
  }
}
</style>