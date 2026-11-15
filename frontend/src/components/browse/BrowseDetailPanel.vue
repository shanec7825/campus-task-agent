<script lang="ts">
import type { ActivityDetail, TaskDetail } from '../../types/models'
import { statusText } from '../task/StatusTag.vue'
import { formatDeadline, quotaText } from '../task/TaskCard.vue'
</script>

<script setup lang="ts">
/**
 * 分栏详情面板（契约 `C-BROWSE-SPLIT@1` + design.md §9.1）。
 *
 * - 只读：按 `type`/`id` 调既有 `getActivity` / `getTask`，渲染核心摘要与计数；
 * - 图谱、成员、验收、报名等操作仍在独立详情页，此处不新增写入路径；
 * - 请求序号丢弃晚到响应：选中 B 后 A 的响应不得落地；加载/错误只出现在右侧。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { getActivity } from '../../api/activities'
import { ApiError } from '../../api/client'
import { getTask } from '../../api/tasks'
import ActivityTaskTable from '../task/ActivityTaskTable.vue'
import ErrorState from '../common/ErrorState.vue'
import LoadingState from '../common/LoadingState.vue'
import type { BrowseType } from './HallTabs.vue'

const props = defineProps<{ type: BrowseType; id: number }>()

const emit = defineEmits<{ (e: 'close'): void }>()

const loading = ref(false)
const error = ref('')
const activity = ref<ActivityDetail | null>(null)
const task = ref<TaskDetail | null>(null)
/** 右栏任务表格的展开状态（随选中活动重置） */
const expanded = ref<number[]>([])

/** 请求序号：每次选中变化自增，晚到的旧响应直接丢弃 */
let requestSeq = 0
let disposed = false

function toggleTask(id: number): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.slice(0, 16).replace('T', ' ')
}

async function load(): Promise<void> {
  const current = ++requestSeq
  loading.value = true
  error.value = ''
  activity.value = null
  task.value = null
  try {
    if (props.type === 'activity') {
      const result = await getActivity(props.id)
      if (current !== requestSeq || disposed) return
      activity.value = result
    } else {
      const result = await getTask(props.id)
      if (current !== requestSeq || disposed) return
      task.value = result
    }
  } catch (err) {
    if (current !== requestSeq || disposed) return
    error.value = errorMessage(err)
  } finally {
    if (current === requestSeq) loading.value = false
  }
}

watch(
  () => [props.type, props.id] as const,
  () => {
    expanded.value = []
    void load()
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  disposed = true
  requestSeq += 1
})

const title = computed<string>(() => activity.value?.title ?? task.value?.title ?? '')

const detailLink = computed<string>(() =>
  props.type === 'activity' ? `/activities/${props.id}` : `/tasks/${props.id}`
)

const activityProgressText = computed<string>(() => {
  const progress = activity.value?.progress
  if (!progress) return ''
  return `${progress.completed_tasks}/${progress.total_tasks} 个任务已完成 · ${progress.percent}%`
})

const taskMetaText = computed<string>(() => {
  const value = task.value
  if (!value) return ''
  return `${statusText(value.status)} · 截止 ${formatDeadline(value.deadline)} · ${quotaText(value)}`
})
</script>

