<script setup lang="ts">
/**
 * 个人中心（计划 T6 / R6）。
 *
 * 自上而下：
 * 1. 用户与积分总览 + 待处理摘要（待审批报名 / 待验收成员 / 未读通知，点击跳区块）；
 * 2. 当前任务分组：我发布的 / 我认领的；
 * 3. 积分流水、签到记录：桌面表格 + 手机卡片双视图（`C-MOBILELIST@1`）；
 * 4. 我的报名：锚点 `id="my-applications"`；
 * 5. 通知只保留未读数入口：点击跳 AI 页右栏（`C-AI-THREE-PANE@1`），本页不渲染通知正文。
 *
 * 所有列表请求都持有 loading / error 两个 ref，并在 `finally` 中复位。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { myApplications } from '../api/applications'
import { getUsage } from '../api/agent'
import { ApiError } from '../api/client'
import { myCheckins } from '../api/checkin'
import { myCredits } from '../api/credits'
import { listTasks } from '../api/tasks'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import StatusTag from '../components/task/StatusTag.vue'
import { applicationStatusMeta, formatDeadline, memberStatusMeta } from '../components/task/TaskCard.vue'
import { useNotificationsStore } from '../stores/notifications'
import { useUserStore } from '../stores/user'
import type {
  AiUsage,
  ApplicationWithTask,
  CheckinItem,
  CreditsMe,
  NotificationItem,
  TaskItem
} from '../types/models'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const notificationsStore = useNotificationsStore()

const myTasks = ref<TaskItem[]>([])
const tasksLoading = ref(false)
const tasksError = ref('')

const credits = ref<CreditsMe | null>(null)
const creditsLoading = ref(false)
const creditsError = ref('')

const checkins = ref<CheckinItem[]>([])
const checkinsLoading = ref(false)
const checkinsError = ref('')

/** 我的报名：报名记录 + 任务摘要 */
const myApplicationsList = ref<ApplicationWithTask[]>([])
const applicationsLoading = ref(false)
const applicationsError = ref('')

const noticesLoading = ref(false)
const noticesError = ref('')

/** AI 用量（`C-AI-USAGE@1`）：额度只限制问答，不影响其他协作功能 */
const aiUsage = ref<AiUsage | null>(null)
const aiUsageLoading = ref(false)
const aiUsageError = ref('')

const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)
const displayName = computed<string>(() => userStore.displayName || '未登录用户')
const roleText = computed<string>(() => {
  const role = userStore.user?.role
  if (role === 'publisher') return '发布者'
  if (role === 'admin') return '管理员'
  if (role === 'student') return '学生'
  return role || '—'
})
const creditsBalance = computed<number>(() => credits.value?.credits ?? userStore.user?.credits ?? 0)
const creditLogs = computed(() => credits.value?.logs ?? [])

const publishedTasks = computed<TaskItem[]>(() =>
  currentUserId.value === null
    ? []
    : myTasks.value.filter((task) => task.publisher_id === currentUserId.value)
)
/** 「我报名通过的」：多负责人模型下以报名状态为准（`assignee_id` 只记首位成员） */
const assignedTasks = computed<TaskItem[]>(() =>
  myTasks.value.filter((task) => task.my_application_status === 'approved')
)

/** 发布者视角：待验收成员数（成员级 `submitted`，与任务聚合状态无关） */
function pendingVerifyCount(task: TaskItem): number {
  return (task.members ?? []).filter((member) => member.status === 'submitted').length
}

const pendingVerifyTotal = computed<number>(() =>
  publishedTasks.value.reduce((sum, task) => sum + pendingVerifyCount(task), 0)
)

const pendingApprovalCount = computed<number>(() =>
  myApplicationsList.value.filter((record) => record.application.status === 'pending').length
)

/** 成员视角：「我」在该任务中的执行状态文案 */
function myMemberMeta(task: TaskItem) {
  return memberStatusMeta(task.my_member_status)
}

/** 只保留未读数：通知正文只在 AI 页右栏展示 */
const unreadCount = computed<number>(() => notificationsStore.unread)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function shortTime(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 16) : value
}

function deltaType(delta: number): 'success' | 'danger' {
  return Number(delta) >= 0 ? 'success' : 'danger'
}

function deltaText(delta: number): string {
  const value = Number(delta)
  return `${value > 0 ? '+' : ''}${value}`
}

