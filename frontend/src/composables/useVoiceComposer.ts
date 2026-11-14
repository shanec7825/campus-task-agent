/**
 * 语音流式录入 composable（契约 C-VOICEUI@2 / T5 交付）
 *
 * 第二轮（R15 语音实时化）相对 P1 的核心变化，正是用户反馈第 4 条的根因修复：
 * 1. **切片算法**改为纯函数 `sliceChunk`（`utils/voiceSlicer.ts`）：
 *    任一标点即切 / 无标点满 12 字强制切 / 800ms 静默切；P1 的「累计 3 个标点」已作废；
 * 2. **interim 立即本地渲染**：`draft.setLiveText(transcript)`（≤200ms 节流），
 *    用户说话时界面立刻逐字出字，不再等到点「停止录音」才一次性出现；
 * 3. **Edge 静默自动续接**：Edge 在无语音一段时间后会自行 `onend`（continuous 并非真无限），
 *    用户未主动停止时 250ms 后自动重启识别，避免「录一半就断」；
 * 4. **onerror 分级**：`no-speech` 不报错不停止、`aborted` 静默、`network`/权限类报错并内部停机。
 *
 * 保留的 P1 行为（不得回归）：
 * - `onresult` 内**不做 await**，切片经 `enqueue()` + `drain()` 单飞串行发送，顺序与说话一致；
 * - transcript 去重规则（interim 前缀替换 / final 定稿）逐字保留；
 * - `stop()` 后延迟 `FINAL_DELAY_MS` 发送尾句（`is_final=true`）；
 * - 草稿是 Pinia store 的唯一写入口（C-STORE@1），本文件只调用 action，不直接改 state。
 *
 * 第三轮（C-VOICEUI@3 / B8、B9）：
 * - 尾片（`is_final=true`）发送成功且发送队列清空后调用 `draft.finishStreaming()`
 *   （`mode` 回到 `'typing'`），并**恰好一次**触发 `onAllChunksSent` 回调，
 *   由 AiPanel 借此自动发起 review（不再需要「悬浮确认」浮层）；
 * - 悬浮确认态（`mode==='suspended'` 浮层）整体下线。
 *
 * 第四轮（T1 / C5）—— 语音收尾重构（修复「尾片与晚到帧重复」）：
 * - `stop()` 只置收尾窗口 `stopping=true` 并挂 3s 兜底定时器，**不再**自己发尾片、**不再**清缓冲；
 * - 尾片改由 `onend` 延迟 `FINAL_DELAY_MS` 后结算（`commitStoppedSession()`），保帧必达；
 * - `stopping` 期间识别帧照常写入缓冲，但 `scheduleSlices()` 守卫拦截，不零散发 `is_final=false`；
 * - 缓冲区统一在 drain 内尾片成功后被 `resetLocalBuffer()` 清空，避免「清空后晚到帧二次切片」。
 *
 * 第五轮（T2 / D2、D3、D4）—— 「同一句出现两遍」根因修复：
 * - D2：`dedupTail` 的清空只保留在「新建会话」分支，`keepSession` 续接**保留**去重链
 *   （清空会让 Edge 重启后重吐前文的帧绕过 `startsWith` 去重而整句重复）；
 * - D3：新增 `trimRestartOverlap` 纯函数 + 续接帧预算 `resumedRestartFrames`，
 *   对「重吐改写版 / 加长版」以及 final 已清空 `dedupTail` 的情形按最长「后缀=前缀」重叠裁剪；
 * - D4：`commitStoppedSession()` 首行幂等守卫（`if (!stopping) return`），杜绝双结算。
 *
 * 第六轮（G1）—— 展示/发送分层（修复「同义改写型重复」，如「十一月」与「11月」同句双写）：
 * - `applyInterim` **只做实时显示**（`pushLiveText` → 蓝色 live 虚线块），不写 `fullText`、不切片；
 * - `applyFinal`（ITN 定稿帧）是**唯一**写入 `fullText` 并参与切片的入口；
 * - 依据：interim 未经 ITN，字面形态与迟到定稿不同，逐字精确去重对其结构性无效；
 *   让暂定稿不进入发送层，重复源即失去入口。`replaceTail` 自本轮起不再被调用（保留函数以备追溯）。
 */
import { computed, ref } from 'vue'

import { streamParse } from '../api/agent'
import { useDraftStore } from '../stores/draft'
import type { StreamParseResult } from '../types/models'
import {
  FINAL_DELAY_MS,
  LIVE_MAX_REFRESH_MS,
  SILENCE_CUT_MS,
  sliceChunk,
  trimRestartOverlap
} from '../utils/voiceSlicer'

/** 不支持语音时的统一提示文案（VoiceButton 直接复用） */
export const UNSUPPORTED_MESSAGE = '仅支持 Chrome / Edge 语音识别'

/**
 * 共享语音输出适配（契约 `C-VOICE-SINK@1`）。
 *
 * 发布页默认写入草稿 store；AI 完整页 / 长条 / 微展开写入当前作用域的问答输入。
 * 本轮录音在 `start()` 时固定 sink，切页或切目标后晚到的尾片仍写回发起时的目标。
 */
export interface VoiceSink {
  setLiveText(text: string): void
  clearLiveText(): void
  markRecording(): void
  finishStreaming(): void
  newSession(): string
  applyStream(res: StreamParseResult, chunk: string): void
}

/** Edge 静默 `onend` 后自动续接的延迟（毫秒） */
const RESTART_DELAY_MS = 250

/**
 * 续接重启后允许做「重吐前文」裁剪的帧数预算（第五轮 D3）。
 * Edge 重启识别后通常在最开始几帧重吐停顿前内容，之后才是新内容；
 * 预算取 3 帧，够覆盖「重吐帧 + 改写/加长帧」，又不会无限期误裁用户后续真实语句。
 */
const RESUMED_RESTART_FRAME_BUDGET = 3

