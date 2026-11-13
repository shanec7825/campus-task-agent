/**
 * AI 只读问答共享 Store（契约 `C-FE-AGENT-DOCK@1` / `C-AI-CHAT@1`）。
 *
 * 三种 Agent 形态（完整页 / 长条 / 微展开）共用同一会话、消息与输入草稿。
 * 保留既有失败边界：发送中不刷新、刷新失败不清空已有消息、发送失败回填输入。
 */
import { defineStore } from 'pinia'

import { chat, getConversation, getUsage, listConversations } from '../api/agent'
import { ApiError } from '../api/client'
import type { AiChatMessage, AiUsage } from '../types/models'

/** 同一时刻只允许一个恢复请求，避免完整页与长条同时挂载时重复拉取 */
let restorePromise: Promise<string | null> | null = null
/** 会话代号：退出登录后递增，拦截上一个账号尚未返回的异步结果 */
let epoch = 0

/** 生成请求幂等键；不支持 crypto.randomUUID 时退化为时间戳 + 随机串 */
function newRequestId(): string {
  const randomUuid = globalThis.crypto?.randomUUID
  if (typeof randomUuid === 'function') return randomUuid.call(globalThis.crypto).replace(/-/g, '')
  return `req_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`
}

function todayText(): string {
  return new Date().toLocaleDateString('sv-SE')
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

export const useAiChatStore = defineStore('aiChat', {
  state: () => ({
    messages: [] as AiChatMessage[],
    conversationId: null as number | null,
    input: '',
    historyLoading: true,
    historyError: '',
    sending: false,
    mockMode: false,
    /** 今日 AI 问答额度（`C-AI-USAGE@1`） */
    usage: null as AiUsage | null,
    usageLoading: false,
    usageError: '',
    /** 上一次失败请求：同内容重试复用同一 request_id，避免响应丢失后重复计费 */
    lastFailedRequest: null as {
      content: string
      requestId: string
      conversationId: number | null
    } | null,
    /** 是否已成功恢复过一次最近会话（空会话也算） */
    bootstrapped: false
  }),

  getters: {
    hasMessages: (state): boolean => state.messages.length > 0,
    recentMessages: (state): AiChatMessage[] => state.messages.slice(-4),
    quotaExhausted: (state): boolean => state.usage !== null && state.usage.remaining <= 0
  },

  actions: {
    /**
     * 恢复最近一次会话。
     *
     * @returns 已有消息时刷新失败的提示；没有已有消息时返回 `null` 并写入 `historyError`。
     */
    async restore(force = false): Promise<string | null> {
      if (this.sending) return null
      if (!force && this.bootstrapped) return null
      if (restorePromise) return restorePromise

      const token = epoch
      restorePromise = this._restore(token)
      try {
        return await restorePromise
      } finally {
        if (token === epoch) restorePromise = null
      }
    },

    async _restore(token: number): Promise<string | null> {
      this.historyLoading = true
      this.historyError = ''
      try {
        const list = await listConversations(1)
        if (token !== epoch) return null
        const latest = list.items[0]
        if (!latest) {
          this.messages = []
          this.conversationId = null
          this.mockMode = false
          this.bootstrapped = true
          return null
        }
        const detail = await getConversation(latest.id)
        if (token !== epoch) return null
        this.conversationId = detail.conversation.id
        this.messages = detail.messages
        const lastAssistant = [...detail.messages]
          .reverse()
          .find((item) => item.role === 'assistant')
        this.mockMode = lastAssistant?.mock === true
        this.bootstrapped = true
        return null
      } catch (err) {
        if (token !== epoch) return null
        const message = errorMessage(err)
        if (this.messages.length > 0) return message
        this.historyError = message
        return null
      } finally {
        if (token === epoch) this.historyLoading = false
      }
    },

    /** 发送一条消息；失败时把文本回填到输入框。 */
    async send(text?: string): Promise<boolean> {
      const content = (text ?? this.input).trim()
      if (!content || this.sending || this.historyLoading) return false
      // 独立页面（未打开 AI 完整页）或跨天时先取一次额度，避免用过期缓存误判。
      if (this.usage === null || this.usage.date !== todayText()) {
        await this.loadUsage()
      }
      if (this.quotaExhausted) return false

      this.input = ''
      this.sending = true
      const token = epoch
      const previous = this.lastFailedRequest
      const reuse =
        previous !== null &&
        previous.content === content &&
        previous.conversationId === this.conversationId
      const requestId = reuse ? previous.requestId : newRequestId()
      const conversationId = reuse ? previous.conversationId : this.conversationId
      try {
        const result = await chat(
          content,
          conversationId ?? undefined,
          requestId
        )
        if (token !== epoch) return false
        this.conversationId = result.conversation_id
        this.messages = [...this.messages, result.user_message, result.assistant_message]
        this.mockMode = result.mock
        this.historyError = ''
        this.bootstrapped = true
        this.lastFailedRequest = null
        await this.loadUsage()
        return true
      } catch (err) {
        if (token === epoch) {
          this.lastFailedRequest = { content, requestId, conversationId }
          if (!this.input) this.input = content
          if (err instanceof ApiError && err.code === 4290) {
            if (this.usage) this.usage = { ...this.usage, remaining: 0 }
            await this.loadUsage()
          }
        }
        throw err
      } finally {
        if (token === epoch) this.sending = false
      }
    },

    /** 读取本人今日 AI 问答额度；失败只记录提示，不阻塞问答与协作功能 */
    async loadUsage(): Promise<void> {
      this.usageLoading = true
      this.usageError = ''
      try {
        this.usage = await getUsage()
        this.usageError = ''
      } catch (err) {
        this.usageError = errorMessage(err)
      } finally {
        this.usageLoading = false
      }
    },

    /** 退出登录时清空本地会话，防止上一个账号的对话留在内存。 */
    reset(): void {
      epoch += 1
      restorePromise = null
      this.messages = []
      this.conversationId = null
      this.input = ''
      this.historyError = ''
      this.historyLoading = false
      this.sending = false
      this.mockMode = false
      this.usage = null
      this.usageLoading = false
      this.usageError = ''
      this.lastFailedRequest = null
      this.bootstrapped = false
    }
  }
})