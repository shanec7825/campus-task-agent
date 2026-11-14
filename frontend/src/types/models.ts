/**
 * 前端共享类型（契约 C-DATA@2，字段名与后端 `app/schemas.py` 逐字一致）。
 *
 * 约束：
 * - 禁止使用 `any`；JSON 自由字段统一 `Record<string, unknown>`。
 * - 本文件由 T1 统一维护（承载 `C-DATA@2` 的 TS 镜像），T4/T6 只 import，不得改写字段名。
 * - 只允许「新增接口 / 追加字段」，P1 既有字段名与类型一律不改。
 */

/** 统一响应包裹 `{"code":0,"msg":"ok","data":...}`（C-BOOT@1） */
export interface ApiEnvelope<T> {
  code: number
  msg: string
  data: T
}

/** 催办规则（`ReminderRule`） */
export interface ReminderRule {
  days_before: number
  day_of: boolean
  on_overdue: boolean
}

/** 用户（`UserOut`） */
export interface User {
  id: number
  username: string
  display_name: string
  role: string
  org: string | null
  credits: number
  /** 平台管理员：可建组织/发重置，但不自动获得任何组织业务内容可见性 */
  platform_admin: boolean
}

/** 登录返回（`LoginOut`） */
export interface LoginResult {
  token: string
  user: User
}

// --------------------------------------------------------------------------- //
// 组织与认证（`C-DATA-AUTH@1` / `C-ORG@1` / `C-FE-AUTH@1`）
// --------------------------------------------------------------------------- //

/** 组织角色（`org_members.role`） */
export type OrgRole = 'admin' | 'collaborator' | 'member'

/** 当前用户的组织成员关系（`OrgMembershipOut`） */
export interface OrgMembership {
  org_id: number
  name: string
  slug: string
  role: OrgRole
  title: string | null
  status: string
}

/** 当前用户（`GET /api/auth/me` → `MeOut`） */
export interface MeOut {
  user: User
  orgs: OrgMembership[]
}

/** 登录 / 注册返回（`LoginOut`），会话由 Cookie 承载 */
export interface LoginOut {
  user: User
  orgs: OrgMembership[]
}

/** 注册请求体（`RegisterIn`，必须携带邀请令牌） */
export interface RegisterIn {
  username: string
  display_name: string
  password: string
  confirm_password: string
  invite_token: string
}

/** 受控密码重置请求体（`PasswordResetIn`） */
export interface PasswordResetIn {
  token: string
  password: string
  confirm_password: string
}

/** 任务主任务 / 子任务摘要（`TaskBrief`） */
export interface TaskBrief {
  id: number
  title: string
  status: string
  assignee_id: number | null
  depends_on: number | null
  quota: number | null
  parent_id: number | null
  /** 所属活动 id；`null` 表示独立任务 */
  activity_id: number | null
  /** 多前置 id 集合；旧接口缺省时按 `depends_on` 兼容 */
  depends_on_ids?: number[]
}

/** 共用图谱节点（`C-ACTIVITY-GRAPH@1`） */
export interface TaskGraphNode {
  id: number
  title: string
  status: string
  parent_id: number | null
  start_time: string | null
  deadline: string | null
  assignee_names: string[]
}

/** 依赖边：`from_id` 为前置，`to_id` 为当前任务 */
export interface TaskGraphEdge {
  from_id: number
  to_id: number
}

/** 活动与任务详情共用的图谱数据（服务端唯一来源） */
export interface TaskGraph {
  nodes: TaskGraphNode[]
  edges: TaskGraphEdge[]
}

/** 进度记录（`ProgressOut`） */
export interface ProgressItem {
  id: number
  task_id: number
  user_id: number
  user_name: string
  content: string
  created_at: string
}