/**
 * 停止录音的兜底结算延迟（毫秒）：
 * `stop()` 后浏览器迟迟不回调 `onend`（部分内核会丢失该事件）时，
 * 到点强制执行与 `onend` 相同的结算逻辑，保证尾片必达。
 * 注意：与 `FINAL_DELAY_MS`（voiceSlicer 冻结值，尾帧等待窗口）是**两个不同语义**的延迟。
 */
const FORCE_FINALIZE_MS = 3000

/* ==========================================================================
   浏览器 SpeechRecognition 最小类型（TS lib.dom 未内置该接口）
   ========================================================================== */

interface SpeechAlternativeLike {
  readonly transcript: string
  readonly confidence: number
}

interface SpeechResultLike {
  readonly isFinal: boolean
  readonly length: number
  readonly [index: number]: SpeechAlternativeLike
}

interface SpeechResultListLike {
  readonly length: number
  readonly [index: number]: SpeechResultLike
}

interface SpeechResultEventLike {
  readonly resultIndex: number
  readonly results: SpeechResultListLike
}

interface SpeechErrorEventLike {
  readonly error: string
  readonly message?: string
}

/** `webkitSpeechRecognition` / `SpeechRecognition` 实例的最小可用签名 */
export interface SpeechRecognitionLike {
  continuous: boolean
  interimResults: boolean
  lang: string
  maxAlternatives: number
  onresult: ((event: SpeechResultEventLike) => void) | null
  onerror: ((event: SpeechErrorEventLike) => void) | null
  onend: (() => void) | null
  onstart: (() => void) | null
  start(): void
  stop(): void
  abort(): void
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike

/** 取浏览器提供的识别构造函数（不存在时返回 null） */
function getSpeechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null
  const host = window as unknown as {
    SpeechRecognition?: SpeechRecognitionCtor
    webkitSpeechRecognition?: SpeechRecognitionCtor
  }
  return host.SpeechRecognition ?? host.webkitSpeechRecognition ?? null
}

/**
 * 浏览器支持性判定：必须同时满足
 * 1. 存在识别构造函数（`webkitSpeechRecognition` / `SpeechRecognition`）；
 * 2. 浏览器内核为 Chromium 系（Chrome / Edge），Safari 等虽有构造函数但行为不可靠。
 */
export function detectVoiceSupport(): boolean {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return false
  const userAgent = navigator.userAgent ?? ''
  const isChromiumBased = /(?:Chrome|Chromium|Edg)\/\d+/i.test(userAgent)
  return isChromiumBased && getSpeechRecognitionCtor() !== null
}

/** 模块级常量：浏览器 UA 不会在运行期变化 */
export const supported: boolean = detectVoiceSupport()

/* ==========================================================================
   共享状态（同一页面只应存在一路录音，故用模块级单例）
   ========================================================================== */

/** 本轮录音的完整识别文本（未经切片，保证去重信息不被切片破坏） */
const fullText = ref('')
/** 已发送给后端的字符游标（等价于方案 6.4 的 sentIndex） */
const sentIndex = ref(0)
/** 尚未发送的文本：pendingText = fullText.slice(sentIndex) */
const pendingText = computed(() => fullText.value.slice(sentIndex.value))

const recording = ref(false)
const error = ref<string | null>(null)
const lastResult = ref<StreamParseResult | null>(null)
/** 当前 interim 文本（与 `draft.liveText` 同步，供 VoiceButton 实时展示） */
const liveText = ref<string>('')

interface QueuedChunk {
  chunk: string
  isFinal: boolean
  /** 发起该切片的 sink：切页/切目标后仍写回原目标（C-VOICE-SINK@1） */
  sink: VoiceSink
  /** 发起该切片的录音轮次：缓冲清空与失败回滚只作用于当前轮 */
  round: number
}

/** 串行发送队列：前一片未返回时后续切片在此排队 */
const queue: QueuedChunk[] = []
/** 串行锁 */
let sending = false

/** 上一次参与去重比较的 transcript（interim 帧的当前版本） */
let dedupTail = ''
/**
 * 续接重启后剩余的「重吐裁剪」帧数预算（第五轮 D3）：
 * `start({keepSession:true})` 时置为 `RESUMED_RESTART_FRAME_BUDGET`，新建会话时归零；
 * 每处理一帧（非空 transcript）递减 1，归零后不再对帧做重叠裁剪。
 */
let resumedRestartFrames = 0
let recognition: SpeechRecognitionLike | null = null

/**
 * 停止录音的**兜底**结算定时器（由原 `stopTimer` 重命名而来）。
 * 语义变化：旧实现是「800ms 后发尾片」的主动定时器（根因：`recognition.stop()` 异步，
 * 定时器先 `resetLocalBuffer()` 而浏览器随后才补发最后一帧，导致文字重复）；
 * 现在只作为「onend 丢失」的 3s 兜底（`FORCE_FINALIZE_MS`），正常路径由 `onend` 结算。
 */
let forceFinalizeTimer: ReturnType<typeof setTimeout> | null = null
/** `onend` 到达后延迟 `FINAL_DELAY_MS` 结算尾片的定时器（给最后一帧转写留窗口） */
let finalizeTimer: ReturnType<typeof setTimeout> | null = null
/** 800ms 静默切片定时器 */
let silenceTimer: ReturnType<typeof setTimeout> | null = null
/** Edge onend 自动续接定时器 */
let resumeTimer: ReturnType<typeof setTimeout> | null = null
/** interim live 渲染的 trailing 定时器 */
let liveTimer: ReturnType<typeof setTimeout> | null = null

/** 用户是否主动停止（stop/abort/错误停机后为 true，阻止 onend 自动续接） */
let userStopped = false
/**
 * 收尾窗口标记：`stop()` 置 true，`onend` 结算或 3s 兜底结算时置 false。
 * 窗口内**照常接收并缓冲**识别帧（保帧），但不做零散切片（`scheduleSlices` 守卫），
 * 也不自动续接；结算时把全部剩余文本一次性作为尾片（`is_final=true`）发出。
 */