async function loadTasks(): Promise<void> {
  tasksLoading.value = true
  tasksError.value = ''
  try {
    const result = await listTasks({ scope: 'mine', include_sub: true })
    myTasks.value = result?.items ?? []
  } catch (err) {
    myTasks.value = []
    tasksError.value = errorMessage(err)
  } finally {
    tasksLoading.value = false
  }
}

async function loadCredits(): Promise<void> {
  creditsLoading.value = true
  creditsError.value = ''
  try {
    credits.value = await myCredits()
  } catch (err) {
    credits.value = null
    creditsError.value = errorMessage(err)
  } finally {
    creditsLoading.value = false
  }
}

async function loadCheckins(): Promise<void> {
  checkinsLoading.value = true
  checkinsError.value = ''
  try {
    const result = await myCheckins()
    checkins.value = result?.items ?? []
  } catch (err) {
    checkins.value = []
    checkinsError.value = errorMessage(err)
  } finally {
    checkinsLoading.value = false
  }
}

async function loadApplications(): Promise<void> {
  applicationsLoading.value = true
  applicationsError.value = ''
  try {
    const result = await myApplications()
    myApplicationsList.value = result?.items ?? []
  } catch (err) {
    myApplicationsList.value = []
    applicationsError.value = errorMessage(err)
  } finally {
    applicationsLoading.value = false
  }
}

async function loadAiUsage(): Promise<void> {
  aiUsageLoading.value = true
  aiUsageError.value = ''
  try {
    aiUsage.value = await getUsage(5)
  } catch (err) {
    aiUsage.value = null
    aiUsageError.value = errorMessage(err)
  } finally {
    aiUsageLoading.value = false
  }
}

function refreshAll(): void {
  void Promise.allSettled([
    loadTasks(),
    loadCredits(),
    loadCheckins(),
    loadApplications(),
    loadAiUsage()
  ])
}

function openTask(taskId: number | null): void {
  if (taskId === null) return
  void router.push({ name: 'detail', params: { id: taskId } })
}

/** 未读通知统一去 AI 页右栏处理（`C-AI-THREE-PANE@1`） */
function openAiNotices(): void {
  void router.push({ name: 'ai', query: { panel: 'inbox' } })
}

/** 固定顶栏高度（含安全间距）：锚点滚动必须落在 header 之下 */
function anchorOffset(): number {
  const raw = getComputedStyle(document.documentElement).getPropertyValue('--app-header-height')
  const parsed = Number.parseInt(raw, 10)
  return (Number.isFinite(parsed) && parsed > 0 ? parsed : 60) + 16
}

function scrollToSection(id: string): void {
  const element = document.getElementById(id)
  if (!element) return
  const top = element.getBoundingClientRect().top + window.scrollY - anchorOffset()
  window.scrollTo({ top: Math.max(top, 0), behavior: 'smooth' })
}


onMounted(async () => {
  await Promise.allSettled([
    loadTasks(),
    loadCredits(),
    loadCheckins(),
    loadApplications(),
    loadAiUsage()
  ])
})

// 同一路由内再次点击红点时不需要滚动：通知入口已迁到 AI 页
</script>