/** 任务列表项 / 任务基本信息（`TaskOut`） */
export interface TaskItem {
  id: number
  parent_id: number | null
  /** 所属活动 id；`null` 表示独立任务 */
  activity_id: number | null
  title: string
  description: string | null
  location: string | null
  start_time: string | null
  deadline: string | null
  quota: number | null
  volunteer_hours: number | null
  status: string
  claim_type: string
  publisher_id: number
  assignee_id: number | null
  /** 旧单前置兼容字段：等于 `depends_on_ids` 首项（无前置为 `null`） */
  depends_on: number | null
  /** 多前置依赖 id（`C-TASK-GRAPH@1`，服务端边表 ∪ 旧字段去重后的结果） */
  depends_on_ids: number[]
  sop_guide: string | null
  style_note: string | null
  extras: Record<string, unknown>
  reminder_rule: ReminderRule | null
  credit_reward: number | null
  created_at: string
  assignee_name: string | null
  publisher_name: string
  is_claimable: boolean
  /** 报名审批派生字段（后端保证 4 个键均出现在响应中，均为非可选） */
  applied_count: number
  approved_count: number
  my_application_status: ApplicationStatus | null
  /** 全部 approved 用户显示名（按报名先后），末位展示口径；`assignee_name` 恒为第 0 个 */
  assignee_names: string[]
  /** 逐人执行状态（契约 `C-DATA-MEMBER@1`，按报名先后） */
  members: TaskMember[]
  /** 当前登录用户在该任务中的执行状态；非成员为 `null` */
  my_member_status: MemberStatus | null
}

/** 成员执行状态（后端仅使用这 5 个字面量） */
export type MemberStatus = 'not_started' | 'in_progress' | 'submitted' | 'rejected' | 'verified'

/** 单条成员执行记录（`MemberOut` 镜像；`user_name` 由服务端填充） */
export interface TaskMember {
  user_id: number
  user_name: string
  status: MemberStatus
  rejection_reason: string | null
  submitted_at: string | null
  verified_at: string | null
  updated_at: string | null
}

/** 任务详情（`TaskDetailOut`） */
export interface TaskDetail extends TaskItem {
  children: TaskBrief[]
  progress: ProgressItem[]
  /** 所属活动标题；无活动为 `null`（契约 `C-TASK-FIELDS@1`） */
  activity_title: string | null
  /** 父任务标题；无父任务为 `null` */
  parent_title: string | null
  /** 直接前置 / 直接后继：只含当前用户可见任务 */
  dependencies: TaskBrief[]
  dependents: TaskBrief[]
  /** 局部图谱：当前任务 + 直接前置 + 直接后继 */
  graph: TaskGraph
}

// --------------------------------------------------------------------------- //
// 活动（`C-DATA-ACTIVITY@1` / `C-FE-API@1`）
// --------------------------------------------------------------------------- //

/** 活动进度聚合（服务端唯一计算来源，前端不自行重算） */
export interface ActivityProgress {
  total_tasks: number
  completed_tasks: number
  cancelled_tasks: number
  subtask_total: number
  subtask_completed: number
  percent: number
  awaiting_owner_confirm: boolean
}

/** 活动任务成员（`ActivityAssigneeOut`，契约 `C-ACT-TABLE-DTO@1`） */
export interface ActivityAssignee {
  user_id: number
  name: string
}

/** 活动任务树中的子任务节点 */
export interface ActivitySubtaskNode {
  id: number
  title: string
  status: string
  /** 所在活动 id；与父节点同值（后端已返回，可选以兼容旧响应） */
  activity_id?: number | null
  start_time: string | null
  deadline: string | null
  assignee_names: string[]
  /** 与 `assignee_names` 同源同顺序的成员标识 */
  assignees: ActivityAssignee[]
}