let stopping = false
let aborting = false
/** 上一次把 interim 渲染到 live 块的时间戳（节流用） */
let lastLiveAt = 0
/** 待渲染的 interim 文本（节流窗口内先缓冲） */
let pendingLiveSnapshot = ''
/** 当前会话号（crypto.randomUUID 生成后复用；与 draft.sessionId 保持一致） */
let sessionId = ''

let sharedDraftStore: ReturnType<typeof useDraftStore> | null = null

/** 在 setup 阶段绑定 Pinia 实例，回调内复用同一 store（避免脱离组件上下文取 store） */
function getDraftStore(): ReturnType<typeof useDraftStore> {
  if (!sharedDraftStore) sharedDraftStore = useDraftStore()
  return sharedDraftStore
}

/** 发布页默认 sink（懒创建：方法内取 store，保持现有「唯一写入口」不变） */
let draftSink: VoiceSink | null = null

function getDraftSink(): VoiceSink {
  if (!draftSink) {
    draftSink = {
      setLiveText: (text) => getDraftStore().setLiveText(text),
      clearLiveText: () => getDraftStore().clearLiveText(),
      markRecording: () => getDraftStore().markRecording(),
      finishStreaming: () => getDraftStore().finishStreaming(),
      newSession: () => getDraftStore().newSession(),
      applyStream: (res, chunk) => getDraftStore().applyStream(res, chunk)
    }
  }
  return draftSink
}

/** `useVoiceComposer(sink)` 注册的 sink；无参时保持发布页默认 */
let configuredSink: VoiceSink | null = null
/** 本轮录音固定的 sink：尾片结算、中止或故障停机后释放 */
let sessionSink: VoiceSink | null = null
/** 当前录音轮次：新建会话递增，Edge 自动续接沿用上一轮 */
let roundId = 0

/**
 * 未开始录音时的写回目标。
 *
 * 不得复用 `sessionSink`：上一轮尾片尚在飞时切目标再开录，会因此把新语音写入旧目标。
 */
function currentSink(): VoiceSink {
  return configuredSink ?? getDraftSink()
}

/** 当前轮次的写回目标（live 文本与切片入队使用）；无在途轮次时退回注册 sink */
function activeSink(): VoiceSink {
  return sessionSink ?? currentSink()
}

/* ==========================================================================
   「全部片段已发送」回调（C-VOICEUI@3 / B8）
   ========================================================================== */

/** 尾片成功后通知页面的回调签名 */
export type AllChunksSentHandler = () => void

/**
 * 订阅者集合：页面（AiPanel）在 `onMounted` 注册，用于语音结束后自动 review。
 * 用 Set 保证同一回调重复注册不会重复触发。
 */
const allChunksSentHandlers = new Set<AllChunksSentHandler>()

/**
 * 注册「语音片段全部发送完毕」回调（契约 C-VOICEUI@3 / B8：统一用注册函数，不新增 emit）。
 *
 * @param handler 尾片发送成功且队列清空后调用一次
 * @returns 注销函数（页面卸载时调用，避免请求泄漏到已销毁组件）
 */
export function onAllChunksSent(handler: AllChunksSentHandler): () => void {
  allChunksSentHandlers.add(handler)
  return () => {
    allChunksSentHandlers.delete(handler)
  }
}

/**
 * 触发一次「全部片段已发送」通知。
 *
 * 契约：**只触发一次，触发后清空注册**（先取快照再清空再回调，
 * 页面若需要多轮生效可在回调内续订）。单个回调异常不影响其他订阅者。
 */
function notifyAllChunksSent(): void {
  if (allChunksSentHandlers.size === 0) return
  const handlers = [...allChunksSentHandlers]
  allChunksSentHandlers.clear()
  for (const handler of handlers) {
    try {
      handler()
    } catch (cause) {
      console.warn('[useVoiceComposer] onAllChunksSent 回调异常', cause)
    }
  }
}

/** 尾片已受理、等待队列清空后统一收尾（保证「最后一次 review 看到的是完整草稿」） */
let finalizePending = false
/**
 * 待收尾的发起轮 sink 队列：不能用单槽，
 * 否则旧轮尾片晚到且新轮已有切片在队时，旧 sink 的 finishStreaming 会被新轮覆盖而永不调用。
 */
const finalizeSinks: VoiceSink[] = []

/**
 * 本轮成功写回 store 的切片数：
 * 决定「空尾片」是否还值得触发 review —— 一句话都没说成时不能拿空草稿去 review。
 */
let sentChunks = 0

/** 统一错误文案提取 */
export function toErrorMessage(cause: unknown): string {
  if (cause instanceof Error) return cause.message
  if (typeof cause === 'string' && cause.trim() !== '') return cause
  return '语音识别发生未知错误'
}

/** 会话号生成：优先 crypto.randomUUID，非安全上下文下退化为时间戳 + 随机串 */
function createSessionId(): string {
  const cryptoLike = globalThis.crypto as Crypto | undefined
  if (cryptoLike && typeof cryptoLike.randomUUID === 'function') {
    return cryptoLike.randomUUID()
  }
  const rand = Math.random().toString(36).slice(2, 10)
  return `sess-${Date.now().toString(36)}-${rand}`
}

/** 清空本地缓冲（不影响 sessionId，也不触碰 store） */
function resetLocalBuffer(): void {
  fullText.value = ''
  sentIndex.value = 0
  dedupTail = ''
  // 第五轮 D3 配套：清空续接重叠窗口，防跨会话误裁新内容
  resumedRestartFrames = 0
}

/* ==========================================================================
   live 块：interim 实时渲染（≤ LIVE_MAX_REFRESH_MS 节流）
   ========================================================================== */

function clearLiveTimer(): void {
  if (liveTimer) {
    clearTimeout(liveTimer)
    liveTimer = null
  }
}

