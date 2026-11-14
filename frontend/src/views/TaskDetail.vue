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
import { getActivity } from '../api/activities'
import { ApiError } from '../api/client'
import { checkin, myCheckins } from '../api/checkin'
import { getTask, getTaskSubmissions, precheckSubmission, submitTask, updateProgress, verifyTask } from '../api/tasks'
import { listResources } from '../api/resources'
import AgentDock from '../components/ai/AgentDock.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import SopSteps from '../components/task/SopSteps.vue'
import StatusTag from '../components/task/StatusTag.vue'
import SubTaskTree from '../components/task/SubTaskTree.vue'
import TaskContentSections from '../components/task/TaskContentSections.vue'
import TaskGraph from '../components/task/TaskGraph.vue'
import {
  applicationStatusMeta,
  applyBlockReason,
  formatDeadline,
  isApprovedMember,
  memberStatusMeta,
  quotaText
} from '../components/task/TaskCard.vue'
import { useUserStore } from '../stores/user'
import type {
  ApplicationStatus,
  MemberStatus,
  PrecheckResult,
  PrecheckStatus,
  ResourceItem,
  SubmissionItem,
  TaskBrief,
  TaskDetail,
  TaskGraph as TaskGraphModel,
  TaskMember
} from '../types/models'

const props = defineProps<{ id: string }>()

const router = useRouter()
const userStore = useUserStore()

/** 非「已通过审核的成员」时的统一提示（验收 ⑨） */
const NOT_MEMBER_HINT = '仅已通过审核的成员可操作'
/** 任务已取消时的统一提示（后端对已取消任务的成员操作返回 4090） */
const CANCELLED_HINT = '任务已取消，无法继续操作'


const task = ref<TaskDetail | null>(null)

const loading = ref(false)
const error = ref('')
const checkinStateLoading = ref(false)
const checkedIn = ref(false)
const checkinLoading = ref(false)
const applyLoading = ref(false)
const withdrawLoading = ref(false)
const submitLoading = ref(false)
const submitDialogVisible = ref(false)
const submitContent = ref('')
const submitResourceUrl = ref('')
/** 当前任务可见的成果版本（管理者看全部，普通成员只看自己） */
const submissions = ref<SubmissionItem[]>([])
const submissionsLoading = ref(false)
/** 成果版本加载失败：与「确实没有版本」区分，失败时禁止盲批 */
const submissionsError = ref('')
/** 本次会话内已运行过的预审结果（key = submission_id） */
const precheckResults = ref<Record<number, PrecheckResult>>({})
const precheckLoading = ref<number | null>(null)
const verifyLoading = ref<number | null>(null)
/** 任务相关资料（同活动 + 同组织往期，权限内） */
const relatedResources = ref<ResourceItem[]>([])
const resourcesLoading = ref(false)
const progressVisible = ref(false)
const progressText = ref('')
const progressLoading = ref(false)

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

/** 本人成果版本（历史 + 最新） */
const mySubmissions = computed<SubmissionItem[]>(() =>
  submissions.value.filter((item) => item.user_id === currentUserId.value)
)

/** 每位成员的最新成果版本（发布者同页验收使用） */
const latestByMember = computed<Map<number, SubmissionItem>>(() => {
  const map = new Map<number, SubmissionItem>()
  for (const item of submissions.value) {
    if (!item.latest) continue
    map.set(item.user_id, item)
  }
  return map
})

/** 待验收成员 + 其最新成果版本（无版本时保持 null，兼容历史提交） */
const pendingVerifications = computed<
  Array<{ member: TaskMember; submission: SubmissionItem | null }>
>(() =>
  memberRows.value
    .filter((member) => member.status === 'submitted')
    .map((member) => ({ member, submission: latestByMember.value.get(member.user_id) ?? null }))
)

function precheckMeta(status: PrecheckStatus): { type: '' | 'success' | 'warning' | 'danger' | 'info'; text: string } {
  if (status === 'pass') return { type: 'success', text: '通过' }
  if (status === 'fail') return { type: 'danger', text: '不通过' }
  if (status === 'warn') return { type: 'warning', text: '需确认' }
  return { type: 'info', text: '待补充' }
}

