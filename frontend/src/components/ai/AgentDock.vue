<script setup lang="ts">
/**
 * 情境助手长条与微展开（契约 `C-FE-AGENT-DOCK@1`）。
 *
 * - 活动详情、任务详情底部使用；与 `/ai` 完整页共用 `aiChat` store；
 * - 长条含上下文标签、输入、发送；展开后显示最近消息与来源；
 * - 展开/收起不重置输入，不创建新会话；完整页入口继续当前目标的同一会话；
 * - 问答请求仍只读权限内事务，不执行写操作。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { ApiError } from '../../api/client'
import { useVoiceComposer } from '../../composables/useVoiceComposer'
import { useAiChatStore } from '../../stores/aiChat'
import AgentVoiceButton from './AgentVoiceButton.vue'

const props = defineProps<{
  contextLabel?: string
  /** 当前页面绑定的问答目标（`C-FE-AI-SCOPE@1`）；缺省为通用作用域 */
  scopeType?: 'activity' | 'task'
  scopeId?: number
}>()

const router = useRouter()
const aiChat = useAiChatStore()
const voice = useVoiceComposer()
const expanded = ref(false)

const recent = computed(() => aiChat.recentMessages)
const contextText = computed(() => props.contextLabel || '当前事务范围')
// 录音中禁用文字输入：interim/定稿写回以录制基文为准，不能让手打被整体覆盖
const voiceRecording = computed(() => voice.recording.value)

// 目标变化（type/id）时停止本轮录音；标题标签异步加载不触发停止
watch(
  [() => props.scopeType, () => props.scopeId],
  () => {
    if (voice.recording.value) {
      // 切目标必须显式停止：晚到尾片仍写回原作用域的 sink，文本保留在原目标
      voice.stop()
      ElMessage.info('已切换目标，录音已停止，文本保留在原目标')
    }
  }
)

watch(
  [() => props.scopeType, () => props.scopeId, () => props.contextLabel],
  () => {
    aiChat.setScope(
      props.scopeType ?? 'general',
      props.scopeId ?? null,
      props.contextLabel ?? ''
    )
    // 失败不阻塞当前页面；该作用域已有缓存时直接展示，不自动重发请求。
    void aiChat.restore()
  },
  { immediate: true }
)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function shortTime(value: string | null): string {
  if (!value) return '—'
  return value.slice(0, 16).replace('T', ' ')
}

