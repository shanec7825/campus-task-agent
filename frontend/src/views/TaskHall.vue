<script setup lang="ts">
/**
 * 事务列表（R3 / 消费 `C-CARD@2`）。
 *
 * - 两个分区：活动（`GET /api/activities`）与独立任务（`activity_id` 与 `parent_id` 均为 `null`）；
 * - 子任务不在本页渲染；
 * - 筛选：状态 / 范围 / 类型；≤768px 收进单个「筛选」按钮的底部抽屉；
 * - 加载中不渲染空状态；本页不放发布入口（发布入口由外壳提供）。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { listActivities } from '../api/activities'
import { applyTask } from '../api/applications'
import { ApiError } from '../api/client'
import { listTasks } from '../api/tasks'
import { STATUS_MAP, statusText } from '../components/task/StatusTag.vue'
import TaskCard, { formatDeadline } from '../components/task/TaskCard.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useUserStore } from '../stores/user'
import type { Activity, TaskItem } from '../types/models'

const router = useRouter()
const userStore = useUserStore()

const activities = ref<Activity[]>([])
const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('all')
const scope = ref('all')
const typeFilter = ref('all')
const filterDrawerOpen = ref(false)
const applyingId = ref<number | null>(null)

/** 状态过滤项直接由 StatusTag 的映射表生成，保证文案唯一来源 */
const statusOptions = Object.entries(STATUS_MAP).map(([value, meta]) => ({
  value,
  label: meta.text
}))

const typeOptions = [
  { value: 'open', label: '公开报名' },
  { value: 'assign', label: '指派' }
]

const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)

/** 独立任务 = 无父任务且无活动归属；子任务一律不进入列表 */
const independentTasks = computed<TaskItem[]>(() =>
  tasks.value.filter(
    (task) =>
      task.parent_id === null &&
      task.activity_id === null &&
      (typeFilter.value === 'all' || task.claim_type === typeFilter.value)
  )
)

const hasFilter = computed<boolean>(
  () => statusFilter.value !== 'all' || scope.value !== 'all' || typeFilter.value !== 'all'
)

const emptyTitle = computed<string>(() => (hasFilter.value ? '没有符合条件的独立任务' : '暂无独立任务'))
const emptyDescription = computed<string>(() =>
  hasFilter.value
    ? '试着切换状态、范围或类型筛选，或点击「刷新」重新加载。'
    : '还没有人发布独立任务，可以在发布页创建第一个事务。'
)

/** 当前筛选摘要：不依赖按钮高亮即可读到「现在筛了什么」 */
const activeFilterText = computed<string>(() => {
  const parts: string[] = []
  if (statusFilter.value !== 'all') parts.push(`状态：${statusText(statusFilter.value)}`)
  if (scope.value !== 'all') parts.push('范围：我的任务')
  if (typeFilter.value !== 'all') {
    const matched = typeOptions.find((option) => option.value === typeFilter.value)
    parts.push(`类型：${matched?.label ?? typeFilter.value}`)
  }
  return parts.length > 0 ? parts.join(' · ') : '全部事务'
})

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function taskQuery(): { status?: string; scope: 'all' | 'mine'; include_sub: boolean } {
  return {
    status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    scope: scope.value === 'mine' ? 'mine' : 'all',
    include_sub: true
  }
}