function verdictText(verdict: 'pass' | 'fail' | 'unknown'): string {
  if (verdict === 'pass') return '规则预审未发现冲突'
  if (verdict === 'fail') return '规则预审发现不通过项'
  return '规则预审有信息缺失'
}

function submissionPrecheck(submission: SubmissionItem): PrecheckResult | null {
  return precheckResults.value[submission.id] ?? null
}

/** 外链只允许 http/https，避免 javascript/data 链接被直接打开 */
function isHttpUrl(value: string | null): boolean {
  return Boolean(value && /^https?:\/\//i.test(value))
}

/** 信息卡的「我的报名 / 我的执行」摘要 */
const myApplyLabel = computed<string>(() =>
  applicationStatus.value ? `报名${applicationMeta.value.text}` : '未报名'
)
const myExecLabel = computed<string>(() =>
  myMemberStatus.value ? memberStatusMeta(myMemberStatus.value).text : '非任务成员'
)

/** 与发布页共享的内容区块（`C-FE-PUBLISH-CONTENT@1`） */
const contentModel = computed(() => ({
  description: task.value?.description ?? null,
  start_time: task.value?.start_time ?? null,
  deadline: task.value?.deadline ?? null,
  location: task.value?.location ?? null,
  quota: task.value?.quota ?? null
}))
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
    activity_id: task.value.activity_id,
    depends_on_ids: task.value.depends_on_ids
  }
})

/** 多前置（`C-TASK-GRAPH@1`）：全部完成才解锁报名 */
const hiddenDependencyCount = computed<number>(() => {
  if (!task.value) return 0
  const total = task.value.depends_on_ids?.length ?? 0
  const visible = task.value.dependencies?.length ?? 0
  return Math.max(0, total - visible)
})
const dependenciesDone = computed<boolean>(() => {
  if (!task.value || hiddenDependencyCount.value > 0) return false
  return (task.value.dependencies ?? []).every((item) => item.status === 'verified')
})
/** 子任务树沿用「首个前置」展示；完整的前置 / 后继由局部图谱承担 */
const primaryPredecessor = computed<TaskBrief | null>(
  () => task.value?.dependencies[0] ?? null
)

/** 活动全景按需加载（默认只显示当前任务局部图） */
const showActivityGraph = ref(false)
const activityGraph = ref<TaskGraphModel | null>(null)
const activityGraphLoading = ref(false)
const activityGraphError = ref('')

async function toggleActivityGraph(): Promise<void> {
  const activityId = task.value?.activity_id
  if (activityId === null || activityId === undefined) return
  if (showActivityGraph.value) {
    showActivityGraph.value = false
    return
  }
  if (activityGraph.value) {
    showActivityGraph.value = true
    return
  }
  activityGraphLoading.value = true
  activityGraphError.value = ''
  try {
    const detail = await getActivity(activityId)
    activityGraph.value = detail.graph
    showActivityGraph.value = true
  } catch (err) {
    activityGraphError.value = errorMessage(err)
  } finally {
    activityGraphLoading.value = false
  }
}

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

/** 成果版本与相关资料属于辅助信息：失败不阻塞任务详情主流程 */
async function loadSubmissions(): Promise<void> {
  if (!task.value) {
    submissions.value = []
    submissionsError.value = ''
    return
  }
  submissionsLoading.value = true
  submissionsError.value = ''
  try {
    submissions.value = (await getTaskSubmissions(task.value.id)).items
  } catch (err) {
    submissions.value = []
    submissionsError.value = errorMessage(err)
  } finally {
    submissionsLoading.value = false
  }
}

