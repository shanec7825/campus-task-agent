<script setup lang="ts">
/**
 * AI 统一入口（契约 `C-FE-AI@1` / `C-AI-CHAT@1` / `C-AI-PAGE@1`）。
 *
 * - 通知卡复用既有通知 store；通知加载失败不影响问答；
 * - 会话与消息来自后端持久化，刷新后恢复最近一次会话；
 * - 回答只展示服务端返回的可见任务引用，不把客户端推断当作来源；
 * - `@` 面板把任务 / 活动作为会话作用域、把 Library 资料作为指定资料上下文。
 */
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { storeToRefs } from 'pinia'

import { ApiError } from '../api/client'
import AgentVoiceButton from '../components/ai/AgentVoiceButton.vue'
import ContextPicker from '../components/ai/ContextPicker.vue'
import HistoryEntry from '../components/nav/HistoryEntry.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import SegmentedTabs from '../components/common/SegmentedTabs.vue'
import { useVoiceComposer } from '../composables/useVoiceComposer'
import { useAiChatStore } from '../stores/aiChat'
import { useNotificationsStore } from '../stores/notifications'
import type { AiCitation, AiCitationKind, NotificationItem } from '../types/models'

/** 权限模式（`C-AI-PAGE@1`）：写操作尚未接入，`operate` 只展示不可选 */
const ACCESS_OPTIONS = [
  { value: 'analyze', label: '只分析' },
  { value: 'operate', label: '可操作' }
]
/** 指定资料上下文上限（`C-AI-CONTEXT@1`：后端取前 5 条） */
const RESOURCE_LIMIT = 5

/** 回答来源类型标签（`C-AI-DOC-CONTEXT@1`）：任务 / 资料 */
const CITATION_KIND_LABELS: Record<AiCitationKind, string> = {
  task: '任务',
  doc: '资料'
}

const route = useRoute()
const router = useRouter()
const notificationsStore = useNotificationsStore()
const aiChat = useAiChatStore()
const voice = useVoiceComposer()
const {
  messages,
  input,
  conversationId,
  historyLoading,
  historyError,
  historyItems,
  historyTotal,
  historyHasMore,
  historyScopeOnly,
  historyOpen,
  sending,

  hasMessages,
  usage,
  usageLoading,
  usageError,
  scopeType,
  scopeId,
  scopeLabel
} = storeToRefs(aiChat)
// 录音中禁用文字输入：interim/定稿写回以录制基文为准，不能让手打被整体覆盖
const voiceRecording = computed(() => voice.recording.value)

const noticesLoading = ref(true)
const noticesError = ref('')
const historyListLoading = ref(false)
const messageListRef = ref<HTMLElement | null>(null)

