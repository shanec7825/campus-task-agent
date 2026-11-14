/**
 * AI 只读问答共享 Store（契约 `C-FE-AGENT-DOCK@1` / `C-AI-CHAT@1` / `C-FE-AI-SCOPE@1` / `C-AI-HISTORY@3`）。
 *
 * 三种 Agent 形态（完整页 / 长条 / 微展开）共用按会话隔离的会话、消息与输入草稿：
 * - `conversationViews` 按会话键（`c<id>` / `new<seq>`）保存视图，同作用域多会话互不覆盖；
 * - `byScope` 镜像每个作用域（`general` / `activity:<id>` / `task:<id>`）当前选中会话的视图；
 * - 切目标或切会话只切换视图，不自动发请求，由调用方随后 `restore()`；
 * - 异步结果必须同时匹配发起时的 `conversationKey` 与账号 `epoch`，晚到响应不覆盖当前会话；
 * - 保留既有失败边界：发送中不刷新、刷新失败不清空已有消息、发送失败回填原会话输入；
 * - 语音写回仍按作用域（`setInputForScope`）落到该作用域当前选中的会话草稿。
 */
import { defineStore } from 'pinia'

import { chat, getConversation, getUsage, listConversations } from '../api/agent'
import { ApiError } from '../api/client'
import type {
  AiChatMessage,
  AiConversationSummary,
  AiScope,
  AiScopeType,
  AiUsage
} from '../types/models'

const HISTORY_PAGE_SIZE = 20
const INPUT_MAX_LENGTH = 2000

interface FailedRequest {
  content: string
  requestId: string
  conversationId: number | null
}