<template>
  <aside class="browse-detail" role="region" aria-live="polite" aria-label="选中事项摘要">
    <header class="browse-detail__head">
      <h2 class="browse-detail__title">{{ title || '事项摘要' }}</h2>
      <el-button class="browse-detail__close" text size="small" aria-label="关闭详情" @click="emit('close')">
        关闭
      </el-button>
    </header>

    <LoadingState v-if="loading" :rows="3" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="摘要加载失败，可打开完整详情页查看。"
      retryable
      @retry="load"
    />

    <template v-else-if="activity">
      <p class="browse-detail__lead">{{ activityProgressText }}</p>
      <p v-if="activity.progress.subtask_total > 0" class="browse-detail__meta">
        子任务 {{ activity.progress.subtask_completed }}/{{ activity.progress.subtask_total }}
      </p>
      <p v-if="activity.description" class="browse-detail__desc">{{ activity.description }}</p>
      <dl class="browse-detail__facts">
        <div>
          <dt>负责人</dt>
          <dd>{{ activity.owner_name || '—' }}</dd>
        </div>
        <div>
          <dt>时间</dt>
          <dd>{{ dateText(activity.start_time) }} 至 {{ dateText(activity.deadline) }}</dd>
        </div>
        <div>
          <dt>地点</dt>
          <dd>{{ activity.location || '未设置' }}</dd>
        </div>
        <div>
          <dt>任务</dt>
          <dd>{{ activity.tasks.length }} 个第一层任务</dd>
        </div>
      </dl>

      <section class="browse-detail__tasks" aria-label="活动任务">
        <h3 class="browse-detail__subtitle">任务</h3>
        <ActivityTaskTable :tasks="activity.tasks" :expanded="expanded" @toggle="toggleTask" />
      </section>
    </template>

    <template v-else-if="task">
      <p class="browse-detail__lead">{{ taskMetaText }}</p>
      <p v-if="task.description" class="browse-detail__desc">{{ task.description }}</p>
      <dl class="browse-detail__facts">
        <div v-if="task.activity_title">
          <dt>所属活动</dt>
          <dd>{{ task.activity_title }}</dd>
        </div>
        <div>
          <dt>子任务</dt>
          <dd>{{ task.children.length }} 个</dd>
        </div>
        <div>
          <dt>前置 / 后继</dt>
          <dd>{{ task.dependencies.length }} / {{ task.dependents.length }}</dd>
        </div>
        <div>
          <dt>发布者</dt>
          <dd>{{ task.publisher_name || '—' }}</dd>
        </div>
        <div v-if="task.location">
          <dt>地点</dt>
          <dd>{{ task.location }}</dd>
        </div>
      </dl>
    </template>

    <footer class="browse-detail__footer">
      <router-link class="browse-detail__link" :to="detailLink">打开完整详情</router-link>
    </footer>
  </aside>
</template>

<style scoped>
.browse-detail {
  position: sticky;
  top: var(--app-space-4);
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  box-sizing: border-box;
  min-width: 0;
  align-self: start;
  padding: var(--app-space-4);
  background: var(--app-surface);
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-sm);
}

.browse-detail__head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-2);
}

.browse-detail__title {
  margin: 0;
  min-width: 0;
  color: var(--app-text);
  font-size: var(--app-font-section-title, 19px);
  font-weight: 600;
  line-height: 1.35;
  word-break: break-word;
}

.browse-detail__close {
  flex-shrink: 0;
  min-height: var(--app-touch);
}

.browse-detail__lead {
  margin: 0;
  color: var(--app-text);
  font-size: var(--app-font-body, 15px);
  line-height: 1.6;
}

.browse-detail__meta {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux, 13px);
  line-height: 1.6;
}

.browse-detail__desc {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg, 14px);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.browse-detail__facts {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  margin: 0;
  padding-top: var(--app-space-2);
  border-top: 1px dashed var(--app-border);
}

.browse-detail__facts > div {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}

.browse-detail__facts dt {
  flex-shrink: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux, 13px);
}

.browse-detail__facts dd {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux, 13px);
  word-break: break-word;
}

.browse-detail__tasks {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  min-width: 0;
  padding-top: var(--app-space-2);
  border-top: 1px dashed var(--app-border);
}

.browse-detail__subtitle {
  margin: 0;
  color: var(--app-text);
  font-size: var(--app-font-aux-lg, 14px);
  font-weight: 600;
}

.browse-detail__footer {
  margin-top: auto;
  padding-top: var(--app-space-2);
  border-top: 1px dashed var(--app-border);
}

.browse-detail__link {
  display: inline-flex;
  align-items: center;
  min-height: var(--app-touch);
  color: var(--app-primary);
  font-size: var(--app-font-body, 15px);
  font-weight: 600;
  text-decoration: none;
}

.browse-detail__link:hover {
  text-decoration: underline;
}
</style>