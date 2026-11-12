<script setup lang="ts">
/**
 * 个人中心（计划 T6 / R5-AC9 / R6-AC5 / R16-AC5）。
 *
 * 五个区块：
 * 1. 我的任务：按「我发布的 / 我报名通过的」分栏；
 * 2. 积分：余额 + 流水表（正负变动着色）；
 * 3. 签到记录表；
 * 4. 我的报名：锚点 `id="my-applications"`，展示审批状态 / 拒绝原因，可跳任务详情；
 * 5. 通知中心：锚点 `id="notifications"`（顶栏红点跳 `/profile#notifications`）、未读高亮、
 *    标记已读、按 `task_id` 快捷跳转详情。
 *
 * 所有列表请求都持有 loading / error 两个 ref，并在 `finally` 中复位。
 */
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { myApplications } from '../api/applications'
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

/** 我的报名（R16-AC5）：报名记录 + 任务摘要 */
const myApplicationsList = ref<ApplicationWithTask[]>([])
const applicationsLoading = ref(false)
const applicationsError = ref('')

const noticesLoading = ref(false)
const noticesError = ref('')

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

/** 成员视角：「我」在该任务中的执行状态文案 */
function myMemberMeta(task: TaskItem) {
  return memberStatusMeta(task.my_member_status)
}

const noticeItems = computed<NotificationItem[]>(() => notificationsStore.items)
const unreadCount = computed<number>(() => notificationsStore.unread)
const unreadIds = computed<number[]>(() =>
  noticeItems.value.filter((item) => item.is_read === 0).map((item) => item.id)
)

/** 通知级别文案（通知 level 与任务状态是两套枚举，故在本页内映射） */
const NOTIFY_LEVELS: Record<string, { text: string; type: 'info' | 'warning' | 'danger' | 'success' }> = {
  info: { text: '通知', type: 'info' },
  warning: { text: '提醒', type: 'warning' },
  urgent: { text: '紧急', type: 'danger' },
  overdue: { text: '逾期', type: 'danger' }
}

function levelMeta(level: string): { text: string; type: 'info' | 'warning' | 'danger' | 'success' } {
  return NOTIFY_LEVELS[level] ?? NOTIFY_LEVELS.info
}

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

async function loadNotices(): Promise<void> {
  noticesLoading.value = true
  noticesError.value = ''
  try {
    await notificationsStore.refresh()
  } catch (err) {
    noticesError.value = errorMessage(err)
  } finally {
    noticesLoading.value = false
  }
}

function refreshAll(): void {
  void Promise.allSettled([
    loadTasks(),
    loadCredits(),
    loadCheckins(),
    loadApplications(),
    loadNotices()
  ])
}

function openTask(taskId: number | null): void {
  if (taskId === null) return
  void router.push({ name: 'detail', params: { id: taskId } })
}

