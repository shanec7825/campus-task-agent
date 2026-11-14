<script setup lang="ts">
/**
 * 发布者后台（计划 T6 / R3-AC5 / R3-AC8 / R5）。
 *
 * - 任务列表：桌面复用共用任务表格（`C-ADMIN-TABLE-REUSE@1`，含活动筛选与所属活动列），
 *   手机保留事务卡片双视图，字段与操作一一对应；
 * - 指派弹窗：候选来自任务中已出现的用户，后端无用户列表接口时允许手输用户 ID；
 * - 验收：仅 `publisher_id === 当前用户` 且状态为 `submitted` 时可见，先选择通过/驳回（驳回必填原因）；
 * - 催办规则：`ReminderRuleForm` 校验通过后通过 `PATCH /api/tasks/{id}` 保存。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { listActivities } from '../api/activities'
import { decideApplication, listApplications } from '../api/applications'
import { ApiError } from '../api/client'
import { archiveSubmission } from '../api/orgResources'
import { assignTask, getTaskChangeImpact, getTaskSubmissions, listTasks, patchTask, verifyTask } from '../api/tasks'
import { getTask } from '../api/tasks'
import AssignDialog, { type AssignCandidate } from '../components/admin/AssignDialog.vue'
import ReminderRuleForm, { DEFAULT_REMINDER_RULE } from '../components/admin/ReminderRuleForm.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import ActivityTaskTable from '../components/task/ActivityTaskTable.vue'
import StatusTag from '../components/task/StatusTag.vue'
import { applicationStatusMeta, formatDeadline, memberStatusMeta } from '../components/task/TaskCard.vue'
import { useUserStore } from '../stores/user'
import {
  effectiveSubmissionFileExts,
  parseSubmissionAcceptance,
  SUBMISSION_FILE_EXTS,
  SUBMISSION_MODE_LABELS,
  SUBMISSION_MODES,
  submissionAcceptanceSummary,
  submissionFileLabel
} from '../types/models'
import type {
  Activity,
  ActivitySubtaskNode,
  ActivityTaskNode,
  ApplicationItem,
  ReminderRule,
  TaskChangeImpact,
  TaskItem,
  TaskMember
} from '../types/models'

const router = useRouter()
const userStore = useUserStore()

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')

/** 活动筛选：`all` / `standalone`（独立任务）/ 活动 id；只过滤已加载任务，不触发请求 */
const activityFilter = ref<'all' | 'standalone' | number>('all')
const activities = ref<Activity[]>([])
const activitiesError = ref('')
/** 共用表格的展开状态由本视图持有 */
const expanded = ref<number[]>([])

const assignVisible = ref(false)
const assignTarget = ref<TaskItem | null>(null)
const assignLoading = ref(false)

const verifyVisible = ref(false)
const verifyTarget = ref<TaskItem | null>(null)
const verifyChoice = ref<'pass' | 'reject'>('pass')
const verifyReason = ref('')
const verifyLoading = ref(false)
/** 本次验收的目标成员（`user_id`）：成员级验收必须逐人指定 */
const verifyMemberId = ref<number | undefined>(undefined)
/** 成员最新成果的预审是否已过期（按 `user_id`）；与任务详情页「通过」禁用口径一致 */
const verifyStaleUsers = ref<number[]>([])
const verifyStaleLoading = ref(false)
const verifyStaleError = ref('')
/** 只接受最后一次预审状态请求的响应，避免快速切换任务时旧响应覆盖新值 */
let verifyStaleSeq = 0
const verifyStaleCurrent = computed<boolean>(
  () => verifyMemberId.value !== undefined && verifyStaleUsers.value.includes(verifyMemberId.value)
)

/** 已验收成果归档（`C-ARCHIVE@1`）：仅在验收通过后打开，默认不允许学生 AI 检索 */
const archiveVisible = ref(false)
const archiveSubmissionId = ref<number | null>(null)
const archiveTargetLabel = ref('')
const archiveOrgId = ref<number | null>(null)
const archiveTitle = ref('')
const archiveLoading = ref(false)
/** 本次会话已归档的成果 id：成功后禁用重复归档（重复提交会在服务端生成新资料行） */
const archiveDoneIds = ref<number[]>([])
/** 本次会话已归档的成员（`taskId:memberId`）：持久入口按成员禁用，避免重复归档 */
const archivedMemberKeys = ref<string[]>([])
/** 当前归档弹窗对应的任务 / 成员，用于成功后回写成员禁用状态 */
const archiveTaskId = ref<number | null>(null)
const archiveMemberId = ref<number | null>(null)

const manageableOrgs = computed(() =>
  userStore.orgs.filter(
    (org) => org.status === 'active' && (org.role === 'admin' || org.role === 'collaborator')
  )
)

const archiveDone = computed<boolean>(
  () =>
    archiveSubmissionId.value !== null &&
    archiveDoneIds.value.includes(archiveSubmissionId.value)
)

/** 截止时间编辑（R4：改期后可继续提交并按新时间提醒） */
const deadlineVisible = ref(false)
const deadlineTarget = ref<TaskItem | null>(null)
const deadlineValue = ref<string | null>(null)
const deadlineLoading = ref(false)
/** 改期影响预览（`C-TASK-CHANGE-API@1`）：只读，确认后才走既有 PATCH */
const changeImpact = ref<TaskChangeImpact | null>(null)
const changeImpactLoading = ref(false)
const changeImpactError = ref('')
/** 只接受最后一次预览请求的响应，避免快速改期时旧响应覆盖新值 */
let changeImpactSeq = 0
const impactMemberNames = computed<string>(() =>
  (changeImpact.value?.affected_members ?? []).map((member) => member.name).join('、')
)
const impactDownstreamTitles = computed<string>(() =>
  (changeImpact.value?.downstream_tasks ?? []).map((task) => task.title).join('、')
)
/** 取消任务进行中的任务 id（防重复点击） */
const cancelLoadingId = ref<number | null>(null)

const ruleVisible = ref(false)
const ruleTarget = ref<TaskItem | null>(null)
const ruleDraft = ref<ReminderRule>({ ...DEFAULT_REMINDER_RULE })
const ruleLoading = ref(false)

/** 成果要求编辑（`C-SUBMISSION-POLICY@1`，R2-01 编辑入口） */
const acceptanceVisible = ref(false)
const acceptanceTarget = ref<TaskItem | null>(null)
const acceptanceWasConfigured = ref(false)
const acceptanceLoading = ref(false)
const acceptanceDraft = ref<AcceptanceDraft>({
  modes: [...SUBMISSION_MODES],
  allowed_exts: [...SUBMISSION_FILE_EXTS],
  ai_precheck: false
})
const acceptanceFileMode = computed<boolean>(() => acceptanceDraft.value.modes.includes('file'))

