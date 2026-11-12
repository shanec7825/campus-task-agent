/**
 * 知识库 API（契约 C-FEAPI@1 / C-KB@1）。
 */
import { request } from './client'
import type { SimilarResult } from '../types/models'

/** 相似任务检索（`threshold` 恒为 0.6，前端据此决定是否展示提示条） */
export function findSimilar(q: string): Promise<SimilarResult> {
  return request<SimilarResult>('GET', '/api/kb/similar', undefined, { q })
}