<template>
  <section class="profile app-page">
    <header class="app-page-header">
      <div>
        <h2 class="app-page-title">个人中心</h2>
        <p class="app-page-subtitle">我的任务、积分流水、签到记录与我的报名</p>
      </div>
      <div class="app-actions">
        <el-button @click="refreshAll">刷新全部</el-button>
      </div>
    </header>

    <section class="app-section-card overview">
      <div class="overview-main">
        <div class="overview-user">
          <h3 class="overview-name">{{ displayName }}</h3>
          <p class="overview-meta">
            <el-tag size="small" effect="plain">{{ roleText }}</el-tag>
            <span>{{ userStore.user?.username || '—' }}</span>
            <span v-if="userStore.user?.org">{{ userStore.user?.org }}</span>
          </p>
        </div>
        <div class="overview-credits">
          <span class="credits-value">{{ creditsBalance }}</span>
          <span class="credits-label">当前积分</span>
        </div>
      </div>

      <ul class="overview-stats">
        <li>
          <button type="button" class="stat-item" @click="scrollToSection('my-applications')">
            <span class="stat-value">{{ pendingApprovalCount }}</span>
            <span class="stat-label">待审批报名</span>
          </button>
        </li>
        <li>
          <button type="button" class="stat-item" @click="scrollToSection('my-tasks')">
            <span class="stat-value">{{ pendingVerifyTotal }}</span>
            <span class="stat-label">待验收成员</span>
          </button>
        </li>
        <li>
          <button type="button" class="stat-item" @click="openAiNotices">
            <span class="stat-value">{{ unreadCount }}</span>
            <span class="stat-label">未读通知</span>
          </button>
        </li>
      </ul>
    </section>

    <section id="my-tasks" class="app-section-card section">
      <header class="section-head">
        <span class="card-title">我的任务</span>
        <span class="header-hint">共 {{ myTasks.length }} 个（发布 + 认领）</span>
      </header>

      <LoadingState v-if="tasksLoading" :rows="4" />
      <ErrorState
        v-else-if="tasksError"
        :message="tasksError"
        detail="我的任务加载失败，请检查后端服务后重试。"
        retryable
        @retry="loadTasks"
      />
      <template v-else>
        <el-row :gutter="16">
          <el-col :xs="24" :md="12">
            <div class="task-column">
              <h4 class="column-title">我发布的（{{ publishedTasks.length }}）</h4>
              <EmptyState
                v-if="publishedTasks.length === 0"
                title="暂无发布的任务"
                description="在「发布任务」页创建任务后会出现在这里。"
              />
              <ul v-else class="mini-list">
                <li v-for="task in publishedTasks" :key="task.id" class="mini-item">
                  <div class="mini-main">
                    <el-link type="primary" :underline="false" @click="openTask(task.id)">
                      {{ task.title }}
                    </el-link>
                    <StatusTag :status="task.status" size="small" />
                    <el-tag
                      v-if="pendingVerifyCount(task) > 0"
                      size="small"
                      type="warning"
                      effect="plain"
                    >
                      待验收 {{ pendingVerifyCount(task) }}
                    </el-tag>
                  </div>
                  <span class="mini-meta">截止 {{ formatDeadline(task.deadline) }}</span>
                </li>
              </ul>
            </div>
          </el-col>
          <el-col :xs="24" :md="12">
            <div class="task-column">
              <h4 class="column-title">我认领的（{{ assignedTasks.length }}）</h4>
              <EmptyState
                v-if="assignedTasks.length === 0"
                title="暂无认领的任务"
                description="去「任务大厅」看看有哪些可以认领的任务。"
              />
              <ul v-else class="mini-list">
                <li v-for="task in assignedTasks" :key="task.id" class="mini-item">
                  <div class="mini-main">
                    <el-link type="primary" :underline="false" @click="openTask(task.id)">
                      {{ task.title }}
                    </el-link>
                    <StatusTag :status="task.status" size="small" />
                    <el-tag
                      v-if="task.my_member_status"
                      size="small"
                      :type="myMemberMeta(task).type"
                      effect="dark"
                    >
                      我：{{ myMemberMeta(task).text }}
                    </el-tag>
                  </div>
                  <span class="mini-meta">截止 {{ formatDeadline(task.deadline) }}</span>
                </li>
              </ul>
            </div>
          </el-col>
        </el-row>
      </template>
    </section>

    <section id="credits" class="app-section-card section">
      <header class="section-head">
        <span class="card-title">积分</span>
        <span class="credits-inline">余额 <strong>{{ creditsBalance }}</strong></span>
      </header>

      <LoadingState v-if="creditsLoading" :rows="3" />
      <ErrorState
        v-else-if="creditsError"
        :message="creditsError"
        detail="积分流水加载失败，请稍后重试。"
        retryable
        @retry="loadCredits"
      />
      <template v-else>
        <EmptyState
          v-if="creditLogs.length === 0"
          title="暂无积分流水"
          description="任务验收通过后会自动结算积分，逾期会扣分。"
        />
        <template v-else>
          <div class="app-desktop-table">
            <el-table :data="creditLogs" size="small" stripe>
              <el-table-column prop="created_at" label="时间" width="180" />
              <el-table-column prop="reason" label="事由" min-width="220" />
              <el-table-column label="变动" width="100">
                <template #default="scope">
                  <el-tag :type="deltaType(scope.row.delta)" size="small">
                    {{ deltaText(scope.row.delta) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="任务" width="110">
                <template #default="scope">
                  <el-link
                    v-if="scope.row.task_id !== null"
                    type="primary"
                    :underline="false"
                    @click="openTask(scope.row.task_id)"
                  >
                    #{{ scope.row.task_id }}
                  </el-link>
                  <span v-else>—</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
          <ul class="app-mobile-list">
            <li v-for="log in creditLogs" :key="log.id" class="mobile-card">
              <div class="mobile-card-head">
                <span class="mobile-card-title">{{ log.reason }}</span>
                <el-tag :type="deltaType(log.delta)" size="small">
                  {{ deltaText(log.delta) }}
                </el-tag>
              </div>
              <div class="mobile-card-meta">
                <span>{{ log.created_at }}</span>
                <el-link
                  v-if="log.task_id !== null"
                  type="primary"
                  :underline="false"
                  @click="openTask(log.task_id)"
                >
                  任务 #{{ log.task_id }}
                </el-link>
                <span v-else>任务 —</span>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </section>

    <section id="ai-usage" class="app-section-card section">
      <header class="section-head">
        <span class="card-title">AI 用量</span>
        <span v-if="aiUsage" class="header-hint">
          今日 {{ aiUsage.used }} / {{ aiUsage.limit }} 次
        </span>
      </header>

      <LoadingState v-if="aiUsageLoading" :rows="2" />
      <ErrorState
        v-else-if="aiUsageError"
        :message="aiUsageError"
        detail="AI 用量加载失败；通知、任务与审批等功能不受影响。"
        retryable
        @retry="loadAiUsage"
      />
      <template v-else-if="aiUsage">
        <p class="ai-usage-summary">
          今日剩余 {{ aiUsage.remaining }} 次。额度只限制 AI 问答，任务、通知、报名、审批与验收照常可用。
        </p>
        <EmptyState
          v-if="aiUsage.items.length === 0"
          title="暂无 AI 用量记录"
          description="向 AI 助手提问后会在这里记录用量。"
        />
        <ul v-else class="ai-usage-list">
          <li v-for="item in aiUsage.items.slice(0, 5)" :key="item.id" class="ai-usage-item">
            <span class="ai-usage-time">{{ shortTime(item.created_at) }}</span>
            <span class="ai-usage-meta">{{ item.operation }} · {{ item.units }} 次</span>
          </li>
        </ul>
      </template>
    </section>

    <section id="checkins" class="app-section-card section">
      <header class="section-head">
        <span class="card-title">签到记录</span>
        <span class="header-hint">共 {{ checkins.length }} 条</span>
      </header>

      <LoadingState v-if="checkinsLoading" :rows="3" />
      <ErrorState
        v-else-if="checkinsError"
        :message="checkinsError"
        detail="签到记录加载失败，请稍后重试。"
        retryable
        @retry="loadCheckins"
      />
      <template v-else>
        <EmptyState
          v-if="checkins.length === 0"
          title="暂无签到记录"
          description="在任务详情页点击「签到」后会记录在这里。"
        />
        <template v-else>
          <div class="app-desktop-table">
            <el-table :data="checkins" size="small" stripe>
              <el-table-column label="任务" min-width="240">
                <template #default="scope">
                  <el-link type="primary" :underline="false" @click="openTask(scope.row.task_id)">
                    {{ scope.row.task_title || `任务 #${scope.row.task_id}` }}
                  </el-link>
                </template>
              </el-table-column>
              <el-table-column prop="checkin_time" label="签到时间" width="200" />
            </el-table>
          </div>
          <ul class="app-mobile-list">
            <li v-for="item in checkins" :key="item.id" class="mobile-card">
              <div class="mobile-card-head">
                <el-link type="primary" :underline="false" @click="openTask(item.task_id)">
                  {{ item.task_title || `任务 #${item.task_id}` }}
                </el-link>
                <el-tag size="small" effect="plain">已签到</el-tag>
              </div>
              <div class="mobile-card-meta">
                <span>签到时间：{{ item.checkin_time }}</span>
              </div>
            </li>
          </ul>
        </template>
      </template>
    </section>

    <section id="my-applications" class="app-section-card section">
      <header class="section-head">
        <span class="card-title">我的报名</span>
        <span class="header-hint">共 {{ myApplicationsList.length }} 条 · 待审批可撤回</span>
      </header>

      <LoadingState v-if="applicationsLoading" :rows="3" />
      <ErrorState
        v-else-if="applicationsError"
        :message="applicationsError"
        detail="我的报名加载失败，请稍后重试。"
        retryable
        @retry="loadApplications"
      />
      <template v-else>
        <EmptyState
          v-if="myApplicationsList.length === 0"
          title="暂无报名记录"
          description="在任务大厅点击「报名」后，这里会显示审批进度。"
        />
        <ul v-else class="apply-list">
          <li
            v-for="record in myApplicationsList"
            :key="record.application.id"
            class="apply-item"
          >
            <div class="apply-main">
              <el-link type="primary" :underline="false" @click="openTask(record.task.id)">
                {{ record.task.title }}
              </el-link>
              <el-tag :type="applicationStatusMeta(record.application.status).type" size="small">
                {{ applicationStatusMeta(record.application.status).text }}
              </el-tag>
              <StatusTag :status="record.task.status" size="small" />
            </div>
            <div class="apply-meta">
              <span>报名时间：{{ shortTime(record.application.created_at) }}</span>
              <span v-if="record.application.decided_at">
                处理时间：{{ shortTime(record.application.decided_at) }}
              </span>
              <el-button size="small" text type="primary" @click="openTask(record.task.id)">
                查看任务
              </el-button>
            </div>
            <p
              v-if="record.application.status === 'rejected' && record.application.reason"
              class="apply-reason"
            >
              拒绝原因：{{ record.application.reason }}
            </p>
            <p
              v-else-if="record.application.status === 'pending'"
              class="apply-reason pending-reason"
            >
              等待发布者审批；审批前可在任务详情页撤回报名
            </p>
          </li>
        </ul>
      </template>
    </section>

  </section>
</template>

<style scoped>
/* 仅页内布局；令牌、公共类与响应式规则由 C-STYLE@1（theme.css）提供 */
.overview-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.overview-name {
  margin: 0 0 6px;
  font-size: 18px;
  color: var(--app-text);
}

.overview-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 14px;
  color: var(--app-text-muted);
}

.overview-credits {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding: 6px 14px;
  border-radius: var(--app-radius-md);
  background: var(--app-primary-soft);
}

.credits-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--app-primary);
  line-height: 1.2;
}

