<script lang="ts">
import type { ApplicationStatus, MemberStatus, TaskItem } from '../../types/models'
import { statusText } from './StatusTag.vue'

/**
 * 报名状态文案与颜色（**唯一来源**，TaskDetail / Profile / AdminConsole 复用）。
 *
 * `null` 表示「未报名」；`rejected` / `cancelled` 允许重新报名（R16-AC4）。
 */
export type ApplicationTagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export interface ApplicationStatusMeta {
  text: string
  type: ApplicationTagType
}

export const APPLICATION_STATUS_MAP: Record<string, ApplicationStatusMeta> = {
  pending: { text: '待审批', type: 'warning' },
  approved: { text: '已通过', type: 'success' },
  rejected: { text: '已拒绝（可重新报名）', type: 'danger' },
  cancelled: { text: '已撤回（可重新报名）', type: 'info' }
}

/** 未报名（`my_application_status === null`）的展示项 */
export const NO_APPLICATION_META: ApplicationStatusMeta = { text: '未报名', type: 'info' }

export function applicationStatusMeta(
  status: ApplicationStatus | null | undefined
): ApplicationStatusMeta {
  if (!status) return NO_APPLICATION_META
  return APPLICATION_STATUS_MAP[status] ?? NO_APPLICATION_META
}

/**
 * 成员执行状态文案与颜色（`MemberStatus`，`C-FE-MEMBER@1` 唯一来源）。
 *
 * 任务聚合状态不等于「我」的执行状态：卡片与详情页一律以本映射展示个人状态。
 */
export const MEMBER_STATUS_MAP: Record<string, ApplicationStatusMeta> = {
  not_started: { text: '未开始', type: 'info' },
  in_progress: { text: '进行中', type: 'primary' },
  submitted: { text: '待验收', type: 'warning' },
  rejected: { text: '已退回', type: 'danger' },
  verified: { text: '已通过', type: 'success' }
}

/** 非成员（`my_member_status === null`）的展示项 */
export const NO_MEMBER_STATUS_META: ApplicationStatusMeta = { text: '非成员', type: 'info' }

export function memberStatusMeta(
  status: MemberStatus | null | undefined
): ApplicationStatusMeta {
  if (!status) return NO_MEMBER_STATUS_META
  return MEMBER_STATUS_MAP[status] ?? NO_MEMBER_STATUS_META
}

/**
 * 是否为「已通过审核的成员」（多负责人模型，`C-APPLY@1`）。
 *
 * - 新版：`my_application_status === 'approved'`；
 * - legacy 回退（P1 数据未迁移）：`assignee_id === 当前用户 && approved_count > 0`。
 */
export function isApprovedMember(task: TaskItem, userId: number | null): boolean {
  if (userId === null) return false
  if (task.my_application_status === 'approved') return true
  return task.assignee_id === userId && task.approved_count > 0
}

/**
 * 计算报名按钮不可用的原因（空字符串表示可报名）。
 *
 * 判定顺序**严格对齐后端 A1 的校验顺序**（`C-APPLY@1`）：
 * 状态 → 已报名（pending/approved） → 名额已满 → 自己发布 → 前置依赖未完成。
 * 前置依赖是否完成前端无法直接得知，故用后端派生的 `is_claimable` 作为判据
 * （此前的分支已排除其它原因）。真正能否报名以后端返回为准。
 */
export function applyBlockReason(task: TaskItem, currentUserId: number | null): string {
  if (task.status !== 'published' && task.status !== 'claimed') {
    return `任务${statusText(task.status)}，当前不可报名`
  }
  if (task.my_application_status === 'pending') return '已报名，等待审核'
  if (task.my_application_status === 'approved') return '报名已通过'
  if (task.quota !== null && task.approved_count >= task.quota) return '名额已满'
  if (currentUserId !== null && task.publisher_id === currentUserId) return '自己发布的任务不可报名'
  if (task.depends_on !== null && !task.is_claimable) return '前置任务尚未完成'
  return ''
}

/** `applyBlockReason` 的兼容别名（P1 命名为 claim，语义已变为报名） */
export function claimBlockReason(task: TaskItem, currentUserId: number | null): string {
  return applyBlockReason(task, currentUserId)
}

/** 名额进度文案：`quota` 为 `null` 视为不限名额（R16-AC2 / R16-AC15） */
export function quotaText(task: TaskItem): string {
  if (task.quota === null) return `已通过 ${task.approved_count} 人（不限名额）`
  return `已通过 ${task.approved_count}/${task.quota}`
}

/** 截止时间展示：截断到分钟，空值显示「不限」 */
export function formatDeadline(deadline: string | null): string {
  if (!deadline) return '不限'
  return deadline.length > 16 ? deadline.slice(0, 16) : deadline
}
</script>

<script setup lang="ts">
import { computed } from 'vue'

import StatusTag from './StatusTag.vue'

const props = withDefaults(
  defineProps<{
    task: TaskItem
    currentUserId?: number | null
    /** 报名请求进行中（按钮 loading） */
    applying?: boolean
  }>(),
  { currentUserId: null, applying: false }
)

const emit = defineEmits<{
  (e: 'apply', task: TaskItem): void
  (e: 'open', id: number): void
  (e: 'manage', id: number): void
}>()

const SELF_PUBLISH_REASON = '自己发布的任务不可报名'