async function loadTasks(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listTasks(taskQuery())
    tasks.value = result?.items ?? []
  } catch (err) {
    tasks.value = []
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function loadAll(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const [taskResult, activityResult] = await Promise.all([listTasks(taskQuery()), listActivities()])
    tasks.value = taskResult?.items ?? []
    activities.value = activityResult?.items ?? []
  } catch (err) {
    tasks.value = []
    activities.value = []
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

/** 筛选变化只重新拉取任务列表（活动列表与筛选无关） */
function handleFilterChange(): void {
  void loadTasks()
}

/** 清空筛选并重新加载（无筛选时为空操作） */
function resetFilters(): void {
  if (!hasFilter.value) return
  statusFilter.value = 'all'
  scope.value = 'all'
  typeFilter.value = 'all'
  void loadTasks()
}

function goDetail(id: number): void {
  void router.push({ name: 'detail', params: { id } })
}

/** 报名（A1）：返回 `ApplyResult`，成功后本卡片的 `my_application_status` 变为 `pending` */
async function handleApply(task: TaskItem): Promise<void> {
  if (applyingId.value !== null) return
  applyingId.value = task.id
  try {
    const result = await applyTask(task.id)
    // 返回值是 ApplyResult，任务数据在 `result.task`（不得当作 TaskItem）
    const taskTitle = result.task?.title ?? task.title
    ElMessage.success(`已报名《${taskTitle}》，等待发布者审核`)
    await loadTasks()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    applyingId.value = null
  }
}

onMounted(() => {
  void loadAll()
})
</script>

<template>
  <section class="app-page hall" :aria-busy="loading ? 'true' : 'false'">
    <header class="app-page-header hall-header">
      <div class="hall-heading">
        <h1 class="app-page-title">事务</h1>
        <p class="app-page-subtitle" aria-live="polite">
          <template v-if="loading">正在加载事务…</template>
          <template v-else>共 {{ activities.length }} 个活动 · {{ independentTasks.length }} 个独立任务</template>
        </p>
      </div>
      <el-button class="hall-refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </header>

    <LoadingState v-if="loading" :rows="4" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="事务列表加载失败，请检查后端服务后重试。"
      retryable
      @retry="loadAll"
    />

    <template v-else>
      <section class="hall-region hall-region--activities" aria-labelledby="hall-activities-heading">
        <div class="region-head">
          <h2 id="hall-activities-heading" class="region-title">活动</h2>
          <span class="region-count">{{ activities.length }} 个</span>
        </div>

        <p v-if="activities.length === 0" class="region-empty">暂无活动</p>

        <ul v-else class="activity-list">
          <li v-for="activity in activities" :key="activity.id">
            <article class="activity-item">
              <h3 class="activity-title">
                <router-link :to="`/activities/${activity.id}`">{{ activity.title }}</router-link>
              </h3>
              <p class="activity-progress">
                整体进度 {{ activity.progress.percent }}% ·
                {{ activity.progress.completed_tasks }}/{{ activity.progress.total_tasks }} 个任务已完成
              </p>
              <p class="activity-meta">
                负责人 {{ activity.owner_name || '—' }} · 截止
                {{ formatDeadline(activity.deadline) }}
              </p>
            </article>
          </li>
        </ul>
      </section>

      <section class="hall-region hall-region--tasks" aria-labelledby="hall-tasks-heading">
        <div class="region-head">
          <h2 id="hall-tasks-heading" class="region-title">独立任务</h2>
          <span class="region-count">{{ independentTasks.length }} 个</span>
        </div>

        <div class="filter-mobile-row">
          <span class="app-muted">当前筛选：{{ activeFilterText }}</span>
          <el-button @click="filterDrawerOpen = true">筛选</el-button>
        </div>

        <section class="app-section-card filter-panel" aria-label="事务筛选">
          <div class="filter-row">
            <span class="filter-label">状态</span>
            <el-radio-group v-model="statusFilter" class="filter-group" @change="handleFilterChange">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button v-for="option in statusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <div class="filter-row">
            <span class="filter-label">范围</span>
            <el-radio-group v-model="scope" class="filter-group" @change="handleFilterChange">
              <el-radio-button value="all">全部任务</el-radio-button>
              <el-radio-button value="mine">我的任务</el-radio-button>
            </el-radio-group>
          </div>

          <div class="filter-row">
            <span class="filter-label">类型</span>
            <el-radio-group v-model="typeFilter" class="filter-group" @change="handleFilterChange">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button v-for="option in typeOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <div class="filter-current">
            <span class="app-muted">当前筛选：{{ activeFilterText }}</span>
            <el-button v-if="hasFilter" text type="primary" size="small" @click="resetFilters">
              清除筛选
            </el-button>
          </div>
        </section>

        <EmptyState
          v-if="independentTasks.length === 0"
          :title="emptyTitle"
          :description="emptyDescription"
        />

        <div v-else class="task-grid">
          <TaskCard
            v-for="task in independentTasks"
            :key="task.id"
            :task="task"
            :current-user-id="currentUserId"
            :applying="applyingId === task.id"
            @apply="handleApply"
            @open="goDetail"
            @manage="goDetail"
          />
        </div>
      </section>
    </template>

    <el-drawer v-model="filterDrawerOpen" direction="btt" size="70%" title="筛选">
      <div class="drawer-filters">
        <div class="filter-row">
          <span class="filter-label">状态</span>
          <el-radio-group v-model="statusFilter" class="filter-group" @change="handleFilterChange">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="option in statusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
        </div>

        <div class="filter-row">
          <span class="filter-label">范围</span>
          <el-radio-group v-model="scope" class="filter-group" @change="handleFilterChange">
            <el-radio-button value="all">全部任务</el-radio-button>
            <el-radio-button value="mine">我的任务</el-radio-button>
          </el-radio-group>
        </div>

        <div class="filter-row">
          <span class="filter-label">类型</span>
          <el-radio-group v-model="typeFilter" class="filter-group" @change="handleFilterChange">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="option in typeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
        </div>

        <p class="app-muted">当前筛选：{{ activeFilterText }}</p>
      </div>

      <div class="drawer-footer">
        <el-button :disabled="!hasFilter" @click="resetFilters">清除筛选</el-button>
        <el-button @click="filterDrawerOpen = false">完成</el-button>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.hall-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.hall-heading {
  min-width: 0;
}

.hall-region {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.region-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.region-title {
  margin: 0;
  font-size: var(--app-font-section-title, 19px);
  font-weight: 600;
  line-height: 1.3;
  color: var(--app-text);
}

.region-count {
  font-size: var(--app-font-aux, 13px);
  color: var(--app-text-muted);
}

.region-empty {
  margin: 0;
  padding: 12px 14px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  font-size: var(--app-font-aux-lg, 14px);
  color: var(--app-text-secondary);
}

.activity-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.activity-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100%;
  box-sizing: border-box;
  padding: 12px 14px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-sm);
}

.activity-title {
  margin: 0;
  font-size: var(--el-font-size-medium);
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}

.activity-title a {
  color: var(--app-text);
  text-decoration: none;
}

.activity-title a:hover {
  color: var(--app-primary);
}

.activity-progress,
.activity-meta {
  margin: 0;
  font-size: var(--app-font-aux, 13px);
  line-height: 1.5;
  color: var(--app-text-secondary);
}

.activity-meta {
  color: var(--app-text-muted);
}

.filter-mobile-row {
  display: none;
}

.filter-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.filter-label {
  font-size: var(--app-font-aux-lg, 14px);
  color: var(--app-text-secondary);
  width: 32px;
  flex-shrink: 0;
}

.filter-group {
  flex-wrap: wrap;
  min-width: 0;
}

.filter-current {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  font-size: var(--app-font-aux, 13px);
  border-top: 1px dashed var(--app-border);
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
  gap: 16px;
}

.drawer-filters {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.drawer-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: var(--app-space-5);
}

.drawer-footer :deep(.el-button) {
  flex: 1 1 0;
  margin-left: 0;
}

/* 手机：筛选收进单个「筛选」按钮的底部抽屉；独立任务前置以保证首屏可见 */
@media (max-width: 768px) {
  .hall-header {
    order: 0;
  }

  .hall-region--tasks {
    order: 1;
  }

  .hall-region--activities {
    order: 2;
  }

  .hall-refresh {
    min-width: var(--app-touch);
    min-height: var(--app-touch);
  }

  .filter-mobile-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: var(--app-font-aux, 13px);
  }

  .filter-panel {
    display: none;
  }

  .filter-mobile-row :deep(.el-button),
  .drawer-footer :deep(.el-button) {
    min-height: var(--app-touch);
  }

  .activity-title a {
    display: inline-flex;
    align-items: center;
    min-height: var(--app-touch);
  }

  .filter-label {
    width: auto;
    font-size: var(--app-font-body, 15px);
  }

  .filter-group {
    width: 100%;
  }

  .filter-group :deep(.el-radio-button) {
    flex: 1 1 auto;
  }

  .filter-group :deep(.el-radio-button__inner) {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: var(--app-touch);
    padding: 0 12px;
    font-size: var(--app-font-body, 15px);
  }
}
</style>