/** 活动任务树中的第一层任务节点 */
export interface ActivityTaskNode {
  id: number
  title: string
  status: string
  /**
   * 所在活动 id，服务端已返回（契约 `C-ACT-TABLE-DTO@1`）；可选仅为兼容旧响应，
   * 缺省时「所属活动」列显示「独立任务」。
   */
  activity_id?: number | null
  start_time: string | null
  deadline: string | null
  assignee_names: string[]
  /** 与 `assignee_names` 同源同顺序的成员标识 */
  assignees: ActivityAssignee[]
  children: ActivitySubtaskNode[]
  /** `children` 中状态为 verified 的数量（cancelled 只计入分母） */
  completed_children: number
  total_children: number
}

/** 活动（`ActivityOut`） */
export interface Activity {
  id: number
  title: string
  description: string | null
  location: string | null
  start_time: string | null
  deadline: string | null
  owner_id: number
  owner_name: string
  org: string | null
  org_id: number | null
  status: string
  created_at: string
  progress: ActivityProgress
}

/** 活动详情（`ActivityDetailOut`） */
export interface ActivityDetail extends Activity {
  tasks: ActivityTaskNode[]
  /** 活动全量依赖与时间图谱（只含当前用户可见任务） */
  graph: TaskGraph
}

/** 活动列表（`GET /api/activities`） */
export interface ActivityListResult {
  items: Activity[]
}

/** 创建活动的请求体（`ActivityCreate`） */
export interface ActivityCreatePayload {
  title: string
  description?: string | null
  location?: string | null
  start_time?: string | null
  deadline?: string | null
  org?: string | null
  /** 活动归属组织；必须是本人 admin/collaborator 的组织（服务端 `resolve_task_org` 校验） */
  org_id?: number | null
}

/** 整批发布中的任务草稿（`ActivityBatchTaskDraft`，契约 `C-BATCH-PUBLISH@1`） */
export interface ActivityBatchTaskDraft {
  /** 批内唯一引用键；同批任务只能通过它声明依赖与父任务 */
  key: string
  title: string
  description?: string | null
  location?: string | null
  start_time?: string | null
  deadline?: string | null
  quota?: number | null
  volunteer_hours?: number | null
  claim_type?: 'open' | 'assign'
  sop_guide?: string | null
  style_note?: string | null
  extras?: Record<string, unknown>
  credit_reward?: number
  /** 前置任务 key（只能引用同批次其他任务） */
  depends_on_keys: string[]
  /** 父任务 key；`null` 表示顶层任务（父任务自身不得再有父任务） */
  parent_key: string | null
}

/** 整批发布请求体（`POST /api/activities/publish-batch`） */
export interface ActivityBatchPublishPayload {
  activity: ActivityCreatePayload
  tasks: ActivityBatchTaskDraft[]
}

/** 整批发布返回（`{activity, tasks}`，任务顺序与请求一致） */
export interface ActivityBatchPublishResult {
  activity: Activity
  tasks: TaskItem[]
}

// --------------------------------------------------------------------------- //
// 报名审批（`C-APPLY@1` 的数据结构，契约 `C-DATA@2`）
// --------------------------------------------------------------------------- //

/** 报名状态（`ApplicationOut.status`） */
export type ApplicationStatus = 'pending' | 'approved' | 'rejected' | 'cancelled'

/** 单条报名记录（`ApplicationOut`；`user_name` 由服务端批量填充） */
export interface ApplicationItem {
  id: number
  task_id: number
  user_id: number
  user_name: string
  status: ApplicationStatus
  reason: string | null
  created_at: string
  decided_at: string | null
}

/** `ApplicationItem` 的同义别名（同为 `ApplicationOut` 镜像）：`Application` / `ApplicationItem` 均可使用 */
export type Application = ApplicationItem

/** 报名 / 撤回 / 审批的返回体（`ApplyOut`；`claim` 兼容别名同构） */
export interface ApplyResult {
  task_id: number
  application: ApplicationItem
  task: TaskItem
}

/** 我的报名列表项（`ApplicationItemOut`：报名记录 + 任务摘要） */
export interface ApplicationWithTask {
  application: ApplicationItem
  task: TaskBrief
}

