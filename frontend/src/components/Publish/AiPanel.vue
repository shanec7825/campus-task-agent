<script setup lang="ts">
/**
 * AI 智能发布面板（T7 / 需求 R2.2、R2.4-AC1~AC3、R2.5-AC1~AC4、R2.3-AC6/AC8、R9-AC2）
 *

 * 全链路：
 * 1. 输入原文（解析前为 textarea，解析后切换为彩色块容器）；
 * 2. 点击「AI 解析」→ **先** `findSimilar(rawText)`，top1 相似度 > threshold 时展示 SimilarTip；
 * 3. `extract` → `draft.applyExtract` 建块染色 + 字段写回；
 * 4. **自动调用一次** `review` → 问号气泡 / 润色建议 / 风格要求 / 拆解建议；
 * 5. 失败（5001/5002/5003/-1）展示内联错误态 + 「重试」（重发同一请求，草稿不丢）；
 * 6. 语音：VoiceButton 自行驱动录音，本组件只接收 toggle/error；
 *    尾片发送完毕（`onAllChunksSent`）后**自动发起一次 review**，不再有悬浮确认浮层；
 * 7. 发布：先创建主任务，仅当用户在 SubTaskCard 勾选时才串行创建子任务。
 *
 * P2 迭代（第二轮用户反馈 1/2/3 条）：
 * - 解析后左侧**仍可继续输入**：追加输入框 + 「AI 增量解析」按钮（`mode='incremental'` + `base_draft`）；
 * - 左侧渲染 5 类追溯块（raw / ai_applied / user_edit / user_note / live），live 为虚拟块（id=-1，不入 store）；
 * - 右侧「AI 建议」逐条「采纳」→ `draft.adoptChange(change)`：**只写 new_value 纯值**，左侧出紫色追溯块；
 * - 块为纯展示层：不再有块内编辑，文本修正统一走「右侧字段面板 + 增量解析」。
 *
 * 第三轮（C-VOICEUI@3 / B2~B5、B8、B9、B11）：
 * - B2：增量按钮改为默认尺寸实心，与追加输入框同组；已有文字块时主按钮变为「重新全量解析」，
 *       点击先二次确认（重建会丢弃已采纳建议与手改记录）；
 * - B3：纯语音时块容器自动切换（blocks 由 0 变非 0 且 mode==='streaming' 时收起 textarea）；
 * - B4：清空草稿文案说明「左侧块 / 右侧字段 / AI 建议 / 拆解建议」都会消失；
 * - B8：语音全部片段发送完成后自动 review，失败走 `handleFailure('review')`，草稿不清空；
 * - B9：悬浮确认浮层（mode==='suspended'）整体删除；
 * - B11：拆解建议 >=2 条才渲染，且只有勾选「随主任务一起发布」才创建子任务。
 *
 * 注意：草稿只能通过 store action 修改。
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { extract, review } from '../../api/agent'
import { ApiError } from '../../api/client'
import { findSimilar } from '../../api/kb'
import { createTask, getTask } from '../../api/tasks'
import { supported as voiceSupported, useVoiceComposer } from '../../composables/useVoiceComposer'
import { useDraftStore, type Block } from '../../stores/draft'
import type { Change, SimilarItem, SubTaskSuggestion } from '../../types/models'
import { WARN_CSS_COLOR } from '../../utils/colorPool'
import { formatChangeText } from '../../utils/traceText'
import ErrorState from '../common/ErrorState.vue'
import BlockText from '../VoiceComposer/BlockText.vue'
import FieldPanel from '../VoiceComposer/FieldPanel.vue'
import VoiceButton from '../VoiceComposer/VoiceButton.vue'
import WarnBubble from '../VoiceComposer/WarnBubble.vue'
import SimilarTip from './SimilarTip.vue'
import SubTaskCard from './SubTaskCard.vue'

/** 虚拟 live 块 id（liveText 从不写入 store.blocks） */
const LIVE_BLOCK_ID = -1

/** LLM 相关错误码：这些错误展示可重试的错误态（其余错误直接 toast） */
const LLM_ERROR_CODES: number[] = [5001, 5002, 5003, -1]

/** 错误码 → 中文标题 */
const ERROR_TITLES: Record<number, string> = {
  5001: 'AI 调用失败',
  5002: 'AI 解析超时（30 秒）',
  5003: 'AI 输出校验失败',
  [-1]: '网络异常，请检查后端服务'
}

/** 解析失败快照：重试时按 `stage` 重发同一请求 */
interface ParseFailure {
  stage: 'extract' | 'review' | 'incremental'
  text: string
  code: number
  message: string
}

/** SubTaskCard 通过 defineExpose 暴露的批量发布入参/出参 */
interface SubTaskBatchApi {
  publishAll(parentId: number): Promise<{ created: number; error: string | null }>
}

const draft = useDraftStore()
const router = useRouter()

