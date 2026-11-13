<script setup lang="ts">
/**
 * 活动详情（契约 C-SEMANTIC@1 / R5、R6）。
 *
 * 结构顺序固定：`header`（活动名 + 负责人/截止/组织/状态）→ 整体进度 →
 * 任务树（含展开全部/收起全部）→ 操作。整页可被浏览器助手直接阅读：
 * 根节点用 `section.app-page`（`AppLayout` 的 `main#main-content` 是全局唯一 `<main>`），
 * 加载态用 `aria-busy` 表达且不渲染空状态。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { getActivity } from '../api/activities'
import { ApiError } from '../api/client'
import AgentDock from '../components/ai/AgentDock.vue'
import ActivityTaskTree from '../components/task/ActivityTaskTree.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import type { ActivityDetail as ActivityDetailModel } from '../types/models'

const route = useRoute()
const router = useRouter()

const activity = ref<ActivityDetailModel | null>(null)
const loading = ref(false)
const error = ref('')
/** 当前展开的任务 id（子任务列表可见） */
const expanded = ref<number[]>([])

const activityId = computed<number>(() => Number(route.params.id))

const progressText = computed<string>(() => {
  const progress = activity.value?.progress
  if (!progress) return ''
  const base = `${progress.percent}% · ${progress.completed_tasks}/${progress.total_tasks} 个任务已完成`
  return progress.cancelled_tasks > 0 ? `${base} · 已取消 ${progress.cancelled_tasks} 个` : base
})

/** 只有带子任务的第一层任务才参与「展开全部 / 收起全部」 */
const expandableIds = computed<number[]>(() =>
  (activity.value?.tasks ?? []).filter((task) => task.children.length > 0).map((task) => task.id)
)

const allExpanded = computed<boolean>(
  () => expandableIds.value.length > 0 && expandableIds.value.every((id) => expanded.value.includes(id))
)

function activityStatusText(status: string): string {
  if (status === 'published') return '进行中'
  if (status === 'closed') return '已结束'
  return '未知'
}

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.length > 16 ? value.slice(0, 16) : value
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 4040) return err.message || '活动不存在'
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function toggleTask(id: number): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

function toggleAll(): void {
  expanded.value = allExpanded.value ? [] : [...expandableIds.value]
}

function backToHall(): void {
  void router.push({ name: 'hall' })
}

function goPublish(): void {
  void router.push({ name: 'publish' })
}

/** 携带活动归属进入发布页（C-FE-ACTIVITY-PUBLISH@1） */
function publishUnderActivity(): void {
  void router.push({ name: 'publish', query: { activity: String(activityId.value) } })
}

async function load(): Promise<void> {
  if (!Number.isFinite(activityId.value) || activityId.value <= 0) {
    error.value = '活动编号无效'
    return
  }
  loading.value = true
  error.value = ''
  try {
    activity.value = await getActivity(activityId.value)
    const validIds = new Set(expandableIds.value)
    expanded.value = expanded.value.filter((id) => validIds.has(id))
  } catch (err) {
    activity.value = null
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})

watch(
  () => route.params.id,
  () => {
    expanded.value = []
    void load()
  }
)
</script>

<template>
  <section class="app-page activity-detail" :aria-busy="loading ? 'true' : 'false'">
    <LoadingState v-if="loading" :rows="6" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="无法加载活动详情，请确认活动是否存在或检查后端服务。"
      retryable
      @retry="load"
    />

    <template v-else-if="activity">
      <header class="activity-header app-section-card">
        <h1 class="activity-title">{{ activity.title }}</h1>
        <p v-if="activity.description" class="activity-desc">{{ activity.description }}</p>
        <dl class="activity-facts">
          <div class="fact">
            <dt>负责人</dt>
            <dd>{{ activity.owner_name }}</dd>
          </div>
          <div class="fact">
            <dt>截止</dt>
            <dd>{{ dateText(activity.deadline) }}</dd>
          </div>
          <div class="fact">
            <dt>组织</dt>
            <dd>{{ activity.org || '未加入组织' }}</dd>
          </div>
          <div class="fact">
            <dt>状态</dt>
            <dd>{{ activityStatusText(activity.status) }}</dd>
          </div>
        </dl>
      </header>

      <section class="app-section-card" aria-labelledby="activity-progress-heading">
        <h2 id="activity-progress-heading" class="section-title">整体进度</h2>
        <p class="progress-text">{{ progressText }}</p>
        <p v-if="activity.progress.awaiting_owner_confirm" class="awaiting-hint">
          下层工作已完成，待负责人确认
        </p>
      </section>

      <section class="app-section-card" aria-labelledby="activity-tasks-heading">
        <div class="section-head">
          <h2 id="activity-tasks-heading" class="section-title">任务</h2>
          <button
            v-if="expandableIds.length > 0"
            type="button"
            class="expand-all"
            :aria-expanded="allExpanded ? 'true' : 'false'"
            @click="toggleAll"
          >
            {{ allExpanded ? '收起全部' : '展开全部' }}
          </button>
        </div>
        <ActivityTaskTree :tasks="activity.tasks" :expanded="expanded" @toggle="toggleTask" />
      </section>

      <section class="app-section-card" aria-label="操作">
        <div class="app-actions">
          <el-button @click="backToHall">返回事务列表</el-button>
          <el-button type="primary" @click="publishUnderActivity">在此活动下新建任务</el-button>
          <el-button @click="goPublish">发布相关事务</el-button>
        </div>
      </section>

      <AgentDock :context-label="`活动：${activity.title}`" />
    </template>
  </section>
</template>

<style scoped>
.activity-detail {
  max-width: 1000px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.activity-header {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.activity-title {
  margin: 0;
  font-size: var(--app-font-page-title);
  font-weight: 700;
  line-height: 1.3;
  color: var(--app-text);
  word-break: break-word;
}

.activity-desc {
  margin: 0;
  font-size: var(--app-font-body);
  line-height: 1.7;
  color: var(--app-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.activity-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 10px;
  margin: 0;
}

.fact {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.fact dt {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.fact dd {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.section-title {
  margin: 0;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  color: var(--app-text);
}

.activity-detail .section-title + .progress-text,
.section-head + .activity-tree {
  margin-top: 10px;
}

.progress-text {
  margin: 10px 0 0;
  font-size: var(--app-font-body);
  color: var(--app-text);
  word-break: break-word;
}

.awaiting-hint {
  margin: 8px 0 0;
  font-size: var(--app-font-aux-lg);
  color: var(--el-color-warning);
  word-break: break-word;
}

.expand-all {
  min-height: var(--app-touch);
  min-width: var(--app-touch);
  padding: 0 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.expand-all:hover,
.expand-all:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

@media (max-width: 768px) {
  .activity-detail {
    gap: 12px;
  }

  .activity-facts {
    grid-template-columns: 1fr;
  }

  .section-head :deep(.expand-all),
  .section-head .expand-all {
    width: 100%;
  }

  .app-actions {
    flex-direction: column;
    align-items: stretch;
  }

  .app-actions :deep(.el-button) {
    width: 100%;
    min-height: var(--app-touch);
  }
}
</style>