/** 真正把缓冲文本写入 store 的 live 块（唯一写点） */
function flushLiveText(now: number): void {
  lastLiveAt = now
  const text = pendingLiveSnapshot
  if (text === liveText.value) return
  liveText.value = text
  try {
    activeSink().setLiveText(text)
  } catch {
    // store 不可用（极端时序）时不影响识别主流程，下一帧会重试
  }
}

/**
 * interim 文本推送到 live 块，刷新策略：
 * - 文本变长（用户又说出了字）→ 立即刷新，保证「说几个字就出几个字」（R15-AC4）；
 * - 距上次刷新 ≥ `LIVE_MAX_REFRESH_MS` → 兜底刷新（文本未变长但被识别引擎修正）；
 * - 其余情况合并到节流窗口结束时刷新，避免逐帧重渲染。
 */
function pushLiveText(transcript: string): void {
  pendingLiveSnapshot = transcript
  const now = Date.now()
  const elapsed = now - lastLiveAt
  if (transcript.length > liveText.value.length || elapsed >= LIVE_MAX_REFRESH_MS) {
    clearLiveTimer()
    flushLiveText(now)
    return
  }
  if (!liveTimer) {
    liveTimer = setTimeout(() => {
      liveTimer = null
      flushLiveText(Date.now())
    }, Math.max(0, LIVE_MAX_REFRESH_MS - elapsed))
  }
}

/**
 * 清空指定 sink 的 live 块，同时清掉本地节流状态。
 *
 * 不能只调用 `sink.clearLiveText()`：这样会留下在飞的 `liveTimer`，
 * 停止后定时器仍会用 activeSink 回写 interim（草稿 live 块回弹）。
 */
function clearLiveTextFor(sink: VoiceSink): void {
  pendingLiveSnapshot = ''
  clearLiveTimer()
  liveText.value = ''
  try {
    sink.clearLiveText()
  } catch {
    // store 不可用时仅本地状态生效
  }
}

/** 清空当前轮 live 块（final 定稿 / 停止 / 中止 / 出错时调用） */
function clearLiveText(): void {
  clearLiveTextFor(activeSink())
}

/* ==========================================================================
   去重 + 切片 + 静默切片
   ========================================================================== */

/**
 * 用 `nextText` 替换 `fullText` 尾部长度为 `tail.length` 的片段。
 * `tail` 不在尾部时（例如已被切片发送）退化为追加，保证不丢内容。
 */
function replaceTail(tail: string, nextText: string): void {
  const text = fullText.value
  if (tail && text.endsWith(tail)) {
    fullText.value = text.slice(0, text.length - tail.length) + nextText
  } else {
    fullText.value = text + nextText
  }
  // interim 回退可能让文本变短，已发送游标不能越过文本末尾
  if (sentIndex.value > fullText.value.length) sentIndex.value = fullText.value.length
}

/**
 * 续接重启窗口内，对浏览器「重吐前文」的帧做重叠裁剪（第五轮 D3 增强防线）。
 *
 * 背景：Edge 静默 `onend` 后会自动 `start({keepSession:true})`，重启的识别实例会从停顿点
 * 附近重吐已识别内容。D2 保留 `dedupTail` 只覆盖「与上一次 interim 完全相同 / 前缀」的情形；
 * 对「重吐改写版 / 加长版」（如 `明天下午两点` → `明天下午两点去操场`）以及 final 已清空
 * `dedupTail` 的情形仍可能整句重复。这里以 `fullText` 尾部为基准，裁掉 transcript 前缀与
 * fullText 后缀重叠的部分。
 *
 * 误裁边界：只有重叠长度 **≥2 字**才采信裁剪——单字重叠（如用户真实连说「好的好的」时
 * 尾部只重合一个「好」）在自然语言里极常见，裁掉会吞掉用户真实说的话；重叠 0 字原样返回。
 *
 * @param transcript 本帧识别文本
 * @returns 裁剪后的文本；可能为空串，表示整帧都是重吐内容、没有新内容可追加
 */
function trimResumedTranscript(transcript: string): string {
  if (resumedRestartFrames <= 0) return transcript
  // 每处理一帧（非空 transcript）消耗一次预算：重吐通常集中在重启后的最初几帧
  resumedRestartFrames = Math.max(0, resumedRestartFrames - 1)
  if (!fullText.value) return transcript

  // 只取尾部 64 字比对：重吐长度不会超过一两个停顿片段的量级，避免长文 O(n²) 比较
  const trimmed = trimRestartOverlap(fullText.value.slice(-64), transcript)
  const overlapLength = transcript.length - trimmed.length
  return overlapLength >= 2 ? trimmed : transcript
}

/**
 * interim 帧：**只做实时显示**（蓝色 live 虚线块逐字刷新）。
 *
 * 第六轮 G1：interim 是未经 ITN 的临时转写，字面形态可能与迟到定稿不同
 *（实测「十一月」vs「11月」、「三名」vs「3名」），一旦进入发送缓冲就会与 final
 * 形成"同义改写型重复"，逐字精确去重无法识别。故 interim **不写入 fullText、
 * 不参与切片、不发给 AI**，只由 pushLiveText 做可视化。
 */
function applyInterim(transcript: string): void {
  if (!transcript) return
  pushLiveText(transcript)
}

/**
 * final 帧（ITN 定稿）：**唯一写入 fullText 并参与切片切分的入口**。
 *
 * 与缓冲尾部存在精确重叠时（续接重吐原样帧）由 `trimResumedTranscript` 裁剪兜底；
 * 不再与 interim 的 dedupTail 做比较——interim 已不落缓冲，若沿用旧分支
 *（`frameText === dedupTail` 时不追加）会把定稿文本整段丢弃。
 */
function applyFinal(transcript: string): void {
  if (!transcript) return
  const frameText = trimResumedTranscript(transcript)
  if (!frameText) {
    dedupTail = ''
    clearLiveText()
    return
  }
  fullText.value += frameText
  dedupTail = ''
  clearLiveText()
}

