<script setup lang="ts">
/**
 * 发布者后台（计划 T6 / R3-AC5 / R3-AC8 / R5）。
 *
 * - 任务列表（表格）：仅当前用户作为 `publisher_id` 的任务；
 * - 指派弹窗：候选来自任务中已出现的用户，后端无用户列表接口时允许手输用户 ID；
 * - 验收：仅 `publisher_id === 当前用户` 且状态为 `submitted` 时可见，先选择通过/驳回（驳回必填原因）；
 * - 催办规则：`ReminderRuleForm` 校验通过后通过 `PATCH /api/tasks/{id}` 保存。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { decideApplication, listApplications } from '../api/applications'
import { ApiError } from '../api/client'
import { assignTask, listTasks, patchTask, verifyTask } from '../api/tasks'
import AssignDialog, { type AssignCandidate } from '../components/admin/AssignDialog.vue'
import ReminderRuleForm, { DEFAULT_REMINDER_RULE } from '../components/admin/ReminderRuleForm.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import StatusTag from '../components/task/StatusTag.vue'
import { applicationStatusMeta, formatDeadline, memberStatusMeta } from '../components/task/TaskCard.vue'
import { useUserStore } from '../stores/user'
import type { ApplicationItem, ReminderRule, TaskItem, TaskMember } from '../types/models'

const router = useRouter()
const userStore = useUserStore()

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')

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

/** 截止时间编辑（R4：改期后可继续提交并按新时间提醒） */
const deadlineVisible = ref(false)
const deadlineTarget = ref<TaskItem | null>(null)
const deadlineValue = ref<string | null>(null)
const deadlineLoading = ref(false)
/** 取消任务进行中的任务 id（防重复点击） */
const cancelLoadingId = ref<number | null>(null)

const ruleVisible = ref(false)
const ruleTarget = ref<TaskItem | null>(null)
const ruleDraft = ref<ReminderRule>({ ...DEFAULT_REMINDER_RULE })
const ruleLoading = ref(false)

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
}

async function submitVerify(): Promise<void> {
  const target = verifyTarget.value
  if (!target) return
  if (verifyMemberId.value === undefined) {
    ElMessage.warning('请选择要验收的成员')
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
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    verifyLoading.value = false
  }
}

function openDeadline(task: TaskItem): void {
  deadlineTarget.value = task
  deadlineValue.value = task.deadline ?? null
  deadlineVisible.value = true
}

async function saveDeadline(): Promise<void> {
  const target = deadlineTarget.value
  if (!target) return
  // 留空表示清除截止时间：后端 `PATCH` 支持 `{deadline: null}`
  const deadline = deadlineValue.value ? deadlineValue.value : null
  deadlineLoading.value = true
  try {
    await patchTask(target.id, { deadline })
    ElMessage.success(
      deadline
        ? '截止时间已更新，后续提醒按新时间执行'
        : '截止时间已清除，将不再触发基于截止时间的催办'
    )
    deadlineVisible.value = false
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
  await load()
})
</script>

