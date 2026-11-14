/**
 * 我的活动 / 任务搜索 API（契约 `C-MY-SEARCH@1`，design.md §9.3）。
 *
 * 只搜索当前用户 mine 范围，排序与分页由服务端完成；前端不拼接第二套查询条件。
 */
import { request } from './client'
import type { Activity, TaskItem } from '../types/models'

export interface SearchGroup<T> {
  items: T[]
  total: number
}

export interface MySearchResult {
  activities: SearchGroup<Activity>
  tasks: SearchGroup<TaskItem>
}

/** 搜索词上限 100；`limit` 服务端限制 1..20，默认 5 */
export const MY_SEARCH_MAX_QUERY = 100
export const MY_SEARCH_MAX_LIMIT = 20

/** `GET /api/search/mine`：`q` 为空时服务端返回两个空组 */
export function searchMine(q: string, limit = 5): Promise<MySearchResult> {
  return request<MySearchResult>('GET', '/api/search/mine', undefined, { q, limit })
}