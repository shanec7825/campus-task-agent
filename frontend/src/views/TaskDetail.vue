<script setup lang="ts">
/**
 * 任务详情（计划 T6 / R16-AC5~AC8 / R10-AC4）。
 *
 * - 任务信息、状态、成员（`assignee_names`）与名额进度（`approved_count/quota`）；
 * - 报名区块：可报名 / 已报名待审批（可撤回） / 已通过 / 已拒绝、已撤回（可重新报名）；
 * - 子任务树（`depends_on` 前置→当前，未完成节点置灰）与当前任务的前置依赖；
 * - `sop_guide` 步骤清单（空则「暂无实施指导」）；
 * - 进度时间线（`progress_logs`）+ 更新进度弹窗；提交完成；签到（重复签到友好提示）；
 * - 进度 / 提交按本人成员状态（`my_member_status`）开放，签到仅「已通过审核的成员」可用；
 * - 成员执行状态表逐人展示状态 / 提交时间 / 验收时间 / 退回原因。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { applyTask, myApplications, withdrawApply } from '../api/applications'
import { ApiError } from '../api/client'
import { checkin, myCheckins } from '../api/checkin'
import { getTask, submitTask, updateProgress } from '../api/tasks'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import SopSteps from '../components/task/SopSteps.vue'
import StatusTag from '../components/task/StatusTag.vue'
import SubTaskTree from '../components/task/SubTaskTree.vue'
import {
  applicationStatusMeta,
  applyBlockReason,
  formatDeadline,
  isApprovedMember,
  memberStatusMeta,
  quotaText
} from '../components/task/TaskCard.vue'
import { useUserStore } from '../stores/user'
import type { ApplicationStatus, MemberStatus, TaskBrief, TaskDetail, TaskMember } from '../types/models'

const props = defineProps<{ id: string }>()

const router = useRouter()
const userStore = useUserStore()

/** 非「已通过审核的成员」时的统一提示（验收 ⑨） */
const NOT_MEMBER_HINT = '仅已通过审核的成员可操作'
/** 任务已取消时的统一提示（后端对已取消任务的成员操作返回 4090） */
const CANCELLED_HINT = '任务已取消，无法继续操作'
/** 超过该长度或行数的任务要求默认折叠，避免详情页首屏被长文本占满 */
const DESCRIPTION_PREVIEW_LIMIT = 240
const DESCRIPTION_PREVIEW_LINES = 8

const task = ref<TaskDetail | null>(null)
const predecessor = ref<TaskBrief | null>(null)
const loading = ref(false)
const error = ref('')
const checkinStateLoading = ref(false)
const checkedIn = ref(false)
const checkinLoading = ref(false)
const applyLoading = ref(false)
const withdrawLoading = ref(false)
const submitLoading = ref(false)
const progressVisible = ref(false)
const progressText = ref('')
const progressLoading = ref(false)
const descriptionExpanded = ref(false)
/** 最近一次被拒报名的原因（仅 rejected 状态查询，失败不阻塞详情） */
const rejectReason = ref('')
const isMobile = ref(false)

let mobileQuery: MediaQueryList | null = null

const taskId = computed<number>(() => Number(props.id))
const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)


/** 是否为已通过审核的成员（含 legacy 回退，见 `isApprovedMember`） */
const isApproved = computed<boolean>(() =>
  task.value ? isApprovedMember(task.value, currentUserId.value) : false
)
const isPublisher = computed<boolean>(
  () => task.value !== null && currentUserId.value !== null && task.value.publisher_id === currentUserId.value
)

const applicationStatus = computed<ApplicationStatus | null>(
  () => task.value?.my_application_status ?? null
)
const applicationMeta = computed(() => applicationStatusMeta(applicationStatus.value))
/** 可再次提交报名（未报名 / 已拒绝 / 已撤回） */
const showApplyAction = computed<boolean>(
  () => applicationStatus.value !== 'pending' && applicationStatus.value !== 'approved'
)
const canWithdraw = computed<boolean>(() => applicationStatus.value === 'pending')

const applyReason = computed<string>(() =>
  task.value ? applyBlockReason(task.value, currentUserId.value) : ''
)
const canApply = computed<boolean>(() => applyReason.value === '')

const quotaProgress = computed<string>(() => (task.value ? quotaText(task.value) : ''))
const membersText = computed<string>(() => {
  const names = task.value?.assignee_names ?? []
  return names.length > 0 ? names.join('、') : '暂无成员'
})