const isPublisher = computed<boolean>(
  () => props.currentUserId !== null && props.task.publisher_id === props.currentUserId
)
const isPendingApplication = computed<boolean>(() => props.task.my_application_status === 'pending')
const canUpdateProgress = computed<boolean>(
  () =>
    props.task.my_application_status === 'approved' &&
    props.task.my_member_status !== 'verified'
)

const blockReason = computed<string>(() => applyBlockReason(props.task, props.currentUserId))

/** 发布者卡片由「管理」主操作覆盖，不再重复整行警告 */
const showBlockReason = computed<boolean>(
  () => blockReason.value !== '' && blockReason.value !== SELF_PUBLISH_REASON
)

interface PrimaryAction {
  text: string
  disabled: boolean
}

/** 主操作唯一优先级：发布者 → 已通过成员 → 待审批 → 报名 */
const primaryAction = computed<PrimaryAction>(() => {
  if (isPublisher.value) return { text: '管理', disabled: false }
  if (canUpdateProgress.value) return { text: '更新进度', disabled: false }
  if (isPendingApplication.value) return { text: '已报名', disabled: true }
  if (blockReason.value) return { text: '不可报名', disabled: true }
  return { text: '报名', disabled: false }
})

function handlePrimary(): void {
  if (primaryAction.value.disabled) return
  if (isPublisher.value) {
    emit('manage', props.task.id)
    return
  }
  if (canUpdateProgress.value) {
    emit('open', props.task.id)
    return
  }
  emit('apply', props.task)
}

const deadlineText = computed<string>(() => formatDeadline(props.task.deadline))

/** 临近截止：解析失败不标注，「3 天内」含已逾期 */
const deadlineNear = computed<boolean>(() => {
  if (!props.task.deadline) return false
  const time = new Date(props.task.deadline.replace(' ', 'T')).getTime()
  if (Number.isNaN(time)) return false
  return time - Date.now() <= 3 * 86400000
})

const personalMeta = computed(() =>
  props.task.my_member_status
    ? memberStatusMeta(props.task.my_member_status)
    : applicationStatusMeta(props.task.my_application_status)
)
const personalLabel = computed<string>(() => {
  if (props.task.my_member_status) return `我：${personalMeta.value.text}`
  if (props.task.my_application_status) return `报名：${personalMeta.value.text}`
  return ''
})

/** 名额 / 地点 / 积分 / 发布者合并为一条次级信息 */
const secondaryText = computed<string>(() => {
  const parts: string[] = [quotaText(props.task)]
  if (props.task.location) parts.push(props.task.location)
  if (props.task.credit_reward !== null) parts.push(`+${props.task.credit_reward} 积分`)
  parts.push(`发布者：${props.task.publisher_name || '—'}`)
  return parts.join(' · ')
})
</script>

<template>
  <el-card class="task-card" shadow="hover" body-class="task-card-body">
    <article class="task-card-content">
      <h3 class="card-title" :title="task.title">{{ task.title }}</h3>

      <p class="card-deadline">
        <span>截止 {{ deadlineText }}</span>
        <span v-if="deadlineNear" class="deadline-near">临近</span>
      </p>

      <!-- 最多两个标签：任务状态 + 个人状态（执行状态优先于报名状态） -->
      <div class="status-line">
        <StatusTag :status="task.status" size="small" />
        <el-tag v-if="personalLabel" :type="personalMeta.type" size="small" effect="plain">
          {{ personalLabel }}
        </el-tag>
      </div>

      <p class="card-secondary">{{ secondaryText }}</p>

      <div class="card-actions">
        <el-button size="small" text type="primary" @click="emit('open', task.id)">
          查看详情
        </el-button>
        <el-button
          size="small"
          type="primary"
          :disabled="primaryAction.disabled"
          :loading="applying"
          @click="handlePrimary"
        >
          {{ primaryAction.text }}
        </el-button>
      </div>

      <!-- 阻断原因只在主操作下方以小字说明，不做整行警告条 -->
      <p v-if="showBlockReason" class="apply-reason">{{ blockReason }}</p>
    </article>
  </el-card>
</template>

<style scoped>
.task-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.task-card :deep(.task-card-body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 8px;
}

.task-card-content {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.card-title {
  margin: 0;
  font-size: var(--el-font-size-medium);
  font-weight: 600;
  line-height: 1.4;
  color: var(--app-text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  word-break: break-word;
}

.card-deadline {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px;
  margin: 0;
  font-size: var(--app-font-body, 15px);
  font-weight: 400;
  color: var(--app-text);
}

.deadline-near {
  font-size: var(--app-font-aux, 13px);
  font-weight: 600;
  color: var(--el-color-warning);
}

.status-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.card-secondary {
  margin: 0;
  font-size: var(--app-font-aux, 13px);
  line-height: 1.5;
  color: var(--app-text-muted);
  word-break: break-word;
}

.apply-reason {
  margin: 0;
  font-size: var(--app-font-aux, 13px);
  line-height: 1.5;
  text-align: right;
  color: var(--el-color-warning);
}

.card-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-top: auto;
  padding-top: 10px;
  border-top: 1px dashed var(--app-border);
}

@media (max-width: 768px) {
  .card-actions {
    gap: 10px;
  }

  .card-actions :deep(.el-button) {
    flex: 1 1 0;
    margin-left: 0;
  }
}
</style>