/**
 * 发布 / 修改任务的请求体（`TaskCreate` 的前端镜像）。
 * `patchTask` 使用其 `Partial` 形态；省略字段 = 不修改，显式 `null` = 清空。
 */
export interface TaskCreatePayload {
  parent_id?: number | null
  /** 所属活动 id；缺省表示创建独立任务 */
  activity_id?: number | null
  title: string
  description?: string | null
  location?: string | null
  start_time?: string | null
  deadline?: string | null
  quota?: number | null
  volunteer_hours?: number | null
  claim_type?: 'open' | 'assign'
  assignee_id?: number | null
  depends_on?: number | null
  /** 多前置依赖；显式提供时整体替换（发布时用于一次声明多个前置） */
  depends_on_ids?: number[] | null
  sop_guide?: string | null
  style_note?: string | null
  extras?: Record<string, unknown>
  reminder_rule?: ReminderRule | null
  credit_reward?: number
}

/** 任务列表返回（`GET /api/tasks`） */
export interface TaskListResult {
  items: TaskItem[]
}

/** 验收返回（`POST /api/tasks/{id}/verify`，`VerifyOut`） */
export interface VerifyResult {
  task: TaskItem
  credit_delta: number
  /** 本次实际加分的成员（幂等命中时不含已加过的成员） */
  credited_user_ids: number[]
}

/** 签到记录（`CheckinOut`） */
export interface CheckinItem {
  id: number
  task_id: number
  user_id: number
  task_title: string | null
  checkin_time: string
}

/** 签到列表（`GET /api/checkin/me`） */
export interface CheckinListResult {
  items: CheckinItem[]
}

/** 积分流水（`CreditLogOut`） */
export interface CreditLog {
  id: number
  user_id: number
  task_id: number | null
  delta: number
  reason: string
  created_at: string
}

/** 我的积分（`CreditsMeOut`） */
export interface CreditsMe {
  credits: number
  logs: CreditLog[]
}

/** 通知（`NotificationOut`） */
export interface NotificationItem {
  id: number
  user_id: number
  task_id: number | null
  level: string
  title: string
  content: string
  is_read: number
  /** 改期/取消后失效的旧提醒（`C-REMINDER-STALE@1`）：历史保留，不计未读 */
  stale: number
  /** 已归档（`C-NOTICE-ARCHIVE@1`）：从默认列表移入归档箱，不删除、不改已读 */
  archived: number
  archived_at: string | null
  created_at: string
}

/** 通知列表（`NotificationListOut`） */
export interface NotificationList {
  unread: number
  items: NotificationItem[]
}

// --------------------------------------------------------------------------- //
// AI 变更与追溯块（`C-AGENT@2` / `C-TRACE@1`，契约 `C-DATA@2`）
// --------------------------------------------------------------------------- //

/**
 * 字段级变更（`ChangeOut`）。
 * `old_value` / `new_value` 只允许标量：扩展项以 `field="extra_tags.<键名>"` 单键表达。
 */
export interface Change {
  op: 'set' | 'add_tag' | 'remove_tag'
  field: string
  old_value: string | number | null
  new_value: string | number | null
  reason: string
  source: 'ai' | 'user'
}

/** 块类型：`raw` 为 P1 解析块，其余 4 种为本轮追溯块 */
export type BlockKind = 'raw' | 'ai_applied' | 'user_edit' | 'user_note' | 'live'

/** 后端透传的追溯块（`TraceBlock`）：不参与字段写入，后端不清洗 / 不排序 */
export interface TraceBlock {
  id: number
  text: string
  kind: 'ai_applied' | 'user_edit' | 'user_note' | 'live'
  field: string | null
  meta: Record<string, unknown> | null
}