<template>
  <section class="admin">
    <header class="page-header">
      <div>
        <h2 class="page-title">发布者后台</h2>
        <p class="page-subtitle">任务指派、验收结算与分级催办规则配置</p>
      </div>
      <div class="header-actions">
        <el-button @click="goPublish">发布新任务</el-button>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </header>

    <el-card v-if="!isPublisher" shadow="never" class="section-card">
      <el-result
        icon="warning"
        title="当前账号不是发布者"
        sub-title="发布者后台仅对 role=publisher 的账号（如 teacher01）开放。"
      />
    </el-card>

    <template v-else>
      <el-card shadow="never" class="section-card">
        <template #header>
          <div class="card-header">
            <span class="card-title">我的发布任务（{{ tasks.length }}）</span>
            <span class="header-hint">验收按成员逐人进行（仅列已提交成员）；催办规则保存后由后端调度器执行</span>
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
        <el-table v-else :data="tasks" size="small" stripe class="task-table">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column label="标题" min-width="200">
            <template #default="scope">
              <el-link type="primary" :underline="false" @click="goDetail(scope.row.id)">
                {{ scope.row.title }}
              </el-link>
              <el-tag v-if="scope.row.parent_id !== null" size="small" type="warning" effect="plain" class="row-tag">
                子任务
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="95">
            <template #default="scope">
              <StatusTag :status="scope.row.status" size="small" />
            </template>
          </el-table-column>
          <el-table-column label="分配" width="110">
            <template #default="scope">
              <el-tag size="small" effect="plain" :type="scope.row.claim_type === 'assign' ? 'info' : 'success'">
                {{ scope.row.claim_type === 'assign' ? '指派' : '开放认领' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="成员" width="150">
            <template #default="scope">
              <div class="member-cell">
                <span>{{ memberNames(scope.row) }}</span>
                <el-tag
                  v-if="submittedMembers(scope.row).length > 0"
                  size="small"
                  type="warning"
                  effect="plain"
                >
                  待验收 {{ submittedMembers(scope.row).length }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="报名" width="150">
            <template #default="scope">
              <div class="apply-cell">
                <span class="rule-summary">{{ quotaSummary(scope.row) }}</span>
                <el-tag
                  v-if="scope.row.applied_count > 0"
                  size="small"
                  type="warning"
                  effect="plain"
                >
                  待审批 {{ scope.row.applied_count }}
                </el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="截止" width="150">
            <template #default="scope">{{ formatDeadline(scope.row.deadline) }}</template>
          </el-table-column>
          <el-table-column label="积分" width="80">
            <template #default="scope">+{{ scope.row.credit_reward ?? 0 }}</template>
          </el-table-column>
          <el-table-column label="催办规则" min-width="170">
            <template #default="scope">
              <span class="rule-summary">{{ ruleSummary(scope.row) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="380" fixed="right">
            <template #default="scope">
              <div class="row-actions">
                <el-button
                  v-if="canAudit(scope.row)"
                  size="small"
                  text
                  type="warning"
                  @click="openAudit(scope.row)"
                >
                  审核报名（{{ scope.row.applied_count }}）
                </el-button>
                <el-button
                  v-if="canAssign(scope.row)"
                  size="small"
                  text
                  type="primary"
                  @click="openAssign(scope.row)"
                >
                  指派
                </el-button>
                <el-button
                  v-if="canVerify(scope.row)"
                  size="small"
                  text
                  type="success"
                  @click="openVerify(scope.row)"
                >
                  验收（{{ submittedMembers(scope.row).length }}）
                </el-button>
                <el-button
                  v-if="canEditDeadline(scope.row)"
                  size="small"
                  text
                  @click="openDeadline(scope.row)"
                >
                  改截止时间
                </el-button>
                <el-button size="small" text @click="openRule(scope.row)">催办规则</el-button>
                <el-button size="small" text @click="goDetail(scope.row.id)">详情</el-button>
                <el-button
                  v-if="canCancel(scope.row)"
                  size="small"
                  text
                  type="danger"
                  :loading="cancelLoadingId === scope.row.id"
                  @click="handleCancel(scope.row)"
                >
                  取消任务
                </el-button>
              </div>
            </template>
          </el-table-column>
        </el-table>
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
              </el-radio>
            </el-radio-group>
            <span v-if="verifyTarget && submittedMembers(verifyTarget).length === 0" class="verify-hint">
              当前没有待验收的成员
            </span>
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
          v-if="verifyChoice === 'pass'"
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
        <el-button type="primary" :loading="verifyLoading" @click="submitVerify">
          {{ verifyChoice === 'pass' ? '确认通过' : '确认退回' }}
        </el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="deadlineVisible" title="修改截止时间" width="460px" :close-on-click-modal="false">
      <p class="verify-task">{{ deadlineTarget?.title }}</p>
      <el-form label-position="top">
        <el-form-item label="截止时间（留空表示清除 / 不设置截止）">
          <el-date-picker
            v-model="deadlineValue"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择截止时间，留空表示清除"
            class="deadline-picker"
          />
        </el-form-item>
      </el-form>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="改期后后续提醒按新时间执行；逾期扣分不会退回，成员仍可在新截止时间前后提交。"
      />
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="留空保存将清除截止时间，之后不再触发基于截止时间的催办与逾期扣分。"
      />
      <template #footer>
        <el-button :disabled="deadlineLoading" @click="deadlineVisible = false">取消</el-button>
        <el-button type="primary" :loading="deadlineLoading" @click="saveDeadline">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="ruleVisible" title="催办规则" width="600px" :close-on-click-modal="false">
      <p class="verify-task">{{ ruleTarget?.title }}</p>
      <ReminderRuleForm v-model="ruleDraft" :loading="ruleLoading" @submit="saveRule" />
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
      <el-table v-else :data="pendingApplications" size="small" stripe>
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

      <template #footer>
        <el-button :loading="appsLoading" @click="loadApplications">刷新</el-button>
        <el-button @click="auditVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.admin {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  flex-wrap: wrap;
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

.header-actions {
  display: flex;
  gap: 8px;
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
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}

.header-hint {
  font-size: 13px;
  color: #909399;
}

.task-table :deep(.el-table__cell) {
  vertical-align: middle;
}

.row-tag {
  margin-left: 6px;
}

.row-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.rule-summary {
  font-size: 13px;
  color: #606266;
}

.apply-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.member-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
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

.verify-hint {
  font-size: 13px;
  color: #909399;
}

.audit-hint {
  margin: 4px 0 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.audit-user {
  font-weight: 500;
  color: #303133;
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
  color: #303133;
  word-break: break-word;
}
</style>