/** 原文编辑区文本（解析后隐藏，仍保留以便「修改原文」） */
const inputText = ref('')
/** true = 显示原文编辑区；解析成功后切到块容器 */
const showRawEditor = ref(true)
/** 解析后左侧「继续补充」的输入内容（增量解析的 text） */
const appendInput = ref('')
const activeBlockId = ref<number | null>(null)

/** 已被「标记已处理」的 unresolved 项（会话内状态，不落库） */
const handledUnresolvedKeys = ref<string[]>([])

const recording = ref(false)
const parsing = ref(false)
const appending = ref(false)
const reviewing = ref(false)
const submitting = ref(false)
const similarItem = ref<SimilarItem | null>(null)
const similarThreshold = ref(0.6)
const failure = ref<ParseFailure | null>(null)
const subTaskCardRef = ref<InstanceType<typeof SubTaskCard> | null>(null)
/** 子任务是否随主任务一起发布（B11：默认不勾选） */
const includeSubtasks = ref(false)

/** 拆解建议条数（渲染条件 / 发布栏汇总 / 发布流程共用） */
const subtaskTotal = computed<number>(() => draft.suggestedSubTasks.length)

/** 有已解析块时隐藏 textarea，改用块容器（契约：AI 输入区必须是块容器） */
const showEditor = computed<boolean>(() => showRawEditor.value || draft.blocks.length === 0)

/** 主解析按钮文案：已有文字块时表明这会把草稿整体重建（B2） */
const parseButtonText = computed<string>(() => {
  if (parsing.value || reviewing.value) return '解析中…'
  return draft.blocks.length > 0 ? '重新全量解析' : 'AI 解析'
})

/**
 * 纯语音自动切块容器（B3）：
 * 语音首片写回后 `blocks` 由 0 变非 0、且 store 处于 `'streaming'`，
 * 说明用户这次是「纯语音解析」，应收起 textarea（否则空 textarea 会顶在彩色块上方）。
 * 手动解析（mode='typing'）不触发，沿用 `handleExtract` 成功后主动切块容器的行为。
 */
watch(
  () => draft.blocks.length,
  (next, prev) => {
    if (prev === 0 && next > 0 && draft.mode === 'streaming') {
      showRawEditor.value = false
    }
  }
)

/** 拆解建议刷新时重置勾选（B11）：新一批建议默认不随主任务发布 */
watch(
  () => draft.suggestedSubTasks,
  () => {
    includeSubtasks.value = false
  }
)

/**
 * 展示块列表（末尾追加语音 interim 的虚拟 live 块）。
 * 块为纯展示：直接引用 `draft.blocks`，不再做任何块内文本覆盖。
 * 契约 C-TRACE@1：live 块**只存在于展示层**（id=-1），绝不写入 `draft.blocks`。
 */
const displayBlocks = computed<Block[]>(() => {
  const list: Block[] = [...draft.blocks]
  const live = draft.liveText.trim()
  if (live !== '') {
    list.push({
      id: LIVE_BLOCK_ID,
      text: live,
      kind: 'live',
      field: null,
      status: 'pending',
      meta: null
    })
  }
  return list
})

/** 本次解析使用的原文：块容器态取 store 的 rawText */
const sourceText = computed<string>(() =>
  showEditor.value ? inputText.value.trim() : draft.rawText.trim()
)

/** 结果区是否可见（避免空白页：无块且无字段时只显示引导） */
const hasResult = computed<boolean>(
  () =>
    draft.blocks.length > 0 ||
    draft.fieldList.some((field) => field.value !== null && String(field.value).trim() !== '')
)

/** 未处理待确认项（带原始下标，标记后从列表移除） */
const visibleUnresolved = computed<Array<{ text: string; index: number }>>(() =>
  draft.unresolved
    .map((text, index) => ({ text, index }))
    .filter((item) => !handledUnresolvedKeys.value.includes(`#${item.index}`))
)

/** 发布按钮禁用原因（标题为空 / 正在录音 / 正在发布） */
const publishBlockReason = computed<string>(() => {
  if (submitting.value) return '正在发布…'
  if (draft.mode === 'recording') return '正在录音，请先停止录音再发布'
  const title = draft.fields.title?.value
  if (title === null || title === undefined || String(title).trim() === '') {
    return '标题为空，请先在右侧补齐标题'
  }
  return ''
})

const failureTitle = computed<string>(() => {
  const current = failure.value
  if (!current) return ''
  return ERROR_TITLES[current.code] ?? 'AI 解析失败'
})

function errorMessage(cause: unknown): string {
  if (cause instanceof ApiError) return `${cause.message}（code=${cause.code}）`
  if (cause instanceof Error) return cause.message
  return '未知错误'
}

/** ambiguity 字段名 → 中文标签（含扩展项） */
function fieldLabel(field: string): string {
  const direct = draft.fields[field]
  if (direct) return direct.label
  const asExtra = draft.fields[`extra_tags.${field}`]
  if (asExtra) return asExtra.label
  return field
}

/* -------------------------------------------------------------------------- */
/* 相似任务（R2.5-AC4 / R7-AC3）                                              */
/* -------------------------------------------------------------------------- */

