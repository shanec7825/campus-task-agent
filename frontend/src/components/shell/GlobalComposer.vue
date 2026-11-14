<script setup lang="ts">
/**
 * 全局悬浮输入（契约 `C-GLOBAL-COMPOSER@1`）。
 *
 * 三态：小条（bubble）→ 点击 ^ 展开中框（compact，显示最近问答片段）→ AI 页面。
 * 任意页面可提问与语音；发送复用 `aiChat.send`，不在非 AI 页新建第二套请求。
 */
import { computed, nextTick, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { useAiChatStore } from '../../stores/aiChat'
import { useVoiceComposer } from '../../composables/useVoiceComposer'
import AgentVoiceButton from '../ai/AgentVoiceButton.vue'

const route = useRoute()
const router = useRouter()
const aiChat = useAiChatStore()
const voice = useVoiceComposer()

const expanded = ref(false)
const recording = computed(() => voice.recording.value)
const sending = computed(() => aiChat.sending)
const quotaExhausted = computed(() => aiChat.quotaExhausted)
const preview = computed(() => aiChat.messages.slice(-4))
const canSend = computed(
  () =>
    !aiChat.sending &&
    !recording.value &&
    !aiChat.quotaExhausted &&
    aiChat.input.trim().length > 0
)

/** 非 AI 页才显示悬浮入口；AI 页已有完整输入区，避免重复 */
const visible = computed(() => route.name !== 'ai')

function toggleExpanded(): void {
  expanded.value = !expanded.value
}

async function submit(): Promise<void> {
  if (!canSend.value) return
  try {
    // 录音中只允许停止，不发送半句
    if (recording.value) voice.stop()
    if (route.name !== 'ai') {
      await router.push({ name: 'ai' })
      await nextTick()
    }
    // 首次进入 AI 页时历史可能仍在加载；等待后再发送，避免被 send 的 guard 静默拦截
    if (aiChat.historyLoading) await aiChat.loadHistory()
    const sent = await aiChat.send()
    if (sent) expanded.value = false
    else ElMessage.warning('消息未发送，请稍后重试')
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    ElMessage.error(message || '发送失败，请稍后重试')
  }
}

function openPage(): void {
  expanded.value = false
  void router.push({ name: 'ai' })
}
</script>

<template>
  <div v-if="visible" class="global-composer" :class="{ 'is-expanded': expanded }">
    <div v-if="expanded" class="global-composer__preview">
      <p v-if="preview.length === 0" class="global-composer__empty">
        还没有对话，直接在下方提问即可。
      </p>
      <article
        v-for="item in preview"
        :key="`composer-preview-${item.id}`"
        class="composer-preview-item"
        :class="`composer-preview-item--${item.role}`"
      >
        <span class="composer-preview-role">{{ item.role === 'user' ? '你' : '助手' }}</span>
        <p class="composer-preview-text">{{ item.content }}</p>
      </article>
      <button type="button" class="composer-open-link" @click="openPage">打开 AI 页面</button>
    </div>

    <div class="global-composer__bar">
      <button
        type="button"
        class="composer-icon"
        aria-label="附件（请在 AI 页面使用）"
        title="附件请在 AI 页面使用"
        @click="ElMessage.info('附件与文件能力在 AI 页面使用')"
      >
        +
      </button>
      <input
        v-model="aiChat.input"
        class="composer-input"
        type="text"
        maxlength="2000"
        placeholder="问我任何校园事务"
        aria-label="向 AI 助手提问"
        :disabled="aiChat.sending || quotaExhausted"
        @keydown.enter.exact.prevent="submit"
      />
      <AgentVoiceButton class="composer-voice" :disabled="aiChat.sending || quotaExhausted" />
      <button
        type="button"
        class="composer-icon composer-expand"
        :aria-label="expanded ? '收起输入框' : '展开输入框'"
        :aria-expanded="expanded"
        @click="toggleExpanded"
      >
        {{ expanded ? '⌄' : '⌃' }}
      </button>
      <button
        type="button"
        class="composer-send"
        :disabled="!canSend"
        aria-label="发送"
        @click="submit"
      >
        发送
      </button>
    </div>
  </div>
</template>

<style scoped>
.global-composer {
  position: fixed;
  left: 50%;
  bottom: 16px;
  z-index: 30;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  width: min(768px, calc(100vw - 48px));
  transform: translateX(-50%);
  pointer-events: none;
}

.global-composer__bar,
.global-composer__preview {
  pointer-events: auto;
  border: 1px solid var(--app-border);
  border-radius: 28px;
  background: var(--app-surface-raised);
  box-shadow: 0 10px 30px rgb(0 0 0 / 12%);
}

.global-composer__bar {
  display: flex;
  align-items: center;
  gap: var(--app-space-1);
  min-height: 56px;
  padding: 0 var(--app-space-2);
}

.global-composer__preview {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  max-height: 420px;
  padding: var(--app-space-4);
  overflow-y: auto;
  border-radius: 18px;
}

.global-composer__empty {
  margin: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux-lg);
}

.composer-preview-item {
  display: flex;
  gap: var(--app-space-2);
  font-size: var(--app-font-aux-lg);
}

.composer-preview-role {
  flex: 0 0 auto;
  color: var(--app-text-muted);
}

.composer-preview-text {
  margin: 0;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.composer-preview-item--assistant .composer-preview-text {
  color: var(--app-text-secondary);
}

.composer-open-link {
  align-self: flex-start;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--el-color-primary);
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.composer-icon,
.composer-send,
.composer-voice {
  flex: 0 0 auto;
}

.composer-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--app-touch);
  height: var(--app-touch);
  border: 0;
  border-radius: 50%;
  background: transparent;
  color: var(--app-text-secondary);
  font-size: 20px;
  cursor: pointer;
}

.composer-icon:hover,
.composer-icon:focus-visible {
  background: var(--app-surface-sunken);
  color: var(--app-text);
}

.composer-input {
  flex: 1 1 auto;
  min-width: 0;
  height: 40px;
  border: 0;
  background: transparent;
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-body);
  outline: none;
}

.composer-send {
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 0;
  border-radius: 22px;
  background: var(--el-color-primary);
  color: var(--el-color-white);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.composer-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

@media (min-width: 1025px) {
  .global-composer {
    left: auto;
    right: 24px;
    width: min(768px, calc(100vw - 280px));
    transform: none;
  }
}

@media (max-width: 768px) {
  .global-composer {
    bottom: calc(var(--app-bottom-nav-height) + var(--app-safe-bottom) + 8px);
    width: calc(100vw - 16px);
  }

  .global-composer__preview {
    max-height: 45vh;
  }
}
</style>