async function loadRelatedResources(): Promise<void> {
  if (!task.value) {
    relatedResources.value = []
    return
  }
  resourcesLoading.value = true
  try {
    relatedResources.value = (await listResources({ related_task_id: task.value.id, limit: 5 })).items
  } catch {
    relatedResources.value = []
  } finally {
    resourcesLoading.value = false
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
    // 切换任务时丢弃上一个任务的活动全景缓存
    activityGraph.value = null
    showActivityGraph.value = false
    activityGraphError.value = ''
    await loadCheckinState()
    await loadRejectReason()
    // 成果版本与资料是辅助区块，任一失败都不影响任务详情
    await Promise.allSettled([loadSubmissions(), loadRelatedResources()])
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

/** 从大厅或「我的任务」进入时按来源返回，直接打开时回大厅（站内路径白名单） */
function backToHall(): void {
  const back = window.history.state?.back
  if (isInternalBack(back)) {
    router.back()
    return
  }
  void router.push({ name: 'hall' })
}

function isInternalBack(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.startsWith('/') &&
    !value.startsWith('//') &&
    !value.startsWith('/login') &&
    !value.startsWith('/register') &&
    !value.startsWith('/reset-password')
  )
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

function openSubmitDialog(): void {
  if (!task.value) return
  if (!canSubmit.value) {
    ElMessage.warning(submitHint.value || '当前不可提交')
    return
  }
  submitContent.value = ''
  submitResourceUrl.value = ''
  submitDialogVisible.value = true
}

async function confirmSubmit(): Promise<void> {
  if (!task.value || submitLoading.value) return
  submitLoading.value = true
  try {
    await submitTask(task.value.id, {
      content: submitContent.value.trim() || null,
      resource_url: submitResourceUrl.value.trim() || null
    })
    submitDialogVisible.value = false
    ElMessage.success('已提交，等待发布者验收')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    submitLoading.value = false
  }
}

/** 对某个成果版本运行规则预审 + AI 建议（只写预审记录，不改变业务状态） */
async function handlePrecheck(submission: SubmissionItem): Promise<void> {
  if (!task.value || precheckLoading.value !== null) return
  precheckLoading.value = submission.id
  try {
    const result = await precheckSubmission(task.value.id, submission.id)
    precheckResults.value = { ...precheckResults.value, [submission.id]: result }
    ElMessage.success('预审完成；预审不等于验收，仍需负责人确认')
    await loadSubmissions()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    precheckLoading.value = null
  }
}

/** 发布者同页验收：通过 / 退回都绑定当前展示的成果版本 */
async function handleVerifyMember(
  member: TaskMember,
  submission: SubmissionItem | null,
  pass: boolean
): Promise<void> {
  if (!task.value || verifyLoading.value !== null) return
  if (submissionsLoading.value) {
    ElMessage.warning('成果版本正在加载，请稍候再验收')
    return
  }
  if (submissionsError.value) {
    ElMessage.warning('成果版本未能加载，请刷新后再验收，避免在看不到成果时盲批')
    return
  }
  let reason: string | undefined
  try {
    if (pass) {
      await ElMessageBox.confirm(
        `确认通过「${member.user_name || `用户 #${member.user_id}`}」的成果版本？通过后按任务奖励结算积分。`,
        '验收通过',
        { type: 'success', confirmButtonText: '确认通过', cancelButtonText: '再看看' }
      )
    } else {
      const result = await ElMessageBox.prompt('请说明退回原因，成员会收到通知并可重新提交。', '退回收成', {
        type: 'warning',
        confirmButtonText: '确认退回',
        cancelButtonText: '取消',
        inputValidator: (value: string) => (value.trim() ? true : '请填写退回原因')
      })
      reason = result.value.trim()
    }
  } catch {
    return
  }

  verifyLoading.value = member.user_id
  try {
    const result = await verifyTask(task.value.id, pass, reason, member.user_id, submission?.id)
    if (pass) {
      ElMessage.success(
        result.credit_delta > 0 ? `验收通过，成员获得 ${result.credit_delta} 积分` : '验收通过'
      )
    } else {
      ElMessage.success('已退回，成员会收到修改通知')
    }
    await load()
  } catch (err) {
    if (err instanceof ApiError && err.code === 4090) {
      ElMessage.warning('该成果版本已不是最新版本，请刷新后再验收')
      await loadSubmissions()
      return
    }
    ElMessage.error(errorMessage(err))
  } finally {
    verifyLoading.value = null
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
                  @click="openSubmitDialog"
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

        <TaskContentSections :model="contentModel" />

        <el-descriptions :column="infoColumns" border size="small" class="info-table">
          <el-descriptions-item label="发布者">{{ task.publisher_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="首批成员">{{ task.assignee_name || '暂无成员' }}</el-descriptions-item>
          <el-descriptions-item label="名额进度">
            已通过 {{ task.approved_count }}/{{ task.quota === null ? '不限' : task.quota }}
          </el-descriptions-item>
          <el-descriptions-item label="待审批报名">{{ task.applied_count }} 人</el-descriptions-item>
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

      <el-card shadow="never" class="app-section-card review-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">成果与验收</span>
            <span class="header-hint">提交版本、规则预审与人工验收同页完成；预审不等于验收</span>
          </div>
        </template>

        <!-- 本人成果版本：普通成员只看自己的版本 -->
        <section
          v-if="isApproved && mySubmissions.length > 0"
          class="review-block"
          aria-labelledby="my-submissions-heading"
        >
          <h3 id="my-submissions-heading" class="review-subtitle">我的成果版本</h3>
          <ul class="submission-list">
            <li v-for="item in mySubmissions" :key="item.id" class="submission-item">
              <div class="submission-head">
                <span class="submission-version">v{{ item.version }}</span>
                <el-tag v-if="item.latest" size="small" type="success" effect="plain">最新</el-tag>
                <span class="submission-time">{{ memberTime(item.created_at) }}</span>
                <el-tag
                  v-if="item.precheck"
                  :type="precheckMeta(item.precheck.verdict).type"
                  size="small"
                  effect="plain"
                >
                  {{ verdictText(item.precheck.verdict) }}
                </el-tag>
                <el-tag v-if="item.precheck?.stale" size="small" type="warning" effect="plain">
                  要求已变化，预审过期
                </el-tag>
              </div>
              <p v-if="item.content" class="submission-text">{{ item.content }}</p>
              <a
                v-if="isHttpUrl(item.resource_url)"
                class="submission-link"
                :href="item.resource_url || undefined"
                target="_blank"
                rel="noopener noreferrer"
              >
                查看成果链接
              </a>
              <p v-if="item.precheck?.summary" class="precheck-summary">{{ item.precheck.summary }}</p>
              <p v-if="item.precheck?.ai_error" class="precheck-error">{{ item.precheck.ai_error }}</p>
              <div class="submission-actions">
                <el-button
                  size="small"
                  :loading="precheckLoading === item.id"
                  @click="handlePrecheck(item)"
                >
                  运行预审
                </el-button>
              </div>
              <div v-if="submissionPrecheck(item)" class="precheck-detail">
                <p class="precheck-verdict">规则结论：{{ verdictText(submissionPrecheck(item)!.verdict) }}</p>
                <ul class="precheck-list">
                  <li v-for="check in submissionPrecheck(item)!.checks" :key="check.key" class="precheck-row">
                    <el-tag :type="precheckMeta(check.status).type" size="small" effect="plain">
                      {{ precheckMeta(check.status).text }}
                    </el-tag>
                    <span class="precheck-label">{{ check.label }}</span>
                    <span class="precheck-message">{{ check.message }}</span>
                    <span v-if="check.evidence" class="precheck-evidence">证据：{{ check.evidence }}</span>
                  </li>
                </ul>
                <p v-if="submissionPrecheck(item)!.mock" class="precheck-mock">
                  mock 预审：本次未调用真实模型，规则结论仍有效
                </p>
                <ul v-if="submissionPrecheck(item)!.ai_suggestions.length > 0" class="precheck-list">
                  <li
                    v-for="suggestion in submissionPrecheck(item)!.ai_suggestions"
                    :key="suggestion.key"
                    class="precheck-row"
                  >
                    <span class="precheck-label">AI 建议</span>
                    <span class="precheck-message">{{ suggestion.message }}</span>
                  </li>
                </ul>
              </div>
            </li>
          </ul>
        </section>

        <!-- 发布者同页验收：始终绑定当前展示的最新成果版本 -->
        <section v-if="isPublisher" class="review-block" aria-labelledby="pending-review-heading">
          <h3 id="pending-review-heading" class="review-subtitle">
            待验收（{{ pendingVerifications.length }}）
          </h3>
          <el-alert
            v-if="submissionsError"
            type="error"
            :title="`成果版本未能加载：${submissionsError}`"
            description="为避免在看不到成果时盲批，验收按钮已禁用；请刷新后重试。"
            :closable="false"
            show-icon
            class="inline-alert"
          />
          <p v-if="pendingVerifications.length === 0" class="review-empty">当前没有待验收成员。</p>
          <ul v-else class="submission-list">
            <li
              v-for="{ member, submission } in pendingVerifications"
              :key="member.user_id"
              class="submission-item review-pending"
            >
              <div class="submission-head">
                <span class="submission-member">{{ member.user_name || `用户 #${member.user_id}` }}</span>
                <span v-if="submission" class="submission-version">v{{ submission.version }}</span>
                <span class="submission-time">{{ memberTime(member.submitted_at) }}</span>
              </div>
              <template v-if="submission">
                <p v-if="submission.content" class="submission-text">{{ submission.content }}</p>
                <a
                  v-if="isHttpUrl(submission.resource_url)"
                  class="submission-link"
                  :href="submission.resource_url || undefined"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  查看成果链接
                </a>
                <p v-if="submission.precheck?.summary" class="precheck-summary">
                  {{ verdictText(submission.precheck.verdict) }}：{{ submission.precheck.summary }}
                </p>
                <p v-if="submission.precheck?.stale" class="precheck-warning">
                  任务要求已变化，该预审已过期，请重新运行或人工核对。
                </p>
                <p v-if="submission.precheck?.ai_error" class="precheck-error">
                  {{ submission.precheck.ai_error }}
                </p>
              </template>
              <p v-else-if="submissionsLoading" class="review-empty">正在加载成果版本…</p>
              <p v-else-if="!submissionsError" class="review-empty">历史提交没有成果版本；可按现有成员状态人工验收。</p>
              <div class="submission-actions">
                <el-button
                  v-if="submission"
                  size="small"
                  :loading="precheckLoading === submission.id"
                  @click="handlePrecheck(submission)"
                >
                  运行预审
                </el-button>
                <el-button
                  type="success"
                  size="small"
                  :disabled="!!submissionsError || submissionsLoading"
                  :loading="verifyLoading === member.user_id"
                  @click="handleVerifyMember(member, submission, true)"
                >
                  通过
                </el-button>
                <el-button
                  type="danger"
                  plain
                  size="small"
                  :disabled="!!submissionsError || submissionsLoading"
                  :loading="verifyLoading === member.user_id"
                  @click="handleVerifyMember(member, submission, false)"
                >
                  退回
                </el-button>
              </div>
            </li>
          </ul>
        </section>

        <!-- 任务相关资料：同活动 + 同组织往期，后端权限过滤 -->
        <section class="review-block" aria-labelledby="related-resources-heading">
          <h3 id="related-resources-heading" class="review-subtitle">相关资料</h3>
          <p v-if="resourcesLoading" class="review-empty">正在加载资料…</p>
          <p v-else-if="relatedResources.length === 0" class="review-empty">
            当前没有可引用的资料；往届资料只作结构参考，不替代本届要求。
          </p>
          <ul v-else class="resource-list">
            <li v-for="resource in relatedResources" :key="resource.id" class="resource-item">
              <span class="resource-title">{{ resource.title }}</span>
              <span class="resource-meta">
                v{{ resource.version }} · {{ resource.activity_title || '未绑定活动' }}
              </span>
              <a
                v-if="isHttpUrl(resource.url)"
                class="resource-link"
                :href="resource.url"
                target="_blank"
                rel="noopener noreferrer"
              >
                打开原始链接
              </a>
            </li>
          </ul>
        </section>
      </el-card>

      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">前置依赖（{{ task.depends_on_ids.length }}）</span>
            <span class="header-hint">
              <template v-if="task.depends_on_ids.length === 0">无前置依赖，可独立推进</template>
              <template v-else-if="hiddenDependencyCount > 0">
                其中 {{ hiddenDependencyCount }} 项前置当前不可见；报名状态以按钮提示为准
              </template>
              <template v-else>
                {{ dependenciesDone ? '全部前置已完成' : '仍有前置未完成，当前任务暂不可报名' }}
              </template>
            </span>
          </div>
        </template>
        <div v-if="task.depends_on_ids.length === 0" class="dependency-empty">
          当前任务未设置前置任务，不依赖其他任务。
        </div>
        <div v-else-if="hiddenDependencyCount > 0" class="dependency-empty">
          有 {{ hiddenDependencyCount }} 个前置任务当前不可见；这不改变「全部前置完成才可报名」的规则。
        </div>
        <ul v-if="task.dependencies.length > 0" class="dependency-list">
          <li v-for="dep in task.dependencies" :key="dep.id" class="dependency-item">
            <StatusTag :status="dep.status" size="small" />
            <el-link type="primary" :underline="false" @click="goDetail(dep.id)">
              {{ dep.title }} #{{ dep.id }}
            </el-link>
            <span class="dependency-arrow" aria-hidden="true">→</span>
            <span>当前任务：{{ task.title }}</span>
          </li>
        </ul>

        <!-- 局部图：当前任务 + 直接前置 + 直接后继（与活动详情共用同一组件） -->
        <TaskGraph
          :nodes="task.graph.nodes"
          :edges="task.graph.edges"
          mode="local"
          :current-id="task.id"
        />

        <div v-if="task.activity_id !== null" class="graph-actions">
          <el-button size="small" :loading="activityGraphLoading" @click="toggleActivityGraph">
            {{ showActivityGraph ? '收起同活动全景' : '查看同活动全景' }}
          </el-button>
          <span v-if="activityGraphError" class="dependency-missing">{{ activityGraphError }}</span>
        </div>
        <TaskGraph
          v-if="showActivityGraph && activityGraph"
          :nodes="activityGraph.nodes"
          :edges="activityGraph.edges"
          mode="full"
          :current-id="task.id"
        />
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
          :predecessors="task ? task.dependencies : []"
          :predecessor="primaryPredecessor"
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

      <AgentDock :context-label="`任务：${task.title}`" />
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

    <el-dialog
      v-model="submitDialogVisible"
      title="提交完成"
      width="min(560px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="成果说明">
          <el-input
            v-model="submitContent"
            type="textarea"
            :rows="5"
            maxlength="5000"
            show-word-limit
            placeholder="例如：推文终稿已发布，活动时间为 2026-12-25 19:00，地点为礼堂。"
          />
        </el-form-item>
        <el-form-item label="成果链接">
          <el-input
            v-model="submitResourceUrl"
            maxlength="1000"
            placeholder="可选，例如 https://example.com/final-post"
          />
        </el-form-item>
        <el-alert
          type="info"
          :closable="false"
          title="每次提交会保存一个成果版本；退回后重新提交会生成新版本，旧版本不能用于验收。"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="submitLoading" @click="submitDialogVisible = false">取消</el-button>
        <el-button type="success" :loading="submitLoading" @click="confirmSubmit">确认提交</el-button>
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

.dependency-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dependency-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  font-size: 14px;
  color: var(--app-text);
  word-break: break-word;
}

.graph-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
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

.review-block + .review-block {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--app-border);
}

.review-subtitle {
  margin: 0 0 10px;
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  color: var(--app-text);
}

.review-empty {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-muted);
  line-height: 1.6;
}

.submission-list,
.resource-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.submission-item {
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.submission-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.submission-version {
  font-size: var(--app-font-aux-lg);
  font-weight: 700;
  color: var(--app-text);
}

.submission-member {
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.submission-time,
.resource-meta {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.submission-text {
  margin: 8px 0 0;
  font-size: var(--app-font-body);
  line-height: 1.7;
  color: var(--app-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.submission-link,
.resource-link {
  display: inline-block;
  margin-top: 6px;
  font-size: var(--app-font-aux-lg);
  color: var(--app-primary);
}

.submission-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
}

.precheck-summary,
.precheck-verdict {
  margin: 8px 0 0;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-secondary);
  line-height: 1.6;
  word-break: break-word;
}

.precheck-warning {
  margin: 6px 0 0;
  font-size: var(--app-font-aux-lg);
  color: var(--el-color-warning);
  word-break: break-word;
}

.precheck-error {
  margin: 6px 0 0;
  font-size: var(--app-font-aux-lg);
  color: var(--el-color-danger);
  word-break: break-word;
}

.precheck-mock {
  margin: 8px 0 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.precheck-detail {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed var(--app-border);
}

.precheck-list {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.precheck-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-secondary);
  line-height: 1.6;
}

.precheck-label {
  font-weight: 600;
  color: var(--app-text);
}

.precheck-message,
.precheck-evidence {
  word-break: break-word;
}

.precheck-evidence {
  color: var(--app-text-muted);
}

.resource-item {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.resource-title {
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
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

  .submission-actions :deep(.el-button) {
    flex: 1 1 100%;
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