/**
 * 解析前检索相似任务。辅助能力失败**不得**阻塞 AI 解析（R2.1-AC3 降级口径）。
 */
async function lookupSimilar(text: string): Promise<void> {
  try {
    const result = await findSimilar(text)
    similarThreshold.value = result.threshold
    const top = result.items[0]
    similarItem.value = top && top.similarity > result.threshold ? top : null
    draft.setSimilar(result.items)
  } catch {
    similarItem.value = null
  }
}

/**
 * 带入相似任务：拉取任务详情后**只覆盖**时间 / 地点 / 名额 / 志愿时长，
 * 不覆盖用户已改的标题（T7 验收 ④）。
 */
async function adoptSimilar(item: SimilarItem): Promise<void> {
  if (item.task_id === null) {
    ElMessage.info('该历史任务缺少结构化信息，无法带入')
    similarItem.value = null
    return
  }
  try {
    const detail = await getTask(item.task_id)
    if (detail.start_time) draft.setField('time', detail.start_time)
    if (detail.deadline) draft.setField('deadline', detail.deadline)
    if (detail.location) draft.setField('location', detail.location)
    if (detail.quota !== null) draft.setField('quota', detail.quota)
    if (detail.volunteer_hours !== null) draft.setField('volunteer_hours', detail.volunteer_hours)
    similarItem.value = null
    ElMessage.success('已带入起止时间 / 地点 / 名额，标题未被覆盖')
  } catch (cause) {
    ElMessage.error(`带入失败：${errorMessage(cause)}`)
  }
}

/* -------------------------------------------------------------------------- */
/* 解析 / 审核 / 失败重试                                                     */
/* -------------------------------------------------------------------------- */

function handleFailure(stage: ParseFailure['stage'], cause: unknown, text: string): void {
  const code = cause instanceof ApiError ? cause.code : -1
  if (LLM_ERROR_CODES.includes(code)) {
    failure.value = { stage, text, code, message: errorMessage(cause) }
    return
  }
  ElMessage.error(errorMessage(cause))
}

/**
 * 自动审核一次：问号气泡 / 润色 / 风格要求 / 拆解建议（R2.2-AC4、T7 验收 ⑤）。
 * 失败不抛给上层，避免把「提炼成功」误判为整体失败。
 */
async function runReview(): Promise<void> {
  if (reviewing.value) return
  reviewing.value = true
  try {
    const result = await review(draft.buildDraft())
    draft.applyReview(result)
  } catch (cause) {
    handleFailure('review', cause, draft.rawText)
  } finally {
    reviewing.value = false
  }
}

/**
 * AI 解析主流程。
 *
 * @param textOverride 重试时重发同一请求（不使用输入区当前文本）
 * @param skipSimilar  重试时跳过相似检索（相似提示为辅助能力，不必重跑）
 */
async function handleExtract(textOverride?: string, skipSimilar = false): Promise<void> {
  if (parsing.value || submitting.value) return

  const text = (textOverride ?? sourceText.value).trim()
  if (!text) {
    ElMessage.warning('请先输入任务描述')
    return
  }
  if (draft.mode === 'recording') {
    ElMessage.warning('正在录音，请先停止录音')
    return
  }

  parsing.value = true
  failure.value = null
  try {
    draft.setRawText(text)
    if (!skipSimilar) await lookupSimilar(text)

    const extracted = await extract(text)
    draft.applyExtract(extracted, text)

    handledUnresolvedKeys.value = []
    showRawEditor.value = false

    // 解析成功后自动审核一次
    await runReview()
  } catch (cause) {
    handleFailure('extract', cause, text)
  } finally {
    parsing.value = false
  }
}

function onParseClick(): void {
  void handleParseClick()
}

/**
 * 主解析按钮点击（B2）：已有文字块时先二次确认。
 * 重新全量解析会 `applyExtract(reset)` 重建块与字段，已采纳建议、手改记录都会丢失。
 */
async function handleParseClick(): Promise<void> {
  if (parsing.value || reviewing.value || submitting.value) return
  if (draft.blocks.length > 0) {
    try {
      await ElMessageBox.confirm(
        '重新全量解析将清空现有文字块并重建，已采纳的建议与手改记录会丢失，确定吗？',
        '重新全量解析',
        { type: 'warning', confirmButtonText: '重新解析', cancelButtonText: '取消' }
      )
    } catch {
      // 用户取消：无副作用（草稿、模式、输入区都不改）
      return
    }
  }
  await handleExtract()
}

/**
 * 增量解析（P2 用户反馈第 1 条）：解析后左侧仍可继续补充一句话。
 *
 * 请求体走契约 `C-FEAPI-AGENT@2`：`{ text, base_draft, mode:'incremental' }`；
 * store 侧 `applyExtractIncremental` 保证「用户原话块 → 落值 → AI 追溯块」顺序。
 *
 * @param textOverride 失败重试时重发同一段补充文本
 */