async function markRead(id: number): Promise<void> {
  try {
    await notificationsStore.markRead([id])
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function markAllRead(): Promise<void> {
  if (unreadIds.value.length === 0) return
  try {
    await notificationsStore.markRead([...unreadIds.value])
    ElMessage.success('已全部标记为已读')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

/** 顶栏红点跳 `/profile#notifications` 时滚动到通知中心 */
function scrollToAnchor(): void {
  if (route.hash !== '#notifications') return
  const element = document.getElementById('notifications')
  if (element) element.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

onMounted(async () => {
  await Promise.allSettled([
    loadTasks(),
    loadCredits(),
    loadCheckins(),
    loadApplications(),
    loadNotices()
  ])
  await nextTick()
  scrollToAnchor()
})

// 同一路由内再次点击红点（hash 变化但组件复用）时仍需滚动
watch(
  () => route.hash,
  async () => {
    await nextTick()
    scrollToAnchor()
  }
)
</script>

<template>
  <section class="profile">
    <header class="page-header">
      <div>
        <h2 class="page-title">个人中心</h2>
        <p class="page-subtitle">我的任务、积分流水、签到记录、我的报名与通知中心</p>
      </div>
      <el-button @click="refreshAll">刷新全部</el-button>
    </header>

    <el-card shadow="never" class="user-card">
      <div class="user-main">
        <div class="user-info">
          <h3 class="user-name">{{ displayName }}</h3>
          <p class="user-meta">
            <el-tag size="small" effect="plain">{{ roleText }}</el-tag>
            <span class="user-account">{{ userStore.user?.username || '—' }}</span>
            <span v-if="userStore.user?.org" class="user-org">{{ userStore.user?.org }}</span>
          </p>
        </div>
        <div class="user-credits">
          <span class="credits-value">{{ creditsBalance }}</span>
          <span class="credits-label">当前积分</span>
        </div>
      </div>
    </el-card>

    <el-card id="my-tasks" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">我的任务</span>
          <span class="header-hint">共 {{ myTasks.length }} 个（发布 + 认领）</span>
        </div>
      </template>

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
    </el-card>

    <el-card id="credits" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">积分</span>
          <span class="credits-inline">余额 <strong>{{ creditsBalance }}</strong></span>
        </div>
      </template>

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
        <el-table v-else :data="creditLogs" size="small" stripe>
          <el-table-column prop="created_at" label="时间" width="180" />
          <el-table-column prop="reason" label="事由" min-width="220" />
          <el-table-column label="变动" width="100">
            <template #default="scope">
              <el-tag :type="Number(scope.row.delta) >= 0 ? 'success' : 'danger'" size="small">
                {{ Number(scope.row.delta) > 0 ? '+' : '' }}{{ scope.row.delta }}
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
      </template>
    </el-card>

    <el-card id="checkins" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">签到记录</span>
          <span class="header-hint">共 {{ checkins.length }} 条</span>
        </div>
      </template>

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
        <el-table v-else :data="checkins" size="small" stripe>
          <el-table-column label="任务" min-width="240">
            <template #default="scope">
              <el-link type="primary" :underline="false" @click="openTask(scope.row.task_id)">
                {{ scope.row.task_title || `任务 #${scope.row.task_id}` }}
              </el-link>
            </template>
          </el-table-column>
          <el-table-column prop="checkin_time" label="签到时间" width="200" />
        </el-table>
      </template>
    </el-card>

    <el-card id="my-applications" shadow="never" class="section-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">我的报名</span>
          <span class="header-hint">共 {{ myApplicationsList.length }} 条 · 待审批可撤回</span>
        </div>
      </template>

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
    </el-card>

    <el-card id="notifications" shadow="never" class="section-card notice-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            通知中心
            <el-badge v-if="unreadCount > 0" :value="unreadCount" :max="99" class="notice-badge" />
          </span>
          <div class="header-actions">
            <el-button size="small" :disabled="unreadIds.length === 0" @click="markAllRead">
              全部标为已读
            </el-button>
            <el-button size="small" :loading="noticesLoading" @click="loadNotices">刷新</el-button>
          </div>
        </div>
      </template>

      <LoadingState v-if="noticesLoading" :rows="3" />
      <ErrorState
        v-else-if="noticesError"
        :message="noticesError"
        detail="通知列表加载失败，请稍后重试。"
        retryable
        @retry="loadNotices"
      />
      <template v-else>
        <EmptyState
          v-if="noticeItems.length === 0"
          title="暂无通知"
          description="任务被认领、提交、验收或临近截止时，这里会收到提醒。"
        />
        <ul v-else class="notice-list">
          <li
            v-for="item in noticeItems"
            :key="item.id"
            class="notice-item"
            :class="{ unread: item.is_read === 0 }"
          >
            <div class="notice-head">
              <el-tag :type="levelMeta(item.level).type" size="small" effect="light">
                {{ levelMeta(item.level).text }}
              </el-tag>
              <span class="notice-title">{{ item.title }}</span>
              <span v-if="item.is_read === 0" class="unread-flag">未读</span>
              <span class="notice-time">{{ shortTime(item.created_at) }}</span>
            </div>
            <p class="notice-content">{{ item.content }}</p>
            <div class="notice-actions">
              <el-button
                v-if="item.task_id !== null"
                size="small"
                text
                type="primary"
                @click="openTask(item.task_id)"
              >
                查看任务 #{{ item.task_id }}
              </el-button>
              <el-button v-if="item.is_read === 0" size="small" text @click="markRead(item.id)">
                标记已读
              </el-button>
            </div>
          </li>
        </ul>
      </template>
    </el-card>
  </section>
</template>

<style scoped>
.profile {
  max-width: 1000px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.page-title {
  margin: 0 0 4px;
  font-size: 20px;
  color: #303133;
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: #909399;
}

.user-card {
  border-radius: 10px;
}

.user-main {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.user-name {
  margin: 0 0 6px;
  font-size: 18px;
  color: #303133;
}

.user-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0;
  font-size: 14px;
  color: #909399;
}

.user-account {
  color: #606266;
}

.user-org {
  color: #909399;
}

.user-credits {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  padding: 4px 12px;
  border-radius: 10px;
  background: linear-gradient(135deg, #eef5ff 0%, #f5f7fa 100%);
}

.credits-value {
  font-size: 26px;
  font-weight: 700;
  color: #409eff;
  line-height: 1.2;
}

.credits-label {
  font-size: 13px;
  color: #909399;
}

.section-card {
  border-radius: 10px;
}

.card-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.header-hint {
  font-size: 13px;
  color: #909399;
}

.header-actions {
  display: flex;
  gap: 8px;
}

.credits-inline {
  font-size: 14px;
  color: #606266;
}

.credits-inline strong {
  color: #409eff;
  font-size: 16px;
}

.task-column {
  height: 100%;
}

.column-title {
  margin: 0 0 8px;
  font-size: 14px;
  font-weight: 600;
  color: #606266;
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
  padding: 8px 10px;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #fafbfc;
}

.mini-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.mini-meta {
  font-size: 13px;
  color: #909399;
}

.notice-card {
  scroll-margin-top: 12px;
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
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #ffffff;
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
  color: #909399;
}

.apply-reason {
  margin: 6px 0 0;
  font-size: 13px;
  color: #f56c6c;
  line-height: 1.6;
}

.pending-reason {
  color: #e6a23c;
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
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #ffffff;
}

.notice-item.unread {
  border-color: #c6e2ff;
  background: #f5f9ff;
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
  color: #303133;
}

.unread-flag {
  font-size: 13px;
  color: #f56c6c;
}

.notice-time {
  margin-left: auto;
  font-size: 13px;
  color: #909399;
}

.notice-content {
  margin: 6px 0 0;
  font-size: 14px;
  color: #606266;
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
</style>