.credits-label {
  font-size: 13px;
  color: var(--app-text-secondary);
}

.overview-stats {
  list-style: none;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin: 16px 0 0;
  padding: 0;
}

.stat-item {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
  width: 100%;
  min-height: var(--app-touch);
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: inherit;
  text-align: left;
  cursor: pointer;
}

.stat-item:hover {
  border-color: var(--app-border-strong);
}

.stat-value {
  font-size: 20px;
  font-weight: 700;
  color: var(--app-text);
  line-height: 1.2;
}

.stat-label {
  font-size: 13px;
  color: var(--app-text-muted);
}

.section {
  min-width: 0;
}

.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 12px;
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text);
}

.header-hint {
  font-size: 13px;
  color: var(--app-text-muted);
}

.header-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.credits-inline {
  font-size: 14px;
  color: var(--app-text-secondary);
}

.credits-inline strong {
  font-size: 16px;
  color: var(--app-primary);
}

.task-column {
  height: 100%;
}

.column-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text-secondary);
}

.mini-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.mini-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px 10px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  min-width: 0;
}

.mini-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.mini-meta {
  font-size: 13px;
  color: var(--app-text-muted);
}

.mobile-card {
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  min-width: 0;
}

.mobile-card + .mobile-card {
  margin-top: 8px;
}

