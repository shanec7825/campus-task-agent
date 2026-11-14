/**
 * 个人参考链接 API（契约 `C-LIBRARY@1`，design.md §9.2）。
 *
 * owner 由服务端从当前会话取得，前端不传也不可选；只提供列表 / 新增 / 更新，
 * 契约不提供删除与公开共享。
 */
import { request } from './client'
import type { LibraryRef } from '../types/models'

/** 个人参考链接（`LibraryLinkOut`）：归属由服务端按会话判定，响应不含 `owner_id` */
export interface LibraryLink {
  id: number
  title: string
  url: string
  note: string | null
  created_at: string
  updated_at: string
}

export interface LibraryLinkListResult {
  items: LibraryLink[]
  total: number
}

export interface LibraryLinkCreatePayload {
  title: string
  url: string
  note?: string | null
}

export interface LibraryLinkUpdatePayload {
  title?: string
  url?: string
  note?: string | null
}

/** `GET /api/library/links`：仅返回本人链接，`limit` 服务端限制 1..50 */
export function listLibraryLinks(p?: {
  offset?: number
  limit?: number
}): Promise<LibraryLinkListResult> {
  return request<LibraryLinkListResult>('GET', '/api/library/links', undefined, p)
}

/** `POST /api/library/links`：校验失败由服务端返回 `code=4001` */
export function createLibraryLink(p: LibraryLinkCreatePayload): Promise<LibraryLink> {
  return request<LibraryLink>('POST', '/api/library/links', p)
}

/** `PATCH /api/library/links/{id}`：非本人或不存在统一 `code=4040` */
export function updateLibraryLink(
  linkId: number,
  p: LibraryLinkUpdatePayload
): Promise<LibraryLink> {
  return request<LibraryLink>('PATCH', `/api/library/links/${linkId}`, p)
}
/** 引用资料列表（`C-LIB-REF@1`）：`items` 只含仍可访问的引用，`revoked_count` 为其余条数 */
export interface LibraryRefListResult {
  items: LibraryRef[]
  revoked_count: number
}

/** `GET /api/library/refs`：只返回本人仍可访问的引用，不泄露被撤回资料的标题 */
export function listLibraryRefs(): Promise<LibraryRefListResult> {
  return request<LibraryRefListResult>('GET', '/api/library/refs')
}

/** `POST /api/library/refs`：资料不可访问时服务端返回 `code=4040` */
export function saveLibraryRef(resourceId: number): Promise<LibraryRef> {
  return request<LibraryRef>('POST', '/api/library/refs', { resource_id: resourceId })
}