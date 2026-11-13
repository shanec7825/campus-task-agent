/**
 * AI 只读问答共享 Store（契约 `C-FE-AGENT-DOCK@1` / `C-AI-CHAT@1`）。
 *
 * 三种 Agent 形态（完整页 / 长条 / 微展开）共用同一会话、消息与输入草稿。
 * 保留既有失败边界：发送中不刷新、刷新失败不清空已有消息、发送失败回填输入。
 */
import { defineStore } from 'pinia'

import { chat, getConversation, listConversations } from '../api/agent'
import { ApiError } from '../api/client'
import type { AiChatMessage } from '../types/models'

/** 同一时刻只允许一个恢复请求，避免完整页与长条同时挂载时重复拉取 */
let restorePromise: Promise<string | null> | null = null
/** 会话代号：退出登录后递增，拦截上一个账号尚未返回的异步结果 */
let epoch = 0

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
    /** 是否已成功恢复过一次最近会话（空会话也算） */
    bootstrapped: false
  }),

  getters: {
    hasMessages: (state): boolean => state.messages.length > 0,
    recentMessages: (state): AiChatMessage[] => state.messages.slice(-4)
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

      this.input = ''
      this.sending = true
      const token = epoch
      try {
        const result = await chat(content, this.conversationId ?? undefined)
        if (token !== epoch) return false
        this.conversationId = result.conversation_id
        this.messages = [...this.messages, result.user_message, result.assistant_message]
        this.mockMode = result.mock
        this.historyError = ''
        this.bootstrapped = true
        return true
      } catch (err) {
        if (token === epoch && !this.input) this.input = content
        throw err
      } finally {
        if (token === epoch) this.sending = false
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
      this.bootstrapped = false
    }
  }
})