/**
 * 按 `sliceChunk` 循环切片并入队（同步执行，不做 await）。
 *
 * **收尾窗口守卫**：`stopping` 期间不发送任何 `is_final=false` 的零散切片，
 * 全部文本留在 `pendingText` 里，由 `onend`/兜底结算一次性作为尾片发出。
 * （根因修复点：旧实现会在 `stop()` 后继续切片，与尾片在后端 `accumulated_text` 上重叠。）
 */
function scheduleSlices(): void {
  if (stopping) return
  let sliced = sliceChunk(pendingText.value)
  // 一次识别可能带回较长一段（含多个标点或超过 12 字），循环切到不足阈值为止
  while (sliced) {
    enqueue(sliced.chunk, false)
    sentIndex.value += sliced.chunk.length
    sliced = sliceChunk(pendingText.value)
  }
}

function clearSilenceTimer(): void {
  if (silenceTimer) {
    clearTimeout(silenceTimer)
    silenceTimer = null
  }
}

/**
 * 800ms 静默切片（R15-AC3）：先按标点/12 字规则切干净，
 * 剩余不足阈值的文本**整体**作为一个切片发出（`is_final=false`，用户可能继续说）。
 */
function flushPendingOnSilence(): void {
  scheduleSlices()
  const rest = pendingText.value
  if (!rest) return
  enqueue(rest, false)
  sentIndex.value += rest.length
}

/** 每次处理完识别结果都重置静默定时器（用户已主动停止时不再排期） */
function resetSilenceTimer(): void {
  clearSilenceTimer()
  if (userStopped) return
  silenceTimer = setTimeout(() => {
    silenceTimer = null
    flushPendingOnSilence()
  }, SILENCE_CUT_MS)
}

/**
 * 识别结果回调（**非 async**：不得在此 await，发送由 drain 串行驱动）。
 *
 * `stopping` 期间**仍然**正常走 `applyFinal` / `applyInterim`：浏览器在 `recognition.stop()`
 * 之后补发的最后一帧必须落进 `fullText`（即 `pendingText`），否则尾字丢失；
 * 只是随后的 `scheduleSlices()` 会被守卫拦住，不再零散发切片。
 */
function handleRecognitionResult(event: SpeechResultEventLike): void {
  const results = event.results
  for (let i = event.resultIndex; i < results.length; i += 1) {
    const result = results[i] as SpeechResultLike | undefined
    if (!result) continue
    const alternative = result[0] as SpeechAlternativeLike | undefined
    const transcript = alternative?.transcript ?? ''
    if (!transcript) continue
    if (result.isFinal) applyFinal(transcript)
    else applyInterim(transcript)
  }
  scheduleSlices()
  resetSilenceTimer()
}

/* ==========================================================================
   onerror：分级处理（no-speech 不报错 / aborted 静默 / 其余报错停机）
   ========================================================================== */

const SPEECH_ERROR_MESSAGES: Record<string, string> = {
  'not-allowed': '麦克风权限被拒绝，请在浏览器中允许使用麦克风',
  'service-not-allowed': '浏览器语音服务不可用，请使用 Chrome / Edge',
  'no-speech': '未检测到语音输入，请靠近麦克风后重试',
  'audio-capture': '未检测到可用的麦克风设备',
  network: '语音识别服务网络异常，请稍后重试',
  aborted: '语音识别已中止'
}

/**
 * 识别层故障后的内部停机：不发尾句、不触发自动 review、不自动续接。
 * 已入队的切片仍会按序发送完（不丢已经说出的话）。
 */
function haltAfterError(): void {
  userStopped = true
  // 故障停机时取消待收尾标记：本轮不会有尾片落地，不能触发 review
  finalizePending = false
  recording.value = false
  stopping = false
  clearSilenceTimer()
  if (resumeTimer) {
    clearTimeout(resumeTimer)
    resumeTimer = null
  }
  if (forceFinalizeTimer) {
    clearTimeout(forceFinalizeTimer)
    forceFinalizeTimer = null
  }
  if (finalizeTimer) {
    clearTimeout(finalizeTimer)
    finalizeTimer = null
  }
  const current = recognition
  recognition = null
  // 先清发起轮 sink 的 live 文本，再释放 sessionSink（否则会落到切页后的新 sink）
  clearLiveText()
  sessionSink = null
  finalizeSinks.length = 0
  try {
    current?.stop()
  } catch {
    // 识别实例可能已结束，忽略 InvalidStateError
  }
}

function handleRecognitionError(event: SpeechErrorEventLike): void {
  const code = event.error

  // `no-speech`：静默无语音是常见现象，不进入错误态、不停止，等待 onend 续接继续监听
  if (code === 'no-speech') return

  // `aborted`：用户主动中止或浏览器内部取消，静默处理（是否续接交给 onend 判断）
  if (code === 'aborted') {
    aborting = false
    return
  }

  // 网络 / 权限 / 无设备：写错误文案并内部停机（不触发自动 review）
  error.value = SPEECH_ERROR_MESSAGES[code] ?? `语音识别失败：${code}`
  haltAfterError()
}

/* ==========================================================================
   串行发送（P1 单飞锁与队列保留）
   ========================================================================== */

/**
 * 尾片落地后的统一收尾（B8 / B9）：
 * 1. 队列与在飞请求都空闲时才执行，保证 review 读到的是**全部**切片写回后的草稿；
 * 2. `finishStreaming()` 把 `mode` 从 `'streaming'` 置回 `'typing'`（悬浮确认态已下线）；
 * 3. 恰好触发一次 `onAllChunksSent`，由页面自动发起 review；触发后注册表被清空
 *    （页面如需下一轮语音继续自动 review，可在回调内续订）。
 *
 * `finalizePending` 在触发前清零，因此重复调用（drain 的 finally 可能多次进入）不会重复通知。
 */
