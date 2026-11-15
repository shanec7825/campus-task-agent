/**
 * 双 Agent API（契约 C-FEAPI@1 / C-AGENT@2 / C-FEAPI-AGENT@2 / C-AI-CHAT@1）。
 */
import { request } from './client'
import type {
  AiChatResult,
  AiConversationDetail,
  AiConversationList,
  AiScope,
  AiUsage,
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
/**
 * 权限内只读问答；`conversationId` 缺省时由后端新建会话，`requestId` 用于重试幂等。
 * `scope` 省略时保持通用作用域，兼容旧调用（`C-FE-AI-SCOPE@1`）。
 */
export function chat(
  message: string,
  conversationId?: number,
  requestId?: string,
  scope?: AiScope,
  resourceIds?: number[]
): Promise<AiChatResult> {
  const body: Record<string, unknown> = { message }
  if (conversationId !== undefined) body.conversation_id = conversationId
  if (requestId !== undefined) body.request_id = requestId
  if (scope !== undefined) {
    body.scope_type = scope.type
    if (scope.type !== 'general' && scope.id !== null) body.scope_id = scope.id
  }
  // 指定资料上下文（`C-AI-CONTEXT@1`）：空数组与缺省一致，不发该字段
  if (resourceIds !== undefined && resourceIds.length > 0) body.resource_ids = resourceIds
  return request<AiChatResult>('POST', '/api/agent/chat', body)
}

/** 当前用户今日 AI 问答额度与最近用量 */
export function getUsage(limit = 20): Promise<AiUsage> {
  return request<AiUsage>('GET', '/api/agent/usage', undefined, { limit })
}

/**
 * 当前用户最近的会话；`scope` 省略时不按作用域过滤（旧调用行为）。
 * `general` 只传 `scope_type`，活动 / 任务同时传 `scope_id`；`offset` 用于分页取更旧记录。
 */
export function listConversations(
  limit = 20,
  scope?: AiScope | null,
  offset = 0
): Promise<AiConversationList> {
  const query: Record<string, string | number | boolean | undefined> = { limit }
  if (scope) {
    query.scope_type = scope.type
    if (scope.type !== 'general' && scope.id !== null) query.scope_id = scope.id
  }
  if (offset > 0) query.offset = offset
  return request<AiConversationList>('GET', '/api/agent/conversations', undefined, query)
}

/** 本人会话详情（跨账号由后端返回 4040） */
export function getConversation(conversationId: number): Promise<AiConversationDetail> {
  return request<AiConversationDetail>('GET', `/api/agent/conversations/${conversationId}`)
}