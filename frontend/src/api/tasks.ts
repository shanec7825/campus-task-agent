/**
 * 任务 / 流转 API（契约 C-FEAPI@1 / C-TASKS@1）。
 * 签到与积分分别见 `api/checkin.ts` / `api/credits.ts`。
 */
import { request } from './client'
import type {
  ApplyResult,
  DecomposeResult,
  ProgressItem,
  TaskCreatePayload,
  TaskDetail,
  TaskItem,
  TaskListResult,
  VerifyResult
} from '../types/models'

/** 任务列表 / 详情 / 发布 / 修改 */
export function listTasks(p?: {
  status?: string
  scope?: 'all' | 'mine'
  include_sub?: boolean
}): Promise<TaskListResult> {
  return request<TaskListResult>('GET', '/api/tasks', undefined, p)
}

export function createTask(p: TaskCreatePayload): Promise<TaskItem> {
  return request<TaskItem>('POST', '/api/tasks', p)
}

export function getTask(id: number): Promise<TaskDetail> {
  return request<TaskDetail>('GET', `/api/tasks/${id}`)
}

export function patchTask(
  id: number,
  p: Partial<TaskCreatePayload> & { status?: string }
): Promise<TaskItem> {
  return request<TaskItem>('PATCH', `/api/tasks/${id}`, p)
}

/**
 * 任务流转
 *
 * `claim` 是 A1 `/api/tasks/{id}/apply` 的兼容别名（A6，`C-APPLY@1`）：语义**已变为「报名」**，
 * 返回 `ApplyResult`（含最新 `task` 与 `application`），不再直接把当前用户置为负责人。
 * 新代码建议直接用 `api/applications.applyTask`；此处保留以避免旧调用 404。
 */
export function claimTask(id: number): Promise<ApplyResult> {
  return request<ApplyResult>('POST', `/api/tasks/${id}/claim`)
}

export function assignTask(id: number, userId: number): Promise<TaskItem> {
  return request<TaskItem>('POST', `/api/tasks/${id}/assign`, { user_id: userId })
}

export function updateProgress(id: number, content: string): Promise<ProgressItem> {
  return request<ProgressItem>('POST', `/api/tasks/${id}/progress`, { content })
}

export function submitTask(id: number): Promise<TaskItem> {
  return request<TaskItem>('POST', `/api/tasks/${id}/submit`)
}

/**
 * 验收 / 退回单个成员（`C-TASK-API@1`）。
 * 传入 `userId` 时只处理该成员；省略时由后端按已提交成员选择目标。
 */
export function verifyTask(
  id: number,
  pass: boolean,
  reason?: string,
  userId?: number
): Promise<VerifyResult> {
  const payload: { pass: boolean; reason?: string; user_id?: number } = { pass }
  if (reason !== undefined) payload.reason = reason
  if (userId !== undefined) payload.user_id = userId
  return request<VerifyResult>('POST', `/api/tasks/${id}/verify`, payload)
}

/** 拆解（仅发布者，不落库） */
export function decomposeTask(id: number): Promise<DecomposeResult> {
  return request<DecomposeResult>('POST', `/api/tasks/${id}/decompose`)
}