/** 报名审核弹窗（R16-AC7/AC8） */
const auditVisible = ref(false)
const auditTarget = ref<TaskItem | null>(null)
const applications = ref<ApplicationItem[]>([])
const appsLoading = ref(false)
const appsError = ref('')
const decideLoadingId = ref<number | null>(null)
/** 拒绝原因（按报名 id 记录；拒绝时必填） */
const rejectReasons = ref<Record<number, string>>({})

/** 弹窗内仅展示待审批报名（A3 返回全部状态，由前端过滤） */
const pendingApplications = computed<ApplicationItem[]>(() =>
  applications.value.filter((item) => item.status === 'pending')
)

const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)
const isPublisher = computed<boolean>(() => userStore.isPublisher)

/** 活动筛选只作用于已加载的 `tasks`，不改变权限判定与写操作 */
const filteredTasks = computed<TaskItem[]>(() => {
  const filter = activityFilter.value
  if (filter === 'all') return tasks.value
  if (filter === 'standalone') return tasks.value.filter((task) => task.activity_id === null)
  return tasks.value.filter((task) => task.activity_id === filter)
})

/** 后台任务行：保留 `TaskItem` 写操作字段，同时满足共用表格的只读节点契约 */
type AdminTableTask = TaskItem & ActivityTaskNode
type AdminSubtaskRow = TaskItem & ActivitySubtaskNode

/** 成果要求草稿：`modes` 用 `string[]` 兼容 el-checkbox-group 的 v-model 类型 */
interface AcceptanceDraft {
  modes: string[]
  allowed_exts: string[]
  ai_precheck: boolean
}

function assigneeList(task: TaskItem): ActivityTaskNode['assignees'] {
  return (task.members ?? []).map((member) => ({
    user_id: member.user_id,
    name: member.user_name
  }))
}

/** 扁平列表中的子任务按 `parent_id` 归入父任务（表格内缩进展开）；父任务不在当前筛选集合时保持顶层 */
const tableTasks = computed<AdminTableTask[]>(() => {
  const ids = new Set(filteredTasks.value.map((task) => task.id))
  const childrenByParent = new Map<number, AdminSubtaskRow[]>()
  for (const task of filteredTasks.value) {
    if (task.parent_id === null || !ids.has(task.parent_id)) continue
    const siblings = childrenByParent.get(task.parent_id) ?? []
    siblings.push({ ...task, assignees: assigneeList(task) })
    childrenByParent.set(task.parent_id, siblings)
  }
  return filteredTasks.value
    .filter((task) => task.parent_id === null || !ids.has(task.parent_id))
    .map((task) => {
      const children = childrenByParent.get(task.id) ?? []
      return {
        ...task,
        assignees: assigneeList(task),
        children,
        completed_children: children.filter((child) => child.status === 'verified').length,
        total_children: children.length
      }
    })
})

/** 所属活动标题映射；缺失的活动由表格回退显示 `#id` */
const activityTitles = computed<Record<number, string>>(() => {
  const titles: Record<number, string> = {}
  for (const activity of activities.value) titles[activity.id] = activity.title
  return titles
})

