<script setup lang="ts">
/**
 * AI 统一入口（契约 `C-FE-AI@1` / `C-AI-CHAT@1`）。
 *
 * - 通知卡复用既有通知 store；通知加载失败不影响问答；
 * - 会话与消息来自后端持久化，刷新后恢复最近一次会话；
 * - 回答只展示服务端返回的可见任务引用，不把客户端推断当作来源；
 * - mock 模式明确标注，不与真实模型结果混淆。
 */
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { chat, getConversation, listConversations } from '../api/agent'
import { ApiError } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useNotificationsStore } from '../stores/notifications'
import type { AiChatMessage, NotificationItem } from '../types/models'

const SUGGESTIONS = ['我有哪些临近截止的事务？', '我有权限查看哪些活动？', '我接下来该先处理什么？']

const router = useRouter()
const notificationsStore = useNotificationsStore()

const messages = ref<AiChatMessage[]>([])
const conversationId = ref<number | null>(null)
const input = ref('')
const historyLoading = ref(true)
const historyError = ref('')
const noticesLoading = ref(true)
const noticesError = ref('')
const sending = ref(false)
const mockMode = ref(false)
const messageListRef = ref<HTMLElement | null>(null)

const unreadItems = computed<NotificationItem[]>(() => notificationsStore.unreadItems.slice(0, 3))
const unreadCount = computed<number>(() => notificationsStore.unread)
const hasMessages = computed<boolean>(() => messages.value.length > 0)

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

async function loadHistory(): Promise<void> {
  if (sending.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const list = await listConversations(1)
    const latest = list.items[0]
    if (!latest) {
      messages.value = []
      conversationId.value = null
      return
    }
    const detail = await getConversation(latest.id)
    conversationId.value = detail.conversation.id
    messages.value = detail.messages
    const lastAssistant = [...detail.messages].reverse().find((item) => item.role === 'assistant')
    mockMode.value = lastAssistant?.mock === true
  } catch (err) {
    const message = errorMessage(err)
    if (hasMessages.value) ElMessage.error(`刷新对话失败：${message}`)
    else historyError.value = message
  } finally {
    historyLoading.value = false
  }
  if (!historyError.value) await scrollToBottom()
}

async function loadNotices(): Promise<void> {
  noticesLoading.value = true
  noticesError.value = ''
  try {
    await notificationsStore.refresh(20)
  } catch (err) {
    noticesError.value = errorMessage(err)
  } finally {
    noticesLoading.value = false
  }
}

