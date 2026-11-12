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
}>()

const blockReason = computed<string>(() => applyBlockReason(props.task, props.currentUserId))
const deadlineText = computed<string>(() => formatDeadline(props.task.deadline))
const quotaProgress = computed<string>(() => quotaText(props.task))
const applicationMeta = computed(() => applicationStatusMeta(props.task.my_application_status))
const memberMeta = computed(() => memberStatusMeta(props.task.my_member_status))
const rewardText = computed<string>(() => `+${props.task.credit_reward ?? 0} 积分`)
const isSubTask = computed<boolean>(() => props.task.parent_id !== null)

/** 按钮文案随报名状态变化：报名 / 已报名 / 已通过 / 不可报名（实现要点 2） */
const buttonText = computed<string>(() => {
  const status = props.task.my_application_status
  if (status === 'pending') return '已报名'
  if (status === 'approved') return '已通过'
  return blockReason.value ? '不可报名' : '报名'
})
</script>

<template>
  <el-card class="task-card" shadow="hover" body-class="task-card-body">
    <div class="card-header">
      <div class="title-line">
        <h3 class="card-title" :title="task.title">{{ task.title }}</h3>
        <el-tag v-if="isSubTask" size="small" type="warning" effect="plain">子任务</el-tag>
      </div>
      <div class="status-line">
        <StatusTag :status="task.status" />
        <el-tag
          v-if="task.my_application_status"
          :type="applicationMeta.type"
          size="small"
          effect="plain"
        >
          {{ applicationMeta.text }}
        </el-tag>
        <el-tag
          v-if="task.my_member_status"
          :type="memberMeta.type"
          size="small"
          effect="dark"
        >
          我：{{ memberMeta.text }}
        </el-tag>
      </div>
    </div>

    <p class="card-description">{{ task.description || '暂无任务描述' }}</p>

    <div class="card-meta">
      <span class="meta-item">
        <span class="meta-label">名额</span>{{ quotaProgress }}
      </span>
      <span v-if="task.applied_count > 0" class="meta-item">
        <span class="meta-label">待审批</span>{{ task.applied_count }} 人
      </span>
      <span class="meta-item">
        <span class="meta-label">奖励</span>{{ rewardText }}
      </span>
      <span class="meta-item">
        <span class="meta-label">截止</span>{{ deadlineText }}
      </span>
      <span v-if="task.location" class="meta-item">
        <span class="meta-label">地点</span>{{ task.location }}
      </span>
    </div>

    <div class="card-footer">
      <span class="publisher">发布者：{{ task.publisher_name || '—' }}</span>
      <div class="actions">
        <el-button size="small" text type="primary" @click="emit('open', task.id)">查看详情</el-button>
        <el-button
          size="small"
          type="primary"
          :disabled="Boolean(blockReason)"
          :loading="applying"
          @click="emit('apply', task)"
        >
          {{ buttonText }}
        </el-button>
      </div>
    </div>

    <p v-if="blockReason" class="apply-reason">{{ blockReason }}</p>
  </el-card>
</template>

<style scoped>
.task-card {
  height: 100%;
  border-radius: 10px;
  display: flex;
  flex-direction: column;
}

.task-card :deep(.task-card-body) {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 10px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.card-title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 4px;
  flex-shrink: 0;
}

.card-description {
  margin: 0;
  font-size: 14px;
  color: #606266;
  line-height: 1.6;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  min-height: 41px;
  word-break: break-word;
}

.card-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 14px;
  font-size: 14px;
  color: #303133;
}

.meta-label {
  color: #909399;
  margin-right: 4px;
}

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: auto;
  padding-top: 8px;
  border-top: 1px dashed #ebeef5;
}

.publisher {
  font-size: 13px;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.apply-reason {
  margin: 0;
  font-size: 13px;
  color: #e6a23c;
  line-height: 1.5;
}
</style>