async function handleIncremental(textOverride?: string): Promise<void> {
  if (appending.value || parsing.value || submitting.value) return

  const text = (textOverride ?? appendInput.value).trim()
  if (!text) {
    ElMessage.warning('请先输入要补充的内容')
    return
  }
  if (draft.mode === 'recording') {
    ElMessage.warning('正在录音，请先停止录音')
    return
  }

  appending.value = true
  failure.value = null
  try {
    const baseDraft = draft.buildDraft()
    const extracted = await extract(text, { baseDraft, mode: 'incremental' })
    draft.applyExtractIncremental(extracted, text)
    appendInput.value = ''
    draft.setAppendedText('')
    handledUnresolvedKeys.value = []

    // 增量后重新审核一次：新字段可能带来新的歧义 / 建议
    await runReview()
  } catch (cause) {
    handleFailure('incremental', cause, text)
  } finally {
    appending.value = false
  }
}

function onIncrementalClick(): void {
  void handleIncremental()
}

/** 重发同一请求：extract / incremental 失败重跑解析；review 失败只重跑审核（草稿保留） */
async function retryParse(): Promise<void> {
  const snapshot = failure.value
  if (!snapshot || parsing.value || appending.value) return
  failure.value = null
  if (snapshot.stage === 'extract') {
    await handleExtract(snapshot.text, true)
    return
  }
  if (snapshot.stage === 'incremental') {
    await handleIncremental(snapshot.text)
    return
  }
  parsing.value = true
  try {
    await runReview()
  } finally {
    parsing.value = false
  }
}

function onRetryClick(): void {
  void retryParse()
}

/* -------------------------------------------------------------------------- */
/* 块容器 / 字段面板                                                          */
/* -------------------------------------------------------------------------- */

function onSelectBlock(block: Block): void {
  activeBlockId.value = block.id
}


/** 回到原文编辑态，便于整体重写后再次解析 */
function openRawEditor(): void {
  inputText.value = draft.rawText
  showRawEditor.value = true
}

/** 值归一：用于比较 FieldPanel 传来的 oldValue 与 store 当前值（并发保护） */
function normalizeValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

/**
 * 右侧字段手改（字段面板 emit 三参）。
 *
 * `oldValue` 由 FieldPanel 从**当前 props** 读取（并发编辑时避免旧值错位）。
 * store 的 `setField` 仍以「写入前的值」为唯一权威来源生成追溯文案；
 * 这里仅在两者不一致时告警（说明面板回写滞后），不阻断用户操作。
 */
function onUpdateField(
  key: string,
  value: string | number | null,
  oldValue?: string | number | null
): void {
  if (oldValue !== undefined) {
    const current = draft.fields[key]?.value ?? null
    if (normalizeValue(oldValue) !== normalizeValue(current)) {
      console.warn('[AiPanel] 字段旧值与 store 不一致，按 store 当前值生成追溯块', {
        key,
        oldValue,
        current
      })
    }
  }
  draft.setField(key, value)
}

/**
 * 采纳一条 AI 建议（P2 用户反馈第 2 条）：
 * 右侧**只写入 new_value 纯值**（不会把「AI建议：将…」整句写进字段），
 * 左侧由 store 追加紫色 `ai_applied` 追溯块。
 */
function onAdoptChange(change: Change): void {
  draft.adoptChange(change)
  ElMessage.success('已采纳：右侧只写入新的值，左侧保留了 AI 建议记录')
}

function onAdoptField(field: string, suggestion: string): void {
  if (!suggestion) return
  draft.adoptSuggestion(field, suggestion)
  ElMessage.success('已采纳建议')
}

function onAddExtra(): void {
  draft.addExtra()
}

function onRemoveExtra(key: string): void {
  draft.removeExtraTag(key)
}

function adoptPolished(kind: 'details' | 'notes'): void {
  draft.adoptPolished(kind)
  ElMessage.success(kind === 'details' ? '已用润色建议替换详情' : '已用润色建议替换备注')
}

function markUnresolvedHandled(index: number): void {
  handledUnresolvedKeys.value = [...handledUnresolvedKeys.value, `#${index}`]
}

/* -------------------------------------------------------------------------- */
/* 语音（R2.3）                                                               */
/* -------------------------------------------------------------------------- */

/**
 * 语音结束自动 review（B8）：注册函数方案（`useVoiceComposer().onAllChunksSent`）。
 *
 * composable 在「尾片 `is_final` 发送成功且 drain 队列清空」时调用 `finalizeIfIdle()`：
 * 先 `draft.finishStreaming()`，再触发一次回调并**清空注册表**。
 * 因此这里每收到一次回调就立即续订，保证第二轮及之后的语音结束仍能自动 review。
 * 失败沿用 `handleFailure('review')` 错误态 + 重试，草稿不清空。
 */
const voiceComposer = useVoiceComposer()
/** 当前注册的注销函数（续订时先注销旧的，避免重复多次 review） */
let stopAllChunksSent: (() => void) | null = null

