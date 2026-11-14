/**
 * AI 任务树草案 API（契约 `C-AI-DRAFT@1`，S5 design §2.2）。
 *
 * 只读生成，不写任何活动/任务行；草案返回后由发布页填入可编辑任务行，
 * 最终仍走 `POST /api/activities/publish-batch` 由辅导员确认发布。
 */
import { request } from './client'
import type { TaskDraftResult } from '../types/models'

export interface TaskDraftPayload {
  prompt: string
  /** 提供时必须为本人可管理的组织（服务端 4030/4040） */
  org_id: number | null
}

/** 基于组织开放资料生成任务树草案（失败提示服务端 msg，不自动发布） */
export function generateTaskDraft(payload: TaskDraftPayload): Promise<TaskDraftResult> {
  return request<TaskDraftResult>('POST', '/api/ai/task-draft', payload)
}