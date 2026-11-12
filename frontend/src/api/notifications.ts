/**
 * 通知 API（契约 C-FEAPI@1 / C-NOTIFY@1）。
 */
import { request } from './client'
import type { NotificationList } from '../types/models'

/** 通知列表（仅当前用户，按创建时间倒序） */
export function listNotifications(p?: {
  unread_only?: boolean
  limit?: number
}): Promise<NotificationList> {
  return request<NotificationList>('GET', '/api/notifications', undefined, p)
}

/** 批量标记已读（不存在的 id 由后端静默忽略） */
export function readNotifications(ids: number[]): Promise<{ updated: number }> {
  return request<{ updated: number }>('POST', '/api/notifications/read', { ids })
}

/**
 * 构造 SSE 地址：`EventSource` 无法携带 Authorization 头，token 走查询参数（2.3 D3）。
 */
export function streamUrl(token: string): string {
  return `/api/notifications/stream?token=${encodeURIComponent(token)}`
}