/**
 * 积分 API（契约 C-FEAPI@1 / C-TASKS@1 #13）。
 */
import { request } from './client'
import type { CreditsMe } from '../types/models'

/** 我的积分余额与全部流水（按创建时间倒序） */
export function myCredits(): Promise<CreditsMe> {
  return request<CreditsMe>('GET', '/api/credits/me')
}