function finalizeIfIdle(): void {
  if (!finalizePending || sending || queue.length > 0) return
  finalizePending = false
  // 逐个结束各发起轮的 streaming 态：发布页录音后切到 AI 页停止也不能落到 AI sink
  const sinks = finalizeSinks.splice(0, finalizeSinks.length)
  for (const sink of new Set(sinks)) {
    try {
      sink.finishStreaming()
    } catch (cause) {
      // store 不可用（极端时序）不应阻断 review 回调，仅记录
      console.warn('[useVoiceComposer] finishStreaming 调用失败', cause)
    }
  }
  notifyAllChunksSent()
}

/** 入队并触发串行发送；每个切片固定发起时的 sink 与轮次 */
function enqueue(chunk: string, isFinal: boolean, sink: VoiceSink = activeSink()): void {
  if (!chunk) {
    // 尾句为空（用户没说出新内容）：结束 streaming 态；
    // 只有本轮确实有切片落地时才通知页面 review，避免「点开就停」触发空草稿审核
    if (isFinal) {
      if (sentChunks > 0) {
        finalizeSinks.push(sink)
        finalizePending = true
      } else {
        try {
          sink.finishStreaming()
        } catch (cause) {
          console.warn('[useVoiceComposer] finishStreaming 调用失败', cause)
        }
      }
      sessionSink = null
      void drain()
    }
    return
  }
  queue.push({ chunk, isFinal, sink, round: roundId })
  void drain()
}

/**
 * 串行发送：同一时刻只有一个 `streamParse` 在飞；
 * 失败时保留未发送文本（回滚 sentIndex 或整段退回 pendingText），不清空草稿。
 * 尾片成功后置 `finalizePending`，队列排空时由 `finalizeIfIdle()` 统一收尾。
 */
async function drain(): Promise<void> {
  if (sending) return
  sending = true
  try {
    while (queue.length > 0) {
      const item = queue[0]
      let res: StreamParseResult
      try {
        // 契约 C-FEAPI@1：位置参数，内部拼 { session_id, chunk, is_final }
        res = await streamParse(sessionId, item.chunk, item.isFinal)
      } catch (cause) {
        queue.shift()
        // 只回滚与丢弃失败轮次自己的缓冲/排队项：新轮已开始时不污染它的文本
        if (item.round === roundId) {
          if (item.isFinal) {
            // 尾句失败：整段退回待发送区，保证草稿内容不丢
            fullText.value = item.chunk
            sentIndex.value = 0
            dedupTail = ''
          } else {
            sentIndex.value = Math.max(0, sentIndex.value - item.chunk.length)
          }
        }
        // 该轮尾片失败：不把未完成收尾当成可 review 的完成态；移除该 sink 的所有待收尾项
        for (let index = finalizeSinks.length - 1; index >= 0; index -= 1) {
          if (finalizeSinks[index] === item.sink) finalizeSinks.splice(index, 1)
        }
        finalizePending = finalizeSinks.length > 0
        for (let index = queue.length - 1; index >= 0; index -= 1) {
          if (queue[index].round === item.round) queue.splice(index, 1)
        }
        error.value = toErrorMessage(cause)
        break
      }

      queue.shift()
      lastResult.value = res
      error.value = null

      try {
        // 每个切片写回发起时的 sink：晚到结果不落到切页后的新目标
        item.sink.applyStream(res, item.chunk)
        if (item.round === roundId) sentChunks += 1
      } catch (cause) {
        // 合并异常不阻塞后续切片，但要暴露给调用方
        error.value = toErrorMessage(cause)
      }

      if (item.isFinal) {
        // 尾片已落地：等队列清空后再结束发起轮 sink 的 streaming 态并通知页面 review
        clearLiveTextFor(item.sink)
        finalizeSinks.push(item.sink)
        finalizePending = true
        // 缓冲清空与 sink 释放只作用于当前轮；旧轮尾片晚到时不得清掉新轮内容
        if (item.round === roundId) {
          resetLocalBuffer()
          sessionSink = null
        }
      }
    }
  } finally {
    sending = false
    finalizeIfIdle()
  }
}

/* ==========================================================================
   public API 实现
   ========================================================================== */

interface StartOptions {
  /** true 时复用当前 `sessionId`（Edge onend 续接场景，避免后端累计文本断档） */
  keepSession?: boolean
}

/**
 * 摘除当前识别实例的全部回调引用（只用于「onend 丢失、状态不可信」的兜底路径）。
 * 兜底结算后实例若再吐帧，不应再被追加进缓冲区（否则结算过的文本会被二次切片，后端重叠重复）。
 */
function detachRecognition(): void {
  const current = recognition
  recognition = null
  if (!current) return
  current.onresult = null
  current.onerror = null
  current.onend = null
  current.onstart = null
}

/**
 * 停止录音的**统一结算**（`onend` 延迟到期与 3s 兜底共用）。
 *
 * 行为：
 * 1. 退出收尾窗口（`stopping=false`），此后不再拦截切片；
 * 2. 把 `pendingText` 整体作为尾片以 `is_final=true` 入队（读取**最新**文本，不丢晚到帧）；
 * 3. `sentIndex` 推进到 `fullText` 末尾，尾片内容不会再次进入 `pendingText`；
 * 4. `clearLiveText()` 清掉实时块。
 *
 * **不清** `fullText` / `dedupTail`：清空统一交给 drain 内尾片成功后的 `resetLocalBuffer()`，
 * 这样结算前（onend 延迟窗口内）又晚到一帧也能被尾片带上。
 */
function commitStoppedSession(): void {
  // 幂等守卫：onend 与 3s 兜底/finalizeTimer 任一将来时序变化都不允许双结算
  if (!stopping) return
  // 先固定发起轮 sink：空尾片入队会释放 sessionSink，随后清 live 不能落到新目标
  const sink = activeSink()
  const tail = pendingText.value
  sentIndex.value = fullText.value.length
  stopping = false
  enqueue(tail, true, sink)
  clearLiveTextFor(sink)
}