const unreadItems = computed<NotificationItem[]>(() => notificationsStore.unreadItems.slice(0, 3))
const unreadCount = computed<number>(() => notificationsStore.unread)
/** 右栏视图：待处理（未归档）或归档箱，`?panel=archive` 可深链 */
const noticePanel = computed<'inbox' | 'archive'>(() =>
  route.query.panel === 'archive' ? 'archive' : 'inbox'
)
const paneItems = computed<NotificationItem[]>(() =>
  noticePanel.value === 'archive' ? notificationsStore.archivedItems : unreadItems.value
)
const paneTitle = computed<string>(() =>
  noticePanel.value === 'archive' ? '归档通知' : '待处理通知'
)
/** 右栏折叠（桌面）：`cta_ai_notice_panel`；移动端保持堆叠 */
const NOTICE_COLLAPSED_KEY = 'cta_ai_notice_panel'
function readNoticeCollapsed(): boolean {
  try {
    return window.localStorage.getItem(NOTICE_COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}
const noticeCollapsed = ref(readNoticeCollapsed())
function toggleNoticePane(): void {
  noticeCollapsed.value = !noticeCollapsed.value
  try {
    window.localStorage.setItem(NOTICE_COLLAPSED_KEY, noticeCollapsed.value ? '1' : '0')
  } catch {
    // 存储失败只影响下次记忆，不影响当前折叠
  }
}
const quotaExhausted = computed<boolean>(() => usage.value !== null && usage.value.remaining <= 0)
const isScoped = computed<boolean>(() => scopeType.value !== 'general')

/** 当前权限模式；`operate` 不可选，因此只会在 `analyze` */
const accessMode = ref<'analyze' | 'operate'>('analyze')

const pickerOpen = ref(false)
/** 已选资料的标题，仅用于 chip 展示；资料本身由后端按 id 校验可见性 */
const resourceTitles = ref<Record<number, string>>({})

const scopeChip = computed<{ type: 'task' | 'activity'; id: number; label: string } | null>(() => {
  const type = scopeType.value
  const id = scopeId.value
  if (type === 'general' || id === null) return null
  const label = scopeLabel.value || (type === 'activity' ? `活动 #${id}` : `任务 #${id}`)
  return { type, id, label }
})
const resourceChips = computed<Array<{ id: number; title: string }>>(() =>
  aiChat.contextResourceIds.map((id) => ({
    id,
    title: resourceTitles.value[id] ?? `资料 #${id}`
  }))
)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function shortText(value: string, limit = 90): string {
  return value.length > limit ? `${value.slice(0, limit)}…` : value
}

function shortTime(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 16) : value
}

async function scrollToBottom(): Promise<void> {
  await nextTick()
  const element = messageListRef.value
  if (element) element.scrollTop = element.scrollHeight
}

async function loadHistory(force = false): Promise<void> {
  const refreshError = await aiChat.restore(force)
  if (refreshError) ElMessage.error(`刷新对话失败：${refreshError}`)
  await scrollToBottom()
}

/** 历史抽屉第一页 / 下一页；scopeOnly 在「最近」标签下只列当前目标的会话。 */
async function loadConversationHistory(reset: boolean, scopeOnly = false): Promise<void> {
  historyListLoading.value = true
  try {
    await aiChat.loadHistory(reset, scopeOnly)
  } finally {
    historyListLoading.value = false
  }
}

/** 选中会话写回 `?conversation=`，刷新/前进后退都按 query 恢复。 */
function syncConversationQuery(id: number | null): void {
  const current = typeof route.query.conversation === 'string' ? route.query.conversation : ''
  if (id === null) {
    if (!current) return
    const query = { ...route.query }
    delete query.conversation
    void router.replace({ query })
    return
  }
  if (current === String(id)) return
  void router.replace({ query: { ...route.query, conversation: String(id) } })
}

function syncHistoryQuery(open: boolean): void {
  const current = route.query.history === '1'
  if (current === open) return
  const query = { ...route.query }
  if (open) query.history = '1'
  else delete query.history
  // 关闭抽屉不得清掉已选中会话：以 store 当前会话为准补齐 query。
  if (conversationId.value !== null) query.conversation = String(conversationId.value)
  void router.replace({ query })
}

function queryConversationId(): number | null {
  const raw = route.query.conversation
  if (typeof raw !== 'string' || !/^\d+$/.test(raw)) return null
  return Number(raw)
}

async function openHistoryConversation(id: number): Promise<void> {
  const ok = await aiChat.selectConversation(id)
  if (!ok) {
    ElMessage.error('该会话不存在或无权查看，请稍后重试')
    return
  }
  // 显式写回：store 的 conversationId 可能已指向该会话（如页面刚恢复的就是这一条），
  // 只靠 conversationId watcher 不会触发。
  syncConversationQuery(id)
  aiChat.historyOpen = false
  await scrollToBottom()
}

async function openHistoryDrawer(): Promise<void> {
  aiChat.historyOpen = true
  await loadConversationHistory(true, false)
}

function switchHistoryTab(scopeOnly: boolean): void {
  if (historyScopeOnly.value === scopeOnly) return
  void loadConversationHistory(true, scopeOnly)
}

async function startNewConversation(): Promise<void> {
  if (voice.recording.value) voice.stop()
  aiChat.newConversation()
  await nextTick()
}

watch(conversationId, (id) => syncConversationQuery(id))
watch(historyOpen, (open) => syncHistoryQuery(open))
watch(
  () => route.query.history,
  (value) => {
    aiChat.historyOpen = value === '1'
    if (value === '1' && historyItems.value.length === 0) {
      void loadConversationHistory(true, false)
    }
  }
)
watch(
  () => route.query.conversation,
  async (value) => {
    const target = typeof value === 'string' && /^\d+$/.test(value) ? Number(value) : null
    // 前进/后退到无会话 query：保留当前视图，避免清空刚打开的会话。
    if (target === null || target === conversationId.value) return
    const ok = await aiChat.selectConversation(target)
    if (!ok) ElMessage.error('该会话不存在或无权查看')
    else await scrollToBottom()
  }
)

/** 回到通用助手：恢复通用作用域缓存/最近会话，不删除已有 scoped 会话。 */
async function backToGeneral(): Promise<void> {
  if (voice.recording.value) voice.stop()
  aiChat.setScope('general', null)
  await loadHistory()
}

/** 选中任务 / 活动作为会话作用域，复用通用的作用域切换流程 */
async function applyContextScope(
  type: 'task' | 'activity',
  id: number,
  title: string
): Promise<void> {
  if (voice.recording.value) voice.stop()
  pickerOpen.value = false
  aiChat.setScope(type, id, title)
  await loadHistory()
}

function selectTask(id: number, title: string): void {
  void applyContextScope('task', id, title)
}

function selectActivity(id: number, title: string): void {
  void applyContextScope('activity', id, title)
}

function removeResource(id: number): void {
  aiChat.contextResourceIds = aiChat.contextResourceIds.filter((item) => item !== id)
  const next = { ...resourceTitles.value }
  delete next[id]
  resourceTitles.value = next
}

/** 资料 chip 多选：再点同一条视为取消，最多 `RESOURCE_LIMIT` 条 */
function toggleResource(id: number, title: string): void {
  const ids = aiChat.contextResourceIds
  if (ids.includes(id)) {
    removeResource(id)
    return
  }
  if (ids.length >= RESOURCE_LIMIT) {
    ElMessage.warning(`最多选择 ${RESOURCE_LIMIT} 条资料`)
    return
  }
  aiChat.contextResourceIds = [...ids, id]
  resourceTitles.value = { ...resourceTitles.value, [id]: title }
}

/** 输入 `@` 打开上下文面板；`@` 本身不进入正文，避免被当作无意义字符发送 */
function onComposerKeydown(event: KeyboardEvent): void {
  if (event.key !== '@') return
  event.preventDefault()
  pickerOpen.value = true
}

function changeAccessMode(value: string): void {
  // 「可操作」当前不可用：拒绝该值即不会切换模式
  if (value === 'operate') return
  accessMode.value = value as 'analyze' | 'operate'
}

watch([scopeType, scopeId], () => {
  // 切换目标必须显式停止：晚到尾片仍写回发起时的作用域
  if (voice.recording.value) voice.stop()
})

async function loadNotices(): Promise<void> {
  noticesLoading.value = true
  noticesError.value = ''
  try {
    await Promise.all([notificationsStore.refresh(20), notificationsStore.loadArchived(20)])
  } catch (err) {
    noticesError.value = errorMessage(err)
  } finally {
    noticesLoading.value = false
  }
}

async function sendMessage(text?: string): Promise<void> {
  // 录音中不发送半句 interim；先停止录音再发送
  if (voiceRecording.value) return
  if (accessMode.value !== 'analyze') {
    ElMessage.warning('写操作尚未接入，当前只能分析')
    return
  }
  if (quotaExhausted.value) {
    ElMessage.warning('今日 AI 问答额度已用完；任务、通知与审批等协作功能仍可正常使用')
    return
  }
  try {
    const sent = await aiChat.send(text)
    if (sent) await scrollToBottom()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function openNotice(item: NotificationItem): Promise<void> {
  try {
    if (item.is_read === 0) await notificationsStore.markRead([item.id])
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
  if (item.task_id !== null) {
    void router.push({ name: 'detail', params: { id: item.task_id } })
  }
}


async function markAllNoticesRead(): Promise<void> {
  try {
    await notificationsStore.markRead(notificationsStore.unreadItems.map((item) => item.id))
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function archiveNotice(item: NotificationItem): Promise<void> {
  try {
    await notificationsStore.archive([item.id])
    ElMessage.success('已归档，可在左侧「归档通知」查看')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function switchNoticePanel(panel: 'inbox' | 'archive'): void {
  const query: Record<string, string> = {}
  for (const [key, value] of Object.entries(route.query)) {
    if (typeof value === 'string') query[key] = value
  }
  if (panel === 'archive') query.panel = 'archive'
  else delete query.panel
  void router.replace({ query })
}

/** 只认 doc；未知值与历史的 activity 一律兜底为 task，避免出现死标签 */
function citationKind(citation: AiCitation): AiCitationKind {
  return citation.kind === 'doc' ? 'doc' : 'task'
}

function citationLabel(citation: AiCitation): string {
  return CITATION_KIND_LABELS[citationKind(citation)]
}

function citationTagType(citation: AiCitation): 'info' | 'success' {
  return citationKind(citation) === 'doc' ? 'success' : 'info'
}

function openCitation(taskId: number): void {
  void router.push({ name: 'detail', params: { id: taskId } })
}

/** 资料引用跳 Library 引用区；没有资料详情路由，不做客户端拼接 */
function openCitationLibrary(): void {
  void router.push({ name: 'library' })
}

onMounted(async () => {

  await Promise.allSettled([loadNotices(), aiChat.loadUsage()])
  // `?conversation=` 优先恢复指定会话；失败或缺失时回退最近一条。
  const requested = queryConversationId()
  if (requested !== null) {
    const opened = await aiChat.openConversation(requested)
    if (opened) {
      await scrollToBottom()
    } else {
      ElMessage.error('该会话不存在或无权查看，已回到最近会话')
      await loadHistory()
      syncConversationQuery(conversationId.value)
    }
  } else {
    await loadHistory()
  }
  if (route.query.history === '1') {
    aiChat.historyOpen = true
    await loadConversationHistory(true, false)
  }
})

onUnmounted(() => {
  // 离开完整页时正常停止（不 abort）：尾片仍按本轮 sink 结算
  if (voice.recording.value) voice.stop()
})
</script>

<template>
  <section class="app-page ai-console" :aria-busy="historyLoading || sending ? 'true' : 'false'">
    <header class="app-page-header">
      <div>
        <h1 class="app-page-title">AI 助手</h1>
      </div>
      <div class="app-actions">
        <el-button v-if="isScoped" class="header-button" @click="backToGeneral">
          回到通用助手
        </el-button>
        <el-button class="header-button" @click="startNewConversation">新对话</el-button>
        <el-button class="header-button" @click="openHistoryDrawer">历史记录</el-button>
      </div>
    </header>

    <div class="ai-three-pane" :class="{ 'has-collapsed-notice': noticeCollapsed }">
    <aside
      class="app-section-card notices-card ai-notice-pane"
      :class="{ 'is-collapsed': noticeCollapsed }"
      aria-labelledby="ai-notices-heading"
    >
      <button
        type="button"
        class="notice-toggle"
        :aria-label="noticeCollapsed ? '展开通知栏' : '收起通知栏'"
        :aria-expanded="!noticeCollapsed"
        @click="toggleNoticePane"
      >
        {{ noticeCollapsed ? '‹' : '›' }}
      </button>
      <div class="card-head">
        <div>
          <h2 id="ai-notices-heading" class="section-title">{{ paneTitle }}</h2>
          <p class="section-hint">
            <template v-if="noticePanel === 'inbox'">
              未读 {{ unreadCount }} 条 · 最近 {{ unreadItems.length }} 条
            </template>
            <template v-else>已处理 {{ notificationsStore.archivedItems.length }} 条</template>
          </p>
        </div>
        <div class="app-actions">
          <el-button
            v-if="noticePanel === 'inbox' && unreadCount > 0"
            class="header-button"
            text
            @click="markAllNoticesRead"
          >
            全部已读
          </el-button>
          <el-button
            class="header-button"
            text
            @click="switchNoticePanel(noticePanel === 'archive' ? 'inbox' : 'archive')"
          >
            {{ noticePanel === 'archive' ? '返回待处理' : '查看归档' }}
          </el-button>
        </div>
      </div>

      <p v-if="noticesLoading" class="inline-hint">正在读取通知…</p>
      <div v-else-if="noticesError" class="inline-error">
        <span>{{ noticesError }}</span>
        <el-button class="header-button" text @click="loadNotices">重试</el-button>
      </div>
      <p v-else-if="paneItems.length === 0" class="inline-hint">
        {{ noticePanel === 'archive' ? '归档箱为空。' : '当前没有未读通知。' }}
      </p>
      <ul v-else class="notice-list">
        <li v-for="item in paneItems" :key="item.id" class="notice-item">
          <div class="notice-body">
            <p class="notice-title">{{ item.title }}</p>
            <p class="notice-text">{{ shortText(item.content) }}</p>
            <p class="notice-time">
              <template v-if="noticePanel === 'archive'">
                已处理于 {{ shortTime(item.archived_at ?? item.created_at) }}
              </template>
              <template v-else>{{ shortTime(item.created_at) }}</template>
            </p>
          </div>
          <div class="notice-actions">
            <el-button class="notice-action" @click="openNotice(item)">
              {{ item.task_id !== null ? '查看任务' : '标为已读' }}
            </el-button>
            <el-button
              v-if="noticePanel === 'inbox'"
              class="notice-action"
              text
              @click="archiveNotice(item)"
            >
              归档
            </el-button>
          </div>
        </li>
      </ul>
    </aside>

    <section class="app-section-card chat-card" aria-labelledby="ai-chat-heading">
      <div class="card-head">
        <h2 id="ai-chat-heading" class="section-title">事务问答</h2>
      </div>

      <LoadingState v-if="historyLoading" :rows="3" />
      <ErrorState
        v-else-if="historyError && !hasMessages"
        :message="historyError"
        detail="对话记录加载失败，请稍后重试；通知卡不受影响。"
        retryable
        @retry="() => loadHistory(true)"
      />
      <EmptyState v-else-if="!hasMessages" title="从一个具体问题开始" />

      <div v-else ref="messageListRef" class="message-list" aria-live="polite">
        <article
          v-for="item in messages"
          :key="item.id"
          class="message"
          :class="`message--${item.role}`"
        >
          <p class="message-role">{{ item.role === 'user' ? '你' : '助手' }}</p>
          <p class="message-content">{{ item.content }}</p>
          <ul v-if="item.citations.length > 0" class="citation-list" aria-label="回答来源">
            <li
              v-for="(citation, index) in item.citations"
              :key="`${citation.kind}-${index}`"
              class="citation-item"
            >
              <el-tag
                size="small"
                effect="plain"
                :type="citationTagType(citation)"
                class="citation-tag"
              >
                {{ citationLabel(citation) }}
              </el-tag>
              <button
                v-if="citationKind(citation) === 'doc'"
                type="button"
                class="citation-link"
                :aria-label="`在 Library 查看资料：${citation.title}`"
                @click="openCitationLibrary"
              >
                {{ citation.title }}
              </button>
              <button
                v-else
                type="button"
                class="citation-link"
                :aria-label="`打开来源任务：${citation.title}`"
                @click="openCitation(citation.id)"
              >
                {{ citation.title }}
              </button>
            </li>
          </ul>
          <p class="message-time">{{ shortTime(item.created_at) }}</p>
        </article>
      </div>

      <div class="quota-bar">
        <span v-if="usage" class="quota-text">剩余 {{ usage.remaining }} 次</span>
        <span v-else-if="usageLoading" class="quota-text">正在读取 AI 额度…</span>
        <span v-else-if="usageError" class="quota-text quota-error">AI 额度读取失败：{{ usageError }}</span>
      </div>
      <el-alert
        v-if="quotaExhausted"
        type="warning"
        :closable="false"
        show-icon
        title="今日 AI 问答额度已用完"
        description="任务、通知、报名、审批与验收等协作功能仍可正常使用。"
        class="quota-alert"
      />

      <div v-if="scopeChip || resourceChips.length > 0" class="context-chips" aria-label="本轮上下文">
        <span v-if="scopeChip" class="context-chip context-chip--scope">
          <span class="context-chip__label">{{ scopeChip.label }}</span>
          <button
            type="button"
            class="context-chip__remove"
            :aria-label="`移除上下文：${scopeChip.label}`"
            @click="backToGeneral"
          >
            ×
          </button>
        </span>
        <span
          v-for="chip in resourceChips"
          :key="`resource-${chip.id}`"
          class="context-chip context-chip--resource"
        >
          <span class="context-chip__label">{{ chip.title }}</span>
          <button
            type="button"
            class="context-chip__remove"
            :aria-label="`移除资料：${chip.title}`"
            @click="removeResource(chip.id)"
          >
            ×
          </button>
        </span>
      </div>

      <div class="composer-area">
        <ContextPicker
          :open="pickerOpen"
          @select-task="selectTask"
          @select-activity="selectActivity"
          @toggle-resource="toggleResource"
          @close="pickerOpen = false"
        />
        <div class="composer-access">
          <SegmentedTabs
            :model-value="accessMode"
            :options="ACCESS_OPTIONS"
            :disabled-values="['operate']"
            ariaLabel="AI 权限"
            aria-label="AI 权限"
            @update:model-value="changeAccessMode"
          />
        </div>
        <div class="composer">
          <button
            type="button"
            class="composer-at"
            aria-label="添加任务、活动或资料上下文"
            @click="pickerOpen = !pickerOpen"
          >
            @
          </button>
          <el-input
            v-model="input"
            class="composer-input"
            type="textarea"
            :rows="2"
            maxlength="2000"
            show-word-limit
            resize="none"
            :disabled="sending || quotaExhausted || voiceRecording"
            placeholder="输入问题，例如：我有哪些临近截止的事务？"
            aria-label="向 AI 助手提问"
            @keydown="onComposerKeydown"
            @keydown.enter.exact.prevent="sendMessage()"
          />
          <AgentVoiceButton
            class="composer-voice"
            :disabled="!voiceRecording && (sending || quotaExhausted)"
          />
          <el-button
            class="send-button"
            type="primary"
            :loading="sending"
            :disabled="sending || historyLoading || quotaExhausted || voiceRecording || input.trim().length === 0"
            @click="sendMessage()"
          >
            发送
          </el-button>
        </div>
      </div>
    </section>
    </div>

    <el-drawer
      v-model="historyOpen"
      title="历史记录"
      direction="rtl"
      size="min(420px, 92vw)"
      class="history-drawer"
    >
      <div class="history-toolbar" role="tablist" aria-label="AI 历史范围">
        <button
          type="button"
          role="tab"
          class="history-tab"
          :class="{ 'is-active': historyScopeOnly }"
          :aria-selected="historyScopeOnly ? 'true' : 'false'"
          @click="switchHistoryTab(true)"
        >
          最近
        </button>
        <button
          type="button"
          role="tab"
          class="history-tab"
          :class="{ 'is-active': !historyScopeOnly }"
          :aria-selected="!historyScopeOnly ? 'true' : 'false'"
          @click="switchHistoryTab(false)"
        >
          全部
        </button>
      </div>

      <p v-if="historyListLoading && historyItems.length === 0" class="inline-hint">
        正在读取历史记录…
      </p>
      <div v-else-if="historyError && historyItems.length === 0" class="inline-error">
        <span>{{ historyError }}</span>
        <el-button
          class="header-button"
          text
          @click="loadConversationHistory(true, historyScopeOnly)"
        >
          重试
        </el-button>
      </div>
      <p v-else-if="historyItems.length === 0" class="inline-hint">暂无历史会话。</p>
      <ul v-else class="history-list">
        <li v-for="item in historyItems" :key="item.id" class="history-list__item">
          <HistoryEntry :conversation="item" @select="openHistoryConversation" />
        </li>
      </ul>

      <div v-if="historyItems.length > 0 && historyError" class="inline-error">
        <span>{{ historyError }}</span>
        <el-button text @click="loadConversationHistory(true, historyScopeOnly)">重试</el-button>
      </div>

      <div class="history-footer">
        <span class="history-total">共 {{ historyTotal }} 条</span>
        <el-button
          v-if="historyHasMore"
          class="header-button"
          :loading="historyListLoading"
          @click="loadConversationHistory(false, historyScopeOnly)"
        >
          加载更多
        </el-button>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.ai-console {
  gap: var(--app-space-4);
}

/* 三栏：左 AI 问答 + 右通知/归档；<1024px 堆叠，不挤压问答区 */
.ai-three-pane {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: var(--app-space-4);
  align-items: start;
}

/* notices 在 DOM 前、chat 在后；显式指定列，保证「左问答、右通知」 */
.ai-three-pane > .chat-card {
  grid-column: 1;
  grid-row: 1;
}

.ai-three-pane > .ai-notice-pane {
  grid-column: 2;
  grid-row: 1;
}

.ai-three-pane.has-collapsed-notice {
  grid-template-columns: minmax(0, 1fr) 48px;
}

.ai-notice-pane.is-collapsed {
  overflow: hidden;
}

.ai-notice-pane.is-collapsed > :not(.notice-toggle) {
  display: none;
}

.notice-toggle {
  align-self: flex-end;
  width: 32px;
  height: 32px;
  margin-bottom: var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
  color: var(--app-text-secondary);
  cursor: pointer;
}

.ai-notice-pane {
  position: sticky;
  top: var(--app-space-4);
  max-height: calc(100vh - 120px);
  overflow-y: auto;
}

.notice-actions {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

@media (max-width: 1023px) {
  .ai-three-pane {
    grid-template-columns: minmax(0, 1fr);
  }

  .ai-three-pane > .chat-card,
  .ai-three-pane > .ai-notice-pane {
    grid-column: 1;
    grid-row: auto;
  }

  .ai-three-pane.has-collapsed-notice {
    grid-template-columns: minmax(0, 1fr);
  }

  .ai-notice-pane.is-collapsed > :not(.notice-toggle) {
    display: block;
  }

  .ai-notice-pane {
    position: static;
    max-height: none;
  }
}

.card-head {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}

.section-title {
  margin: 0;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  line-height: 1.4;
  color: var(--app-text);
}

.section-hint {
  margin: var(--app-space-1) 0 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
}


.header-button {
  min-height: var(--app-touch);
}

.inline-hint {
  margin: var(--app-space-3) 0 0;
  font-size: var(--app-font-body);
  color: var(--app-text-secondary);
}

.inline-error {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-3);
  color: var(--el-color-danger);
  font-size: var(--app-font-body);
}

.notice-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: var(--app-space-3) 0 0;
  padding: 0;
}

.notice-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-width: 0;
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.notice-body {
  min-width: 0;
}

.notice-title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.notice-text {
  margin: var(--app-space-1) 0 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
  word-break: break-word;
}

.notice-time {
  margin: var(--app-space-1) 0 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.notice-action {
  flex-shrink: 0;
  min-height: var(--app-touch);
}


.message-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  max-height: 52vh;
  margin-top: var(--app-space-3);
  padding: var(--app-space-1);
  overflow-y: auto;
}

.message {
  box-sizing: border-box;
  max-width: 88%;
  padding: var(--app-space-3) var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
}

.message--user {
  align-self: flex-end;
  background: var(--app-primary-soft);
  border-color: var(--el-color-primary-light-7);
}

.message--assistant {
  align-self: flex-start;
  background: var(--app-surface-sunken);
}

.message-role {
  margin: 0 0 var(--app-space-1);
  font-size: var(--app-font-aux);
  font-weight: 600;
  color: var(--app-text-muted);
}

.message-content {
  margin: 0;
  font-size: var(--app-font-body);
  line-height: 1.7;
  color: var(--app-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.message-time {
  margin: var(--app-space-1) 0 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.citation-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.citation-item {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}

.citation-tag {
  flex-shrink: 0;
}


.citation-link {
  display: inline-flex;
  align-items: center;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-primary);
  font-size: var(--app-font-aux-lg);
  text-align: left;
  cursor: pointer;
}

.citation-link:hover {
  background: var(--app-primary-soft);
  border-color: var(--app-border-strong);
}

.quota-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin-top: var(--app-space-3);
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-secondary);
}

.quota-error {
  color: var(--el-color-danger);
}

.quota-alert {
  margin-top: var(--app-space-2);
}

.context-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-top: var(--app-space-3);
}

.context-chip {
  display: inline-flex;
  align-items: center;
  gap: var(--app-space-1);
  max-width: 100%;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2) 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-sunken);
  font-size: var(--app-font-aux-lg);
  color: var(--app-text);
}

.context-chip--scope {
  border-color: var(--el-color-primary-light-7);
  background: var(--app-primary-soft);
}

.context-chip__label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.context-chip__remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  border: none;
  border-radius: 999px;
  background: transparent;
  color: var(--app-text-secondary);
  font-size: var(--app-font-body);
  cursor: pointer;
}

.context-chip__remove:hover {
  color: var(--app-text);
  background: var(--app-surface);
}

.composer-area {
  position: relative;
  margin-top: var(--app-space-4);
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--app-border);
}

.composer-access {
  display: flex;
  margin-bottom: var(--app-space-2);
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-2);
}

.composer-at {
  flex-shrink: 0;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-size: var(--app-font-body);
  cursor: pointer;
}

.composer-at:hover {
  border-color: var(--app-border-strong);
  color: var(--app-text);
}

.composer-input {
  flex: 1;
  min-width: 0;
}

.composer-voice {
  flex-shrink: 0;
}

.send-button {
  flex-shrink: 0;
  min-width: 88px;
  min-height: var(--app-touch);
}

.history-toolbar {
  display: flex;
  gap: var(--app-space-2);
  margin-bottom: var(--app-space-3);
}

.history-tab {
  min-height: var(--app-touch);
  min-width: 88px;
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-text-secondary);
  font-size: var(--app-font-body);
  cursor: pointer;
}

.history-tab.is-active {
  border-color: var(--app-border-strong);
  background: var(--app-primary-soft);
  color: var(--app-primary);
  font-weight: 600;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.history-list__item {
  min-width: 0;
}

.history-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
  margin-top: var(--app-space-3);
}

.history-total {
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-muted);
}

@media (max-width: 768px) {
  .notice-item {
    flex-direction: column;
    align-items: stretch;
  }

  .notice-action {
    width: 100%;
  }

  .message {
    max-width: 100%;
  }

  .message-list {
    max-height: 46vh;
  }

  .composer {
    flex-direction: column;
    align-items: stretch;
  }

  .composer-at {
    align-self: flex-start;
  }

  .send-button {
    width: 100%;
  }
}
</style>