async function send(): Promise<void> {
  // 录音中不发送半句 interim；先停止录音再发送
  if (voiceRecording.value) return
  if (aiChat.quotaExhausted) {
    ElMessage.warning('今日 AI 问答额度已用完；任务、通知与审批等协作功能仍可正常使用')
    return
  }
  try {
    const sent = await aiChat.send()
    if (sent) expanded.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function openCitation(taskId: number): void {
  void router.push({ name: 'detail', params: { id: taskId } })
}

function openFull(): void {
  void router.push({ name: 'ai' })
}

onMounted(() => {

  if (!aiChat.usage) void aiChat.loadUsage()
})

onUnmounted(() => {
  // 卸载时正常停止（不 abort）：尾片仍按本轮 sink 结算
  if (voice.recording.value) voice.stop()
})
</script>

<template>
  <section class="agent-dock app-section-card" aria-label="事务助手">
    <div class="dock-bar">
      <div class="dock-context">
        <p class="dock-label">情境助手</p>
        <p class="dock-context-text">{{ contextText }}</p>
      </div>

      <div class="dock-composer">
        <el-input
          v-model="aiChat.input"
          class="dock-input"
          type="textarea"
          :rows="1"
          :autosize="{ minRows: 1, maxRows: 3 }"
          maxlength="2000"
          resize="none"
          :disabled="aiChat.sending || aiChat.quotaExhausted || voiceRecording"
          placeholder="问 AI：这项事务接下来做什么？"
          aria-label="向情境助手提问"
          @keydown.enter.exact.prevent="send"
        />
        <AgentVoiceButton
          class="dock-voice"
          :disabled="!voiceRecording && (aiChat.sending || aiChat.quotaExhausted)"
        />
        <el-button
          class="dock-send"
          type="primary"
          :loading="aiChat.sending"
          :disabled="aiChat.sending || aiChat.historyLoading || aiChat.quotaExhausted || voiceRecording || aiChat.input.trim().length === 0"
          @click="send"
        >
          发送
        </el-button>
        <button
          type="button"
          class="dock-toggle"
          :aria-controls="expanded ? 'agent-dock-panel' : undefined"
          :aria-expanded="expanded ? 'true' : 'false'"
          @click="expanded = !expanded"
        >
          {{ expanded ? '收起对话' : '展开对话' }}
        </button>
      </div>
    </div>

    <div v-if="expanded" id="agent-dock-panel" class="dock-panel">
      <div class="dock-panel-head">
        <p class="dock-panel-title">最近对话</p>
        <el-button text type="primary" @click="openFull">打开完整页</el-button>
      </div>

      <p v-if="aiChat.historyLoading" class="dock-hint">正在读取最近对话…</p>
      <p v-else-if="aiChat.historyError" class="dock-error">{{ aiChat.historyError }}</p>
      <p v-else-if="recent.length === 0" class="dock-hint">
        还没有对话。输入问题后，这里会显示最近消息与来源。
      </p>
      <ul v-else class="dock-messages">
        <li v-for="item in recent" :key="item.id" class="dock-message">
          <p class="dock-message-role">{{ item.role === 'user' ? '你' : '助手' }}</p>
          <p class="dock-message-content">{{ item.content }}</p>
          <ul v-if="item.citations.length > 0" class="dock-citations" aria-label="回答来源">
            <li v-for="citation in item.citations" :key="`${citation.id}-${citation.title}`">
              <button
                type="button"
                class="dock-citation"
                :aria-label="`打开来源任务：${citation.title}`"
                @click="openCitation(citation.id)"
              >
                {{ citation.title }}
              </button>
            </li>
          </ul>
          <p class="dock-time">{{ shortTime(item.created_at) }}</p>
        </li>
      </ul>

      <p class="dock-hint">
        问答只读取你有权限查看的事务，不替你发布、改期或验收；完整页、长条与微展开共用同一会话与草稿。
      </p>
    </div>
  </section>
</template>

<style scoped>
.agent-dock {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.dock-bar {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.dock-context {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--app-space-2);
  min-width: 0;
}

.dock-label {
  margin: 0;
  font-size: var(--app-font-aux);
  font-weight: 600;
  color: var(--app-primary);
  white-space: nowrap;
}

.dock-context-text {
  min-width: 0;
  margin: 0;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dock-composer {
  display: flex;
  align-items: flex-end;
  gap: var(--app-space-2);
}

.dock-input {
  flex: 1;
  min-width: 0;
}

.dock-voice {
  flex-shrink: 0;
}

.dock-send {
  flex-shrink: 0;
  min-height: var(--app-touch);
}

.dock-toggle {
  flex-shrink: 0;
  min-height: var(--app-touch);
  min-width: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text-secondary);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.dock-toggle:hover,
.dock-toggle:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.dock-panel {
  padding-top: var(--app-space-3);
  border-top: 1px dashed var(--app-border);
}

.dock-panel-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}

.dock-panel-title {
  margin: 0;
  color: var(--app-text);
  font-size: var(--app-font-body);
  font-weight: 600;
}

.dock-messages {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.dock-message {
  padding: var(--app-space-2) var(--app-space-3);
  background: var(--app-surface-sunken);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
}

.dock-message-role {
  margin: 0 0 var(--app-space-1);
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
  font-weight: 600;
}

.dock-message-content {
  margin: 0;
  color: var(--app-text);
  font-size: var(--app-font-aux-lg);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.dock-citations {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
  margin: var(--app-space-2) 0 0;
  padding: 0;
  list-style: none;
}

.dock-citation {
  display: inline-flex;
  align-items: center;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
  color: var(--app-primary);
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.dock-citation:hover,
.dock-citation:focus-visible {
  background: var(--app-primary-soft);
  border-color: var(--app-border-strong);
}

.dock-time {
  margin: var(--app-space-1) 0 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

.dock-hint,
.dock-error {
  margin: var(--app-space-2) 0 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
}

.dock-error {
  color: var(--el-color-danger);
}

@media (max-width: 768px) {
  .dock-composer {
    flex-direction: column;
    align-items: stretch;
  }

  .dock-send,
  .dock-toggle {
    width: 100%;
  }
}
</style>