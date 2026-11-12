/**
 * 签到 API（契约 C-FEAPI@1 / C-TASKS@1 #11/#12）。
 */
import { request } from './client'
import type { CheckinItem, CheckinListResult } from '../types/models'

/** 签到（同一任务重复签到由后端返回 4090） */
export function checkin(taskId: number): Promise<CheckinItem> {
  return request<CheckinItem>('POST', '/api/checkin', { task_id: taskId })
}

/** 我的全部签到记录 */
export function myCheckins(): Promise<CheckinListResult> {
  return request<CheckinListResult>('GET', '/api/checkin/me')
}