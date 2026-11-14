/**
 * 通知 API（契约 C-FEAPI@1 / C-NOTIFY@1）。
 */
import { request } from './client'
import type { NotificationList } from '../types/models'

/** 通知列表（仅当前用户，按创建时间倒序；`archived` 切换归档箱） */
export function listNotifications(p?: {
  unread_only?: boolean
  archived?: boolean
  limit?: number
}): Promise<NotificationList> {
  return request<NotificationList>('GET', '/api/notifications', undefined, p)
}

/** 批量标记已读（不存在的 id 由后端静默忽略） */
export function readNotifications(ids: number[]): Promise<{ updated: number }> {
  return request<{ updated: number }>('POST', '/api/notifications/read', { ids })
}

/** 批量归档（`C-NOTICE-ARCHIVE@1`）：只处理本人未归档记录，重复调用幂等 */
export function archiveNotifications(ids: number[]): Promise<{ updated: number }> {
  return request<{ updated: number }>('POST', '/api/notifications/archive', { ids })
}

/**
 * SSE 地址：登录态由同源 Cookie 承载，`EventSource` 默认携带 Cookie，无需令牌参数。
 */
export function streamUrl(): string {
  return '/api/notifications/stream'
}