/** 草稿结构（`Draft`）——与后端 Pydantic `Draft` 一致 */
export interface Draft {
  title: string | null
  time: string | null
  deadline: string | null
  location: string | null
  details: string | null
  quota: number | null
  volunteer_hours: number | null
  notes: string | null
  requirements: string | null
  extra_tags: Record<string, string>
  style_prompt: string | null
  /** 前端权威追溯块：后端原样透传，`null` 与 `[]` 均表示无追溯块 */
  trace?: TraceBlock[] | null
}

/** 原文片段（`SpanOut`） */
export interface Span {
  text: string
  field: string | null
}

/** 后到覆盖先到的更正（`CorrectionOut`） */
export interface Correction {
  target: string
  old_value: string | null
  new_value: string
  reason: string
}

/** 歧义问号（`Ambiguity`） */
export interface Ambiguity {
  field: string
  question: string
  suggestion: string | null
}

/** 拆解建议子任务（`SubTaskSuggestion`） */
export interface SubTaskSuggestion {
  title: string
  description: string
  sop_guide: string
  quota: number | null
  depends_on: number | null
}

/** 润色结果（`Polished`） */
export interface Polished {
  details: string
  notes: string
}

/** 提炼结果（`ExtractOut`） */
export interface ExtractResult {
  draft: Draft
  spans: Span[]
  unresolved: string[]
  style_prompt: string | null
  corrections: Correction[]
  mock: boolean
  /** 字段级变更（增量模式下相对 `base_draft` 的 diff） */
  changes: Change[]
  /** 与 `changes` 等长、顺序一一对应的追溯文案（后端唯一来源） */
  applied_texts: string[]
}

/** 审核结果（`ReviewOut`） */
export interface ReviewResult {
  ambiguities: Ambiguity[]
  polished: Polished | null
  suggested_sub_tasks: SubTaskSuggestion[]
  mock: boolean
  /** 待采纳建议（不自动落值） */
  changes: Change[]
}

/** 流式解析结果（`StreamParseOut`） */
export interface StreamParseResult {
  draft: Draft
  spans: Span[]
  unresolved: string[]
  corrections: Correction[]
  mock: boolean
  changes: Change[]
}

/** 拆解结果（`POST /api/tasks/{id}/decompose`） */
export interface DecomposeResult {
  suggested_sub_tasks: SubTaskSuggestion[]
  mock: boolean
}

/** 知识库相似项（`SimilarItem`） */
export interface SimilarItem {
  task_id: number | null
  title: string
  summary: string | null
  similarity: number
  created_at: string | null
}

/** 相似检索结果（`KbSimilarOut`） */
export interface SimilarResult {
  items: SimilarItem[]
  threshold: number
}
// --------------------------------------------------------------------------- //
// AI 只读问答（`C-AI-CHAT@1`）
// --------------------------------------------------------------------------- //

/** 回答来源类型（`C-AI-DOC-CONTEXT@1`）：任务 / 资料（`activity` 永不产生） */
export type AiCitationKind = 'task' | 'doc'

/** 回答来源：只由服务端从当前用户可见任务 / 开放资料映射生成 */
export interface AiCitation {
  /** 来源类型；历史或未知值前端一律按 `task` 展示 */
  kind: AiCitationKind
  type: 'task' | 'doc'
  id: number
  title: string
  activity_id: number | null
  /** `kind="doc"` 的资料 id（跳 Library 用）；任务来源无此字段 */
  resource_id?: number | null
}

/** AI 会话作用域（`C-AI-SCOPE@1`）：通用 / 活动 / 任务 */
export type AiScopeType = 'general' | 'activity' | 'task'

/** 请求作用域；`general` 不绑定对象，`id` 必须为 null */
export interface AiScope {
  type: AiScopeType
  id: number | null
}

/** 会话消息（`AiMessageOut`） */
export interface AiChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  citations: AiCitation[]
  mock: boolean
  created_at: string
}

