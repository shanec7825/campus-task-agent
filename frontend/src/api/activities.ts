/**
 * 活动 API（契约 C-ACTIVITY-API@1 / C-FE-API@1）。
 *
 * 无缓存层：每次进入页面重新拉取；活动进度以服务端返回为准。
 */
import { request } from './client'
import type {
  Activity,
  ActivityCreatePayload,
  ActivityDetail,
  ActivityListResult
} from '../types/models'

export function listActivities(): Promise<ActivityListResult> {
  return request<ActivityListResult>('GET', '/api/activities')
}

export function getActivity(id: number): Promise<ActivityDetail> {
  return request<ActivityDetail>('GET', `/api/activities/${id}`)
}

export function createActivity(payload: ActivityCreatePayload): Promise<Activity> {
  return request<Activity>('POST', '/api/activities', payload)
}