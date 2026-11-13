<script setup lang="ts">
/**
 * 工作台（契约 C-WORKBENCH@1 / C-SEMANTIC@1）。
 *
 * 数据只来自 `listTasks({ scope: 'mine', include_sub: true })` 与 `listActivities()`。
 * 待审批 / 待验收 / 我的事项按发布者与参与者身份派生；同一任务可同时出现在多个分区，
 * 分区内按 id 去重。请求失败必须显示可重试的 ErrorState，不得伪装成「暂无待办」。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listActivities } from '../api/activities'
import { ApiError } from '../api/client'
import { listTasks } from '../api/tasks'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { statusText } from '../components/task/StatusTag.vue'
import { useUserStore } from '../stores/user'
import type { Activity, TaskItem } from '../types/models'

interface WorkbenchGroup {
  key: string
  title: string
  items: TaskItem[]
}

const TERMINAL_STATUSES = ['verified', 'cancelled']
const MINE_MEMBER_STATUSES = ['not_started', 'in_progress', 'rejected']
const APPROACHING_WINDOW_MS = 7 * 86400000

const router = useRouter()
const userStore = useUserStore()

const tasks = ref<TaskItem[]>([])
const activities = ref<Activity[]>([])
const tasksLoading = ref(false)
const activitiesLoading = ref(false)
const tasksError = ref('')
const activitiesError = ref('')
/** 临近截止判定基准时间，在每次加载时刷新 */
const nowMs = ref(Date.now())

const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)
const loading = computed<boolean>(() => tasksLoading.value || activitiesLoading.value)
/** 两个请求都失败时降级为页面级错误 */
const pageError = computed<boolean>(() => Boolean(tasksError.value && activitiesError.value))

/** `value.replace(' ', 'T')` 后解析；不可解析返回 `null`（该类任务不进入「临近截止」） */
function parseDeadline(value: string | null): Date | null {
  if (!value) return null
  const date = new Date(value.replace(' ', 'T'))
  return Number.isNaN(date.getTime()) ? null : date
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}