/** 一次问答结果（`AiChatOut`） */
export interface AiChatResult {
  conversation_id: number
  user_message: AiChatMessage
  assistant_message: AiChatMessage
  mock: boolean
  /** 同一 request_id 的重放结果，不再新增消息或用量 */
  replayed: boolean
}

/** 会话摘要（`AiConversationSummary`） */
export interface AiConversationSummary {
  id: number
  title: string
  created_at: string
  updated_at: string
  message_count: number
  scope_type: AiScopeType
  scope_id: number | null
}

/** 会话列表（`AiConversationListOut`） */
export interface AiConversationList {
  items: AiConversationSummary[]
  /** 同 owner、同过滤条件的会话总数，供前端判断是否还有更旧记录 */
  total: number
}

/** 会话详情（`AiConversationDetailOut`） */
export interface AiConversationDetail {
  conversation: AiConversationSummary
  messages: AiChatMessage[]
}

/** AI 用量记录（`AiUsageItem`） */
export interface AiUsageItem {
  id: number
  conversation_id: number | null
  request_id: string | null
  operation: string
  status: string
  units: number
  created_at: string
}

/** 当日 AI 问答额度（`AiUsageOut`） */
export interface AiUsage {
  date: string
  used: number
  limit: number
  remaining: number
  items: AiUsageItem[]
}

/** 改期影响预览（`TaskChangeImpactOut`） */
export interface TaskChangeMember {
  id: number
  name: string
}

export interface TaskChangeImpact {
  task_id: number
  title: string
  current_deadline: string | null
  proposed_deadline: string | null
  reminders_reset: boolean
  affected_members: TaskChangeMember[]
  downstream_tasks: Array<{ id: number; title: string; status: string }>
  notified_user_ids: number[]
}

/** PATCH 任务后的变更结果（`C-TASK-CHANGE@1`） */
export interface TaskChangeSummary {
  kind: 'deadline' | 'cancelled'
  old_deadline: string | null
  new_deadline: string | null
  reminders_stale: number
  notifications_created: number
  downstream_tasks: Array<{ id: number; title: string }>
  notified_user_ids: number[]
}
// --------------------------------------------------------------------------- //
// 资料与成果审核（`C-RESOURCE@1` / `C-SUBMISSION@1` / `C-PRECHECK@1`）
// --------------------------------------------------------------------------- //

/** 资料条目（`ResourceOut`）：同一 `resource_key` 可有多个版本 */
export interface ResourceItem {
  id: number
  resource_key: string
  activity_id: number | null
  task_id: number | null
  org_id: number | null
  activity_title: string | null
  title: string
  summary: string | null
  resource_type: string
  url: string
  version: number
  created_by: number
  created_by_name: string
  created_at: string
}

export interface ResourceListResult {
  items: ResourceItem[]
  total: number
}

/** 资料创建 / 追加版本入参 */
export interface ResourceCreatePayload {
  title: string
  url: string
  summary?: string | null
  resource_type?: string
  activity_id?: number | null
  task_id?: number | null
  org_id?: number | null
  resource_key?: string | null
}

/** 成果提交入参：两项均可留空（保持旧的无 body 提交语义） */
export interface SubmitPayload {
  content?: string | null
  resource_url?: string | null
}

// --------------------------------------------------------------------------- //
// 成果提交策略（`C-SUBMISSION-POLICY@1`）
// --------------------------------------------------------------------------- //

/** 成果提交方式：文字说明 / 成果链接 / 文件上传 */
export type SubmissionMode = 'text' | 'link' | 'file'

/** 全部提交方式（顺序即界面顺序） */
export const SUBMISSION_MODES: SubmissionMode[] = ['text', 'link', 'file']

/** 提交方式展示名 */
export const SUBMISSION_MODE_LABELS: Record<SubmissionMode, string> = {
  text: '文字说明',
  link: '成果链接',
  file: '文件上传'
}

/** 未配置策略时的文件扩展名白名单（与后端全局白名单一致） */
export const SUBMISSION_FILE_EXTS: string[] = ['.pdf', '.docx', '.txt', '.md']