/** 注册（或续订）语音收尾回调 */
function registerAllChunksSent(): void {
  stopAllChunksSent?.()
  stopAllChunksSent = voiceComposer.onAllChunksSent(() => {
    void runReview()
    // composable 触发后已清空注册表：立即续订，下一轮语音结束继续自动 review
    registerAllChunksSent()
  })
}

onMounted(() => {
  registerAllChunksSent()

  // B6 配套：刷新后 localStorage 已恢复草稿的块，直接展示块容器，
  // 避免空 textarea 遮住恢复出来的彩色块；原文同时回填，保证「修改原文」可回到 textarea。
  if (draft.blocks.length > 0) {
    showRawEditor.value = false
    if (!inputText.value) inputText.value = draft.rawText
  }
})

onBeforeUnmount(() => {
  stopAllChunksSent?.()
  stopAllChunksSent = null
})

function onVoiceToggle(next: boolean): void {
  recording.value = next
}

/** 语音错误只提示，不清空草稿（T8 已把未发送文本退回待发区） */
function onVoiceError(message: string): void {
  ElMessage.error(message)
}

/* -------------------------------------------------------------------------- */
/* 拆解建议                                                                   */
/* -------------------------------------------------------------------------- */

function onUpdateSubTask(index: number, patch: Partial<SubTaskSuggestion>): void {
  draft.updateSubTask(index, patch)
}

/** 删除建议后修正 depends_on：指向被删项 → null；指向后续项 → 下标 -1 */
function onRemoveSubTask(index: number): void {
  draft.removeSubTask(index)
  draft.suggestedSubTasks.forEach((task, taskIndex) => {
    const depends = task.depends_on
    if (depends === null || depends === undefined) return
    if (depends === index) draft.updateSubTask(taskIndex, { depends_on: null })
    else if (depends > index) draft.updateSubTask(taskIndex, { depends_on: depends - 1 })
  })
}

/* -------------------------------------------------------------------------- */
/* 发布                                                                       */
/* -------------------------------------------------------------------------- */

/**
 * 发布（B11 勾选制）：先创建主任务；**只有勾选**「将 N 个子任务随主任务一起发布」时，
 * 才交给 SubTaskCard 串行创建子任务。
 * 失败时不清空草稿；主任务已创建后即使子任务失败也会跳转详情（提示已创建 N 个）。
 */
async function handlePublish(): Promise<void> {
  if (submitting.value || !draft.canPublish) return

  submitting.value = true
  const total = subtaskTotal.value
  /** 勾选且确有建议时才创建子任务；未勾选只创建主任务 */
  const publishSubtasks = includeSubtasks.value && total > 0
  try {
    const mainTask = await createTask(draft.toTaskPayload())

    let created = 0
    let batchError: string | null = null
    if (publishSubtasks) {
      const api = subTaskCardRef.value as unknown as SubTaskBatchApi | null
      if (api) {
        const result = await api.publishAll(mainTask.id)
        created = result.created
        batchError = result.error
      } else {
        batchError = '拆解卡片未挂载，子任务未创建'
      }
    }

    if (batchError) {
      ElMessage.error(`主任务已发布；子任务已创建 ${created} 个后失败：${batchError}`)
    } else if (publishSubtasks) {
      ElMessage.success(`发布成功：主任务 + ${created} 个子任务`)
    } else if (total > 0) {
      ElMessage.success(`发布成功：仅主任务（${total} 条拆解建议未创建）`)
    } else {
      ElMessage.success(`发布成功：${mainTask.title}`)
    }

    draft.resetDraft()

    handledUnresolvedKeys.value = []
    inputText.value = ''
    appendInput.value = ''
    showRawEditor.value = true
    similarItem.value = null
    failure.value = null
    recording.value = false
    includeSubtasks.value = false

    void router.push(`/tasks/${mainTask.id}`)
  } catch (cause) {
    ElMessage.error(`发布失败：${errorMessage(cause)}`)
  } finally {
    submitting.value = false
  }
}

function onPublishClick(): void {
  if (publishBlockReason.value) {
    ElMessage.warning(publishBlockReason.value)
    return
  }
  void handlePublish()
}

/** 清空草稿（二次确认，避免误触丢失内容） */
function onClearDraft(): void {
  void ElMessageBox.confirm(
    '将清空智能模式中的全部内容：左侧彩色文字块、右侧字段值、AI 建议与拆解建议都会消失且无法恢复。如只想修改部分内容，请在右侧字段面板编辑对应字段，或补一句话做增量解析。',
    '清空草稿',
    {
      type: 'warning',
      confirmButtonText: '清空',
      cancelButtonText: '取消'
    }
  )
    .then(() => {
      draft.resetDraft()

      handledUnresolvedKeys.value = []
      inputText.value = ''
      appendInput.value = ''
      showRawEditor.value = true
      similarItem.value = null
      failure.value = null
      ElMessage.success('草稿已清空')
    })
    .catch(() => {
      // 用户取消，不做任何处理
    })
}
</script>