.mobile-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.mobile-card-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.mobile-card-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 13px;
  color: var(--app-text-muted);
  word-break: break-word;
}

.notice-card {
  scroll-margin-top: calc(var(--app-header-height) + 16px);
}

.apply-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.apply-item {
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  min-width: 0;
}

.apply-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.apply-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 12px;
  margin-top: 6px;
  font-size: 13px;
  color: var(--app-text-muted);
}

.apply-reason {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-color-danger);
  line-height: 1.6;
  word-break: break-word;
}

.pending-reason {
  color: var(--el-color-warning);
}

.notice-badge {
  margin-left: 2px;
}

.notice-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.notice-item {
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  min-width: 0;
}

.notice-item.unread {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
}

.notice-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.notice-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.unread-flag {
  font-size: 13px;
  color: var(--el-color-danger);
}

.notice-time {
  margin-left: auto;
  font-size: 13px;
  color: var(--app-text-muted);
}

.notice-content {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--app-text-secondary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.notice-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.notice-item.stale {
  border-style: dashed;
}

.notice-item.stale .notice-title {
  color: var(--app-text-muted);
}

.ai-usage-summary {
  margin: 0 0 10px;
  font-size: 14px;
  color: var(--app-text-secondary);
  line-height: 1.7;
}

.ai-usage-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ai-usage-item {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  gap: 4px 12px;
  font-size: 14px;
  color: var(--app-text-secondary);
}

.ai-usage-time {
  color: var(--app-text-muted);
}

@media (max-width: 768px) {
  .overview-stats {
    grid-template-columns: 1fr;
  }

  .overview-credits {
    align-items: flex-start;
  }
}
</style>