/** 扩展名展示名 */
export const SUBMISSION_FILE_LABELS: Record<string, string> = {
  '.pdf': 'PDF',
  '.docx': 'DOCX',
  '.txt': 'TXT',
  '.md': 'Markdown'
}

/** 任务成果提交策略（`tasks.extras["acceptance"]`） */
export interface SubmissionAcceptance {
  modes: SubmissionMode[]
  allowed_exts: string[]
  ai_precheck: boolean
}

/** 扩展名展示名；未知类型原样返回，避免界面出现空标签 */
export function submissionFileLabel(ext: string): string {
  return SUBMISSION_FILE_LABELS[ext] ?? ext
}

export function isSubmissionMode(value: unknown): value is SubmissionMode {
  return value === 'text' || value === 'link' || value === 'file'
}

/**
 * 解析 `extras.acceptance`。
 * 未配置或结构非法时返回 `null`，调用方按「三种方式全允许」处理。
 */
export function parseSubmissionAcceptance(
  extras: Record<string, unknown> | null | undefined
): SubmissionAcceptance | null {
  const raw = extras?.acceptance
  if (raw === null || raw === undefined || typeof raw !== 'object' || Array.isArray(raw)) {
    return null
  }
  const record = raw as Record<string, unknown>
  const modes = Array.isArray(record.modes)
    ? [...new Set(record.modes.filter(isSubmissionMode))]
    : []
  if (modes.length === 0) return null
  const allowedExts = Array.isArray(record.allowed_exts)
    ? [
        ...new Set(
          record.allowed_exts
            .filter((ext): ext is string => typeof ext === 'string')
            .map((ext) => ext.trim().toLowerCase())
            .filter((ext) => SUBMISSION_FILE_EXTS.includes(ext))
        )
      ]
    : []
  return { modes, allowed_exts: allowedExts, ai_precheck: record.ai_precheck === true }
}

/**
 * 有效文件扩展名：`allowed_exts` 为空（或全部非法）时回退为全局四类。
 * 后端对空 `allowed_exts` 按「不限具体类型」处理，前端渲染与校验必须保持同一语义。
 */
export function effectiveSubmissionFileExts(allowedExts: string[]): string[] {
  const normalized = [
    ...new Set(
      allowedExts
        .map((ext) => ext.trim().toLowerCase())
        .filter((ext) => SUBMISSION_FILE_EXTS.includes(ext))
    )
  ]
  return normalized.length > 0 ? normalized : [...SUBMISSION_FILE_EXTS]
}

/** 成果要求摘要（与任务详情同文案）：未配置返回空串，由调用方决定兜底文案 */
export function submissionAcceptanceSummary(acceptance: SubmissionAcceptance | null): string {
  if (!acceptance) return ''
  const parts = [acceptance.modes.map((mode) => SUBMISSION_MODE_LABELS[mode]).join(' / ')]
  if (acceptance.modes.includes('file')) {
    const fileLabels = effectiveSubmissionFileExts(acceptance.allowed_exts)
      .map(submissionFileLabel)
      .join(' / ')
    parts.push(`文件类型：${fileLabels}`)
  }
  if (acceptance.ai_precheck) parts.push('AI 成果预审已开启')
  return parts.join(' · ')
}

export type PrecheckStatus = 'pass' | 'fail' | 'warn' | 'unknown'
export type PrecheckVerdict = 'pass' | 'fail' | 'unknown'

export interface PrecheckItem {
  key: string
  label: string
  status: PrecheckStatus
  message: string
  evidence: string | null
  source: string | null
}

export interface PrecheckSuggestion {
  key: string
  message: string
  evidence: string | null
}