<template>
  <div class="ai-panel">
    <!-- 相似任务提示条：只在 top1 相似度 > threshold 时由父级数据驱动展示 -->
    <SimilarTip
      v-if="similarItem"
      :item="similarItem"
      :threshold="similarThreshold"
      @adopt="adoptSimilar(similarItem)"
      @close="similarItem = null"
    />

    <!-- AI 不可用时的降级说明（R2.1-AC3 的口径提示） -->
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="AI 智能模式"
      description="用一句话描述任务，AI 会拆成结构化字段；解析后还能继续补充一句话（AI 只改被说到的字段），所有改动都会在左侧留下可追溯的彩色块。解析失败可点「重试」，也可以随时切回手动模式发布。"
      class="ai-panel__alert"
    />

    <div class="ai-panel__grid">
      <!-- 输入区 / 块容器 -->
      <section class="composer" data-testid="ai-composer">
        <header class="composer__header">
          <span class="composer__title">任务描述</span>
          <el-tag v-if="draft.mockMode" size="small" type="warning" effect="plain">
            离线示例模式
          </el-tag>
          <el-button
            v-if="!showEditor"
            link
            type="primary"
            size="small"
            :disabled="submitting"
            @click="openRawEditor"
          >
            修改原文
          </el-button>
        </header>

        <div v-show="showEditor" class="composer__editor">
          <el-input
            v-model="inputText"
            type="textarea"
            :rows="6"
            maxlength="4000"
            show-word-limit
            resize="vertical"
            placeholder="例如：下周三下午三点在操场办秋之韵晚会，需要 3 个人搬桌椅、2 个人摄影，措辞严谨一点"
          />
          <p class="composer__hint">也可以点击「开始语音」边说边解析（Chrome / Edge）。</p>
        </div>

        <!-- 块容器：解析后渲染，颜色由 BlockText 内部按 colorForBlock 绑定 -->
        <div v-if="!showEditor" class="composer__blocks" role="list">
          <BlockText
            v-for="block in displayBlocks"
            :key="block.id"
            :block="block"
            :active="activeBlockId === block.id"
            @select="onSelectBlock"

          />
          <span v-if="displayBlocks.length === 0" class="composer__empty">暂无已解析文字块</span>
        </div>

        <!-- 追溯说明：色值全部来自 styles/color-pool.css 变量，组件内不写色值 -->
        <p v-if="!showEditor" class="composer__legend">
          <span class="composer__legend-chip is-ai-applied">AI 建议</span>
          <span class="composer__legend-chip is-user-edit">你的手改</span>
          <span class="composer__legend-chip is-user-note">你的补充</span>
          <span class="composer__legend-chip is-live">语音实时</span>
          <span class="composer__legend-text">彩色文字是追溯记录，右侧字段只落纯值</span>
        </p>

        <!-- 解析后仍可继续输入（P2 用户反馈第 1 条）：增量解析不重建已有块 -->
        <div v-if="!showEditor" class="composer__append">
          <el-input
            v-model="appendInput"
            type="textarea"
            :rows="2"
            maxlength="1000"
            show-word-limit
            resize="vertical"
            placeholder="继续补充或修改，例如：人数修改为 6 人"
            :disabled="submitting"
          />
          <div class="composer__append-actions">
            <el-button
              type="primary"
              :loading="appending"
              :disabled="draft.mode === 'recording' || submitting || parsing"
              @click="onIncrementalClick"
            >
              {{ appending ? '增量解析中…' : 'AI 增量解析' }}
            </el-button>
            <span class="composer__hint">只改被说到的字段，其余保持不变；每次改动都会留下追溯块。</span>
          </div>
        </div>

        <div class="composer__actions">
          <VoiceButton
            :recording="recording"
            :supported="voiceSupported"
            :disabled="submitting"
            @toggle="onVoiceToggle"
            @error="onVoiceError"
          />
          <div class="composer__parse">
            <el-button
              type="primary"
              :loading="parsing || reviewing"
              :disabled="draft.mode === 'recording' || submitting"
              @click="onParseClick"
            >
              {{ parseButtonText }}
            </el-button>
            <el-button
              v-if="draft.blocks.length > 0 || inputText"
              link
              type="danger"
              size="small"
              :disabled="submitting"
              @click="onClearDraft"
            >
              清空草稿
            </el-button>
          </div>
        </div>
      </section>

      <!-- 任务数据面板：与文字块同字段同色（颜色由 colorForField 提供） -->
      <aside class="fields" data-testid="ai-fields">
        <header class="fields__header">
          <span class="fields__title">任务数据面板</span>
          <el-tag v-if="draft.pendingCount > 0" size="small" type="info" effect="plain">
            未解析片段 {{ draft.pendingCount }}
          </el-tag>
        </header>
        <FieldPanel
          :fields="draft.fieldList"
          :corrections="draft.corrections"
          :ambiguities="draft.ambiguities"
          :style-prompt="draft.stylePrompt"
          @update-field="onUpdateField"
          @adopt="onAdoptField"
          @add-extra="onAddExtra"
          @remove-extra="onRemoveExtra"
        />
      </aside>
    </div>

    <!-- 解析失败态（复用 C-UI-COMMON@1 的 ErrorState）：展示原因 + 重试（重发同一请求），草稿不清空 -->
    <ErrorState
      v-if="failure"
      :message="failureTitle"
      :detail="`${failure.message}；草稿内容已保留，重试将重发同一请求`"
      retryable
      @retry="onRetryClick"
    />

    <!-- 结果区 -->
    <section v-if="hasResult" class="review">
      <!-- 待确认内容（unresolved）：红色列表，可逐条标记已处理 -->
      <div v-if="visibleUnresolved.length > 0" class="review__card">
        <header class="review__card-header">
          <span class="review__card-title">待确认内容</span>
          <el-tag size="small" type="danger" effect="plain">
            {{ visibleUnresolved.length }} 条
          </el-tag>
        </header>
        <ul class="unresolved">
          <li v-for="item in visibleUnresolved" :key="item.index" class="unresolved__item">
            <span class="unresolved__text" :style="{ color: WARN_CSS_COLOR }">{{ item.text }}</span>
            <el-button link type="primary" size="small" @click="markUnresolvedHandled(item.index)">
              标记已处理
            </el-button>
          </li>
        </ul>
      </div>

      <!-- 歧义汇总：字段面板内同字段旁也有同色问号角标，这里保证未知字段同样有采纳入口 -->
      <div v-if="draft.ambiguities.length > 0" class="review__card">
        <header class="review__card-header">
          <span class="review__card-title">审核助手追问</span>
          <el-tag size="small" type="danger" effect="plain">
            {{ draft.ambiguities.length }} 个
          </el-tag>
        </header>
        <div v-for="(item, index) in draft.ambiguities" :key="`${item.field}-${index}`" class="ambiguity">
          <el-tag size="small" effect="plain">{{ fieldLabel(item.field) }}</el-tag>
          <span class="ambiguity__question">{{ item.question }}</span>
          <WarnBubble
            :question="item.question"
            :suggestion="item.suggestion"
            @adopt="onAdoptField(item.field, $event)"
          />
        </div>
      </div>

      <!-- AI 建议（P2 用户反馈第 2 条）：右侧只落 new_value 纯值，左侧生成紫色追溯块 -->
      <div v-if="draft.suggestedChanges.length > 0" class="review__card">
        <header class="review__card-header">
          <span class="review__card-title">AI 建议</span>
          <el-tag size="small" type="info" effect="plain">
            {{ draft.suggestedChanges.length }} 条待采纳
          </el-tag>
          <span class="review__note">采纳只写入建议的新值，不会把建议语写进字段</span>
        </header>
        <div
          v-for="(item, index) in draft.suggestedChanges"
          :key="`${item.field}-${item.new_value}-${index}`"
          class="suggest"
        >
          <span class="suggest__text">{{ formatChangeText(item) }}</span>
          <el-button
            size="small"
            type="primary"
            plain
            :disabled="submitting"
            @click="onAdoptChange(item)"
          >
            采纳
          </el-button>
        </div>
      </div>

      <!-- 润色建议：必须由用户点击才替换（不静默覆盖手改内容，R2.5-AC3） -->
      <div v-if="draft.polished" class="review__card">
        <header class="review__card-header">
          <span class="review__card-title">润色建议</span>
          <span class="review__note">替换前不会自动覆盖你已修改的内容</span>
        </header>

        <div class="polished">
          <div class="polished__row">
            <span class="polished__label">详情</span>
            <p class="polished__text">{{ draft.polished.details || '（无润色建议）' }}</p>
            <el-button
              size="small"
              type="primary"
              plain
              :disabled="!draft.polished.details || submitting"
              @click="adoptPolished('details')"
            >
              一键替换详情
            </el-button>
          </div>
          <div class="polished__row">
            <span class="polished__label">备注</span>
            <p class="polished__text">{{ draft.polished.notes || '（无润色建议）' }}</p>
            <el-button
              size="small"
              type="primary"
              plain
              :disabled="!draft.polished.notes || submitting"
              @click="adoptPolished('notes')"
            >
              一键替换备注
            </el-button>
          </div>
        </div>
      </div>

      <!-- 拆解建议：>=2 条才展示；勾选后才随主任务串行创建 -->
      <SubTaskCard
        v-if="draft.suggestedSubTasks.length >= 2"
        ref="subTaskCardRef"
        v-model:include="includeSubtasks"
        :tasks="draft.suggestedSubTasks"
        :disabled="submitting"
        @update="onUpdateSubTask"
        @remove="onRemoveSubTask"
      />

      <!-- 发布栏：移动端吸底于底部导航之上 -->
      <footer class="publish-bar" data-testid="publish-bar">
        <div class="publish-bar__info">
          <span v-if="draft.suggestedSubTasks.length >= 2" class="publish-bar__summary">
            {{
              includeSubtasks
                ? `确认发布将创建 1 个主任务 + ${draft.suggestedSubTasks.length} 个串行子任务`
                : '仅发布主任务（拆解建议保留在草稿中，不会创建）'
            }}
          </span>
          <span v-if="publishBlockReason" class="publish-bar__reason">{{ publishBlockReason }}</span>
        </div>
        <el-button
          data-testid="publish-button"
          type="primary"
          size="large"
          :loading="submitting"
          :disabled="!draft.canPublish || submitting"
          @click="onPublishClick"
        >
          确认发布
        </el-button>
      </footer>
    </section>
  </div>