function formatDeadline(value: string | null): string {
  const date = parseDeadline(value)
  if (!date) return '未设置'
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

function isTerminal(task: TaskItem): boolean {
  return TERMINAL_STATUSES.includes(task.status)
}

function isPublisher(task: TaskItem): boolean {
  return currentUserId.value !== null && task.publisher_id === currentUserId.value
}

function dedupeById(items: TaskItem[]): TaskItem[] {
  const seen = new Set<number>()
  return items.filter((item) => {
    if (seen.has(item.id)) return false
    seen.add(item.id)
    return true
  })
}

/** 待审批：我发布、有人报名、且任务尚未进入终态 */
const pendingApproval = computed<TaskItem[]>(() =>
  dedupeById(
    tasks.value.filter((task) => isPublisher(task) && task.applied_count > 0 && !isTerminal(task))
  )
)

/** 待验收：我发布、且存在成员处于 `submitted` */
const pendingVerify = computed<TaskItem[]>(() =>
  dedupeById(
    tasks.value.filter(
      (task) => isPublisher(task) && (task.members ?? []).some((member) => member.status === 'submitted')
    )
  )
)

/** 我的事项：我作为成员待推进/被退回，或我的报名仍在待审批 */
const mineItems = computed<TaskItem[]>(() =>
  dedupeById(
    tasks.value.filter(
      (task) =>
        (task.my_member_status !== null && MINE_MEMBER_STATUSES.includes(task.my_member_status)) ||
        task.my_application_status === 'pending'
    )
  )
)

/** 临近截止：非终态、截止可解析、7 天内，且我与任务有直接关系 */
const approaching = computed<TaskItem[]>(() =>
  dedupeById(
    tasks.value.filter((task) => {
      if (isTerminal(task)) return false
      const deadline = parseDeadline(task.deadline)
      if (!deadline) return false
      if (deadline.getTime() > nowMs.value + APPROACHING_WINDOW_MS) return false
      return (
        isPublisher(task) ||
        task.my_application_status === 'approved' ||
        task.my_member_status !== null
      )
    })
  )
)

const todoCount = computed<number>(() => {
  const ids = new Set<number>()
  for (const item of [...pendingApproval.value, ...pendingVerify.value, ...mineItems.value]) {
    ids.add(item.id)
  }
  return ids.size
})

const approachingCount = computed<number>(() => approaching.value.length)

const groups = computed<WorkbenchGroup[]>(() =>
  [
    { key: 'approval', title: '待审批', items: pendingApproval.value },
    { key: 'verify', title: '待验收', items: pendingVerify.value },
    { key: 'mine', title: '我的事项', items: mineItems.value },
    { key: 'deadline', title: '临近截止', items: approaching.value }
  ].filter((group) => group.items.length > 0)
)

const myActivities = computed<Activity[]>(() => activities.value.slice(0, 5))

function isOverdue(task: TaskItem): boolean {
  const deadline = parseDeadline(task.deadline)
  return deadline !== null && deadline.getTime() < Date.now()
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function loadTasks(): Promise<void> {
  tasksLoading.value = true
  tasksError.value = ''
  try {
    const result = await listTasks({ scope: 'mine', include_sub: true })
    tasks.value = result?.items ?? []
    nowMs.value = Date.now()
  } catch (err) {
    tasks.value = []
    tasksError.value = errorMessage(err)
  } finally {
    tasksLoading.value = false
  }
}

async function loadActivities(): Promise<void> {
  activitiesLoading.value = true
  activitiesError.value = ''
  try {
    const result = await listActivities()
    activities.value = result?.items ?? []
  } catch (err) {
    activities.value = []
    activitiesError.value = errorMessage(err)
  } finally {
    activitiesLoading.value = false
  }
}

function retryAll(): void {
  void Promise.allSettled([loadTasks(), loadActivities()])
}

function openTask(id: number): void {
  void router.push({ name: 'detail', params: { id } })
}

function openActivity(id: number): void {
  void router.push({ name: 'activity', params: { id } })
}

function goPublish(): void {
  void router.push({ name: 'publish' })
}

onMounted(() => {
  retryAll()
})
</script>

<template>
  <section class="app-page workbench" :aria-busy="loading ? 'true' : 'false'">
    <header class="app-page-header">
      <div>
        <h1 class="app-page-title">工作台</h1>
        <p class="app-page-subtitle">按你的身份汇总待处理事务</p>
      </div>
      <div class="app-actions">
        <el-button type="primary" class="publish-button" @click="goPublish">发布</el-button>
      </div>
    </header>

    <ErrorState
      v-if="pageError"
      :message="tasksError"
      detail="工作台数据加载失败，请检查网络或后端服务后重试。"
      retryable
      @retry="retryAll"
    />

    <template v-else>
      <p class="summary-line">
        今天需要你处理 {{ todoCount }} 项 · 临近截止 {{ approachingCount }} 项
      </p>

      <LoadingState v-if="tasksLoading" :rows="4" />
      <ErrorState
        v-else-if="tasksError"
        :message="tasksError"
        detail="待办数据加载失败，请稍后重试。"
        retryable
        @retry="loadTasks"
      />
      <template v-else>
        <EmptyState
          v-if="groups.length === 0"
          title="当前没有需要处理的事项"
          description="可以去事务列表看看可报名的事务。"
        />
        <section
          v-for="group in groups"
          :key="group.key"
          class="app-section-card workbench-group"
          :aria-labelledby="`workbench-${group.key}-heading`"
        >
          <h2 :id="`workbench-${group.key}-heading`" class="group-title">{{ group.title }}</h2>
          <ul class="workbench-list">
            <li v-for="task in group.items" :key="task.id" class="workbench-item">
              <div class="item-main">
                <a class="item-title" :href="`/tasks/${task.id}`" @click.prevent="openTask(task.id)">
                  {{ task.title }}
                </a>
                <span class="item-deadline">
                  截止 {{ formatDeadline(task.deadline) }}
                  <template v-if="group.key === 'deadline' && isOverdue(task)"> · 已逾期</template>
                </span>
              </div>
              <div class="item-side">
                <span class="item-status">{{ statusText(task.status) }}</span>
                <a class="item-link" :href="`/tasks/${task.id}`" @click.prevent="openTask(task.id)">
                  查看
                </a>
              </div>
            </li>
          </ul>
        </section>
      </template>

      <section class="app-section-card workbench-group" aria-labelledby="workbench-activities-heading">
        <h2 id="workbench-activities-heading" class="group-title">我的活动</h2>

        <LoadingState v-if="activitiesLoading" :rows="2" />
        <ErrorState
          v-else-if="activitiesError"
          :message="activitiesError"
          detail="我的活动加载失败，请稍后重试。"
          retryable
          @retry="loadActivities"
        />
        <template v-else>
          <p v-if="myActivities.length === 0" class="activities-empty">暂无活动</p>
          <ul v-else class="workbench-list">
            <li v-for="activity in myActivities" :key="activity.id" class="workbench-item">
              <div class="item-main">
                <a
                  class="item-title"
                  :href="`/activities/${activity.id}`"
                  @click.prevent="openActivity(activity.id)"
                >
                  {{ activity.title }}
                </a>
                <span class="item-deadline">截止 {{ formatDeadline(activity.deadline) }}</span>
              </div>
              <div class="item-side">
                <span class="item-status">负责人 {{ activity.owner_name }}</span>
              </div>
            </li>
          </ul>
        </template>
      </section>
    </template>
  </section>
</template>

<style scoped>
.summary-line {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
}

.group-title {
  margin: 0 0 var(--app-space-3);
  font-size: var(--app-font-section-title);
  font-weight: 600;
  line-height: 1.4;
  color: var(--app-text);
}

.workbench-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: 0;
  padding: 0;
}

.workbench-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2) var(--app-space-3);
  min-width: 0;
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.item-main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.item-title {
  font-size: var(--app-font-body);
  font-weight: 600;
  line-height: 1.5;
  color: var(--app-primary);
  text-decoration: none;
  word-break: break-word;
}

.item-title:hover {
  text-decoration: underline;
}

.item-deadline {
  font-size: var(--app-font-aux);
  line-height: 1.5;
  color: var(--app-text-secondary);
}

.item-side {
  display: flex;
  align-items: center;
  gap: var(--app-space-3);
}

.item-status {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.item-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--app-touch);
  min-width: var(--app-touch);
  padding: 0 var(--app-space-2);
  font-size: var(--app-font-aux-lg);
  color: var(--app-primary);
  text-decoration: none;
}

.item-link:hover {
  text-decoration: underline;
}

.activities-empty {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-muted);
}

/* 桌面端发布入口由 AppLayout 侧栏承载，页面标题区只在手机端显示该按钮 */
.publish-button {
  display: none;
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .publish-button {
    display: inline-flex;
  }

  .workbench-item {
    align-items: flex-start;
  }

  .item-side {
    width: 100%;
    justify-content: space-between;
  }
}
</style>