/** 预审结果（`PrecheckOut`）：规则结论 + 可选 AI 建议 */
export interface PrecheckResult {
  submission_id: number
  requirement_digest: string
  checks: PrecheckItem[]
  verdict: PrecheckVerdict
  summary: string | null
  ai_suggestions: PrecheckSuggestion[]
  mock: boolean
  ai_error: string | null
  created_at: string
}

/** 版本列表中的预审摘要；`stale` 表示任务要求或引用资料已变化 */
export interface PrecheckSummary {
  id: number
  verdict: PrecheckVerdict
  summary: string | null
  mock: boolean
  ai_error: string | null
  requirement_digest: string
  stale: boolean
  created_at: string
}

/** 单条成果版本（`SubmissionOut`） */
export interface SubmissionItem {
  id: number
  task_id: number
  user_id: number
  user_name: string
  version: number
  content: string | null
  resource_url: string | null
  /** 成果文件（`C-SUBMISSION-FILE@1`）：文件名/大小/MIME；下载走同源接口 */
  file_name: string | null
  file_size: number | null
  file_mime: string | null
  created_at: string
  latest: boolean
  precheck: PrecheckSummary | null
}

export interface SubmissionListResult {
  items: SubmissionItem[]
}
// --------------------------------------------------------------------------- //
// AI 任务树草案 / 成果归档（`C-AI-DRAFT@1` / `C-ARCHIVE@1`，S5 §2.2）
// --------------------------------------------------------------------------- //

/** 草案中的单个任务（`TaskDraftItem`）：只含可编辑的任务树字段，不含发布动作 */
export interface TaskDraftItem {
  key: string
  title: string
  sop_guide: string | null
  deadline: string | null
  depends_on_keys: string[]
  parent_key: string | null
}

/** 草案参考资料来源（只读展示）：组织开放资料的 id 与标题 */
export interface TaskDraftSource {
  resource_id: number
  title: string
}

/** AI 任务树草案返回（`POST /api/ai/task-draft`）：只读，不写库 */
export interface TaskDraftResult {
  activity_title: string
  tasks: TaskDraftItem[]
  sources: TaskDraftSource[]
  /** mock 模式下的确定性草案 */
  mock: boolean
}

/** 已验收成果归档请求体（`POST /api/org-resources/from-submission`） */
export interface ArchiveSubmissionPayload {
  submission_id: number
  org_id: number
  /** 缺省时服务端使用「任务标题 · 提交人姓名」 */
  title?: string | null
}
// --------------------------------------------------------------------------- //
// 组织资料库（`C-ORG-LIBRARY@1`）
// --------------------------------------------------------------------------- //

/** 正文解析状态（`org_resources.text_status`）：解析失败不阻断保存 */
export type OrgResourceTextStatus = 'pending' | 'ready' | 'failed'

/** 组织资料（`OrgResourceOut`）：响应不含解析正文，`search_text` 也不外露 */
export interface OrgResource {
  id: number
  org_id: number
  title: string
  summary: string | null
  resource_type: 'file' | 'link'
  /** link 必填；file 为空 */
  url: string | null
  file_name: string | null
  file_mime: string | null
  file_size: number | null
  text_status: OrgResourceTextStatus
  /** 后端按 0/1 存储、PATCH 接受 bool；读取时兼容两种形态 */
  allow_student_ai: boolean | number
  archived: boolean | number
  created_by: number
  created_at: string
  updated_at: string
}
// --------------------------------------------------------------------------- //
// 个人 Library 引用（`C-LIB-REF@1`）
// --------------------------------------------------------------------------- //

/**
 * AI 收藏的引用资料（`LibraryRefOut`）：只含当前仍可访问的引用，不复制文件。
 * 已撤回 / 归档的引用不出现在列表项中，只在响应的 `revoked_count` 里计数。
 */
export interface LibraryRef {
  resource_id: number
  title: string
  summary: string | null
  resource_type: 'file' | 'link'
  file_name: string | null
  file_size: number | null
  url: string | null
  org_id: number
  added_at: string
  last_used_at: string
}