</template>

<style scoped>
.ai-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.ai-panel__alert {
  border-radius: 10px;
}

.ai-panel__grid {
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

.composer,
.fields {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.composer__header,
.fields__header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.composer__title,
.fields__title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.composer__editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.composer__hint {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.composer__blocks {
  min-height: 132px;
  padding: 10px;
  border: 1px dashed var(--el-border-color);
  border-radius: 10px;
  background: var(--el-fill-color-lighter);
  line-height: 1.8;
}

.composer__empty {
  font-size: 14px;
  color: var(--el-text-color-secondary);
}

/* 追溯说明：颜色只引用 color-pool.css 的 CSS 变量（禁止硬编码色值） */
.composer__legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.composer__legend-chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 8px;
  border-radius: 999px;
  border-bottom: 2px solid currentColor;
  color: var(--el-text-color-regular);
  background: var(--el-fill-color-light);
}

.composer__legend-chip.is-ai-applied {
  color: var(--c-ai-applied);
  background: color-mix(in srgb, var(--c-ai-applied) 10%, transparent);
}

.composer__legend-chip.is-user-edit {
  color: var(--c-user-edit);
  background: color-mix(in srgb, var(--c-user-edit) 10%, transparent);
}

.composer__legend-chip.is-user-note {
  color: var(--c-user-note);
  background: color-mix(in srgb, var(--c-user-note) 10%, transparent);
}

.composer__legend-chip.is-live {
  color: var(--c-live);
  border-bottom-style: dashed;
  background: color-mix(in srgb, var(--c-live) 10%, transparent);
}

.composer__legend-text {
  color: var(--el-text-color-secondary);
}

/* 解析后的「继续补充」区：输入框 + 增量按钮属于同一操作组，间距收紧 */
.composer__append {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding-top: 6px;
  border-top: 1px dashed var(--el-border-color);
}

.composer__append-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* AI 建议采纳行 */
.suggest {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 10px;
  border-radius: 8px;
  border-left: 3px solid var(--c-ai-applied);
  background: color-mix(in srgb, var(--c-ai-applied) 6%, transparent);
}

.suggest__text {
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  word-break: break-word;
}

.composer__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.composer__parse {
  display: flex;
  align-items: center;
  gap: 8px;
}


.review {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.review__card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface);
}

.review__card-header {
  display: flex;
  align-items: center;
  gap: 8px;
}

.review__card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.review__note {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.unresolved {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.unresolved__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--el-color-danger-light-9);
}

.unresolved__text {
  font-size: 14px;
  line-height: 1.5;
}

.ambiguity {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.ambiguity__question {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.polished {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.polished__row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
}

.polished__label {
  flex: none;
  width: 40px;
  font-size: 13px;
  font-weight: 600;
  color: var(--el-text-color-secondary);
}

.polished__text {
  flex: 1;
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--el-text-color-regular);
  white-space: pre-wrap;
  word-break: break-word;
}

.publish-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: var(--app-surface-raised);
  box-shadow: var(--app-shadow-sm);
}

.publish-bar__info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.publish-bar__summary {
  font-size: 14px;
  color: var(--el-text-color-regular);
}

.publish-bar__reason {
  font-size: 13px;
  color: var(--el-color-warning);
}

@media (max-width: 960px) {
  .ai-panel__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* 移动端：按「输入 → 字段 → 审核结果」顺序单栏阅读，发布栏吸底且不遮挡最后的控件 */
@media (max-width: 768px) {
  .composer,
  .fields,
  .review__card {
    padding: 14px;
  }

  .composer__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .composer__parse {
    flex-wrap: wrap;
  }

  .composer__append-actions {
    align-items: stretch;
  }

  .suggest,
  .unresolved__item,
  .polished__row {
    flex-wrap: wrap;
  }

  .polished__label {
    width: auto;
  }

  /* 为吸底发布栏留出可滚动余量，保证最后一项控件能完整露出 */
  .review {
    padding-bottom: calc(var(--app-bottom-nav-height) + var(--app-safe-bottom) + 88px);
  }

  .publish-bar {
    position: sticky;
    bottom: calc(var(--app-bottom-nav-height) + var(--app-safe-bottom) + 8px);
    z-index: 10;
    flex-wrap: wrap;
    background: var(--app-surface-raised);
    box-shadow: var(--app-shadow-md);
  }

  .publish-bar .el-button {
    width: 100%;
  }
}
</style>