/**
 * 新建录音前强制结算上一轮尚未落地的尾片（Critical 修复）。
 *
 * 旧实现直接清掉 finalize/force 定时器，在「onend → 尾片请求」窗口内切目标再开录时，
 * 上一轮尾句永远不会发送；同时 `sessionSink` 可能被新轮复用，导致语音串目标。
 * 这里先摘掉旧识别回调、把待发文本作为尾片入队（sink/轮次随队列项固定），再清缓冲。
 */
function settlePreviousSession(): void {
  // resumeTimer 也算未结算：Edge 静默 onend 已排期续接时，旧轮 pendingText 仍在缓冲
  if (!stopping && !finalizeTimer && !forceFinalizeTimer && !resumeTimer) return
  if (forceFinalizeTimer) {
    clearTimeout(forceFinalizeTimer)
    forceFinalizeTimer = null
  }
  if (finalizeTimer) {
    clearTimeout(finalizeTimer)
    finalizeTimer = null
  }
  if (resumeTimer) {
    // 取消旧轮自动续接，避免它在切页后复用会话重开
    clearTimeout(resumeTimer)
    resumeTimer = null
  }
  detachRecognition()
  if (stopping) {
    // 用户已 stop：按既有收尾链入队尾片（sink 仍是旧轮 sessionSink）
    commitStoppedSession()
  } else {
    // Edge 静默 onend 尚未结算：旧轮未发文本必须作为尾片写回旧 sink，
    // 否则新轮会把它当作自己的首帧重发（同目标重复、跨目标串写）
    const sink = activeSink()
    const tail = pendingText.value
    sentIndex.value = fullText.value.length
    enqueue(tail, true, sink)
    clearLiveTextFor(sink)
  }
  resetLocalBuffer()
}

/**
 * 开始录音。
 * @param options `keepSession=true` 表示自动续接（复用会话），默认新建会话隔离上一轮上下文
 */
function start(options: StartOptions = {}): void {
  if (recording.value) return
  error.value = null

  if (!options.keepSession) {
    // 非续接：先结算上一轮尾片，再开启独立轮次（不复用旧 sessionSink）
    settlePreviousSession()
    roundId += 1
  }

  // 上一轮遗留的尾句结算/静默/续接定时器必须先清掉：
  // 否则结算定时器会把新一轮录音的 pendingText 当作尾句误发并触发 review
  // 已落地但尚未收尾的旧轮 sink 必须保留：清空会让其 finishStreaming 永不调用
  finalizePending = finalizeSinks.length > 0
  sentChunks = 0
  stopping = false
  if (forceFinalizeTimer) {
    clearTimeout(forceFinalizeTimer)
    forceFinalizeTimer = null
  }
  if (finalizeTimer) {
    clearTimeout(finalizeTimer)
    finalizeTimer = null
  }
  clearSilenceTimer()
  if (resumeTimer) {
    clearTimeout(resumeTimer)
    resumeTimer = null
  }

  userStopped = false
  aborting = false

  if (!supported) {
    error.value = UNSUPPORTED_MESSAGE
    return
  }
  const Ctor = getSpeechRecognitionCtor()
  if (!Ctor) {
    error.value = UNSUPPORTED_MESSAGE
    return
  }

  // 本轮录音固定写回目标：切页/切目标后晚到的尾片仍写回发起时的 sink
  // （Edge 自动续接属于同一轮，沿用已固定的 sink）
  const sink = options.keepSession && sessionSink ? sessionSink : currentSink()
  sessionSink = sink
  if (options.keepSession && sessionId) {
    // 续接：同一段话继续用同一个后端 parse_session。
    // 识别实例重启后浏览器可能重吐停顿前内容，这里进入「重吐裁剪」窗口（D3），
    // 并由 D2 保留 dedupTail 去重链（见 else 分支的注释）。
    resumedRestartFrames = RESUMED_RESTART_FRAME_BUDGET
  } else {
    // 每次真正开始录音都新建会话：隔离后端 parse_sessions 的累计文本（newSession 不清空草稿）
    let created = ''
    try {
      created = sink.newSession()
    } catch {
      created = ''
    }
    sessionId = created || createSessionId()
    // 续接（keepSession）必须保留 dedupTail：Edge 重启后会重吐停顿前内容，清空会让 startsWith 去重链断裂并导致整句重复（第五轮 D2 根因）
    dedupTail = ''
    // 新建会话不进入重吐裁剪窗口：上一轮文本已结算/本地缓冲已清空，没有可比对的重吐前文
    resumedRestartFrames = 0
  }

  // 进入录音态（草稿唯一写入口：只调 action，不改 state）
  try {
    sink.markRecording()
  } catch {
    // store 尚未提供 markRecording 时保持静默，不阻塞录音
  }
  clearLiveText()

  // 不清空 fullText / sentIndex：上一轮失败的尾句要作为初始 pendingText 继续参与切片
  // （dedupTail 的清空已移入上方「新建会话」分支，续接必须保留去重链，第五轮 D2）

  const instance = new Ctor()
  instance.continuous = true
  instance.interimResults = true
  instance.lang = 'zh-CN'
  instance.maxAlternatives = 1
  instance.onresult = handleRecognitionResult
  instance.onerror = handleRecognitionError
  instance.onend = () => {
    // onend 已到：3s 兜底不再需要，先清掉（正常路径只走本分支结算）
    if (forceFinalizeTimer) {
      clearTimeout(forceFinalizeTimer)
      forceFinalizeTimer = null
    }
    // 浏览器已收尾，但「是否续接」由三重短路决定：用户未停止 + 未 abort + 本地仍在录音态
    const wasRecording = recording.value
    const shouldResume = !userStopped && !aborting && wasRecording
    recognition = null
    clearSilenceTimer()
    // 实例已结束，本地录音态必须复位：否则 250ms 后的 start() 会被首行 `if (recording) return` 短路
    recording.value = false

    // 分支一：用户主动停止（`stopping`）→ 延迟 FINAL_DELAY_MS 结算尾片后结束，**绝不续接**
    if (stopping) {
      // 延迟窗口内浏览器补发的最后一帧仍会走 handleRecognitionResult：
      // 缓冲区保持不清，帧全部落进 pendingText，到点后整体作为尾片发出（保帧）
      finalizeTimer = setTimeout(() => {
        finalizeTimer = null
        commitStoppedSession()
      }, FINAL_DELAY_MS)
      return
    }

    // 分支二：Edge 静默自动 onend → 自动续接（与上面的停止分支互斥）
    if (!shouldResume) return
    // Edge 在静默一段时间后会自动 onend（continuous 并非真无限）：
    // 用户没点「停止录音」就自动续接，避免要反复点按钮；续接失败静默（不打断用户）
    resumeTimer = setTimeout(() => {
      resumeTimer = null
      if (userStopped || aborting || recording.value) return
      try {
        start({ keepSession: true })
      } catch {
        // 续接失败静默：下次 onend 或用户点击可恢复
      }
    }, RESTART_DELAY_MS)
  }
  recognition = instance

  try {
    instance.start()
    recording.value = true
  } catch (cause) {
    recognition = null
    recording.value = false
    error.value = toErrorMessage(cause)
  }
}

