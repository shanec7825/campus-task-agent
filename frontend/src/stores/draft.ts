/**
 * 草稿 Store（契约 C-STORE@1 / C-TRACE@1）。
 *
 * 唯一写入口：T7/T8 只能调用本文件的 action 修改草稿，禁止直接改 state。
 *
 * P2 扩展（第二轮迭代）：
 * - `Block` 增加 `kind`（5 类块）与 `meta`（字段级变更快照）；
 * - 新增 `liveText` / `suggestedChanges` / `appendedText` 三个 state；
 * - `applyExtract` 支持 full 模式「按 changes 落值 + raw 块染色」（不生成 applied_texts 追溯块）；
 * - `applyExtractIncremental` 严格按「用户原话 → 落值」顺序写入（不再追加自动 `ai_applied` 块）；
 * - `adoptChange` 只写 `new_value`（纯值）+ 生成 `ai_applied` 块（仅显式采纳留痕）；
 * - `setField(key, value, trace)` 默认 `trace='user'`，用户右侧手改自动留痕；
 * - `toTaskPayload` **只从 fields 组装**，追溯块永不污染发布请求。
 *
 * 追溯块以 `blocks` 为唯一存储（`kind !== 'raw'` 即追溯块），不再额外维护一份 trace state，
 * 避免两处数据不一致；`buildDraft().trace` 由 `blocks` 派生（raw/live 不入 trace）。
 */
import { computed, ref, watch } from 'vue'
import { defineStore } from 'pinia'

import type {
  Ambiguity,
  BlockKind,
  Change,
  Correction,
  Draft,
  ExtractResult,
  Polished,
  ReviewResult,
  SimilarItem,
  Span,
  StreamParseResult,
  SubTaskSuggestion,
  TaskCreatePayload,
  TraceBlock
} from '../types/models'
import { formatChangeText, formatFieldLabel } from '../utils/traceText'

/**
 * 草稿状态机（P3 收窄：`'confirmed'` 全仓无引用已删除）。
 *
 * `suspended` 仅为兼容历史数据保留（旧版本持久化 / 旧会话），运行时不再置位；
 * 语音流式收尾统一走 `finishStreaming()` 回到 `'typing'`。
 */
export type DraftMode =
  | 'idle'
  | 'typing'
  | 'recording'
  | 'streaming'
  /** @deprecated 仅兼容历史数据（旧持久化 / 旧会话），不再置位 */
  | 'suspended'

/** 原文块状态：pending=未解析（灰黑），parsed=已染色，confirmed=用户确认 */
export type BlockStatus = 'pending' | 'parsed' | 'confirmed'

/** 追溯块写入时的来源标记：user=用户右侧手改（留痕），none=程序落值（由调用方补块） */
export type FieldTrace = 'user' | 'none'

/**
 * 彩色文字块（T8 `BlockText` 直接消费）。
 * `kind` 决定染色来源：`raw` 走字段色，其余 4 类走 `TRACE_COLORS`。
 */
export interface Block {
  id: number
  text: string
  kind: BlockKind
  field: string | null
  status: BlockStatus
  meta?: Change | null
}

/** 字段面板数据（T8 `FieldPanel` 直接消费） */
export interface DraftField {
  key: string
  label: string
  value: string | number | null
  sourceBlockId: number | null
  warned: boolean
}

/** 固定字段顺序（`fields` 的 key 集合固定） */
const BASE_FIELD_KEYS = [
  'title',
  'time',
  'deadline',
  'location',
  'details',
  'quota',
  'volunteer_hours',
  'notes',
  'requirements'
] as const

/** 扩展项 key 前缀 */
const EXTRA_PREFIX = 'extra_tags.'

/** 后端透传追溯块的条数上限（防止 payload 膨胀） */
const TRACE_LIMIT = 200

/** 草稿持久化的 localStorage key（B6：刷新不丢草稿） */
export const DRAFT_STORAGE_KEY = 'cta_draft_v1'

/** 草稿持久化结构版本：与本地数据不一致时丢弃并删除键 */
export const DRAFT_VERSION = 1

/** 草稿写盘防抖（毫秒） */
const DRAFT_SAVE_DEBOUNCE_MS = 300

/** 块类型白名单（持久化数据校验用） */
const BLOCK_KINDS: readonly BlockKind[] = ['raw', 'ai_applied', 'user_edit', 'user_note', 'live']

/** 块状态白名单（持久化数据校验用） */
const BLOCK_STATUSES: readonly BlockStatus[] = ['pending', 'parsed', 'confirmed']

/** 块 id 自增序列（resetDraft 时归零） */
let blockSeq = 0

function nextBlockId(): number {
  blockSeq += 1
  return blockSeq
}

function fieldLabel(key: string): string {
  return formatFieldLabel(key)
}

function createBaseFields(): Record<string, DraftField> {
  const result: Record<string, DraftField> = {}
  for (const key of BASE_FIELD_KEYS) {
    result[key] = {
      key,
      label: fieldLabel(key),
      value: null,
      sourceBlockId: null,
      warned: false
    }
  }
  return result
}

function createField(key: string): DraftField {
  return { key, label: fieldLabel(key), value: null, sourceBlockId: null, warned: false }
}

/** 生成会话 id（crypto.randomUUID 需要安全上下文，非安全环境降级） */
function createSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `sess-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`
}

// --------------------------------------------------------------------------- //
// B6 草稿持久化：结构定义 + 反序列化校验
// --------------------------------------------------------------------------- //

/** 落盘草稿（不含 `liveText` / `appendedText` / `mode` / `sessionId` / `similar`） */
interface PersistedDraftData {
  blocks: Block[]
  fields: Record<string, DraftField>
  rawText: string
  stylePrompt: string | null
  unresolved: string[]
  corrections: Correction[]
  ambiguities: Ambiguity[]
  polished: Polished | null
  suggestedSubTasks: SubTaskSuggestion[]
  suggestedChanges: Change[]
  mockMode: boolean
}

