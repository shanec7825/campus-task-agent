/**
 * AI 只读问答共享 Store（契约 `C-FE-AGENT-DOCK@1` / `C-AI-CHAT@1` / `C-FE-AI-SCOPE@1`）。
 *
 * 三种 Agent 形态（完整页 / 长条 / 微展开）共用按目标隔离的会话、消息与输入草稿：
 * - `byScope` 保存每个作用域（`general` / `activity:<id>` / `task:<id>`）的视图；
 * - 切目标只切换视图，不自动发请求，由调用方随后 `restore()`；
 * - 异步结果只写回发起时的作用域，晚到响应不覆盖当前目标；
 * - 保留既有失败边界：发送中不刷新、刷新失败不清空已有消息、发送失败回填原作用域输入。
 */
import { defineStore } from 'pinia'

import { chat, getConversation, getUsage, listConversations } from '../api/agent'
import { ApiError } from '../api/client'
import type { AiChatMessage, AiScope, AiScopeType, AiUsage } from '../types/models'

interface FailedRequest {
  content: string
  requestId: string
  conversationId: number | null
}

/** 单个作用域的视图快照（`C-FE-AI-SCOPE@1`） */
interface ScopeView {
  conversationId: number | null
  messages: AiChatMessage[]
  input: string
  mockMode: boolean
  bootstrapped: boolean
  lastFailedRequest: FailedRequest | null
  /** 该作用域的目标展示标签（活动/任务标题） */
  label: string
}

function emptyView(): ScopeView {
  return {
    conversationId: null,
    messages: [],
    input: '',
    mockMode: false,
    bootstrapped: false,
    lastFailedRequest: null,
    label: ''
  }
}

function scopeKeyOf(type: AiScopeType, id: number | null): string {
  return type === 'general' ? 'general' : `${type}:${id ?? ''}`
}

