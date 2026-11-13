/**
 * 活动 API（契约 C-ACTIVITY-API@1 / C-ACT-SCOPE@1 / C-FE-API@1）。
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

export interface ActivityListParams {
  /** `mine` 只返回我是负责人或活动下存在我参与/管理任务的活动 */
  scope?: 'all' | 'mine'
}

export function listActivities(params: ActivityListParams = {}): Promise<ActivityListResult> {
  const scope = params.scope === 'mine' ? '?scope=mine' : ''
  return request<ActivityListResult>('GET', `/api/activities${scope}`)
}

export function getActivity(id: number): Promise<ActivityDetail> {
  return request<ActivityDetail>('GET', `/api/activities/${id}`)
}

export function createActivity(payload: ActivityCreatePayload): Promise<Activity> {
  return request<Activity>('POST', '/api/activities', payload)
}