/** 当前用户的成员执行状态（`my_member_status`，与任务聚合状态无关） */
const myMemberStatus = computed<MemberStatus | null>(() => task.value?.my_member_status ?? null)
/** 当前用户对应的成员行（`task.members` 按 `user_id` 匹配） */
const myMember = computed<TaskMember | null>(() => {
  const userId = currentUserId.value
  if (!task.value || userId === null) return null
  return (task.value.members ?? []).find((member) => member.user_id === userId) ?? null
})
/** 成员状态表：按报名先后顺序原样展示 */
const memberRows = computed<TaskMember[]>(() => task.value?.members ?? [])

/** 信息卡的「我的报名 / 我的执行」摘要 */
const myApplyLabel = computed<string>(() =>
  applicationStatus.value ? `报名${applicationMeta.value.text}` : '未报名'
)
const myExecLabel = computed<string>(() =>
  myMemberStatus.value ? memberStatusMeta(myMemberStatus.value).text : '非任务成员'
)
const descriptionText = computed<string>(() => task.value?.description || '暂无任务描述')
const descriptionIsLong = computed<boolean>(() => {
  const text = descriptionText.value
  return text.length > DESCRIPTION_PREVIEW_LIMIT || text.split('\n').length > DESCRIPTION_PREVIEW_LINES
})
/** 窄屏下信息表改为单列，避免标签与值挤在一起 */
const infoColumns = computed<number>(() => (isMobile.value ? 1 : 2))

/** 成员时间列展示：截断到分钟，空值显示「—」 */
function memberTime(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 16) : value
}

/** 高亮当前用户所在成员行 */
function memberRowClass({ row }: { row: TaskMember }): string {
  const userId = myMember.value?.user_id
  return userId !== undefined && row.user_id === userId ? 'is-me' : ''
}

/** 进度仅对「未开始 / 进行中 / 已退回」的本人成员状态开放（C-FE-MEMBER@1） */
const canProgress = computed<boolean>(() => {
  if (task.value?.status === 'cancelled') return false
  const status = myMemberStatus.value
  return status === 'not_started' || status === 'in_progress' || status === 'rejected'
})
const progressHint = computed<string>(() => {
  if (!task.value) return ''
  if (task.value.status === 'cancelled') return CANCELLED_HINT
  if (!isApproved.value) return NOT_MEMBER_HINT
  if (canProgress.value) return ''
  if (myMemberStatus.value === 'submitted') return '已提交，等待发布者验收'
  if (myMemberStatus.value === 'verified') return '已验收通过，无需再更新进度'
  return '当前状态不允许更新进度'
})

/** 提交仅对「进行中 / 已退回」的本人成员状态开放（C-FE-MEMBER@1） */
const canSubmit = computed<boolean>(() => {
  if (task.value?.status === 'cancelled') return false
  const status = myMemberStatus.value
  return status === 'in_progress' || status === 'rejected'
})
const submitHint = computed<string>(() => {
  if (!task.value) return ''
  if (task.value.status === 'cancelled') return CANCELLED_HINT
  if (!isApproved.value) return NOT_MEMBER_HINT
  if (canSubmit.value) return ''
  if (myMemberStatus.value === 'submitted') return '已提交，等待发布者验收'
  if (myMemberStatus.value === 'verified') return '已验收通过，无需再提交'
  return '需先更新一次进度（进入进行中）后才能提交'
})

const canCheckin = computed<boolean>(() => isApproved.value && !checkedIn.value)
const checkinHint = computed<string>(() => {
  if (!task.value) return ''
  if (!isApproved.value) return NOT_MEMBER_HINT
  if (checkedIn.value) return '已签到，无需重复签到'
  return ''
})

/**
 * 不可用操作的可见原因（触屏无 hover，`:title` 在手机上不可达）。
 * 同一原因合并到一行，避免三个按钮重复输出同一段提示。
 */
const actionHints = computed<string[]>(() => {
  if (!task.value) return []
  const hints = new Map<string, string[]>()
  const push = (action: string, reason: string) => {
    if (!reason) return
    const actions = hints.get(reason) ?? []
    actions.push(action)
    hints.set(reason, actions)
  }
  if (showApplyAction.value) push('报名', applyReason.value)
  push('更新进度', progressHint.value)
  push('提交完成', submitHint.value)
  if (!checkedIn.value) push('签到', checkinHint.value)
  return [...hints.entries()].map(([reason, actions]) => `${actions.join(' / ')}不可用：${reason}`)
})