/** 单个会话的视图快照（`C-FE-AI-SCOPE@1` / `C-AI-HISTORY@3`） */
interface ScopeView {
  conversationId: number | null
  messages: AiChatMessage[]
  input: string
  mockMode: boolean
  bootstrapped: boolean
  lastFailedRequest: FailedRequest | null
  /** 该会话所属目标（活动/任务标题）的展示标签 */
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

function emptyConversationViews(): Record<string, ScopeView> {
  return { new1: emptyView() }
}

function scopeKeyOf(type: AiScopeType, id: number | null): string {
  return type === 'general' ? 'general' : `${type}:${id ?? ''}`
}

/** 会话键：已落库会话为 `c<id>`，本地新会话为 `new<seq>` */
function conversationKeyOf(id: number): string {
  return `c${id}`
}

/** 合并分页结果，按会话 id 去重，保持先到顺序 */
function mergeConversations(
  existing: AiConversationSummary[],
  incoming: AiConversationSummary[]
): AiConversationSummary[] {
  const seen = new Set(existing.map((item) => item.id))
  const merged = [...existing]
  for (const item of incoming) {
    if (seen.has(item.id)) continue
    seen.add(item.id)
    merged.push(item)
  }
  return merged
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
    /** 当前选中的会话键：`c<id>` 或 `new<seq>` */
    selectedConversationKey: 'new1',
    conversationSeq: 1,
    /** 按会话键保存的独立视图（消息 / 输入草稿 / 失败重试状态） */
    conversationViews: emptyConversationViews(),
    /** 作用域 → 该作用域当前选中的会话键 */
    scopeSelection: { general: 'new1' } as Record<string, string>,
    messages: [] as AiChatMessage[],
    conversationId: null as number | null,
    input: '',
    historyLoading: true,
    historyError: '',
    /** 历史抽屉列表（`C-AI-HISTORY@3`） */
    historyItems: [] as AiConversationSummary[],
    historyTotal: 0,
    historyHasMore: false,
    historyScopeOnly: false,
    historyOpen: false,
    sending: false,
    mockMode: false,
    /** 今日 AI 问答额度（`C-AI-USAGE@1`） */
    usage: null as AiUsage | null,
    usageLoading: false,
    usageError: '',
    /** 上一次失败请求：同内容重试复用同一 request_id，避免响应丢失后重复计费 */
    lastFailedRequest: null as FailedRequest | null,
    /** 是否已成功恢复过一次当前会话（空会话也算） */
    bootstrapped: false,
    /** 按作用域镜像当前选中会话的视图（供作用域切换与语音草稿写回） */
    byScope: {} as Record<string, ScopeView>,
    /** 正在飞行的作用域；`sending` 只表示当前作用域是否在飞 */
    inflight: {} as Record<string, boolean>
  }),

  getters: {
    scopeKey: (state): string =>
      state.scopeType === 'general' ? 'general' : `${state.scopeType}:${state.scopeId ?? ''}`,
    /** 当前视图所属的会话键（`c<id>` 或 `new<seq>`） */
    activeConversationKey: (state): string =>
      state.selectedConversationKey ||
      (state.conversationId !== null ? conversationKeyOf(state.conversationId) : 'new1'),
    hasMessages: (state): boolean => state.messages.length > 0,
    recentMessages: (state): AiChatMessage[] => state.messages.slice(-4),
    quotaExhausted: (state): boolean => state.usage !== null && state.usage.remaining <= 0
  },

  actions: {
    /** 当前屏幕视图快照（不复制数组内容，写入方一律替换数组而非原地修改） */
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

    /** 把视图写到屏幕状态 */
    _applyView(view: ScopeView): void {
      this.conversationId = view.conversationId
      this.messages = view.messages
      this.input = view.input
      this.mockMode = view.mockMode
      this.bootstrapped = view.bootstrapped
      this.lastFailedRequest = view.lastFailedRequest
      this.scopeLabel = view.label
    },

    /** 异步回包是否仍属于当前屏幕上的作用域与会话 */
    _isActive(scopeKey: string, convKey: string): boolean {
      return this.scopeKey === scopeKey && this.selectedConversationKey === convKey
    },

    _newKey(): string {
      this.conversationSeq += 1
      return `new${this.conversationSeq}`
    },

    /** 取作用域当前选中的会话键；没有则接管该作用域的既有草稿或新建空会话 */
    _ensureSelection(key: string): string {
      const existing = this.scopeSelection[key]
      if (existing && this.conversationViews[existing]) return existing
      const legacy = this.byScope[key]
      const legacyKey = legacy && legacy.conversationId !== null
        ? conversationKeyOf(legacy.conversationId)
        : ''
      if (legacyKey && legacy) {
        this.conversationViews[legacyKey] = this.conversationViews[legacyKey] ?? legacy
        this.scopeSelection[key] = legacyKey
        return legacyKey
      }
      const convKey = this._newKey()
      this.conversationViews[convKey] = legacy ?? emptyView()
      this.scopeSelection[key] = convKey
      return convKey
    },

    /** 把屏幕视图存回会话缓存与作用域镜像 */
    _saveCurrentView(): void {
      const view = this._snapshot()
      this.conversationViews[this.selectedConversationKey] = view
      this.scopeSelection[this.scopeKey] = this.selectedConversationKey
      this.byScope[this.scopeKey] = view
    },

    /**
     * 写入指定会话视图；只有它仍是当前屏幕的会话时才同步屏幕状态，
     * 否则只更新缓存，避免晚到回包覆盖用户已切换的会话。
     */
    _writeView(scopeKey: string, convKey: string, patch: Partial<ScopeView>): void {
      const active = scopeKey === this.scopeKey && convKey === this.selectedConversationKey
      const base = this.conversationViews[convKey] ?? (active ? this._snapshot() : emptyView())
      const next: ScopeView = { ...base, ...patch }
      this.conversationViews[convKey] = next
      if (!active) return
      this.scopeSelection[scopeKey] = convKey
      this.byScope[scopeKey] = next
      this._applyView(next)
    },

    /** 会话键迁移（`new<seq>` → `c<id>`，或恢复到的历史会话），同步当前选择 */
    _replaceView(scopeKey: string, fromKey: string, toKey: string, view: ScopeView): void {
      if (fromKey !== toKey) delete this.conversationViews[fromKey]
      this.conversationViews[toKey] = view
      if (scopeKey !== this.scopeKey) {
        if (this.scopeSelection[scopeKey] === fromKey) this.scopeSelection[scopeKey] = toKey
        return
      }
      this.scopeSelection[scopeKey] = toKey
      this.selectedConversationKey = toKey
      this.byScope[scopeKey] = view
      this._applyView(view)
    },

    /**
     * 写入指定作用域的输入草稿（`C-AI-VOICE@1`）。
     * 语音晚到结果按发起时的作用域写回该作用域当前选中的会话；非当前作用域只更新缓存，不覆盖当前输入。
     */
    setInputForScope(key: string, text: string): void {
      const clipped = text.slice(0, INPUT_MAX_LENGTH)
      const selection = this.scopeSelection[key]
      if (!selection || !this.conversationViews[selection]) {
        const base = this.byScope[key] ?? emptyView()
        this.byScope[key] = { ...base, input: clipped }
        return
      }
      this._writeView(key, selection, { input: clipped })
    },

    /**
     * 切换问答目标：先保存当前会话视图，再恢复目标作用域选中的会话视图（无则新建空会话）。
     * 同 key 只更新标签后返回；不自动发请求，由调用方随后 `restore()`。
     */
    setScope(type: AiScopeType, id: number | null, label?: string): void {
      const nextType: AiScopeType = type === 'general' ? 'general' : type
      const nextId = nextType === 'general' ? null : id
      const nextKey = scopeKeyOf(nextType, nextId)
      if (nextKey === this.scopeKey) {
        if (label !== undefined && label !== this.scopeLabel) {
          this._writeView(nextKey, this.selectedConversationKey, { label })
        }
        return
      }

      this._saveCurrentView()
      const nextConvKey = this._ensureSelection(nextKey)
      const cached = this.conversationViews[nextConvKey] ?? emptyView()
      const nextLabel = label ?? cached.label
      const view: ScopeView = { ...cached, label: nextLabel }
      this.conversationViews[nextConvKey] = view
      this.byScope[nextKey] = view
      this.scopeSelection[nextKey] = nextConvKey

      this.scopeType = nextType
      this.scopeId = nextId
      this.scopeLabel = nextLabel
      this.selectedConversationKey = nextConvKey
      this._applyView(view)
      this.historyLoading = false
      this.historyError = ''
      this.sending = Boolean(this.inflight[nextKey])
    },

    /**
     * 恢复当前作用域当前选中会话的内容；本地新会话才拉最近一次会话。
     *
     * @returns 已有消息时刷新失败的提示；没有已有消息时返回 `null` 并写入 `historyError`。
     */
    async restore(force = false): Promise<string | null> {
      const key = this.scopeKey
      const convKey = this.selectedConversationKey
      if (this.inflight[key]) return null
      if (!force && this.bootstrapped) return null
      const pending = restorePromises.get(key)
      if (pending) return pending

      const token = epoch
      const scope: AiScope = { type: this.scopeType, id: this.scopeId }
      const promise = this._restore(token, key, convKey, scope)
      restorePromises.set(key, promise)
      try {
        return await promise
      } finally {
        if (token === epoch && restorePromises.get(key) === promise) restorePromises.delete(key)
      }
    },

    async _restore(
      token: number,
      key: string,
      convKey: string,
      scope: AiScope
    ): Promise<string | null> {
      if (token === epoch && this.scopeKey === key) {
        this.historyLoading = true
        this.historyError = ''
      }
      try {
        const list = await listConversations(1, scope)
        if (token !== epoch || !this._isActive(key, convKey)) return null
        const latest = list.items[0]
        if (!latest) {
          this._writeView(key, convKey, {
            conversationId: null,
            messages: [],
            mockMode: false,
            bootstrapped: true
          })
          return null
        }
        const detail = await getConversation(latest.id)
        if (token !== epoch || !this._isActive(key, convKey)) return null
        const lastAssistant = [...detail.messages]
          .reverse()
          .find((item) => item.role === 'assistant')
        const base = this.conversationViews[convKey] ?? emptyView()
        this._replaceView(key, convKey, conversationKeyOf(detail.conversation.id), {
          ...base,
          conversationId: detail.conversation.id,
          messages: detail.messages,
          mockMode: lastAssistant?.mock === true,
          bootstrapped: true,
          lastFailedRequest: null
        })
        return null
      } catch (err) {
        if (token !== epoch) return null
        // 晚到失败不覆盖已切换的会话或目标，也不在新视图弹错。
        if (!this._isActive(key, convKey)) return null
        const message = errorMessage(err)
        if (this.messages.length > 0) return message
        this.historyError = message
        return null
      } finally {
        if (token === epoch && this.scopeKey === key) this.historyLoading = false
      }
    },

    /**
     * 加载历史会话列表（`C-AI-HISTORY@3`）。
     * `reset=true` 从 offset 0 重载；`reset=false` 取下一页。失败写 `historyError` 并保留已有 items。
     */
    async loadHistory(reset = true, scopeOnly = false): Promise<void> {
      if (!reset && !this.historyHasMore) return
      const token = epoch
      const offset = reset ? 0 : this.historyItems.length
      const scope: AiScope | null = scopeOnly
        ? { type: this.scopeType, id: this.scopeType === 'general' ? null : this.scopeId }
        : null
      this.historyLoading = true
      this.historyError = ''
      try {
        const list = await listConversations(HISTORY_PAGE_SIZE, scope, offset)
        if (token !== epoch) return
        const items = reset
          ? list.items.slice()
          : mergeConversations(this.historyItems, list.items)
        this.historyItems = items
        this.historyTotal = list.total
        this.historyHasMore = items.length < list.total
        this.historyScopeOnly = scopeOnly
      } catch (err) {
        if (token !== epoch) return
        this.historyError = errorMessage(err)
      } finally {
        if (token === epoch) this.historyLoading = false
      }
    },

    /**
     * 打开一条历史会话：按返回的 scope 切换目标并载入消息。
     * 失败返回 false 且不改当前视图；不调用模型、不扣额度。
     */
    async openConversation(id: number): Promise<boolean> {
      const token = epoch
      try {
        const detail = await getConversation(id)
        if (token !== epoch) return false
        this._saveCurrentView()

        const type = detail.conversation.scope_type
        const nextId = type === 'general' ? null : detail.conversation.scope_id
        const key = scopeKeyOf(type, nextId)
        const targetKey = conversationKeyOf(detail.conversation.id)
        const lastAssistant = [...detail.messages]
          .reverse()
          .find((item) => item.role === 'assistant')
        const existing = this.conversationViews[targetKey]
        const view: ScopeView = {
          conversationId: detail.conversation.id,
          messages: detail.messages,
          input: existing?.input ?? '',
          mockMode: lastAssistant?.mock === true,
          bootstrapped: true,
          lastFailedRequest: null,
          label: key === this.scopeKey ? this.scopeLabel : ''
        }

        this.conversationViews[targetKey] = view
        this.scopeSelection[key] = targetKey
        this.scopeType = type
        this.scopeId = nextId
        this.scopeLabel = view.label
        this.selectedConversationKey = targetKey
        this.byScope[key] = view
        this._applyView(view)
        this.historyLoading = false
        this.historyError = ''
        this.sending = Boolean(this.inflight[key])
        return true
      } catch (err) {
        if (token === epoch) this.historyError = errorMessage(err)
        return false
      }
    },

    /** 界面选择会话；`openConversation` 的别名 */
    selectConversation(id: number): Promise<boolean> {
      return this.openConversation(id)
    },

    /**
     * 开新对话：当前视图存回缓存，清空会话与消息，保留作用域与输入草稿。
     * 不请求后端、不扣额度。
     */
    newConversation(): void {
      this._saveCurrentView()
      const carriedInput = this.conversationViews[this.selectedConversationKey]?.input ?? this.input
      const convKey = this._newKey()
      const view: ScopeView = { ...emptyView(), input: carriedInput, label: this.scopeLabel }
      this.conversationViews[convKey] = view
      this.scopeSelection[this.scopeKey] = convKey
      this.selectedConversationKey = convKey
      this.byScope[this.scopeKey] = view
      this._applyView(view)
      this.historyError = ''
    },

    /** 发送一条消息；失败时把文本回填到发起时的会话输入框。 */
    async send(text?: string): Promise<boolean> {
      const key = this.scopeKey
      const convKey = this.selectedConversationKey
      const scope: AiScope = {
        type: this.scopeType,
        id: this.scopeType === 'general' ? null : this.scopeId
      }
      const content = (text ?? this.input).trim()
      // 当前作用域恢复进行中时拒绝发送，避免错配 conversationId 或覆盖恢复结果。
      if (!content || this.inflight[key] || this.historyLoading || restorePromises.has(key)) {
        return false
      }

      const base = this.conversationViews[convKey] ?? this._snapshot()
      // 独立页面（未打开 AI 完整页）或跨天时先取一次额度，避免用过期缓存误判。
      if (this.usage === null || this.usage.date !== todayText()) {
        await this.loadUsage()
      }
      if (this.inflight[key] || restorePromises.has(key) || this.quotaExhausted) return false

      this.conversationViews[convKey] = base
      this._writeView(key, convKey, { input: '' })
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
        const resultKey = conversationKeyOf(result.conversation_id)
        if (convKey === resultKey) {
          this._writeView(key, convKey, {
            conversationId: result.conversation_id,
            messages: [
              ...(this.conversationViews[convKey]?.messages ?? base.messages),
              result.user_message,
              result.assistant_message
            ],
            mockMode: result.mock,
            bootstrapped: true,
            lastFailedRequest: null
          })
        } else if (
          this._isActive(key, convKey) &&
          (this.conversationViews[convKey]?.conversationId ?? null) === null
        ) {
          // 本地新会话首次落库：会话键由 `new<seq>` 迁移为 `c<id>`。
          const carried = this.conversationViews[convKey] ?? base
          this._replaceView(key, convKey, resultKey, {
            ...carried,
            conversationId: result.conversation_id,
            messages: [...carried.messages, result.user_message, result.assistant_message],
            mockMode: result.mock,
            bootstrapped: true,
            lastFailedRequest: null
          })
        }
        // 其余情况属于已切换走的会话，结果只丢弃，不回写当前视图。
        if (this.scopeKey === key && this.selectedConversationKey === resultKey) {
          this.historyError = ''
        }
        await this.loadUsage()
        return true
      } catch (err) {
        if (token === epoch) {
          this._writeView(key, convKey, { lastFailedRequest: { content, requestId, conversationId } })
          const retained = this.conversationViews[convKey]?.input ?? ''
          if (!retained) this._writeView(key, convKey, { input: content })
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

    /** 退出登录时清空本地会话、历史与所有会话缓存，防止上一个账号的对话留在内存。 */
    reset(): void {
      epoch += 1
      restorePromises.clear()
      this.scopeType = 'general'
      this.scopeId = null
      this.scopeLabel = ''
      this.selectedConversationKey = 'new1'
      this.conversationSeq = 1
      this.conversationViews = emptyConversationViews()
      this.scopeSelection = { general: 'new1' }
      this.byScope = {}
      this.inflight = {}
      this.messages = []
      this.conversationId = null
      this.input = ''
      this.historyError = ''
      this.historyLoading = false
      this.historyItems = []
      this.historyTotal = 0
      this.historyHasMore = false
      this.historyScopeOnly = false
      this.historyOpen = false
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