/** 落盘外层结构：`{ version, savedAt, data }` */
interface PersistedDraftPayload {
  version: number
  savedAt: number
  data: PersistedDraftData
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isScalar(value: unknown): value is string | number | null {
  return value === null || typeof value === 'string' || typeof value === 'number'
}

/** localStorage 可用性：SSR / 非浏览器环境、隐私模式下取不到 Storage 时返回 null */
function getDraftStorage(): Storage | null {
  if (typeof window === 'undefined') return null
  try {
    return window.localStorage ?? null
  } catch {
    // Safari 隐私模式访问 localStorage 会抛 SecurityError
    return null
  }
}

function sanitizeStrings(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.filter((item): item is string => typeof item === 'string')
}

function sanitizeChange(value: unknown): Change | null {
  if (!isPlainRecord(value)) return null
  const op = value.op
  if (op !== 'set' && op !== 'add_tag' && op !== 'remove_tag') return null
  if (typeof value.field !== 'string') return null
  if (!isScalar(value.old_value) || !isScalar(value.new_value)) return null
  return {
    op,
    field: value.field,
    old_value: value.old_value,
    new_value: value.new_value,
    reason: typeof value.reason === 'string' ? value.reason : '',
    source: value.source === 'user' ? 'user' : 'ai'
  }
}

function sanitizeBlocks(value: unknown): Block[] {
  if (!Array.isArray(value)) return []
  const result: Block[] = []
  for (const item of value) {
    if (!isPlainRecord(item)) continue
    if (typeof item.id !== 'number' || !Number.isFinite(item.id)) continue
    if (typeof item.text !== 'string') continue
    if (!BLOCK_KINDS.includes(item.kind as BlockKind)) continue
    if (!BLOCK_STATUSES.includes(item.status as BlockStatus)) continue
    result.push({
      id: item.id,
      text: item.text,
      kind: item.kind as BlockKind,
      field: typeof item.field === 'string' ? item.field : null,
      status: item.status as BlockStatus,
      meta: sanitizeChange(item.meta)
    })
  }
  return result
}

/**
 * 字段恢复：以 `createBaseFields()` 打底，只接受固定键与 `extra_tags.*` 键，
 * 脏键 / 脏值直接丢弃（避免坏数据把面板渲染坏）。
 */
function sanitizeFields(value: unknown): Record<string, DraftField> {
  const result = createBaseFields()
  if (!isPlainRecord(value)) return result
  for (const [key, raw] of Object.entries(value)) {
    if (!isPlainRecord(raw)) continue
    if (!isScalar(raw.value)) continue
    const isBase = BASE_FIELD_KEYS.includes(key as (typeof BASE_FIELD_KEYS)[number])
    if (!isBase && !isExtraFieldKey(key)) continue
    result[key] = {
      key,
      label: isNonEmptyString(typeof raw.label === 'string' ? raw.label : null)
        ? (raw.label as string)
        : fieldLabel(key),
      value: raw.value,
      sourceBlockId:
        typeof raw.sourceBlockId === 'number' && Number.isFinite(raw.sourceBlockId)
          ? raw.sourceBlockId
          : null,
      warned: raw.warned === true
    }
  }
  return result
}

function sanitizeCorrections(value: unknown): Correction[] {
  if (!Array.isArray(value)) return []
  const result: Correction[] = []
  for (const item of value) {
    if (!isPlainRecord(item)) continue
    if (typeof item.target !== 'string' || typeof item.new_value !== 'string') continue
    result.push({
      target: item.target,
      old_value: typeof item.old_value === 'string' ? item.old_value : null,
      new_value: item.new_value,
      reason: typeof item.reason === 'string' ? item.reason : ''
    })
  }
  return result
}

function sanitizeAmbiguities(value: unknown): Ambiguity[] {
  if (!Array.isArray(value)) return []
  const result: Ambiguity[] = []
  for (const item of value) {
    if (!isPlainRecord(item)) continue
    if (typeof item.field !== 'string') continue
    result.push({
      field: item.field,
      question: typeof item.question === 'string' ? item.question : '',
      suggestion: typeof item.suggestion === 'string' ? item.suggestion : null
    })
  }
  return result
}

function sanitizeSubTasks(value: unknown): SubTaskSuggestion[] {
  if (!Array.isArray(value)) return []
  const result: SubTaskSuggestion[] = []
  for (const item of value) {
    if (!isPlainRecord(item)) continue
    if (typeof item.title !== 'string') continue
    result.push({
      title: item.title,
      description: typeof item.description === 'string' ? item.description : '',
      sop_guide: typeof item.sop_guide === 'string' ? item.sop_guide : '',
      quota: typeof item.quota === 'number' ? item.quota : null,
      depends_on: typeof item.depends_on === 'number' ? item.depends_on : null
    })
  }
  return result
}

function sanitizeChanges(value: unknown): Change[] {
  if (!Array.isArray(value)) return []
  const result: Change[] = []
  for (const item of value) {
    const change = sanitizeChange(item)
    if (change) result.push(change)
  }
  return result
}

function sanitizePolished(value: unknown): Polished | null {
  if (!isPlainRecord(value)) return null
  if (typeof value.details !== 'string' || typeof value.notes !== 'string') return null
  return { details: value.details, notes: value.notes }
}

/**
 * 反序列化 + 校验落盘草稿。
 * 返回 null 表示「版本不匹配 / JSON 损坏 / 结构非法」，调用方须丢弃并删除键。
 */
function parsePersistedPayload(raw: string): PersistedDraftData | null {
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    return null
  }
  if (!isPlainRecord(parsed)) return null
  if (parsed.version !== DRAFT_VERSION) return null
  const data = parsed.data
  if (!isPlainRecord(data)) return null
  return {
    blocks: sanitizeBlocks(data.blocks),
    fields: sanitizeFields(data.fields),
    rawText: typeof data.rawText === 'string' ? data.rawText : '',
    stylePrompt: typeof data.stylePrompt === 'string' ? data.stylePrompt : null,
    unresolved: sanitizeStrings(data.unresolved),
    corrections: sanitizeCorrections(data.corrections),
    ambiguities: sanitizeAmbiguities(data.ambiguities),
    polished: sanitizePolished(data.polished),
    suggestedSubTasks: sanitizeSubTasks(data.suggestedSubTasks),
    suggestedChanges: sanitizeChanges(data.suggestedChanges),
    mockMode: data.mockMode === true
  }
}

