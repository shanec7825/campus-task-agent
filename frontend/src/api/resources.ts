/**
 * 资料库 API（契约 `C-RESOURCE@1`）。
 *
 * 检索与可见范围全部由后端判定；前端只负责传关键词 / 归属过滤与展示。
 */
import { request } from './client'
import type { ResourceCreatePayload, ResourceItem, ResourceListResult } from '../types/models'

export function listResources(p?: {
  q?: string
  activity_id?: number
  task_id?: number
  related_task_id?: number
  limit?: number
}): Promise<ResourceListResult> {
  return request<ResourceListResult>('GET', '/api/resources', undefined, p)
}

export function createResource(p: ResourceCreatePayload): Promise<ResourceItem> {
  return request<ResourceItem>('POST', '/api/resources', p)
}