/** 每个作用域独立保存进行中的恢复请求，避免完整页与长条同时挂载时重复拉取 */
const restorePromises = new Map<string, Promise<string | null>>()
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
    scopeType: 'general' as AiScopeType,
    scopeId: null as number | null,
    /** 当前目标展示标签；无标签时由界面回退为「活动 #id / 任务 #id」 */
    scopeLabel: '',
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
    lastFailedRequest: null as FailedRequest | null,
    /** 是否已成功恢复过一次最近会话（空会话也算） */
    bootstrapped: false,
    /** 按作用域保存的独立视图 */
    byScope: {} as Record<string, ScopeView>,
    /** 正在飞行的作用域；`sending` 只表示当前作用域是否在飞 */
    inflight: {} as Record<string, boolean>
  }),

  getters: {
    scopeKey: (state): string =>
      state.scopeType === 'general' ? 'general' : `${state.scopeType}:${state.scopeId ?? ''}`,
    hasMessages: (state): boolean => state.messages.length > 0,
    recentMessages: (state): AiChatMessage[] => state.messages.slice(-4),
    quotaExhausted: (state): boolean => state.usage !== null && state.usage.remaining <= 0
  },

  actions: {
    /** 当前视图快照（不复制数组内容，写入方一律替换数组而非原地修改） */
    _snapshot(): ScopeView {
      return {
        conversationId: this.conversationId,
        messages: this.messages,
        input: this.input,
        mockMode: this.mockMode,
        bootstrapped: this.bootstrapped,
        lastFailedRequest: this.lastFailedRequest,
        label: this.scopeLabel
      }
    },

    /** 写入指定作用域；仅当它仍是当前视图时才同步屏幕状态 */
    _writeScope(key: string, patch: Partial<ScopeView>): void {
      const base = this.byScope[key] ?? (key === this.scopeKey ? this._snapshot() : emptyView())
      this.byScope[key] = { ...base, ...patch }
      if (key !== this.scopeKey) return
      if (patch.conversationId !== undefined) this.conversationId = patch.conversationId
      if (patch.messages !== undefined) this.messages = patch.messages
      if (patch.input !== undefined) this.input = patch.input
      if (patch.mockMode !== undefined) this.mockMode = patch.mockMode
      if (patch.bootstrapped !== undefined) this.bootstrapped = patch.bootstrapped
      if (patch.lastFailedRequest !== undefined) this.lastFailedRequest = patch.lastFailedRequest
      if (patch.label !== undefined) this.scopeLabel = patch.label
    },

    /**
     * 切换问答目标：先保存当前视图，再恢复目标作用域缓存（无缓存则初始化空视图）。
     * 同 key 只更新标签后返回；不自动发请求，由调用方随后 `restore()`。
     */
    setScope(type: AiScopeType, id: number | null, label?: string): void {
      const nextType: AiScopeType = type === 'general' ? 'general' : type
      const nextId = nextType === 'general' ? null : id
      const nextKey = scopeKeyOf(nextType, nextId)
      if (nextKey === this.scopeKey) {
        if (label !== undefined && label !== this.scopeLabel) {
          this.byScope[nextKey] = { ...(this.byScope[nextKey] ?? this._snapshot()), label }
          this.scopeLabel = label
        }
        return
      }

      this.byScope[this.scopeKey] = this._snapshot()
      const cached = this.byScope[nextKey] ?? emptyView()
      const nextLabel = label ?? cached.label
      this.byScope[nextKey] = { ...cached, label: nextLabel }
      this.scopeType = nextType
      this.scopeId = nextId
      this.scopeLabel = nextLabel
      this.conversationId = cached.conversationId
      this.messages = cached.messages
      this.input = cached.input
      this.mockMode = cached.mockMode
      this.bootstrapped = cached.bootstrapped
      this.lastFailedRequest = cached.lastFailedRequest
      this.historyLoading = false
      this.historyError = ''
      this.sending = Boolean(this.inflight[nextKey])
    },

    /**
     * 恢复当前作用域最近一次会话。
     *
     * @returns 已有消息时刷新失败的提示；没有已有消息时返回 `null` 并写入 `historyError`。
     */
    async restore(force = false): Promise<string | null> {
      const key = this.scopeKey
      if (this.inflight[key]) return null
      if (!force && this.bootstrapped) return null
      const pending = restorePromises.get(key)
      if (pending) return pending

      const token = epoch
      const scope: AiScope = { type: this.scopeType, id: this.scopeId }
      const promise = this._restore(token, key, scope)
      restorePromises.set(key, promise)
      try {
        return await promise
      } finally {
        if (token === epoch && restorePromises.get(key) === promise) restorePromises.delete(key)
      }
    },

    async _restore(token: number, key: string, scope: AiScope): Promise<string | null> {
      if (token === epoch && this.scopeKey === key) {
        this.historyLoading = true
        this.historyError = ''
      }
      try {
        const list = await listConversations(1, scope)
        if (token !== epoch) return null
        const latest = list.items[0]
        if (!latest) {
          this._writeScope(key, {
            conversationId: null,
            messages: [],
            mockMode: false,
            bootstrapped: true
          })
          return null
        }
        const detail = await getConversation(latest.id)
        if (token !== epoch) return null
        const lastAssistant = [...detail.messages]
          .reverse()
          .find((item) => item.role === 'assistant')
        this._writeScope(key, {
          conversationId: detail.conversation.id,
          messages: detail.messages,
          mockMode: lastAssistant?.mock === true,
          bootstrapped: true
        })
        return null
      } catch (err) {
        if (token !== epoch) return null
        // 晚到失败不覆盖已切换的新目标，也不在新目标弹错。
        if (this.scopeKey !== key) return null
        const message = errorMessage(err)
        if (this.messages.length > 0) return message
        this.historyError = message
        return null
      } finally {
        if (token === epoch && this.scopeKey === key) this.historyLoading = false
      }
    },

    /** 发送一条消息；失败时把文本回填到发起时的作用域输入框。 */
    async send(text?: string): Promise<boolean> {
      const key = this.scopeKey
      const scope: AiScope = {
        type: this.scopeType,
        id: this.scopeType === 'general' ? null : this.scopeId
      }
      const content = (text ?? this.input).trim()
      // 当前作用域恢复进行中时拒绝发送，避免错配 conversationId 或覆盖恢复结果。
      if (!content || this.inflight[key] || this.historyLoading || restorePromises.has(key)) {
        return false
      }

      const base = this.byScope[key] ?? this._snapshot()
      // 独立页面（未打开 AI 完整页）或跨天时先取一次额度，避免用过期缓存误判。
      if (this.usage === null || this.usage.date !== todayText()) {
        await this.loadUsage()
      }
      if (this.inflight[key] || restorePromises.has(key) || this.quotaExhausted) return false

      this.byScope[key] = base
      this._writeScope(key, { input: '' })
      this.inflight[key] = true
      if (this.scopeKey === key) this.sending = true

      const token = epoch
      const conversationId = base.conversationId
      const previous = base.lastFailedRequest
      const reuse =
        previous !== null &&
        previous.content === content &&
        previous.conversationId === conversationId
      const requestId = reuse ? previous.requestId : newRequestId()
      try {
        const result = await chat(content, conversationId ?? undefined, requestId, scope)
        if (token !== epoch) return false
        this._writeScope(key, {
          conversationId: result.conversation_id,
          messages: [...(this.byScope[key]?.messages ?? base.messages), result.user_message, result.assistant_message],
          mockMode: result.mock,
          bootstrapped: true,
          lastFailedRequest: null
        })
        if (this.scopeKey === key) this.historyError = ''
        await this.loadUsage()
        return true
      } catch (err) {
        if (token === epoch) {
          this._writeScope(key, { lastFailedRequest: { content, requestId, conversationId } })
          const retained = this.byScope[key]?.input ?? ''
          if (!retained) this._writeScope(key, { input: content })
          if (err instanceof ApiError && err.code === 4290) {
            if (this.usage) this.usage = { ...this.usage, remaining: 0 }
            await this.loadUsage()
          }
        }
        throw err
      } finally {
        if (token === epoch) {
          delete this.inflight[key]
          if (this.scopeKey === key) this.sending = false
        }
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

    /** 退出登录时清空本地会话与所有作用域缓存，防止上一个账号的对话留在内存。 */
    reset(): void {
      epoch += 1
      restorePromises.clear()
      this.scopeType = 'general'
      this.scopeId = null
      this.scopeLabel = ''
      this.byScope = {}
      this.inflight = {}
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