/** 指派候选：任务里出现过的负责人 / 发布者（去重，排除自己） */
const candidates = computed<AssignCandidate[]>(() => {
  const map = new Map<number, string>()
  for (const task of tasks.value) {
    if (task.assignee_id !== null) {
      map.set(task.assignee_id, task.assignee_name || `用户 #${task.assignee_id}`)
    }
    map.set(task.publisher_id, task.publisher_name || `用户 #${task.publisher_id}`)
  }
  if (currentUserId.value !== null) map.delete(currentUserId.value)
  return [...map.entries()]
    .map(([id, name]) => ({ id, name }))
    .sort((left, right) => left.id - right.id)
})

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    if (err.code === 4030) return '当前账号没有该操作的权限'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function load(): Promise<void> {
  if (!isPublisher.value) {
    tasks.value = []
    return
  }
  loading.value = true
  error.value = ''
  try {
    const result = await listTasks({ scope: 'mine', include_sub: true })
    const items = result?.items ?? []
    tasks.value = currentUserId.value === null
      ? items
      : items.filter((task) => task.publisher_id === currentUserId.value)
  } catch (err) {
    tasks.value = []
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function goDetail(id: number): void {
  void router.push({ name: 'detail', params: { id } })
}

/** 活动筛选选项：沿用 `scope=all`（服务端已叠可见性）；失败只提示，不阻塞任务列表 */
async function loadActivities(): Promise<void> {
  try {
    const result = await listActivities({ scope: 'all' })
    activities.value = result?.items ?? []
    activitiesError.value = ''
  } catch (err) {
    activities.value = []
    activitiesError.value = errorMessage(err)
  }
}

function toggleExpanded(id: number): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

/** 插槽回传只读节点；表格行由 `TaskItem` 展开而来，可安全还原为原始数据 */
function asRow(task: ActivityTaskNode | ActivitySubtaskNode): TaskItem {
  return task as unknown as TaskItem
}

function goPublish(): void {
  void router.push({ name: 'publish' })
}

/** 指派入口：仅发布者、且任务处于 published / claimed */
function canAssign(task: TaskItem): boolean {
  return task.publisher_id === currentUserId.value && ['published', 'claimed'].includes(task.status)
}

/** 待验收成员（成员级：只有 `submitted` 的成员可被验收 / 退回） */
function submittedMembers(task: TaskItem): TaskMember[] {
  return (task.members ?? []).filter((member) => member.status === 'submitted')
}

/** 验收入口：仅发布者，任务未处于终态，且至少一名成员处于 `submitted`（成员级验收） */
function canVerify(task: TaskItem): boolean {
  return (
    task.publisher_id === currentUserId.value &&
    task.status !== 'cancelled' &&
    task.status !== 'verified' &&
    submittedMembers(task).length > 0
  )
}

/** 改期入口：仅发布者，且任务未被取消 */
function canEditDeadline(task: TaskItem): boolean {
  return task.publisher_id === currentUserId.value && task.status !== 'cancelled'
}

/** 取消入口：仅发布者，且任务未取消 / 未完成 */
function canCancel(task: TaskItem): boolean {
  return (
    task.publisher_id === currentUserId.value &&
    task.status !== 'cancelled' &&
    task.status !== 'verified'
  )
}

function openAssign(task: TaskItem): void {
  assignTarget.value = task
  assignVisible.value = true
}

async function confirmAssign(userId: number): Promise<void> {
  if (!assignTarget.value) return
  assignLoading.value = true
  try {
    await assignTask(assignTarget.value.id, userId)
    ElMessage.success('指派成功')
    assignVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    assignLoading.value = false
  }
}

function openVerify(task: TaskItem): void {
  verifyTarget.value = task
  verifyChoice.value = 'pass'
  verifyReason.value = ''
  // 只有一名待验收成员时默认选中，避免重复点击选择
  const submitted = submittedMembers(task)
  verifyMemberId.value = submitted.length === 1 ? submitted[0].user_id : undefined
  verifyVisible.value = true
  void loadVerifyStale(task)
}

/** 读取各成员最新成果的预审过期状态；失败不阻塞验收，后端仍会在通过时返回 4090 */
async function loadVerifyStale(task: TaskItem): Promise<void> {
  const seq = ++verifyStaleSeq
  verifyStaleUsers.value = []
  verifyStaleError.value = ''
  verifyStaleLoading.value = true
  try {
    const list = await getTaskSubmissions(task.id)
    if (seq !== verifyStaleSeq || verifyTarget.value?.id !== task.id) return
    verifyStaleUsers.value = list.items
      .filter((item) => item.latest && item.precheck?.stale)
      .map((item) => item.user_id)
  } catch {
    if (seq !== verifyStaleSeq) return
    verifyStaleUsers.value = []
    verifyStaleError.value = '预审状态未加载，通过时仍会由服务端校验'
  } finally {
    if (seq === verifyStaleSeq) verifyStaleLoading.value = false
  }
}

async function submitVerify(): Promise<void> {
  const target = verifyTarget.value
  if (!target) return
  if (verifyMemberId.value === undefined) {
    ElMessage.warning('请选择要验收的成员')
    return
  }
  const acceptedMemberId = verifyMemberId.value
  const targetTitle = target.title
  if (verifyChoice.value === 'pass' && verifyStaleCurrent.value) {
    ElMessage.warning('该成员预审已过期，请成员重新预审后再验收通过；退回不受影响')
    return
  }
  const reason = verifyReason.value.trim()
  if (verifyChoice.value === 'reject' && !reason) {
    ElMessage.warning('退回时请填写原因，便于成员修改后重新提交')
    return
  }
  verifyLoading.value = true
  try {
    const result = await verifyTask(
      target.id,
      verifyChoice.value === 'pass',
      reason || undefined,
      verifyMemberId.value
    )
    if (verifyChoice.value === 'pass') {
      ElMessage.success(`验收通过，该成员获得 ${result.credit_delta} 积分`)
    } else {
      ElMessage.success('已退回该成员，任务回到「进行中」')
    }
    verifyVisible.value = false
    await load()
    // 归档入口只在验收通过后出现：退回的成果不允许归档
    if (verifyChoice.value === 'pass') {
      await openArchive(target.id, targetTitle, acceptedMemberId)
    }
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    verifyLoading.value = false
  }
}

/** 已验收成员：只有 verified 成员的成果可归档（`C-ARCHIVE@1`） */
function verifiedMembers(task: TaskItem): TaskMember[] {
  return (task.members ?? []).filter((member) => member.status === 'verified')
}

function memberArchiveKey(taskId: number, memberId: number): string {
  return `${taskId}:${memberId}`
}

function isMemberArchived(task: TaskItem, memberId: number): boolean {
  return archivedMemberKeys.value.includes(memberArchiveKey(task.id, memberId))
}

/** 全部已验收成员都已归档时禁用持久入口 */
function allVerifiedArchived(task: TaskItem): boolean {
  const members = verifiedMembers(task)
  return members.length > 0 && members.every((member) => isMemberArchived(task, member.user_id))
}

/** 持久归档入口：已验收成员逐人归档，仍走 openArchive 取该成员 latest 提交 */
function archiveVerifiedMember(task: TaskItem, command: string | number | object): void {
  const memberId = typeof command === 'number' ? command : Number(command)
  if (!Number.isFinite(memberId)) return
  if (isMemberArchived(task, memberId)) return
  if (!verifiedMembers(task).some((member) => member.user_id === memberId)) return
  void openArchive(task.id, task.title, memberId)
}

/** 验收通过后的归档入口：只取该成员最新成果，组织默认取第一个可管理组织 */
async function openArchive(taskId: number, taskTitle: string, memberId: number): Promise<void> {
  if (manageableOrgs.value.length === 0) {
    ElMessage.warning('没有可管理的组织，无法归档到资料库')
    return
  }
  try {
    const list = await getTaskSubmissions(taskId)
    const latest = list.items.find((item) => item.user_id === memberId && item.latest)
    if (!latest) {
      ElMessage.warning('未找到该成员的最新成果，暂不能归档')
      return
    }
    const memberName = latest.user_name || `用户 #${memberId}`
    archiveTaskId.value = taskId
    archiveMemberId.value = memberId
    archiveSubmissionId.value = latest.id
    archiveTargetLabel.value = `${taskTitle} · ${memberName}`
    archiveTitle.value = ''
    archiveOrgId.value = manageableOrgs.value[0].org_id
    archiveVisible.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

/** 归档已验收成果：服务端固定关闭学生 AI 检索，重复归档会生成新资料行 */
async function submitArchive(): Promise<void> {
  const submissionId = archiveSubmissionId.value
  if (submissionId === null || archiveLoading.value || archiveDone.value) return
  if (archiveOrgId.value === null) {
    ElMessage.warning('请选择归档组织')
    return
  }
  archiveLoading.value = true
  try {
    const resource = await archiveSubmission({
      submission_id: submissionId,
      org_id: archiveOrgId.value,
      title: archiveTitle.value.trim() || null
    })
    archiveDoneIds.value = [...archiveDoneIds.value, submissionId]
    if (archiveTaskId.value !== null && archiveMemberId.value !== null) {
      const memberKey = memberArchiveKey(archiveTaskId.value, archiveMemberId.value)
      archivedMemberKeys.value = [...new Set([...archivedMemberKeys.value, memberKey])]
    }
    ElMessage.success(
      `已归档《${resource.title}》：默认不允许学生 AI 检索，需在 Library 再开启`
    )
    archiveVisible.value = false
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    archiveLoading.value = false
  }
}

function openDeadline(task: TaskItem): void {
  deadlineTarget.value = task
  deadlineValue.value = task.deadline ?? null
  changeImpact.value = null
  changeImpactError.value = ''
  deadlineVisible.value = true
  void loadChangeImpact(task.id, deadlineValue.value)
}

/** 读取改期影响预览；失败只提示，不阻塞人工确认与既有 PATCH */
async function loadChangeImpact(taskId: number, deadline: string | null): Promise<void> {
  const seq = ++changeImpactSeq
  changeImpactLoading.value = true
  changeImpactError.value = ''
  try {
    const result = await getTaskChangeImpact(taskId, deadline)
    if (seq !== changeImpactSeq) return
    changeImpact.value = result
  } catch (err) {
    if (seq !== changeImpactSeq) return
    changeImpact.value = null
    changeImpactError.value = errorMessage(err)
  } finally {
    if (seq === changeImpactSeq) changeImpactLoading.value = false
  }
}

function onDeadlineChange(value: string | null): void {
  if (deadlineTarget.value) {
    void loadChangeImpact(deadlineTarget.value.id, value)
  }
}

/** 关闭或保存后让在途预览响应失效。 */
function invalidateImpact(): void {
  changeImpactSeq += 1
  changeImpactLoading.value = false
}

function closeDeadline(): void {
  invalidateImpact()
  deadlineVisible.value = false
}

async function saveDeadline(): Promise<void> {
  const target = deadlineTarget.value
  if (!target) return
  // 留空表示清除截止时间：后端 `PATCH` 支持 `{deadline: null}`
  const deadline = deadlineValue.value ? deadlineValue.value : null
  deadlineLoading.value = true
  try {
    const result = await patchTask(target.id, { deadline })
    const change = result.change
    const notified = change?.notifications_created ?? 0
    ElMessage.success(
      deadline
        ? notified > 0
          ? `截止时间已更新，已通知 ${notified} 位相关成员`
          : '截止时间已更新，后续提醒按新时间执行'
        : notified > 0
          ? `截止时间已清除，已通知 ${notified} 位相关成员`
          : '截止时间已清除，将不再触发基于截止时间的催办'
    )
    deadlineVisible.value = false
    invalidateImpact()
    changeImpact.value = null
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    deadlineLoading.value = false
  }
}

async function handleCancel(task: TaskItem): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `取消后「${task.title}」将不再提醒与验收，已产生的积分与记录不会被撤销。`,
      '取消任务',
      { type: 'warning', confirmButtonText: '确认取消', cancelButtonText: '再想想' }
    )
  } catch {
    return
  }
  cancelLoadingId.value = task.id
  try {
    await patchTask(task.id, { status: 'cancelled' })
    ElMessage.success('任务已取消')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    cancelLoadingId.value = null
  }
}

function openRule(task: TaskItem): void {
  ruleTarget.value = task
  ruleDraft.value = { ...(task.reminder_rule ?? DEFAULT_REMINDER_RULE) }
  ruleVisible.value = true
}

async function saveRule(rule: ReminderRule): Promise<void> {
  const target = ruleTarget.value
  if (!target) return
  ruleLoading.value = true
  try {
    await patchTask(target.id, { reminder_rule: rule })
    ElMessage.success('催办规则已保存')
    ruleVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    ruleLoading.value = false
  }
}

function ruleSummary(task: TaskItem): string {
  const rule = task.reminder_rule
  if (!rule) return '默认（提前 1 天 / 当天 / 逾期）'
  const flags: string[] = [`提前 ${rule.days_before} 天`]
  if (rule.day_of) flags.push('当天')
  if (rule.on_overdue) flags.push('逾期')
  return flags.join(' / ')
}

/** 当前成果要求摘要（与任务详情同文案）；未配置时展示默认口径 */
function acceptanceSummary(task: TaskItem): string {
  return (
    submissionAcceptanceSummary(parseSubmissionAcceptance(task.extras)) ||
    '默认（三种方式均可，不自动预审）'
  )
}

function openAcceptance(task: TaskItem): void {
  const stored = parseSubmissionAcceptance(task.extras)
  acceptanceTarget.value = task
  acceptanceWasConfigured.value = stored !== null
  acceptanceDraft.value = stored
    ? {
        modes: [...stored.modes],
        allowed_exts: [...stored.allowed_exts],
        ai_precheck: stored.ai_precheck
      }
    : {
        modes: [...SUBMISSION_MODES],
        allowed_exts: [...SUBMISSION_FILE_EXTS],
        ai_precheck: false
      }
  acceptanceVisible.value = true
}

async function saveAcceptance(): Promise<void> {
  const target = acceptanceTarget.value
  if (!target || acceptanceLoading.value) return
  const draft = acceptanceDraft.value
  if (draft.modes.length === 0) {
    ElMessage.warning('请至少选择一种成果提交方式')
    return
  }
  acceptanceLoading.value = true
  try {
    // 先取最新 extras，仅替换 acceptance，避免清空其它扩展键
    const detail = await getTask(target.id)
    const extras: Record<string, unknown> = { ...(detail.extras ?? {}) }
    extras.acceptance = {
      modes: [...draft.modes],
      allowed_exts: effectiveSubmissionFileExts(draft.allowed_exts),
      ai_precheck: draft.ai_precheck
    }
    await patchTask(target.id, { extras })
    ElMessage.success('成果要求已保存')
    acceptanceVisible.value = false

  } catch (err) {
    if (err instanceof ApiError && err.code === 4001) {
      ElMessage.error(err.message || '成果要求配置不合法')
    } else {
      ElMessage.error(errorMessage(err))
    }
  } finally {
    acceptanceLoading.value = false
  }
}

function onAcceptanceClosed(): void {
  acceptanceTarget.value = null
  void load()
}

/** 表格 `meta` 摘要：分配方式 · 报名 · 积分 · 催办；空值不占位 */
function metaSummary(task: ActivityTaskNode | ActivitySubtaskNode): string {
  const row = asRow(task)
  const parts: string[] = []
  if (row.claim_type) parts.push(row.claim_type === 'assign' ? '指派' : '开放认领')
  if (row.applied_count > 0 || row.approved_count > 0) {
    const quota = row.quota === null ? '' : `（名额 ${row.quota}）`
    parts.push(`报名 ${row.approved_count}/${row.applied_count}${quota}`)
  }
  if ((row.credit_reward ?? 0) > 0) parts.push(`积分 ${row.credit_reward}`)
  if (row.reminder_rule) parts.push(`催办 ${ruleSummary(row)}`)
  return parts.join(' · ')
}

/** 成员展示：`assignee_names` 全部 approved 成员（报名先后） */
function memberNames(task: TaskItem): string {
  const names = task.assignee_names ?? []
  return names.length > 0 ? names.join('、') : '—'
}

/** 名额进度（`quota` 为 null 视为不限名额） */
function quotaSummary(task: TaskItem): string {
  return task.quota === null
    ? `已通过 ${task.approved_count} 人（不限）`
    : `已通过 ${task.approved_count}/${task.quota}`
}

/** 审核报名入口：仅任务发布者本人、任务仍可报名（published / claimed）、且存在待审批报名（验收 ⑦） */
function canAudit(task: TaskItem): boolean {
  return (
    task.publisher_id === currentUserId.value &&
    (task.status === 'published' || task.status === 'claimed') &&
    task.applied_count > 0
  )
}

function openAudit(task: TaskItem): void {
  auditTarget.value = task
  applications.value = []
  rejectReasons.value = {}
  auditVisible.value = true
  void loadApplications()
}

async function loadApplications(): Promise<void> {
  const target = auditTarget.value
  if (!target) return
  appsLoading.value = true
  appsError.value = ''
  try {
    const result = await listApplications(target.id)
    // 契约 A3：`data` 为 `{"items": ApplicationOut[]}`（含 cancelled/rejected）
    applications.value = result?.items ?? []
  } catch (err) {
    applications.value = []
    appsError.value = errorMessage(err)
  } finally {
    appsLoading.value = false
  }
}

/** 审批单条报名：拒绝必须填写原因，否则提示且不提交（R16-AC8） */
async function decideOne(item: ApplicationItem, approve: boolean): Promise<void> {
  if (decideLoadingId.value !== null) return
  let reason: string | undefined
  if (!approve) {
    reason = (rejectReasons.value[item.id] ?? '').trim()
    if (!reason) {
      ElMessage.warning('拒绝报名必须填写原因')
      return
    }
  }
  decideLoadingId.value = item.id
  try {
    await decideApplication(item.id, approve, reason)
    ElMessage.success(
      approve ? `已通过 ${item.user_name} 的报名` : `已拒绝 ${item.user_name} 的报名`
    )
    // 审批会影响任务的名额计数与状态，列表与报名列表都刷新
    await Promise.all([loadApplications(), load()])
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    decideLoadingId.value = null
  }
}

onMounted(async () => {
  if (!userStore.user) {
    try {
      await userStore.fetchMe()
    } catch {
      return
    }
  }
  await Promise.all([load(), loadActivities()])
})
</script>

<template>
  <section class="admin app-page">
    <header class="app-page-header admin-header">
      <div>
        <h2 class="app-page-title">发布者后台</h2>
        <p class="app-page-subtitle">任务指派、验收结算与分级催办规则配置</p>
      </div>
      <div class="app-actions header-actions">
        <el-button @click="goPublish">发布新任务</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <el-card v-if="!isPublisher" shadow="never" class="app-section-card">
      <el-result
        icon="warning"
        title="当前账号没有管理权限"
        sub-title="发布者后台仅对组织管理员或协作者开放，请联系组织管理员。"
      />
    </el-card>

    <template v-else>
      <el-card shadow="never" class="app-section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">我的发布任务（{{ tasks.length }}）</span>
            <span class="app-muted header-hint">
              验收按成员逐人进行（仅列已提交成员）；催办规则保存后由后端调度器执行
            </span>
          </div>
        </template>

        <LoadingState v-if="loading" :rows="5" />
        <ErrorState
          v-else-if="error"
          :message="error"
          detail="任务列表加载失败，请检查后端服务后重试。"
          retryable
          @retry="load"
        />
        <EmptyState
          v-else-if="tasks.length === 0"
          title="暂无发布的任务"
          description="在「发布任务」页创建任务后，即可在这里指派负责人、验收与配置催办。"
        />
        <template v-else>
          <div class="activity-filter">
            <span class="activity-filter__label app-muted">活动筛选</span>
            <el-select
              v-model="activityFilter"
              size="small"
              aria-label="活动筛选"
              class="activity-filter__select"
            >
              <el-option label="全部活动" value="all" />
              <el-option label="独立任务" value="standalone" />
              <el-option
                v-for="activity in activities"
                :key="activity.id"
                :label="activity.title"
                :value="activity.id"
              />
            </el-select>
            <span v-if="activitiesError" class="app-muted filter-hint">
              活动选项加载失败：{{ activitiesError }}，仍可使用「全部活动 / 独立任务」
            </span>
          </div>

          <div class="app-desktop-table app-desktop-only">
            <ActivityTaskTable
              :tasks="tableTasks"
              :expanded="expanded"
              :show-activity="true"
              :activity-titles="activityTitles"
              @toggle="toggleExpanded"
            >
              <template #meta="{ task }">
                <span v-if="metaSummary(task)" class="task-table__meta">{{ metaSummary(task) }}</span>
                <span class="acceptance-meta">成果要求：{{ acceptanceSummary(asRow(task)) }}</span>
              </template>
              <template #actions="{ task }">
                <div class="row-actions">
                  <el-button
                    v-if="canAudit(asRow(task))"
                    size="small"
                    text
                    type="warning"
                    @click="openAudit(asRow(task))"
                  >
                    审核报名（{{ asRow(task).applied_count }}）
                  </el-button>
                  <el-button
                    v-if="canAssign(asRow(task))"
                    size="small"
                    text
                    type="primary"
                    @click="openAssign(asRow(task))"
                  >
                    指派
                  </el-button>
                  <el-button
                    v-if="canVerify(asRow(task))"
                    size="small"
                    text
                    type="success"
                    @click="openVerify(asRow(task))"
                  >
                    验收（{{ submittedMembers(asRow(task)).length }}）
                  </el-button>
                  <el-button
                    v-if="canEditDeadline(asRow(task))"
                    size="small"
                    text
                    @click="openDeadline(asRow(task))"
                  >
                    改截止时间
                  </el-button>
                  <el-button size="small" text @click="openAcceptance(asRow(task))">成果要求</el-button>
                  <el-dropdown
                    v-if="verifiedMembers(asRow(task)).length > 0"
                    trigger="click"
                    :disabled="allVerifiedArchived(asRow(task))"
                    @command="archiveVerifiedMember(asRow(task), $event)"
                  >
                    <el-button size="small" text :disabled="allVerifiedArchived(asRow(task))">
                      归档到资料库
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item
                          v-for="member in verifiedMembers(asRow(task))"
                          :key="member.user_id"
                          :command="member.user_id"
                          :disabled="isMemberArchived(asRow(task), member.user_id)"
                        >
                          {{ member.user_name || `用户 #${member.user_id}` }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <el-button size="small" text @click="openRule(asRow(task))">催办规则</el-button>
                  <el-button size="small" text @click="goDetail(task.id)">详情</el-button>
                  <el-button
                    v-if="canCancel(asRow(task))"
                    size="small"
                    text
                    type="danger"
                    :loading="cancelLoadingId === task.id"
                    @click="handleCancel(asRow(task))"
                  >
                    取消任务
                  </el-button>
                </div>
              </template>
            </ActivityTaskTable>
          </div>

          <div class="app-mobile-list app-mobile-only">
            <ul v-if="filteredTasks.length > 0" class="mobile-list">
              <li v-for="task in filteredTasks" :key="task.id" class="mobile-card">
                <div class="mobile-card__head">
                  <el-link type="primary" :underline="false" @click="goDetail(task.id)">
                    {{ task.title }}
                  </el-link>
                  <el-tag v-if="task.parent_id !== null" size="small" type="warning" effect="plain">
                    子任务
                  </el-tag>
                  <StatusTag :status="task.status" size="small" />
                </div>

                <dl class="mobile-card__meta">
                  <div class="meta-row">
                    <dt>任务 ID</dt>
                    <dd>#{{ task.id }}</dd>
                  </div>
                  <div class="meta-row">
                    <dt>分配</dt>
                    <dd>
                      <el-tag size="small" effect="plain" :type="task.claim_type === 'assign' ? 'info' : 'success'">
                        {{ task.claim_type === 'assign' ? '指派' : '开放认领' }}
                      </el-tag>
                    </dd>
                  </div>
                  <div class="meta-row">
                    <dt>成员</dt>
                    <dd>
                      <span>{{ memberNames(task) }}</span>
                      <el-tag
                        v-if="submittedMembers(task).length > 0"
                        size="small"
                        type="warning"
                        effect="plain"
                      >
                        待验收 {{ submittedMembers(task).length }}
                      </el-tag>
                    </dd>
                  </div>
                  <div class="meta-row">
                    <dt>报名</dt>
                    <dd>
                      <span>{{ quotaSummary(task) }}</span>
                      <el-tag v-if="task.applied_count > 0" size="small" type="warning" effect="plain">
                        待审批 {{ task.applied_count }}
                      </el-tag>
                    </dd>
                  </div>
                  <div class="meta-row">
                    <dt>截止</dt>
                    <dd>{{ formatDeadline(task.deadline) }}</dd>
                  </div>
                  <div class="meta-row">
                    <dt>积分</dt>
                    <dd>+{{ task.credit_reward ?? 0 }}</dd>
                  </div>
                  <div class="meta-row">
                    <dt>催办规则</dt>
                    <dd>{{ ruleSummary(task) }}</dd>
                  </div>
                  <div class="meta-row">
                    <dt>成果要求</dt>
                    <dd>{{ acceptanceSummary(task) }}</dd>
                  </div>
                </dl>

                <div class="mobile-card__actions">
                  <el-button v-if="canAudit(task)" size="small" type="warning" plain @click="openAudit(task)">
                    审核报名（{{ task.applied_count }}）
                  </el-button>
                  <el-button v-if="canAssign(task)" size="small" type="primary" plain @click="openAssign(task)">
                    指派
                  </el-button>
                  <el-button v-if="canVerify(task)" size="small" type="success" plain @click="openVerify(task)">
                    验收（{{ submittedMembers(task).length }}）
                  </el-button>
                  <el-button v-if="canEditDeadline(task)" size="small" @click="openDeadline(task)">
                    改截止时间
                  </el-button>
                  <el-button size="small" @click="openAcceptance(task)">成果要求</el-button>
                  <el-dropdown
                    v-if="verifiedMembers(task).length > 0"
                    trigger="click"
                    :disabled="allVerifiedArchived(task)"
                    @command="archiveVerifiedMember(task, $event)"
                  >
                    <el-button size="small" :disabled="allVerifiedArchived(task)">
                      归档到资料库
                    </el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item
                          v-for="member in verifiedMembers(task)"
                          :key="member.user_id"
                          :command="member.user_id"
                          :disabled="isMemberArchived(task, member.user_id)"
                        >
                          {{ member.user_name || `用户 #${member.user_id}` }}
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <el-button size="small" @click="openRule(task)">催办规则</el-button>
                  <el-button size="small" @click="goDetail(task.id)">详情</el-button>
                  <el-button
                    v-if="canCancel(task)"
                    size="small"
                    type="danger"
                    plain
                    :loading="cancelLoadingId === task.id"
                    @click="handleCancel(task)"
                  >
                    取消任务
                  </el-button>
                </div>
              </li>
            </ul>
            <p v-else class="filter-empty app-muted">当前筛选下没有任务</p>
          </div>
        </template>
      </el-card>
    </template>

    <AssignDialog
      v-model:visible="assignVisible"
      :task="assignTarget"
      :candidates="candidates"
      :loading="assignLoading"
      @confirm="confirmAssign"
    />

    <el-dialog v-model="verifyVisible" title="验收成员" width="520px" :close-on-click-modal="false">
      <div class="verify-body">
        <p class="verify-task">{{ verifyTarget?.title }}</p>

        <!-- 成员级验收：只列 `submitted` 成员，逐人通过 / 退回 -->
        <el-form label-position="top">
          <el-form-item label="验收成员（待验收）" required>
            <el-radio-group v-model="verifyMemberId" class="member-picker">
              <el-radio
                v-for="member in verifyTarget ? submittedMembers(verifyTarget) : []"
                :key="member.user_id"
                :value="member.user_id"
                border
              >
                {{ member.user_name || `用户 #${member.user_id}` }}
                <el-tag
                  :type="memberStatusMeta(member.status).type"
                  size="small"
                  effect="plain"
                  class="row-tag"
                >
                  {{ memberStatusMeta(member.status).text }}
                </el-tag>
                <el-tag
                  v-if="verifyStaleUsers.includes(member.user_id)"
                  type="warning"
                  size="small"
                  effect="plain"
                  class="row-tag"
                >
                  预审已过期
                </el-tag>
              </el-radio>
            </el-radio-group>
            <span v-if="verifyTarget && submittedMembers(verifyTarget).length === 0" class="verify-hint app-muted">
              当前没有待验收的成员
            </span>
            <span v-else-if="verifyStaleLoading" class="verify-hint app-muted">正在读取最新成果的预审状态…</span>
            <span v-else-if="verifyStaleError" class="verify-hint app-muted">{{ verifyStaleError }}</span>
          </el-form-item>
        </el-form>

        <el-radio-group v-model="verifyChoice">
          <el-radio value="pass">通过（结算积分）</el-radio>
          <el-radio value="reject">退回（回到进行中）</el-radio>
        </el-radio-group>

        <el-input
          v-model="verifyReason"
          type="textarea"
          :rows="3"
          maxlength="200"
          show-word-limit
          :placeholder="verifyChoice === 'pass' ? '可选：验收备注' : '必填：请说明退回原因'"
        />

        <el-alert
          v-if="verifyChoice === 'pass' && verifyStaleCurrent"
          type="warning"
          :closable="false"
          show-icon
          title="该成员最新成果的预审已过期（任务要求或资料已变化）：请先重新预审再通过；退回不受影响"
        />
        <el-alert
          v-else-if="verifyChoice === 'pass'"
          type="success"
          :closable="false"
          show-icon
          :title="`通过后该成员将获得 ${verifyTarget?.credit_reward ?? 0} 积分（未设置时后端按 20 结算）`"
        />
        <el-alert
          v-else
          type="warning"
          :closable="false"
          show-icon
          title="退回只影响该成员：其余成员的状态与积分保持不变"
        />
      </div>

      <template #footer>
        <el-button :disabled="verifyLoading" @click="verifyVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="verifyLoading"
          :disabled="verifyChoice === 'pass' && (verifyStaleLoading || verifyStaleCurrent)"
          @click="submitVerify"
        >
          {{ verifyChoice === 'pass' ? '确认通过' : '确认退回' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 已验收成果归档：仅在验收通过后由 openArchive 打开，默认关闭学生 AI 检索 -->
    <el-dialog
      v-model="archiveVisible"
      title="归档到资料库"
      width="520px"
      :close-on-click-modal="false"
    >
      <div class="verify-body">
        <p class="verify-task">{{ archiveTargetLabel }}</p>
        <el-form label-position="top">
          <el-form-item label="归档组织" required>
            <el-select
              v-model="archiveOrgId"
              placeholder="选择可管理组织"
              aria-label="归档组织"
              class="archive-org-select"
            >
              <el-option
                v-for="org in manageableOrgs"
                :key="org.org_id"
                :label="org.name"
                :value="org.org_id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="资料标题（可选）">
            <el-input
              v-model="archiveTitle"
              maxlength="120"
              show-word-limit
              :placeholder="`缺省：${archiveTargetLabel}`"
            />
          </el-form-item>
        </el-form>
        <el-alert
          type="info"
          :closable="false"
          show-icon
          title="归档后默认不允许学生 AI 检索，需在 Library 再开启"
          description="归档会复制该成果为新的组织资料；学生 AI 检索开关保持关闭，需要时由管理员在 Library 手动开启。"
        />
        <p v-if="archiveDone" class="verify-hint app-muted">
          该成果本次已归档过：重复归档会再生成一条组织资料。
        </p>
      </div>
      <template #footer>
        <el-button :disabled="archiveLoading" @click="archiveVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="archiveLoading"
          :disabled="archiveDone"
          @click="submitArchive"
        >
          确认归档
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deadlineVisible" title="修改截止时间" width="460px" :close-on-click-modal="false" @closed="invalidateImpact">
      <p class="verify-task">{{ deadlineTarget?.title }}</p>
      <el-form label-position="top">
        <el-form-item label="截止时间（留空表示清除 / 不设置截止）">
          <el-date-picker
            v-model="deadlineValue"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择截止时间，留空表示清除"
            class="deadline-picker"
            @change="onDeadlineChange"
          />
        </el-form-item>
      </el-form>

      <div v-if="changeImpactLoading" class="change-impact change-impact--loading">
        正在计算改期影响…
      </div>
      <div v-else-if="changeImpactError" class="change-impact change-impact--error">
        <p class="change-impact-line">影响预览读取失败：{{ changeImpactError }}</p>
        <p class="change-impact-line">仍可保存；后端会在执行时再次校验权限并记录变更。</p>
      </div>
      <div v-else-if="changeImpact" class="change-impact">
        <p class="change-impact-flow">
          <span class="change-impact-label">当前截止</span>
          <span>{{ changeImpact.current_deadline || '未设置' }}</span>
          <span aria-hidden="true">→</span>
          <span class="change-impact-label">拟调整</span>
          <span>{{ changeImpact.proposed_deadline || '清除截止' }}</span>
        </p>
        <p class="change-impact-line">
          提醒：{{ changeImpact.reminders_reset ? '旧提醒将失效，按新时间重新计算' : '截止时间未变化，不会重复通知' }}
        </p>
        <p class="change-impact-line">
          受影响成员：{{ changeImpact.affected_members.length }} 人
          <template v-if="impactMemberNames">（{{ impactMemberNames }}）</template>
        </p>
        <p class="change-impact-line">
          后续任务：{{ changeImpact.downstream_tasks.length }} 个
          <template v-if="impactDownstreamTitles">（{{ impactDownstreamTitles }}）</template>
        </p>
        <p class="change-impact-line">通知接收人：{{ changeImpact.notified_user_ids.length }} 人</p>
      </div>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="确认保存后才会执行改期；旧提醒会失效，相关成员将收到变更通知，逾期扣分不会退回。"
      />
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="留空保存将清除截止时间，之后不再触发基于截止时间的催办与逾期扣分。"
      />
      <template #footer>
        <el-button :disabled="deadlineLoading" @click="closeDeadline">取消</el-button>
        <el-button type="primary" :loading="deadlineLoading" @click="saveDeadline">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ruleVisible" title="催办规则" width="600px" :close-on-click-modal="false">
      <p class="verify-task">{{ ruleTarget?.title }}</p>
      <ReminderRuleForm v-model="ruleDraft" :loading="ruleLoading" @submit="saveRule" />
    </el-dialog>

    <el-dialog
      v-model="acceptanceVisible"
      title="成果要求"
      width="min(560px, calc(100vw - 32px))"
      :close-on-click-modal="false"
      class="acceptance-dialog"
      @closed="onAcceptanceClosed"
    >
      <p class="verify-task">{{ acceptanceTarget?.title }}</p>
      <el-form label-position="top">
        <el-form-item label="提交方式（可多选）">
          <el-checkbox-group v-model="acceptanceDraft.modes" class="acceptance-checks">
            <el-checkbox v-for="mode in SUBMISSION_MODES" :key="mode" :value="mode">
              {{ SUBMISSION_MODE_LABELS[mode] }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="允许文件类型">
          <el-checkbox-group
            v-model="acceptanceDraft.allowed_exts"
            :disabled="!acceptanceFileMode"
            class="acceptance-checks"
          >
            <el-checkbox v-for="ext in SUBMISSION_FILE_EXTS" :key="ext" :value="ext">
              {{ submissionFileLabel(ext) }}
            </el-checkbox>
          </el-checkbox-group>
          <p class="acceptance-hint">
            未勾选任何类型时按后端语义允许全部四种；未选择「文件上传」时忽略该配置。
          </p>
        </el-form-item>
        <el-form-item label="AI 成果预审">
          <div class="acceptance-switch">
            <el-switch v-model="acceptanceDraft.ai_precheck" />
            <span class="acceptance-hint">开启后学生提交会自动预审；预审不等于人工验收。</span>
          </div>
        </el-form-item>
        <el-alert
          v-if="!acceptanceWasConfigured"
          type="info"
          :closable="false"
          show-icon
          title="该任务尚未配置成果要求，当前默认为三种方式均可；保存后按此处配置限制提交。"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="acceptanceLoading" @click="acceptanceVisible = false">取消</el-button>
        <el-button type="primary" :loading="acceptanceLoading" @click="saveAcceptance">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="auditVisible" title="审核报名" width="760px" :close-on-click-modal="false">
      <p class="verify-task">{{ auditTarget?.title }}</p>
      <p class="audit-hint">
        仅待审批的报名在此显示（按报名先后）。通过后该同学成为成员并占用一个名额；拒绝需填写原因。
      </p>

      <LoadingState v-if="appsLoading" :rows="3" />
      <ErrorState
        v-else-if="appsError"
        :message="appsError"
        detail="报名列表加载失败，请稍后重试。"
        retryable
        @retry="loadApplications"
      />
      <EmptyState
        v-else-if="pendingApplications.length === 0"
        title="没有待审批的报名"
        description="所有报名都已处理，或暂无新报名。"
      />
      <template v-else>
        <div class="app-desktop-table app-desktop-only">
          <el-table :data="pendingApplications" size="small" stripe>
            <el-table-column label="报名人" width="130">
              <template #default="scope">
                <span class="audit-user">{{ scope.row.user_name }}</span>
                <el-tag
                  v-if="applicationStatusMeta(scope.row.status)"
                  size="small"
                  :type="applicationStatusMeta(scope.row.status).type"
                  effect="plain"
                  class="row-tag"
                >
                  {{ applicationStatusMeta(scope.row.status).text }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="报名时间" width="170">
              <template #default="scope">{{ scope.row.created_at }}</template>
            </el-table-column>
            <el-table-column label="拒绝原因（拒绝时必填）" min-width="200">
              <template #default="scope">
                <el-input
                  v-model="rejectReasons[scope.row.id]"
                  size="small"
                  maxlength="200"
                  placeholder="拒绝时请填写原因"
                />
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140">
              <template #default="scope">
                <div class="row-actions">
                  <el-button
                    size="small"
                    text
                    type="success"
                    :loading="decideLoadingId === scope.row.id"
                    @click="decideOne(scope.row, true)"
                  >
                    通过
                  </el-button>
                  <el-button
                    size="small"
                    text
                    type="danger"
                    :loading="decideLoadingId === scope.row.id"
                    @click="decideOne(scope.row, false)"
                  >
                    拒绝
                  </el-button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div class="app-mobile-list app-mobile-only">
          <ul class="mobile-list">
            <li v-for="item in pendingApplications" :key="item.id" class="mobile-card">
              <div class="mobile-card__head">
                <span class="audit-user">{{ item.user_name }}</span>
                <el-tag
                  v-if="applicationStatusMeta(item.status)"
                  size="small"
                  :type="applicationStatusMeta(item.status).type"
                  effect="plain"
                >
                  {{ applicationStatusMeta(item.status).text }}
                </el-tag>
              </div>

              <dl class="mobile-card__meta">
                <div class="meta-row">
                  <dt>报名时间</dt>
                  <dd>{{ item.created_at }}</dd>
                </div>
              </dl>

              <el-input
                v-model="rejectReasons[item.id]"
                maxlength="200"
                placeholder="拒绝时请填写原因"
              />

              <div class="mobile-card__actions">
                <el-button
                  size="small"
                  type="success"
                  plain
                  :loading="decideLoadingId === item.id"
                  @click="decideOne(item, true)"
                >
                  通过
                </el-button>
                <el-button
                  size="small"
                  type="danger"
                  plain
                  :loading="decideLoadingId === item.id"
                  @click="decideOne(item, false)"
                >
                  拒绝
                </el-button>
              </div>
            </li>
          </ul>
        </div>
      </template>

      <template #footer>
        <el-button :loading="appsLoading" @click="loadApplications">刷新</el-button>
        <el-button @click="auditVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.admin-header {
  flex-wrap: wrap;
}

.header-actions {
  flex-wrap: wrap;
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
  color: var(--el-text-color-primary);
}

.header-hint {
  min-width: 0;
  font-size: 13px;
  line-height: 1.6;
}

.activity-filter {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}

.activity-filter__label {
  font-size: 13px;
}

.activity-filter__select {
  width: 220px;
  max-width: 100%;
}

.filter-hint {
  min-width: 0;
  font-size: 13px;
  line-height: 1.6;
}

.filter-empty {
  margin: 0;
  padding: 12px;
  text-align: center;
  font-size: 13px;
}


.row-tag {
  margin-left: 6px;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.member-picker {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 8px;
}

.member-picker :deep(.el-radio) {
  margin-right: 0;
}

.deadline-picker {
  width: 100%;
}

.archive-org-select {
  width: 100%;
}

.change-impact {
  margin: 4px 0 12px;
  padding: 10px 12px;
  border: 1px solid var(--el-border-color);
  border-radius: var(--el-border-radius-base);
  background: var(--el-fill-color-light);
}

.change-impact--loading,
.change-impact--error {
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

.change-impact-flow {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 0 0 6px;
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.change-impact-label {
  color: var(--el-text-color-secondary);
}

.change-impact-line {
  margin: 2px 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  word-break: break-word;
}

.verify-hint {
  font-size: 13px;
}

.audit-hint {
  margin: 4px 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.audit-user {
  font-weight: 500;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.verify-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.verify-task {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.mobile-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.mobile-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-raised);
}

.mobile-card__head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  min-width: 0;
  word-break: break-word;
}

.mobile-card__meta {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  min-width: 0;
}

.meta-row dt {
  margin: 0;
  font-size: 13px;
  color: var(--app-text-muted);
}

.meta-row dd {
  margin: 0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  min-width: 0;
  color: var(--app-text);
  word-break: break-word;
}

.mobile-card__actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mobile-card__actions :deep(.el-button) {
  margin-left: 0 !important;
}

.acceptance-meta {
  display: block;
  font-size: var(--app-font-aux);
  line-height: 1.5;
  color: var(--app-text-muted);
  word-break: break-word;
}

.acceptance-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
}

.acceptance-checks :deep(.el-checkbox) {
  margin-right: 0;
}

.acceptance-switch {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 12px;
}

.acceptance-hint {
  margin: 4px 0 0;
  font-size: var(--app-font-aux);
  line-height: 1.6;
  color: var(--app-text-muted);
}

@media (max-width: 768px) {
  .acceptance-checks :deep(.el-checkbox) {
    min-height: var(--app-touch);
  }

  .acceptance-switch {
    flex-direction: column;
    align-items: flex-start;
  }

  .acceptance-dialog :deep(.el-button) {
    min-height: var(--app-touch);
  }
}
</style>