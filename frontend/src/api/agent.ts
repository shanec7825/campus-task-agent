/**
 * 双 Agent API（契约 C-FEAPI@1 / C-AGENT@2 / C-FEAPI-AGENT@2 / C-AI-CHAT@1）。
 */
import { request } from './client'
import type {
  AiChatResult,
  AiConversationDetail,
  AiConversationList,
  Draft,
  ExtractResult,
  ReviewResult,
  StreamParseResult
} from '../types/models'

/**
 * `extract` 的可选第二参数（契约 C-FEAPI-AGENT@2）。
 * - `baseDraft`：增量解析的基准草稿（`mode='incremental'` 时后端必填，缺失报 4001）；
 * - `mode`：`'full'` 全量解析（默认，忽略 `baseDraft`）/ `'incremental'` 增量解析。
 */
export interface ExtractOptions {
  baseDraft?: Draft
  mode?: 'full' | 'incremental'
}

/**
 * 一次性提炼：自由文本 → 结构化草稿。
 *
 * 无第二参数时请求体与 P1 完全一致（只发 `{ text }`），保持既有调用兼容；
 * 有第二参数时请求体为 `{ text, base_draft?, mode? }`（字段名 snake_case，与后端 `ExtractIn` 对齐）。
 */
export function extract(text: string, options?: ExtractOptions): Promise<ExtractResult> {
  if (!options) return request<ExtractResult>('POST', '/api/agent/extract', { text })

  const body: Record<string, unknown> = { text }
  if (options.baseDraft !== undefined) body.base_draft = options.baseDraft
  if (options.mode !== undefined) body.mode = options.mode
  return request<ExtractResult>('POST', '/api/agent/extract', body)
}

/** 审核草稿：问号 / 润色 / 拆解建议 / 待采纳 changes（签名与 P1 一致） */
export function review(draft: Draft): Promise<ReviewResult> {
  return request<ReviewResult>('POST', '/api/agent/review', { draft })
}

/** 流式解析：每次送一个标点切片，`isFinal` 时停止累计（签名与 P1 一致） */
export function streamParse(
  sessionId: string,
  chunk: string,
  isFinal: boolean
): Promise<StreamParseResult> {
  return request<StreamParseResult>('POST', '/api/agent/stream/parse', {
    session_id: sessionId,
    chunk,
    is_final: isFinal
  })
}
/** 权限内只读问答；`conversationId` 缺省时由后端新建会话 */
export function chat(message: string, conversationId?: number): Promise<AiChatResult> {
  const body: Record<string, unknown> = { message }
  if (conversationId !== undefined) body.conversation_id = conversationId
  return request<AiChatResult>('POST', '/api/agent/chat', body)
}

/** 当前用户最近的会话 */
export function listConversations(limit = 20): Promise<AiConversationList> {
  return request<AiConversationList>('GET', '/api/agent/conversations', undefined, { limit })
}

/** 本人会话详情（跨账号由后端返回 4040） */
export function getConversation(conversationId: number): Promise<AiConversationDetail> {
  return request<AiConversationDetail>('GET', `/api/agent/conversations/${conversationId}`)
}