async function sendMessage(text?: string): Promise<void> {
  const content = (text ?? input.value).trim()
  if (!content || sending.value || historyLoading.value) return

  input.value = ''
  sending.value = true
  try {
    const result = await chat(content, conversationId.value ?? undefined)
    conversationId.value = result.conversation_id
    messages.value = [...messages.value, result.user_message, result.assistant_message]
    mockMode.value = result.mock
    historyError.value = ''
    await scrollToBottom()
  } catch (err) {
    if (!input.value) input.value = content
    ElMessage.error(errorMessage(err))
  } finally {
    sending.value = false
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


function openCitation(taskId: number): void {
  void router.push({ name: 'detail', params: { id: taskId } })
}

function openWorkbench(): void {
  void router.push({ name: 'workbench' })
}

function openMessages(): void {
  void router.push({ name: 'messages' })
}

onMounted(async () => {
  await Promise.allSettled([loadHistory(), loadNotices()])
})
</script>

<template>
  <section class="app-page ai-console" :aria-busy="historyLoading || sending ? 'true' : 'false'">
    <header class="app-page-header">
      <div>
        <h1 class="app-page-title">AI 助手</h1>
        <p class="app-page-subtitle">
          只读问答：只使用你有权限查看的最近 20 项事务摘要，不执行发布、验收等写操作。
        </p>
      </div>
      <div class="app-actions">
        <el-button class="header-button" @click="openWorkbench">打开工作台</el-button>
        <el-button
          class="header-button"
          :loading="historyLoading"
          :disabled="sending"
          @click="loadHistory"
        >
          刷新对话
        </el-button>
      </div>
    </header>

    <section class="app-section-card notices-card" aria-labelledby="ai-notices-heading">
      <div class="card-head">
        <div>
          <h2 id="ai-notices-heading" class="section-title">待处理通知</h2>
          <p class="section-hint">
            未读 {{ unreadCount }} 条
            <template v-if="unreadCount > 0"> · 以下为最近 {{ unreadItems.length }} 条</template>
          </p>
        </div>
        <div class="app-actions">

          <el-button class="header-button" text @click="openMessages">查看全部消息</el-button>
        </div>
      </div>

      <p v-if="noticesLoading" class="inline-hint">正在读取通知…</p>
      <div v-else-if="noticesError" class="inline-error">
        <span>{{ noticesError }}</span>
        <el-button class="header-button" text @click="loadNotices">重试</el-button>
      </div>
      <p v-else-if="unreadItems.length === 0" class="inline-hint">当前没有未读通知。</p>
      <ul v-else class="notice-list">
        <li v-for="item in unreadItems" :key="item.id" class="notice-item">
          <div class="notice-body">
            <p class="notice-title">{{ item.title }}</p>
            <p class="notice-text">{{ shortText(item.content) }}</p>
            <p class="notice-time">{{ shortTime(item.created_at) }}</p>
          </div>
          <el-button class="notice-action" @click="openNotice(item)">
            {{ item.task_id !== null ? '查看任务' : '标为已读' }}
          </el-button>
        </li>
      </ul>
    </section>

    <section class="app-section-card chat-card" aria-labelledby="ai-chat-heading">
      <div class="card-head">
        <div>
          <h2 id="ai-chat-heading" class="section-title">事务问答</h2>
          <p class="section-hint">回答下方标注来源；点来源可打开对应任务详情。</p>
        </div>
        <el-tag v-if="mockMode" type="info" effect="plain">演示模式</el-tag>
      </div>

      <el-alert
        v-if="mockMode"
        class="mock-alert"
        type="info"
        :closable="false"
        title="演示模式：回答由本地规则生成，未调用真实模型。"
        description="真实模型回答需要配置模型服务；演示模式下仍可验证会话、来源与权限边界。"
      />

      <LoadingState v-if="historyLoading" :rows="3" />
      <ErrorState
        v-else-if="historyError && !hasMessages"
        :message="historyError"
        detail="对话记录加载失败，请稍后重试；通知卡不受影响。"
        retryable
        @retry="loadHistory"
      />
      <EmptyState
        v-else-if="!hasMessages"
        title="从一个具体问题开始"
        description="可以问自己接下来该做什么、哪些事务临近截止，或某个活动下有哪些任务。"
      />

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
            <li v-for="citation in item.citations" :key="`${citation.id}-${citation.title}`">
              <button
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

      <div v-if="!hasMessages && !historyLoading && !historyError" class="suggestions">
        <el-button
          v-for="question in SUGGESTIONS"
          :key="question"
          class="suggestion-button"
          :disabled="sending"
          @click="sendMessage(question)"
        >
          {{ question }}
        </el-button>
      </div>

      <div class="composer">
        <el-input
          v-model="input"
          class="composer-input"
          type="textarea"
          :rows="2"
          maxlength="2000"
          show-word-limit
          resize="none"
          :disabled="sending"
          placeholder="输入问题，例如：我有哪些临近截止的事务？"
          aria-label="向 AI 助手提问"
          @keydown.enter.exact.prevent="sendMessage()"
        />
        <el-button
          class="send-button"
          type="primary"
          :loading="sending"
          :disabled="sending || historyLoading || input.trim().length === 0"
          @click="sendMessage()"
        >
          发送
        </el-button>
      </div>
      <p class="composer-hint">问答只读取你有权限查看的事务；不会替你发布、改期或验收。</p>
    </section>
  </section>
</template>

<style scoped>
.ai-console {
  gap: var(--app-space-4);
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

.mock-alert {
  margin-top: var(--app-space-3);
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

.suggestions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-2);
  margin-top: var(--app-space-3);
}

.suggestion-button {
  min-height: var(--app-touch);
  white-space: normal;
}

.composer {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-2);
  margin-top: var(--app-space-4);
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--app-border);
}

.composer-input {
  flex: 1;
  min-width: 0;
}

.send-button {
  flex-shrink: 0;
  min-width: 88px;
  min-height: var(--app-touch);
}

.composer-hint {
  margin: var(--app-space-2) 0 0;
  font-size: var(--app-font-aux);
  line-height: 1.6;
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

  .suggestions {
    flex-direction: column;
  }

  .suggestion-button {
    width: 100%;
    margin-left: 0;
  }

  .composer {
    flex-direction: column;
    align-items: stretch;
  }

  .send-button {
    width: 100%;
  }
}
</style>