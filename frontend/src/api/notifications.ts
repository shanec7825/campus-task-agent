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
 * SSE 地址：登录态由同源 Cookie 承载，`EventSource` 默认携带 Cookie，无需令牌参数。
 */
export function streamUrl(): string {
  return '/api/notifications/stream'
}