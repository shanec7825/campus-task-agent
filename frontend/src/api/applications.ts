/**
 * 报名 / 审批 API（契约 `C-FEAPI-APPLY@1` / `C-APPLY@1`）。
 *
 * 语义要点：
 * - 报名不再直接成为负责人，而是生成一条 `pending` 报名记录，由发布者审批；
 * - `claim` 是 A1 的兼容别名（见 `api/tasks.ts` 的 `claimTask`），两者返回同构 `ApplyResult`；
 * - 所有请求经 `request` 统一解包，禁止页面出现裸 `fetch('/api/...')`。
 */
import { request } from './client'
import type { ApplicationItem, ApplicationWithTask, ApplyResult } from '../types/models'

/** A1 报名（POST /api/tasks/{id}/apply） */
export function applyTask(taskId: number): Promise<ApplyResult> {
  return request<ApplyResult>('POST', `/api/tasks/${taskId}/apply`)
}

/** A2 撤回报名（仅 `pending` 可撤回；POST /api/tasks/{id}/apply/withdraw） */
export function withdrawApply(taskId: number): Promise<ApplyResult> {
  return request<ApplyResult>('POST', `/api/tasks/${taskId}/apply/withdraw`)
}

/** A3 发布者查看报名列表（GET /api/tasks/{id}/applications，含 cancelled/rejected，由前端自行过滤） */
export function listApplications(taskId: number): Promise<{ items: ApplicationItem[] }> {
  return request<{ items: ApplicationItem[] }>('GET', `/api/tasks/${taskId}/applications`)
}

/**
 * A4 审批（POST /api/applications/{id}/decide）。
 * 仅在 `reason` 非 undefined 时放入请求体（与 `verifyTask` 同风格）；拒绝时后端要求 reason 非空。
 */
export function decideApplication(
  applicationId: number,
  approve: boolean,
  reason?: string
): Promise<ApplyResult> {
  const payload: { approve: boolean; reason?: string } = { approve }
  if (reason !== undefined) payload.reason = reason
  return request<ApplyResult>('POST', `/api/applications/${applicationId}/decide`, payload)
}

/** A5 我的报名（GET /api/applications/me，按报名时间倒序） */
export function myApplications(): Promise<{ items: ApplicationWithTask[] }> {
  return request<{ items: ApplicationWithTask[] }>('GET', '/api/applications/me')
}