/** 字符串值规整：空白串视为 null */
function asText(value: string | number | null): string | null {
  if (value === null) return null
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : null
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

/** 数值规整：非法数字视为 null */
function asNumber(value: string | number | null): number | null {
  if (value === null) return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  const trimmed = value.trim()
  if (trimmed === '') return null
  const parsed = Number(trimmed)
  return Number.isFinite(parsed) ? parsed : null
}

function isNonEmptyString(value: string | null | undefined): value is string {
  return typeof value === 'string' && value.trim() !== ''
}

function isExtraFieldKey(key: string): boolean {
  return key.startsWith(EXTRA_PREFIX)
}

export const useDraftStore = defineStore('draft', () => {
  // ----------------------------------------------------------------------- //
  // state（契约 2.2.11 全量字段 + P2 新增三字段）
  // ----------------------------------------------------------------------- //
  const mode = ref<DraftMode>('idle')
  const blocks = ref<Block[]>([])
  const fields = ref<Record<string, DraftField>>(createBaseFields())
  const rawText = ref('')
  const stylePrompt = ref<string | null>(null)
  const unresolved = ref<string[]>([])
  const corrections = ref<Correction[]>([])
  const ambiguities = ref<Ambiguity[]>([])
  const polished = ref<Polished | null>(null)
  const suggestedSubTasks = ref<SubTaskSuggestion[]>([])
  const similar = ref<SimilarItem[]>([])
  const sessionId = ref('')
  const mockMode = ref(false)

  /** 语音 interim 实时文本：不入 blocks、不入 rawText（T5 节流刷新） */
  const liveText = ref('')
  /** review 返回的待采纳建议（只展示，不自动落值） */
  const suggestedChanges = ref<Change[]>([])
  /** 左侧「继续补充」的输入缓冲（不入 rawText，提交增量解析时才追加） */
  const appendedText = ref('')

  // ----------------------------------------------------------------------- //
  // B6 草稿持久化（localStorage）
  // ----------------------------------------------------------------------- //
  /** 写盘防抖句柄 */
  let saveTimer: ReturnType<typeof setTimeout> | null = null
  /** 写入失败（配额满 / 隐私模式）只告警一次 */
  let storageWarned = false

  /** 删除落盘草稿（resetDraft / 数据非法 / 空草稿时调用） */
  function clearPersistedDraft(): void {
    const storage = getDraftStorage()
    if (!storage) return
    try {
      storage.removeItem(DRAFT_STORAGE_KEY)
    } catch {
      // 隐私模式下 removeItem 同样可能抛异常，静默降级
    }
  }

  /** 需要落盘的字段快照（`liveText` / `appendedText` / `mode` / `sessionId` / `similar` 不落盘） */
  function snapshotForStorage(): PersistedDraftData {
    return {
      blocks: blocks.value,
      fields: fields.value,
      rawText: rawText.value,
      stylePrompt: stylePrompt.value,
      unresolved: unresolved.value,
      corrections: corrections.value,
      ambiguities: ambiguities.value,
      polished: polished.value,
      suggestedSubTasks: suggestedSubTasks.value,
      suggestedChanges: suggestedChanges.value,
      mockMode: mockMode.value
    }
  }

  /** 空草稿不写盘（并顺手删键），避免刷新后恢复出一份空壳 */
  function isEmptyDraft(): boolean {
    const hasFieldValue = Object.values(fields.value).some(
      (field) => field.value !== null && String(field.value).trim() !== ''
    )
    return (
      blocks.value.length === 0 &&
      rawText.value.trim() === '' &&
      !hasFieldValue &&
      corrections.value.length === 0 &&
      ambiguities.value.length === 0 &&
      polished.value === null &&
      suggestedSubTasks.value.length === 0 &&
      suggestedChanges.value.length === 0
    )
  }

  /** 立即写盘（防抖终点） */
  function saveNow(): void {
    saveTimer = null
    const storage = getDraftStorage()
    if (!storage) return
    if (isEmptyDraft()) {
      clearPersistedDraft()
      return
    }
    const payload: PersistedDraftPayload = {
      version: DRAFT_VERSION,
      savedAt: Date.now(),
      data: snapshotForStorage()
    }
    try {
      storage.setItem(DRAFT_STORAGE_KEY, JSON.stringify(payload))
    } catch (error) {
      if (!storageWarned) {
        storageWarned = true
        console.warn('[draft] 草稿持久化失败（配额已满或隐私模式），本会话降级为不持久化', error)
      }
    }
  }

  /** 变更后 300ms 防抖写盘 */
  function scheduleSave(): void {
    if (typeof window === 'undefined') return
    if (saveTimer !== null) clearTimeout(saveTimer)
    saveTimer = setTimeout(saveNow, DRAFT_SAVE_DEBOUNCE_MS)
  }

  /**
   * 从 localStorage 恢复草稿。
   * - 无 `window` / 无 Storage：直接跳过（SSR 安全）；
   * - 版本不匹配或 JSON 损坏：丢弃并删除键；
   * - 恢复成功且有内容：`mode` 置 `'typing'`（用户可继续编辑）。
   */
  function restoreFromStorage(): void {
    const storage = getDraftStorage()
    if (!storage) return

    let raw: string | null = null
    try {
      raw = storage.getItem(DRAFT_STORAGE_KEY)
    } catch {
      return
    }
    if (!raw) return

    const data = parsePersistedPayload(raw)
    if (!data) {
      clearPersistedDraft()
      return
    }

    blocks.value = data.blocks
    fields.value = data.fields
    rawText.value = data.rawText
    stylePrompt.value = data.stylePrompt
    unresolved.value = data.unresolved
    corrections.value = data.corrections
    ambiguities.value = data.ambiguities
    polished.value = data.polished
    suggestedSubTasks.value = data.suggestedSubTasks
    suggestedChanges.value = data.suggestedChanges
    mockMode.value = data.mockMode

    // 块 id 序列必须跟上，否则恢复后新增块会与历史块 id 重复
    blockSeq = data.blocks.reduce((max, block) => (block.id > max ? block.id : max), 0)

    const restoredHasContent =
      data.blocks.length > 0 ||
      data.rawText.trim() !== '' ||
      Object.values(data.fields).some(
        (field) => field.value !== null && String(field.value).trim() !== ''
      )
    mode.value = restoredHasContent ? 'typing' : 'idle'
  }

  // 先恢复再挂 watch：恢复过程本身不触发写盘
  restoreFromStorage()
  watch(
    [
      blocks,
      fields,
      rawText,
      stylePrompt,
      unresolved,
      corrections,
      ambiguities,
      polished,
      suggestedSubTasks,
      suggestedChanges,
      mockMode
    ],
    scheduleSave,
    { deep: true }
  )

  // ----------------------------------------------------------------------- //
  // getters
  // ----------------------------------------------------------------------- //
  const fieldList = computed<DraftField[]>(() => Object.values(fields.value))

  const canPublish = computed<boolean>(() => {
    const title = fields.value.title?.value
    const hasTitle = typeof title === 'number' ? true : isNonEmptyString(title)
    return hasTitle && mode.value !== 'recording'
  })

  /** 未解析片段数：只统计 raw 块，追溯块（status 同为 pending）不计入 */
  const pendingCount = computed<number>(
    () =>
      blocks.value.filter((block) => block.kind === 'raw' && block.status === 'pending').length
  )

  /** 当前追溯块（`blocks` 中非 raw / 非 live 的部分，最多 200 条） */
  const traceBlocks = computed<TraceBlock[]>(() => collectTrace())

  /** 当前草稿快照（供 T7 调 `api/agent.review` 使用，不产生副作用） */
  const currentDraft = computed<Draft>(() => buildDraft())

  // ----------------------------------------------------------------------- //
  // 内部工具：块写入
  // ----------------------------------------------------------------------- //
  /**
   * 追加一条追溯块（非 raw）。
   * 空文本直接丢弃，避免产生「空气泡」；`meta` 保存原始 change 供 tooltip 展示 reason。
   */
  function pushTraceBlock(
    kind: 'ai_applied' | 'user_edit' | 'user_note',
    text: string,
    field: string | null,
    meta: Change | null
  ): void {
    if (!isNonEmptyString(text)) return
    blocks.value.push({
      id: nextBlockId(),
      text,
      kind,
      field,
      status: 'pending',
      meta
    })
  }

  /** 由追溯块生成 `change`（用户手改留痕的唯一文案来源） */
  function buildUserChange(
    op: Change['op'],
    field: string,
    oldValue: string | number | null,
    newValue: string | number | null,
    reason = ''
  ): Change {
    return { op, field, old_value: oldValue, new_value: newValue, reason, source: 'user' }
  }

  /** 由追溯块生成 `change`（AI 建议文案的来源） */
  function buildAiChange(
    field: string,
    oldValue: string | number | null,
    newValue: string | number | null,
    reason = ''
  ): Change {
    return { op: 'set', field, old_value: oldValue, new_value: newValue, reason, source: 'ai' }
  }


  // ----------------------------------------------------------------------- //
  // 内部工具：字段写回 + 块染色（applyExtract / applyStream 唯一共用实现）
  // ----------------------------------------------------------------------- //
  function ensureField(key: string): DraftField {
    const existing = fields.value[key]
    if (existing) return existing
    const created = createField(key)
    fields.value[key] = created
    return created
  }

  /** 查找该字段最近一次出现的块 id，用于 FieldPanel 高亮联动 */
  function latestBlockIdFor(key: string): number | null {
    const bareKey = isExtraFieldKey(key) ? key.slice(EXTRA_PREFIX.length) : null
    for (let i = blocks.value.length - 1; i >= 0; i -= 1) {
      const field = blocks.value[i].field
      if (field === key || (bareKey !== null && field === bareKey)) return blocks.value[i].id
    }
    return null
  }

  /**
   * 按 spans 把原文切成"染色块 + 未解析缝隙"。
   * spans 中在原文里找不到的片段直接忽略（避免脏数据造出空块）。
   */
  function buildBlocks(sourceText: string, spans: Span[]): Block[] {
    if (!sourceText) return []
    const remaining = spans.filter((span) => isNonEmptyString(span.text))
    const result: Block[] = []
    let cursor = 0

    while (cursor < sourceText.length && remaining.length > 0) {
      let bestIndex = -1
      let bestSpanIndex = -1
      for (let i = 0; i < remaining.length; i += 1) {
        const found = sourceText.indexOf(remaining[i].text, cursor)
        if (found < 0) continue
        if (bestIndex < 0 || found < bestIndex) {
          bestIndex = found
          bestSpanIndex = i
        }
      }
      if (bestIndex < 0 || bestSpanIndex < 0) break

      const span = remaining.splice(bestSpanIndex, 1)[0]
      if (bestIndex > cursor) {
        result.push({
          id: nextBlockId(),
          text: sourceText.slice(cursor, bestIndex),
          kind: 'raw',
          field: null,
          status: 'pending'
        })
      }
      result.push({
        id: nextBlockId(),
        text: span.text,
        kind: 'raw',
        field: span.field,
        status: span.field ? 'parsed' : 'pending'
      })
      cursor = bestIndex + span.text.length
      if (span.text.length === 0) break
    }

    if (cursor < sourceText.length) {
      result.push({
        id: nextBlockId(),
        text: sourceText.slice(cursor),
        kind: 'raw',
        field: null,
        status: 'pending'
      })
    }
    return result
  }

  /** 把草稿的非空字段写回 `fields`（后到的非空值覆盖先前的值） */
  function writeDraftFields(draft: Draft): void {
    const assignments: Array<[string, string | number | null]> = [
      ['title', draft.title],
      ['time', draft.time],
      ['deadline', draft.deadline],
      ['location', draft.location],
      ['details', draft.details],
      ['quota', draft.quota],
      ['volunteer_hours', draft.volunteer_hours],
      ['notes', draft.notes],
      ['requirements', draft.requirements]
    ]
    for (const [key, value] of assignments) {
      if (value === null || value === undefined) continue
      if (typeof value === 'string' && value.trim() === '') continue
      const field = ensureField(key)
      field.value = value
      field.sourceBlockId = latestBlockIdFor(key)
    }

    for (const [tagKey, tagValue] of Object.entries(draft.extra_tags ?? {})) {
      if (!isNonEmptyString(tagValue)) continue
      const key = `${EXTRA_PREFIX}${tagKey}`
      const field = ensureField(key)
      field.value = tagValue
      field.sourceBlockId = latestBlockIdFor(key)
    }
  }

  /**
   * corrections 后到覆盖先到：同 target 替换，并给字段打上红色警示。
   *
   * **只警示、不写值（B1）**：解析结果里的更正已经通过 `payload.draft` 落进字段，
   * 这里若再写 `field.value` 会异步覆盖用户正在输入的内容。
   * 新值统一由用户点 `WarnBubble` 采纳（`adoptSuggestion` 链路）。
   */
  function mergeCorrectionsInternal(list: Correction[]): void {
    if (list.length === 0) return
    for (const correction of list) {
      const index = corrections.value.findIndex((item) => item.target === correction.target)
      if (index >= 0) corrections.value[index] = correction
      else corrections.value.push(correction)

      // 只打警示，绝不写值（写值会异步覆盖用户正在输入的内容）
      const key = resolveFieldKey(correction.target)
      if (key) {
        ensureField(key).warned = true
        continue
      }
      // corrections 的 target 也可能是尚未建字段的扩展项裸键名，按扩展项兜底（仅为渲染警示气泡）
      ensureField(`${EXTRA_PREFIX}${correction.target}`).warned = true
    }
  }

  /** correction.target 可能是 `location` / `extra_tags.工作内容` / `工作内容` */
  function resolveFieldKey(target: string): string | null {
    if (!target) return null
    if (fields.value[target]) return target
    if (fields.value[`${EXTRA_PREFIX}${target}`]) return `${EXTRA_PREFIX}${target}`
    if (BASE_FIELD_KEYS.includes(target as (typeof BASE_FIELD_KEYS)[number])) return target
    return null
  }

  /**
   * 把 change.field（`change` / `extra_tags.<key>` / 裸扩展键）解析为 `fields` 的 key。
   * 未知裸键按扩展项处理（与后端 review 的字段归一化一致）。
   */
  function resolveChangeKey(field: string): string {
    if (!field) return ''
    if (isExtraFieldKey(field)) return field
    if (BASE_FIELD_KEYS.includes(field as (typeof BASE_FIELD_KEYS)[number])) return field
    if (fields.value[field]) return field
    return `${EXTRA_PREFIX}${field}`
  }

  interface ParsedPayload {
    draft: Draft
    spans: Span[]
    unresolved: string[]
    corrections: Correction[]
    mock: boolean
  }

  interface ApplyOptions {
    /** 是否为全新解析（重置字段、块与审核态） */
    reset: boolean
    /** 是否追加块（流式）而非重建（一次性提炼） */
    append: boolean
    /** `ExtractOut` 顶层 style_prompt（缺失时回退 `draft.style_prompt`） */
    topLevelStyle?: string | null
    /** 是否用 `draft` 整份写回字段（full 模式有 changes 时置 false，改为按 change 落值） */
    writeFields?: boolean
  }

  /**
   * `applyExtract` / `applyStream` 的唯一共用实现：
   * 1) 处理 rawText 与 blocks（染色）；
   * 2) 字段写回（含扩展项）；
   * 3) unresolved 全量替换、corrections 后到覆盖；
   * 4) 更新风格要求与 mock 标记。
   */
  function applyParsedResult(payload: ParsedPayload, sourceText: string, options: ApplyOptions): void {
    if (options.reset) {
      fields.value = createBaseFields()
      blocks.value = []
      corrections.value = []
      ambiguities.value = []
      polished.value = null
      suggestedSubTasks.value = []
      suggestedChanges.value = []
      unresolved.value = []
      stylePrompt.value = null
      liveText.value = ''
      appendedText.value = ''
      rawText.value = sourceText
    } else if (sourceText) {
      rawText.value = rawText.value ? `${rawText.value}${sourceText}` : sourceText
    }

    if (options.append) {
      const appended = buildBlocks(sourceText, payload.spans)
      if (appended.length > 0) blocks.value.push(...appended)
      else if (sourceText) {
        blocks.value.push({
          id: nextBlockId(),
          text: sourceText,
          kind: 'raw',
          field: null,
          status: 'pending'
        })
      }
    } else {
      blocks.value = buildBlocks(sourceText, payload.spans)
    }

    if (options.writeFields !== false) writeDraftFields(payload.draft)

    const style = isNonEmptyString(options.topLevelStyle)
      ? options.topLevelStyle
      : payload.draft.style_prompt
    if (isNonEmptyString(style)) stylePrompt.value = style

    unresolved.value = [...payload.unresolved]
    mergeCorrectionsInternal(payload.corrections)
    mockMode.value = payload.mock
    mode.value = options.append ? 'streaming' : 'typing'
  }

  /** 把 changes 命中的 raw 块标记为已染色（parsed） */
  function markRawBlocksParsed(changes: Change[]): void {
    if (changes.length === 0) return
    const touched = new Set<string>()
    for (const change of changes) {
      touched.add(change.field)
      touched.add(resolveChangeKey(change.field))
      if (isExtraFieldKey(change.field)) touched.add(change.field.slice(EXTRA_PREFIX.length))
    }
    for (const block of blocks.value) {
      if (block.kind !== 'raw' || !block.field) continue
      if (touched.has(block.field)) block.status = 'parsed'
    }
  }

  /** 由 `fields` 反向组装 Draft（review 入参与状态衔接） */
  function buildDraft(): Draft {
    const extraTags: Record<string, string> = {}
    for (const field of Object.values(fields.value)) {
      if (!isExtraFieldKey(field.key)) continue
      const text = asText(field.value)
      if (text !== null) extraTags[field.key.slice(EXTRA_PREFIX.length)] = text
    }
    return {
      title: asText(fields.value.title?.value ?? null),
      time: asText(fields.value.time?.value ?? null),
      deadline: asText(fields.value.deadline?.value ?? null),
      location: asText(fields.value.location?.value ?? null),
      details: asText(fields.value.details?.value ?? null),
      quota: asNumber(fields.value.quota?.value ?? null),
      volunteer_hours: asNumber(fields.value.volunteer_hours?.value ?? null),
      notes: asText(fields.value.notes?.value ?? null),
      requirements: asText(fields.value.requirements?.value ?? null),
      extra_tags: extraTags,
      style_prompt: isNonEmptyString(stylePrompt.value) ? stylePrompt.value : null,
      trace: collectTrace()
    }
  }

  /**
   * 追溯块 → 后端 `TraceBlock`（非 raw / 非 live；超出 200 条取最后 200 条）。
   * live 块从不进入 `blocks`，因此天然不进入 trace。
   */
  function collectTrace(): TraceBlock[] {
    const result: TraceBlock[] = []
    for (const block of blocks.value) {
      if (block.kind === 'raw' || block.kind === 'live') continue
      result.push({
        id: block.id,
        text: block.text,
        kind: block.kind as TraceBlock['kind'],
        field: block.field,
        meta: block.meta
          ? {
              op: block.meta.op,
              field: block.meta.field,
              old_value: block.meta.old_value,
              new_value: block.meta.new_value,
              reason: block.meta.reason,
              source: block.meta.source
            }
          : null
      })
    }
    return result.length > TRACE_LIMIT ? result.slice(result.length - TRACE_LIMIT) : result
  }

  // ----------------------------------------------------------------------- //
  // actions
  // ----------------------------------------------------------------------- //
  function newSession(): string {
    // 只换会话号，不清草稿（契约：newSession 不清草稿）
    sessionId.value = createSessionId()
    return sessionId.value
  }

  function setMode(next: DraftMode): void {
    mode.value = next
  }

  /** 录音开始（T8 调用；不改动草稿内容） */
  function markRecording(): void {
    mode.value = 'recording'
  }

  /** 手动输入 / 文本解析场景 */
  function setRawText(text: string): void {
    rawText.value = text
    if (mode.value === 'idle' || mode.value === 'suspended') mode.value = 'typing'
  }

  function appendBlock(text: string, field: string | null = null): void {
    if (!text) return
    blocks.value.push({
      id: nextBlockId(),
      text,
      kind: 'raw',
      field,
      status: field ? 'parsed' : 'pending'
    })
    if (field) {
      const target = ensureField(resolveFieldKey(field) ?? field)
      target.sourceBlockId = blocks.value[blocks.value.length - 1].id
    }
    rawText.value = rawText.value ? `${rawText.value}${text}` : text
    if (mode.value === 'idle') mode.value = 'typing'
  }

  /** 语音 final 后追加一条 raw 原话块（T5 调用；不写字段） */
  function appendRawNote(text: string): void {
    const note = (text ?? '').trim()
    if (!note) return
    blocks.value.push({
      id: nextBlockId(),
      text: note,
      kind: 'raw',
      field: null,
      status: 'pending'
    })
    rawText.value = rawText.value ? `${rawText.value}${note}` : note
    if (mode.value === 'idle' || mode.value === 'suspended') mode.value = 'typing'
  }

  /** 左侧「继续补充」的原话块（增量解析第一步；不写字段） */
  function appendUserNote(text: string): void {
    const note = (text ?? '').trim()
    if (!note) return
    blocks.value.push({
      id: nextBlockId(),
      text: note,
      kind: 'user_note',
      field: null,
      status: 'pending'
    })
    rawText.value = rawText.value ? `${rawText.value}${note}` : note
    if (mode.value === 'idle' || mode.value === 'suspended') mode.value = 'typing'
  }

  /**
   * 修改单个字段。
   *
   * - `old` 严格取「写入前的值」；`String(old) === String(new)` 时**不生成**块（避免噪声）；
   * - `trace='user'`（默认）生成 `user_edit` 追溯块，保证右侧任何手改都留痕；
   * - `adoptChange` / `applyExtractIncremental` 等程序落值必须显式传 `'none'`，避免双块。
   */
  function setField(key: string, value: string | number | null, trace: FieldTrace = 'user'): void {
    if (!key) return
    const field = ensureField(key)
    const before = field.value
    field.value = value
    field.warned = false
    field.sourceBlockId = latestBlockIdFor(key)

    if (trace !== 'user') return

    const oldText = asText(before)
    const newText = asText(value)
    if (String(oldText) === String(newText)) return

    const change = buildUserChange('set', key, oldText, newText)
    pushTraceBlock('user_edit', formatChangeText(change), key, change)
  }

  /** 删除字段（固定字段走 setField 置空并留痕；扩展项删除生成 remove_tag 块） */
  function removeField(key: string): void {
    if (isExtraFieldKey(key) || !BASE_FIELD_KEYS.includes(key as (typeof BASE_FIELD_KEYS)[number])) {
      const current = fields.value[key]
      const oldText = current ? asText(current.value) : null
      delete fields.value[key]
      if (oldText === null) return
      const change = buildUserChange('remove_tag', key, oldText, null)
      pushTraceBlock('user_edit', formatChangeText(change), key, change)
      return
    }
    setField(key, null, 'user')
  }

  /** 按一条 change 写入字段值（不生成追溯块，块由调用方统一补） */
  function applyChange(change: Change): void {
    const key = resolveChangeKey(change.field)
    if (!key) return
    if (change.op === 'remove_tag') {
      if (fields.value[key]) delete fields.value[key]
      return
    }
    if (change.new_value === null || change.new_value === undefined) return
    setField(key, change.new_value, 'none')
  }

  /**
   * 一次性提炼写回（full 模式）。
   *
   * 1) 按 spans 重建 raw 块（reset）；
   * 2) 按 `res.changes` 落值（无 changes 时兼容旧响应，整份草稿写回）；
   * 3) 把命中的 raw 块染色（彩色块保留）；
   * 4) **不生成**追溯块：后端 `applied_texts` 仍返回但前端不消费，
   *    `ai_applied` 只在用户显式采纳（adoptChange/adoptSuggestion/adoptPolished）时留痕。
   *
   * @param res        `/api/agent/extract` 响应
   * @param sourceText 原文（块染色依据，同时写入 rawText；省略时用当前 rawText）
   */
  function applyExtract(res: ExtractResult, sourceText?: string): void {
    const text = sourceText ?? rawText.value
    const changes = Array.isArray(res.changes) ? res.changes : []

    applyParsedResult(
      {
        draft: res.draft,
        spans: res.spans ?? [],
        unresolved: res.unresolved ?? [],
        corrections: res.corrections ?? [],
        mock: res.mock
      },
      text,
      {
        reset: true,
        append: false,
        topLevelStyle: res.style_prompt,
        writeFields: changes.length === 0
      }
    )

    for (const change of changes) applyChange(change)
    markRawBlocksParsed(changes)
  }

  /**
   * 增量解析写回（`mode='incremental'`）。
   *
   * 顺序**必须**是：先追加 `user_note`（用户原话）→ 再按 changes 落值（不再追加 `ai_applied`），
   * 解析结果只做染色与落值，左侧不出现 "AI 改了什么" 的自动追溯块。
   */
  function applyExtractIncremental(res: ExtractResult, userText: string): void {
    const noteText = (userText ?? '').trim()
    // 1) 用户原话（用户补充原文必须留痕）
    if (noteText) appendUserNote(noteText)

    const changes = Array.isArray(res.changes) ? res.changes : []

    // 2) 按 changes 落值（不产生追溯块）
    for (const change of changes) applyChange(change)
    if (changes.length === 0) writeDraftFields(res.draft)

    // 3) `applied_texts` 不消费：自动 `ai_applied` 追溯块仅在显式采纳时生成

    // 4) 其余状态（不重建 raw 块：首次 full 解析已建）
    unresolved.value = [...(res.unresolved ?? [])]
    mergeCorrectionsInternal(res.corrections ?? [])
    const style = isNonEmptyString(res.style_prompt) ? res.style_prompt : res.draft.style_prompt
    if (isNonEmptyString(style)) stylePrompt.value = style
    mockMode.value = res.mock
    mode.value = 'typing'
    appendedText.value = ''
  }

  /**
   * 流式解析写回：新 chunk 的块追加到末尾，字段按"后到覆盖先到"更新。
   * 语音路径**不生成追溯块**（契约 C-AGENT@2 F）：`res.changes` 不落追溯块。
   * @param res       `/api/agent/stream/parse` 响应
   * @param chunkText 本次发送的切片
   */
  function applyStream(res: StreamParseResult, chunkText: string): void {
    applyParsedResult(
      {
        draft: res.draft,
        spans: res.spans ?? [],
        unresolved: res.unresolved ?? [],
        corrections: res.corrections ?? [],
        mock: res.mock
      },
      chunkText,
      { reset: false, append: true }
    )
  }

  /** 审核结果写回（问号 / 润色 / 拆解建议 / mock + 待采纳建议） */
  function applyReview(res: ReviewResult): void {
    ambiguities.value = [...res.ambiguities]
    polished.value = res.polished
    suggestedSubTasks.value = [...res.suggested_sub_tasks]
    mockMode.value = res.mock
    // 待采纳建议只展示、不写字段、不生成追溯块
    suggestedChanges.value = Array.isArray(res.changes) ? [...res.changes] : []
  }

  /**
   * 采纳一条 AI 建议：右侧只写 `new_value`（纯值），左侧生成 `ai_applied` 紫块。
   * 内部走 `setField(..., 'none')`，避免同时产生 `user_edit` 双块。
   */
  function adoptChange(change: Change): void {
    const key = resolveChangeKey(change.field)
    if (key) {
      if (change.op === 'remove_tag') {
        if (fields.value[key]) delete fields.value[key]
      } else if (change.new_value !== null && change.new_value !== undefined) {
        setField(key, change.new_value, 'none')
      }
    }

    const text = formatChangeText(change)
    pushTraceBlock('ai_applied', text, key || null, change)

    // 已采纳的建议从待采纳列表中移除（同字段同新值视为同一条）
    suggestedChanges.value = suggestedChanges.value.filter(
      (item) =>
        !(
          item.field === change.field &&
          String(item.new_value ?? '') === String(change.new_value ?? '')
        )
    )
  }

  /** 批量合并 corrections（供 T8 等外部路径使用） */
  function mergeCorrections(list: Correction[]): void {
    mergeCorrectionsInternal(list)
  }

  /** 采纳问号建议：落纯值 + 生成 `ai_applied` 追溯块（不产生"用户："误导文案） */
  function adoptSuggestion(field: string, suggestion: string): void {
    if (!suggestion) return
    const key = resolveFieldKey(field) ?? (isExtraFieldKey(field) ? field : `${EXTRA_PREFIX}${field}`)
    const oldValue = fields.value[key] ? asText(fields.value[key].value) : null
    setField(key, suggestion, 'none')
    const change = buildAiChange(key, oldValue, suggestion, '采纳审核助手的问号建议')
    pushTraceBlock('ai_applied', formatChangeText(change), key, change)
    ambiguities.value = ambiguities.value.filter(
      (item) => item.field !== field && item.field !== key
    )
  }

  /** 采纳润色结果（替换 details / notes，落纯值 + 紫块） */
  function adoptPolished(kind: 'details' | 'notes'): void {
    const current = polished.value
    if (!current) return
    const value = current[kind]
    if (!isNonEmptyString(value)) return
    const oldValue = asText(fields.value[kind]?.value ?? null)
    setField(kind, value, 'none')
    const change = buildAiChange(kind, oldValue, value, '采纳润色建议')
    pushTraceBlock('ai_applied', formatChangeText(change), kind, change)
  }

  /** 扩展项 key 规整：去前缀 + 去空白 */
  function normalizeTagKey(key: string): string {
    const trimmed = (key ?? '').trim()
    return isExtraFieldKey(trimmed) ? trimmed.slice(EXTRA_PREFIX.length) : trimmed
  }

  /**
   * 新增扩展项。
   * 无参调用（FieldPanel 的 `add-extra` 事件）自动生成唯一键名；返回最终键名。
   */
  function addExtra(key?: string, value = ''): string {
    let tagKey = normalizeTagKey(key ?? '')
    if (!tagKey) {
      let index = 1
      while (fields.value[`${EXTRA_PREFIX}扩展项${index}`]) index += 1
      tagKey = `扩展项${index}`
    }
    const fullKey = `${EXTRA_PREFIX}${tagKey}`
    if (isNonEmptyString(value)) {
      addExtraTag(tagKey, value)
      return fullKey
    }
    ensureField(fullKey)
    return fullKey
  }

  /**
   * 新增扩展项（契约命名）：值非空时生成 `user_edit` 追溯块
   * 「用户：新建扩展项「key」，内容为「value」」。
   */
  function addExtraTag(key: string, value: string): void {
    const tagKey = normalizeTagKey(key)
    if (!tagKey) return
    const fullKey = `${EXTRA_PREFIX}${tagKey}`
    const oldValue = fields.value[fullKey] ? asText(fields.value[fullKey].value) : null
    const nextValue = asText(value)
    setField(fullKey, nextValue, 'none')
    if (nextValue === null) return
    const change =
      oldValue === null
        ? buildUserChange('add_tag', fullKey, null, nextValue)
        : buildUserChange('set', fullKey, oldValue, nextValue)
    pushTraceBlock('user_edit', formatChangeText(change), fullKey, change)
  }

  /** 删除扩展项（支持带/不带 `extra_tags.` 前缀）→ 「用户：删除扩展项「key」」 */
  function removeExtraTag(key: string): void {
    const tagKey = normalizeTagKey(key)
    if (!tagKey) return
    removeField(`${EXTRA_PREFIX}${tagKey}`)
  }

  function removeSubTask(index: number): void {
    if (index < 0 || index >= suggestedSubTasks.value.length) return
    suggestedSubTasks.value.splice(index, 1)
  }

  function updateSubTask(index: number, patch: Partial<SubTaskSuggestion>): void {
    const current = suggestedSubTasks.value[index]
    if (!current) return
    suggestedSubTasks.value[index] = { ...current, ...patch }
  }

  /** 相似任务提示条数据（T7 检索后写入） */
  function setSimilar(items: SimilarItem[]): void {
    similar.value = [...items]
  }

  /** 手动设置风格要求（AI 解析路径会自动写回） */
  function setStylePrompt(value: string | null): void {
    stylePrompt.value = isNonEmptyString(value) ? value : null
  }

  /** 语音 interim 实时文本（T5 负责节流，≤200ms 刷新一次） */
  function setLiveText(text: string): void {
    liveText.value = text ?? ''
  }

  /** 清空 interim 文本（final 帧确认 / 停止录音后由 T5 调用） */
  function clearLiveText(): void {
    liveText.value = ''
  }

  /** 左侧「继续补充」输入缓冲（不写 rawText，提交增量解析时才追加） */
  function setAppendedText(text: string): void {
    appendedText.value = text ?? ''
  }

  /**
   * 清理「继续补充」缓冲。`applyExtractIncremental` 成功后会自行清空；
   * 解析失败或用户放弃时由调用方显式调用。
   */
  function clearAppendedText(): void {
    appendedText.value = ''
  }

  /**
   * 结束流式解析 / 语音确认态（B9，替代旧版「挂起待确认」action）。
   *
   * - `streaming` / `suspended`（历史数据）→ `typing`；
   * - 无论当前处于哪个状态，都清空 interim 文本（`liveText`），
   *   保证 final 帧之后不会残留半句实时字幕。
   *
   * 供 T2 `useVoiceComposer` 在最后一片 chunk / 停止录音后调用。
   */
  function finishStreaming(): void {
    if (mode.value === 'streaming' || mode.value === 'suspended') mode.value = 'typing'
    liveText.value = ''
  }

  function resetDraft(): void {
    if (saveTimer !== null) {
      clearTimeout(saveTimer)
      saveTimer = null
    }
    // B6：清空草稿必须同时 localStorage.removeItem(DRAFT_STORAGE_KEY)，避免刷新后恢复旧内容
    clearPersistedDraft()
    mode.value = 'idle'
    blocks.value = []
    fields.value = createBaseFields()
    rawText.value = ''
    stylePrompt.value = null
    unresolved.value = []
    corrections.value = []
    ambiguities.value = []
    polished.value = null
    suggestedSubTasks.value = []
    similar.value = []
    sessionId.value = ''
    mockMode.value = false
    liveText.value = ''
    suggestedChanges.value = []
    appendedText.value = ''
    blockSeq = 0
  }

  /**
   * 草稿 → 发布请求体（严格按 `C-DATA@1` 映射表）。
   *
   * **只从 fields 组装**：不读取 `blocks`，因此 `ai_applied/user_edit/user_note/live`
   * 任何追溯文本都不可能污染发布请求（R13-AC3）。
   * `details/notes/requirements` 按顺序用 `\n` 合并到 `description`；`time → start_time`；
   * `style_prompt → style_note`；扩展项原样写入 `extras`。
   */
  function toTaskPayload(): TaskCreatePayload {
    const draft = buildDraft()
    const descriptionParts = [draft.details, draft.notes, draft.requirements].filter(
      (part): part is string => isNonEmptyString(part)
    )
    const extras: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(draft.extra_tags)) extras[key] = value

    return {
      title: draft.title ?? '',
      description: descriptionParts.length > 0 ? descriptionParts.join('\n') : null,
      location: draft.location,
      start_time: draft.time,
      deadline: draft.deadline,
      quota: draft.quota,
      volunteer_hours: draft.volunteer_hours,
      extras,
      style_note: draft.style_prompt
    }
  }

  /**
   * 拆解建议 → 单个子任务请求体。
   * 注意：`depends_on` 仍是建议数组下标（0/1），T7 串行发布时须替换为真实任务 id；
   * `parent_id` 由调用方传入（或发布前合并进 payload）。
   */
  function toSubTaskPayload(index: number, parentId?: number): TaskCreatePayload {
    const item = suggestedSubTasks.value[index]
    if (!item) throw new Error('子任务建议不存在')
    const payload: TaskCreatePayload = {
      title: item.title,
      description: item.description,
      sop_guide: item.sop_guide,
      quota: item.quota,
      depends_on: item.depends_on,
      extras: {}
    }
    if (parentId !== undefined) payload.parent_id = parentId
    return payload
  }

  return {
    // state
    mode,
    blocks,
    fields,
    rawText,
    stylePrompt,
    unresolved,
    corrections,
    ambiguities,
    polished,
    suggestedSubTasks,
    similar,
    sessionId,
    mockMode,
    liveText,
    suggestedChanges,
    appendedText,
    // getters
    fieldList,
    canPublish,
    pendingCount,
    traceBlocks,
    currentDraft,
    // actions
    newSession,
    setMode,
    markRecording,
    setRawText,
    appendBlock,
    appendRawNote,
    appendUserNote,
    setField,
    removeField,
    applyExtract,
    applyExtractIncremental,
    applyChange,
    applyStream,
    applyReview,
    adoptChange,
    mergeCorrections,
    adoptSuggestion,
    adoptPolished,
    addExtra,
    addExtraTag,
    removeExtraTag,
    removeSubTask,
    updateSubTask,
    setSimilar,
    setStylePrompt,
    setLiveText,
    clearLiveText,
    setAppendedText,
    clearAppendedText,
    finishStreaming,
    resetDraft,
    toTaskPayload,
    toSubTaskPayload,
    /** 额外便捷方法：导出当前草稿快照 */
    buildDraft
  }
})