const subtasks = computed<TaskBrief[]>(() => task.value?.children ?? [])
/** 下层工作已完成、等待负责人验收：纯派生文本，不改任何业务状态与按钮可用性 */
const awaitingOwnerConfirm = computed<boolean>(() =>
  subtasks.value.length > 0 &&
  subtasks.value.every((child) => child.status === 'verified') &&
  task.value !== null &&
  task.value.status !== 'verified'
)
const sortedProgress = computed(() =>
  [...(task.value?.progress ?? [])].sort((a, b) => {
    if (a.created_at === b.created_at) return a.id - b.id
    return a.created_at < b.created_at ? -1 : 1
  })
)
const extrasEntries = computed<Array<[string, unknown]>>(() =>
  task.value ? Object.entries(task.value.extras ?? {}) : []
)

const currentBrief = computed<TaskBrief | null>(() => {
  if (!task.value) return null
  return {
    id: task.value.id,
    title: task.value.title,
    status: task.value.status,
    assignee_id: task.value.assignee_id,
    depends_on: task.value.depends_on,
    quota: task.value.quota,
    parent_id: task.value.parent_id,
    activity_id: task.value.activity_id
  }
})

const predecessorDone = computed<boolean>(() => predecessor.value?.status === 'verified')

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 4040) return err.message || '任务或报名记录不存在'
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function formatExtra(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function handleMobileChange(event: MediaQueryListEvent): void {
  isMobile.value = event.matches
}

/** 查询当前用户是否已对该任务签到（失败不阻塞详情展示） */
async function loadCheckinState(): Promise<void> {
  if (!isApproved.value) {
    checkedIn.value = false
    return
  }
  checkinStateLoading.value = true
  try {
    const result = await myCheckins()
    checkedIn.value = (result?.items ?? []).some((item) => item.task_id === taskId.value)
  } catch {
    // 签到状态是辅助信息，失败时保持未签到展示，真正签到由按钮点击兜底
    checkedIn.value = false
  } finally {
    checkinStateLoading.value = false
  }
}

/** 报名被拒时补充发布者填写的拒绝原因（详情接口不含该字段） */
async function loadRejectReason(): Promise<void> {
  const requestedTaskId = taskId.value
  rejectReason.value = ''
  if (task.value?.my_application_status !== 'rejected') return
  try {
    const result = await myApplications()
    // 快速切换子任务时丢弃过期响应，避免把上一个任务的拒绝原因贴到当前任务
    if (taskId.value !== requestedTaskId) return
    const record = result.items.find(
      (item) => item.task.id === requestedTaskId && item.application.status === 'rejected'
    )
    rejectReason.value = record?.application.reason ?? ''
  } catch {
    // 拒绝原因是辅助信息，失败时仍展示通用说明
  }
}

async function load(): Promise<void> {
  if (!Number.isFinite(taskId.value) || taskId.value <= 0) {
    error.value = '任务编号无效'
    return
  }
  loading.value = true
  error.value = ''
  try {
    const detail = await getTask(taskId.value)
    task.value = detail
    predecessor.value = null
    if (detail.depends_on !== null) {
      try {
        const dependency = await getTask(detail.depends_on)
        predecessor.value = {
          id: dependency.id,
          title: dependency.title,
          status: dependency.status,
          assignee_id: dependency.assignee_id,
          depends_on: dependency.depends_on,
          quota: dependency.quota,
          parent_id: dependency.parent_id,
          activity_id: dependency.activity_id
        }
      } catch {
        // 前置任务信息缺失时由 SubTaskTree 展示「信息缺失」，不影响主流程
        predecessor.value = null
      }
    }
    await loadCheckinState()
    await loadRejectReason()
  } catch (err) {
    task.value = null
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function goDetail(id: number): void {
  void router.push({ name: 'detail', params: { id } })
}

function backToHall(): void {
  void router.push({ name: 'hall' })
}

/** 发布者查看「待验收」任务时可直接去后台验收；也用于「去审核报名」 */
function goAdmin(): void {
  void router.push({ name: 'admin' })
}

async function handleApply(): Promise<void> {
  if (!task.value || applyLoading.value) return
  if (!canApply.value) {
    ElMessage.warning(applyReason.value || '当前不可报名')
    return
  }
  applyLoading.value = true
  try {
    await applyTask(task.value.id)
    ElMessage.success('已报名，等待发布者审核')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    applyLoading.value = false
  }
}

async function handleWithdraw(): Promise<void> {
  if (!task.value || withdrawLoading.value) return
  try {
    await ElMessageBox.confirm(
      '撤回后名额可能被其他同学占用，需要时可重新报名。',
      '撤回报名',
      { type: 'warning', confirmButtonText: '确认撤回', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  withdrawLoading.value = true
  try {
    await withdrawApply(task.value.id)
    ElMessage.success('已撤回报名')
    await load()
  } catch (err) {
    // 已通过审批的报名不允许撤回，后端返回 4090 并给出具体原因
    ElMessage.error(errorMessage(err))
  } finally {
    withdrawLoading.value = false
  }
}

function openProgressDialog(): void {
  if (!canProgress.value) {
    ElMessage.warning(progressHint.value || '当前不可更新进度')
    return
  }
  progressText.value = ''
  progressVisible.value = true
}

async function submitProgress(): Promise<void> {
  if (!task.value) return
  const content = progressText.value.trim()
  if (!content) {
    ElMessage.warning('请填写进度内容')
    return
  }
  progressLoading.value = true
  try {
    await updateProgress(task.value.id, content)
    progressVisible.value = false
    ElMessage.success('进度已更新')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    progressLoading.value = false
  }
}

async function handleSubmit(): Promise<void> {
  if (!task.value || !canSubmit.value) return
  try {
    await ElMessageBox.confirm(
      '提交后任务进入「待验收」状态，发布者验收通过后才会结算积分。',
      '提交完成',
      { type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '再等等' }
    )
  } catch {
    return
  }
  submitLoading.value = true
  try {
    await submitTask(task.value.id)
    ElMessage.success('已提交，等待发布者验收')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    submitLoading.value = false
  }
}

async function handleCheckin(): Promise<void> {
  if (!task.value || checkinLoading.value) return
  if (!isApproved.value) {
    ElMessage.warning(NOT_MEMBER_HINT)
    return
  }
  checkinLoading.value = true
  try {
    await checkin(task.value.id)
    checkedIn.value = true
    ElMessage.success('签到成功')
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.code === 4090) {
        // 重复签到：不视为错误，给出友好提示并同步按钮状态
        checkedIn.value = true
        ElMessage.info('你已经签到过啦，无需重复签到')
        return
      }
      if (err.code === 4030) {
        ElMessage.warning(NOT_MEMBER_HINT)
        return
      }
      if (err.code === 4040) {
        ElMessage.error('任务不存在或已被删除')
        return
      }
      ElMessage.error(err.message || '签到失败，请稍后重试')
      return
    }
    ElMessage.error('签到失败，请稍后重试')
  } finally {
    checkinLoading.value = false
  }
}

onMounted(() => {
  mobileQuery = window.matchMedia('(max-width: 768px)')
  isMobile.value = mobileQuery.matches
  mobileQuery.addEventListener('change', handleMobileChange)
  void load()
})

onBeforeUnmount(() => {
  mobileQuery?.removeEventListener('change', handleMobileChange)
  mobileQuery = null
})

// 同路由不同 id（子任务之间跳转）时重新拉取
watch(
  () => props.id,
  () => {
    descriptionExpanded.value = false
    void load()
  }
)
</script>

<template>
  <section class="app-page detail" :aria-busy="loading ? 'true' : 'false'">
    <!-- 位置导航：活动 → 父任务 → 当前任务（契约 C-SEMANTIC@1） -->
    <nav v-if="task" class="position-nav" aria-label="位置">
      <template v-if="task.activity_id !== null">
        <a class="position-link" :href="`/activities/${task.activity_id}`">
          {{ task.activity_title || `活动 #${task.activity_id}` }}
        </a>
        <span class="position-sep" aria-hidden="true">/</span>
      </template>
      <span v-else class="position-text">独立任务</span>
      <template v-if="task.parent_id !== null">
        <a class="position-link" :href="`/tasks/${task.parent_id}`">
          {{ task.parent_title || `任务 #${task.parent_id}` }}
        </a>
        <span class="position-sep" aria-hidden="true">/</span>
      </template>
      <span class="position-current" aria-current="page">{{ task.title }}</span>
    </nav>

    <el-page-header title="返回" content="任务详情" class="page-header" @back="backToHall" />

    <LoadingState v-if="loading" :rows="6" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="无法加载任务详情，请确认任务是否存在或检查后端服务。"
      retryable
      @retry="load"
    />

    <template v-else-if="task">
      <!-- 首屏信息卡：任务要求 / 截止 / 我的状态 / 当前操作 -->
      <el-card shadow="never" class="app-section-card">
        <div class="key-head">
          <h1 class="task-title">{{ task.title }}</h1>
          <div class="key-tags">
            <StatusTag :status="task.status" />
            <el-tag v-if="task.parent_id !== null" size="small" type="warning" effect="plain">
              子任务 #{{ task.id }}
            </el-tag>
            <el-tag v-else size="small" effect="plain">主任务</el-tag>
            <el-tag
              v-if="applicationStatus"
              :type="applicationMeta.type"
              size="small"
              effect="dark"
            >
              报名{{ applicationMeta.text }}
            </el-tag>
            <el-tag v-else size="small" type="info" effect="plain">未报名</el-tag>
            <el-tag
              v-if="myMemberStatus"
              :type="memberStatusMeta(myMemberStatus).type"
              size="small"
              effect="plain"
            >
              我的执行状态：{{ memberStatusMeta(myMemberStatus).text }}
            </el-tag>
          </div>
        </div>

        <div class="key-meta">
          <div class="meta-item meta-deadline">
            <span class="meta-label">截止时间</span>
            <span class="meta-value">{{ formatDeadline(task.deadline) }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">我的报名</span>
            <span class="meta-value">{{ myApplyLabel }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">我的执行</span>
            <span class="meta-value">{{ myExecLabel }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">名额进度</span>
            <span class="meta-value">{{ quotaProgress }}</span>
          </div>
          <div class="meta-item">
            <span class="meta-label">积分奖励</span>
            <span class="meta-value">+{{ task.credit_reward ?? 0 }}</span>
          </div>
        </div>

        <!-- 当前操作：按角色分组，移动端整行堆叠 -->
        <div class="action-block">
          <span class="block-label">当前操作</span>
          <div class="action-groups">
            <div v-if="showApplyAction || canWithdraw" class="action-group">
              <span class="action-group-label">报名</span>
              <div class="action-group-buttons">
                <el-button
                  v-if="showApplyAction"
                  type="primary"
                  :disabled="!canApply"
                  :title="applyReason"
                  :loading="applyLoading"
                  @click="handleApply"
                >
                  报名
                </el-button>
                <el-button v-if="canWithdraw" :loading="withdrawLoading" @click="handleWithdraw">
                  撤回报名
                </el-button>
              </div>
            </div>

            <div class="action-group">
              <span class="action-group-label">我的执行</span>
              <div class="action-group-buttons">
                <el-button
                  :disabled="!canProgress"
                  :title="canProgress ? '' : progressHint"
                  @click="openProgressDialog"
                >
                  更新进度
                </el-button>
                <el-button
                  type="success"
                  :disabled="!canSubmit"
                  :title="canSubmit ? '' : submitHint"
                  :loading="submitLoading"
                  @click="handleSubmit"
                >
                  提交完成
                </el-button>
                <el-button
                  type="warning"
                  plain
                  :disabled="!canCheckin"
                  :title="checkinHint"
                  :loading="checkinLoading || checkinStateLoading"
                  @click="handleCheckin"
                >
                  {{ checkedIn ? '已签到' : '签到' }}
                </el-button>
              </div>
            </div>

            <div v-if="isPublisher && task.status === 'submitted'" class="action-group">
              <span class="action-group-label">发布者</span>
              <div class="action-group-buttons">
                <el-button type="success" @click="goAdmin">去验收</el-button>
              </div>
            </div>
          </div>
          <ul v-if="actionHints.length > 0" class="hint-list">
            <li v-for="hint in actionHints" :key="hint" class="hint-item">{{ hint }}</li>
          </ul>
        </div>

        <!-- 报名状态说明 -->
        <el-alert
          v-if="applicationStatus === 'pending'"
          type="warning"
          title="已报名，等待发布者审核；审核前可随时撤回报名"
          :closable="false"
          show-icon
          class="inline-alert"
        />
        <el-alert
          v-else-if="applicationStatus === 'approved'"
          type="success"
          title="报名已通过，你已是该任务成员，可以更新进度、签到与提交完成"
          :closable="false"
          show-icon
          class="inline-alert"
        />
        <el-alert
          v-else-if="applicationStatus === 'rejected'"
          type="error"
          title="上次报名已被拒绝，可以重新报名（如名额未满）"
          :closable="false"
          show-icon
          class="inline-alert"
        >
          <p v-if="rejectReason" class="inline-alert__reason">拒绝原因：{{ rejectReason }}</p>
        </el-alert>
        <el-alert
          v-else-if="applicationStatus === 'cancelled'"
          type="info"
          title="你已撤回报名，可随时重新报名"
          :closable="false"
          show-icon
          class="inline-alert"
        />

        <!-- 可报名但被拦截的原因（名额已满 / 自己发布 / 前置未完成 / 状态不符） -->
        <el-alert
          v-if="showApplyAction && applyReason"
          type="warning"
          :title="applyReason"
          :closable="false"
          show-icon
          class="inline-alert"
        />

        <el-alert
          v-if="!isApproved"
          type="info"
          :title="NOT_MEMBER_HINT"
          description="报名并通过发布者审核后，才能更新进度、提交完成与签到。"
          :closable="false"
          class="inline-alert"
        />

        <div class="desc-block">
          <span class="block-label">任务要求</span>
          <p class="description" :class="{ 'is-collapsed': descriptionIsLong && !descriptionExpanded }">
            {{ descriptionText }}
          </p>
          <el-button
            v-if="descriptionIsLong"
            text
            type="primary"
            size="small"
            class="expand-toggle"
            @click="descriptionExpanded = !descriptionExpanded"
          >
            {{ descriptionExpanded ? '收起' : '展开全部' }}
          </el-button>
        </div>

        <el-descriptions :column="infoColumns" border size="small" class="info-table">
          <el-descriptions-item label="发布者">{{ task.publisher_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="首批成员">{{ task.assignee_name || '暂无成员' }}</el-descriptions-item>
          <el-descriptions-item label="名额进度">
            已通过 {{ task.approved_count }}/{{ task.quota === null ? '不限' : task.quota }}
          </el-descriptions-item>
          <el-descriptions-item label="待审批报名">{{ task.applied_count }} 人</el-descriptions-item>
          <el-descriptions-item label="开始时间">{{ formatDeadline(task.start_time) }}</el-descriptions-item>
          <el-descriptions-item label="截止时间">{{ formatDeadline(task.deadline) }}</el-descriptions-item>
          <el-descriptions-item label="地点">{{ task.location || '—' }}</el-descriptions-item>
          <el-descriptions-item label="志愿时长">
            {{ task.volunteer_hours === null ? '—' : `${task.volunteer_hours} 小时` }}
          </el-descriptions-item>
          <el-descriptions-item label="积分奖励">+{{ task.credit_reward ?? 0 }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatDeadline(task.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="风格要求" :span="infoColumns">{{ task.style_note || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div v-if="extrasEntries.length > 0" class="extras">
          <span class="extras-label">扩展项</span>
          <el-tag v-for="[key, value] in extrasEntries" :key="key" class="extra-tag" effect="plain">
            {{ key }}：{{ formatExtra(value) }}
          </el-tag>
        </div>
      </el-card>

      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">成员与名额</span>
            <span class="header-hint">{{ quotaProgress }}</span>
          </div>
        </template>

        <p class="members-line">
          <span class="members-label">已通过成员</span>
          <span :class="{ 'members-empty': (task.assignee_names ?? []).length === 0 }">
            {{ membersText }}
          </span>
        </p>

        <p v-if="isPublisher" class="members-line">
          <span class="members-label">待审批报名</span>
          <span>{{ task.applied_count }} 人</span>
          <el-button v-if="task.applied_count > 0" size="small" text type="primary" @click="goAdmin">
            去审核报名
          </el-button>
        </p>

        <!-- 成员执行状态：桌面表格 + 移动卡片双视图（C-MOBILELIST@1） -->
        <EmptyState
          v-if="memberRows.length === 0"
          title="暂无成员执行记录"
          description="报名通过审核后，成员的执行状态会在这里逐人展示。"
        />
        <template v-else>
          <div class="app-desktop-table">
            <el-table
              :data="memberRows"
              size="small"
              stripe
              class="member-table"
              :row-class-name="memberRowClass"
            >
              <el-table-column label="成员" min-width="130">
                <template #default="scope">
                  <span class="member-name">{{ scope.row.user_name || `用户 #${scope.row.user_id}` }}</span>
                  <el-tag v-if="scope.row.user_id === myMember?.user_id" size="small" effect="plain" class="row-tag">
                    我
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="执行状态" width="110">
                <template #default="scope">
                  <el-tag :type="memberStatusMeta(scope.row.status).type" size="small" effect="plain">
                    {{ memberStatusMeta(scope.row.status).text }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="提交时间" width="160">
                <template #default="scope">{{ memberTime(scope.row.submitted_at) }}</template>
              </el-table-column>
              <el-table-column label="验收时间" width="160">
                <template #default="scope">{{ memberTime(scope.row.verified_at) }}</template>
              </el-table-column>
              <el-table-column label="退回原因" min-width="160">
                <template #default="scope">
                  <span v-if="scope.row.status === 'rejected' && scope.row.rejection_reason" class="member-reason">
                    {{ scope.row.rejection_reason }}
                  </span>
                  <span v-else>—</span>
                </template>
              </el-table-column>
            </el-table>
          </div>

          <ul class="app-mobile-list member-cards">
            <li
              v-for="row in memberRows"
              :key="row.user_id"
              class="member-card"
              :class="{ 'is-me': row.user_id === myMember?.user_id }"
            >
              <div class="member-card-head">
                <span class="member-name">{{ row.user_name || `用户 #${row.user_id}` }}</span>
                <el-tag v-if="row.user_id === myMember?.user_id" size="small" effect="plain">我</el-tag>
                <el-tag :type="memberStatusMeta(row.status).type" size="small" effect="plain">
                  {{ memberStatusMeta(row.status).text }}
                </el-tag>
              </div>
              <dl class="member-card-fields">
                <div class="member-card-field">
                  <dt>提交时间</dt>
                  <dd>{{ memberTime(row.submitted_at) }}</dd>
                </div>
                <div class="member-card-field">
                  <dt>验收时间</dt>
                  <dd>{{ memberTime(row.verified_at) }}</dd>
                </div>
                <div
                  class="member-card-field"
                  :class="{ 'is-danger': row.status === 'rejected' && !!row.rejection_reason }"
                >
                  <dt>退回原因</dt>
                  <dd>
                    {{ row.status === 'rejected' && row.rejection_reason ? row.rejection_reason : '—' }}
                  </dd>
                </div>
              </dl>
            </li>
          </ul>
        </template>
      </el-card>

      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">前置依赖</span>
            <span v-if="task.depends_on === null" class="header-hint">无前置依赖，可独立推进</span>
            <span v-else class="header-hint">
              {{ predecessorDone ? '前置任务已完成' : '前置任务未完成，当前任务暂不可推进' }}
            </span>
          </div>
        </template>
        <div v-if="task.depends_on === null" class="dependency-empty">
          当前任务未设置前置任务，不依赖其他任务。
        </div>
        <div v-else class="dependency-line">
          <span class="dependency-node">
            <template v-if="predecessor">
              <StatusTag :status="predecessor.status" size="small" />
              <el-link type="primary" :underline="false" @click="goDetail(predecessor.id)">
                {{ predecessor.title }} #{{ predecessor.id }}
              </el-link>
            </template>
            <template v-else>
              <span class="dependency-missing">前置任务 #{{ task.depends_on }}（信息缺失）</span>
            </template>
          </span>
          <span class="dependency-arrow" aria-hidden="true">→</span>
          <span class="dependency-node">
            <StatusTag :status="task.status" size="small" />
            <span>当前任务：{{ task.title }}</span>
          </span>
        </div>
      </el-card>

      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">子任务与依赖（{{ subtasks.length }}）</span>
            <span class="header-hint">前置任务未完成的子任务置灰，且不可报名</span>
          </div>
        </template>
        <p v-if="awaitingOwnerConfirm" class="confirm-hint">下层工作已完成，待负责人确认</p>
        <SubTaskTree
          :tasks="subtasks"
          :current="currentBrief"
          :predecessor="predecessor"
          @open="goDetail"
        />
      </el-card>

      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">实施指导（SOP）</span>
          </div>
        </template>
        <SopSteps :guide="task.sop_guide" />
      </el-card>

      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">进度时间线（{{ sortedProgress.length }}）</span>
            <el-button
              size="small"
              :disabled="!canProgress"
              :title="canProgress ? '' : progressHint"
              @click="openProgressDialog"
            >
              更新进度
            </el-button>
          </div>
        </template>
        <EmptyState
          v-if="sortedProgress.length === 0"
          title="暂无进度记录"
          description="成员更新进度后，这里会按时间顺序展示推进过程。"
        />
        <el-timeline v-else>
          <el-timeline-item
            v-for="item in sortedProgress"
            :key="item.id"
            :timestamp="item.created_at"
            placement="top"
            type="primary"
          >
            <div class="progress-item">
              <span class="progress-user">{{ item.user_name || `用户 #${item.user_id}` }}</span>
              <p class="progress-content">{{ item.content }}</p>
            </div>
          </el-timeline-item>
        </el-timeline>
      </el-card>
    </template>

    <el-dialog
      v-model="progressVisible"
      title="更新进度"
      width="min(520px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="进度内容" required>
          <el-input
            v-model="progressText"
            type="textarea"
            :rows="4"
            maxlength="1000"
            show-word-limit
            placeholder="例如：已完成场地测量，物料清单已发给部长，等待确认。"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button :disabled="progressLoading" @click="progressVisible = false">取消</el-button>
        <el-button type="primary" :loading="progressLoading" @click="submitProgress">提交进度</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.position-nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
  word-break: break-word;
}

.position-link {
  color: var(--app-primary);
  text-decoration: none;
}

.position-link:hover,
.position-link:focus-visible {
  text-decoration: underline;
}

.position-sep,
.position-text {
  color: var(--app-text-muted);
}

.position-current {
  color: var(--app-text);
  font-weight: 600;
}

.detail {
  max-width: 1000px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  background: transparent;
}

.key-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.task-title {
  margin: 0;
  font-size: var(--app-font-page-title);
  color: var(--app-text);
  word-break: break-word;
}

.key-tags {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.key-meta {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin-top: 14px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.meta-label {
  font-size: 13px;
  color: var(--app-text-muted);
}

.meta-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.meta-deadline .meta-value {
  color: var(--app-primary);
}

.block-label,
.action-group-label {
  display: inline-block;
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--app-text-muted);
}

.action-block,
.desc-block {
  margin-top: 16px;
}

.action-groups {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.action-group {
  display: flex;
  flex-direction: column;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-sunken);
}

.action-group-buttons {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.action-group-buttons :deep(.el-button) {
  margin: 0;
}

.hint-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.hint-item {
  font-size: 13px;
  color: var(--el-color-warning);
  word-break: break-word;
}

.inline-alert {
  margin-top: 10px;
}

.inline-alert__reason {
  margin: 4px 0 0;
  line-height: 1.6;
  word-break: break-word;
}

.description {
  margin: 0;
  font-size: 15px;
  color: var(--app-text-secondary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.description.is-collapsed {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 6;
  overflow: hidden;
  white-space: normal;
}

.expand-toggle {
  margin-top: 4px;
  padding: 0;
}

.info-table {
  margin-top: 14px;
}

.extras {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
}

.extras-label {
  font-size: 13px;
  color: var(--app-text-muted);
}

.extra-tag {
  margin: 0;
}

.card-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text);
}

.header-hint {
  font-size: 13px;
  color: var(--app-text-muted);
}

.members-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin: 0 0 6px;
  font-size: 14px;
  color: var(--app-text);
}

.members-label {
  color: var(--app-text-muted);
}

.members-empty {
  color: var(--app-text-muted);
}

.confirm-hint {
  margin: 0 0 10px;
  font-size: var(--app-font-aux-lg);
  color: var(--el-color-warning);
  line-height: 1.6;
  word-break: break-word;
}

.member-table {
  margin-top: 12px;
}

.member-table :deep(.is-me) {
  background: var(--el-color-primary-light-9);
}

.member-name {
  font-weight: 500;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.row-tag {
  margin-left: 6px;
}

.member-reason {
  color: var(--el-color-danger);
  font-size: 13px;
}

.member-cards {
  list-style: none;
  margin: 12px 0 0;
  padding: 0;
}

.member-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-raised);
}

.member-card + .member-card {
  margin-top: 10px;
}

.member-card.is-me {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
}

.member-card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.member-card-fields {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.member-card-field {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  font-size: 13px;
}

.member-card-field dt {
  flex-shrink: 0;
  color: var(--app-text-muted);
}

.member-card-field dd {
  margin: 0;
  color: var(--app-text-secondary);
  text-align: right;
  word-break: break-word;
}

.member-card-field.is-danger dd {
  color: var(--el-color-danger);
}

.dependency-empty {
  font-size: 14px;
  color: var(--app-text-muted);
}

.dependency-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  font-size: 14px;
  color: var(--app-text);
}

.dependency-node {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
  word-break: break-word;
}

.dependency-arrow {
  color: var(--app-text-muted);
  font-weight: 700;
}

.dependency-missing {
  color: var(--el-color-danger);
}

.progress-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.progress-user {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-text);
}

.progress-content {
  margin: 0;
  font-size: 14px;
  color: var(--app-text-secondary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 768px) {
  .detail {
    gap: 12px;
  }

  .key-meta {
    grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  }

  .action-groups {
    flex-direction: column;
    gap: 10px;
  }

  .action-group {
    width: 100%;
    box-sizing: border-box;
  }

  .action-group-buttons {
    flex-direction: column;
    align-items: stretch;
  }

  .action-group-buttons :deep(.el-button) {
    width: 100%;
    min-height: var(--app-touch);
  }

  .card-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .card-header :deep(.el-button) {
    width: 100%;
    min-height: var(--app-touch);
  }

  .expand-toggle {
    min-height: var(--app-touch);
  }

  .dependency-line {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>