/**
 * 停止录音（v2：**只置收尾窗口 + 兜底**，不再自己发尾片）。
 *
 * 时序（关键：`recognition.stop()` 是异步的，尾帧可能在其后才补发）：
 * 1. 置 `stopping=true` 进入收尾窗口，期间识别帧照常写入缓冲区，但不零散切片；
 * 2. 调 `recognition.stop()` 让浏览器收尾并补发最后一帧；
 * 3. 启动 `FORCE_FINALIZE_MS`（3s）兜底：`onend` 若丢失，到点执行与 `onend` 相同的结算；
 * 4. 真正发尾片由 `onend` → `FINAL_DELAY_MS` → `commitStoppedSession()` 完成。
 *
 * 本函数**不再**启动 800ms 尾片定时器、**不再** `resetLocalBuffer()`、**不再** `enqueue()`——
 * 旧实现的这三步正是「文字重复」的根因（清缓冲后晚到帧被再次切片发送，与尾片在后端累积文本上重叠）。
 */
function stop(): void {
  // 防重入：3s 兜底或 onend 结算窗口已激活时，重复点击不应重置计时、也不应重复进入收尾
  if (forceFinalizeTimer || finalizeTimer) return
  if (!recognition && !recording.value) return

  userStopped = true
  recording.value = false
  clearSilenceTimer()
  if (resumeTimer) {
    clearTimeout(resumeTimer)
    resumeTimer = null
  }

  // 收尾窗口必须先于 `stop()` 置位：帧继续进缓冲区（handleRecognitionResult 不设守卫），
  // 但 scheduleSlices 被拦截；即便内核同步派发 onend，也能正确进入结算分支。
  stopping = true
  try {
    recognition?.stop()
  } catch {
    // 重复 stop 会抛 InvalidStateError，忽略即可
  }

  // 兜底：部分内核 stop 后可能丢失 onend，超过 3s 未结算则强制结算，保证尾片必达
  forceFinalizeTimer = setTimeout(() => {
    forceFinalizeTimer = null
    // onend 都丢了，实例状态已不可信：摘掉回调，避免结算后晚到帧被二次切片（重复）
    detachRecognition()
    commitStoppedSession()
  }, FORCE_FINALIZE_MS)
}

/** 立即中止：不发送任何内容，也不触发自动 review */
function abort(): void {
  userStopped = true
  aborting = true
  finalizePending = false
  sentChunks = 0
  stopping = false
  if (forceFinalizeTimer) {
    clearTimeout(forceFinalizeTimer)
    forceFinalizeTimer = null
  }
  if (finalizeTimer) {
    clearTimeout(finalizeTimer)
    finalizeTimer = null
  }
  clearSilenceTimer()
  if (resumeTimer) {
    clearTimeout(resumeTimer)
    resumeTimer = null
  }
  try {
    recognition?.abort()
  } catch {
    // 忽略浏览器状态异常
  }
  recognition = null
  recording.value = false
  queue.length = 0
  // 先清发起轮 sink 的 live 文本，再释放 sessionSink
  clearLiveText()
  sessionSink = null
  finalizeSinks.length = 0
  // 不提前释放 sending 锁：仍在飞的请求结束后由 drain 的 finally 统一释放，
  // 否则新入队的切片可能与旧请求并发，造成草稿乱序。
  resetLocalBuffer()
}

/** 录音开关切换（VoiceButton 使用） */
function toggle(): void {
  if (recording.value) stop()
  else start()
}

/**
 * @returns 契约 `C-VOICEUI@3 C` 要求的外部 API（P1 / P2 字段全部保留，
 *   `liveText` 为 P2 新增，`onAllChunksSent` 为第三轮新增：语音结束自动 review 的注册入口）。
 */
export function useVoiceComposer(sink?: VoiceSink): {
  supported: boolean
  recording: typeof recording
  pendingText: typeof pendingText
  error: typeof error
  lastResult: typeof lastResult
  liveText: typeof liveText
  start: typeof start
  stop: typeof stop
  abort: typeof abort
  toggle: typeof toggle
  onAllChunksSent: typeof onAllChunksSent
} {
  // 无参时退回发布页默认 sink；AI 形态在开始录音前传入作用域 sink
  configuredSink = sink ?? null
  // 在 setup 阶段完成 store 绑定，后续异步回调可直接使用
  getDraftStore()
  return {
    supported,
    recording,
    pendingText,
    error,
    lastResult,
    liveText,
    start,
    stop,
    abort,
    toggle,
    onAllChunksSent
  }
}