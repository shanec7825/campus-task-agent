<script setup lang="ts">
/**
 * AI 形态语音入口（契约 `C-AI-VOICEUI@1`）。
 *
 * 完整页 / 长条 / 微展开共用：每次开始录音前按当前作用域与当前输入重建 sink，
 * 定稿只追加在原有文字之后；切目标后的晚到尾片仍写回发起时的作用域。
 */
import { computed } from 'vue'

import { createAiChatVoiceSink } from '../../composables/useAiVoiceSink'
import { UNSUPPORTED_MESSAGE, useVoiceComposer } from '../../composables/useVoiceComposer'

const props = withDefaults(defineProps<{ disabled?: boolean }>(), { disabled: false })

const composer = useVoiceComposer()
// setup 阶段先注册当前作用域的 sink（建立 Pinia 绑定；开始录音前会按最新输入重建）
useVoiceComposer(createAiChatVoiceSink())

const canRecord = computed<boolean>(() => composer.supported && !props.disabled)
const isRecording = computed<boolean>(() => composer.recording.value)
const liveHint = computed<string>(() => {
  if (!isRecording.value) return ''
  const text = composer.liveText.value.trim()
  return text ? `识别中：${text}` : '正在聆听，请开始说话…'
})
const errorText = computed<string>(() => composer.error.value ?? '')
const unsupportedHint = `${UNSUPPORTED_MESSAGE}，可改用文字输入`

function onClick(): void {
  if (!canRecord.value) return
  if (isRecording.value) {
    composer.stop()
    return
  }
  // 基文取点击瞬间的输入：用户先打字再语音时，原有文字不被覆盖
  useVoiceComposer(createAiChatVoiceSink())
  composer.start()
}
</script>

<template>
  <div class="agent-voice">
    <button
      type="button"
      class="agent-voice__toggle"
      :class="{ 'agent-voice__toggle--recording': isRecording }"
      :disabled="!canRecord"
      :aria-pressed="isRecording ? 'true' : 'false'"
      @click="onClick"
    >
      <span
        class="agent-voice__dot"
        :class="{ 'agent-voice__dot--recording': isRecording }"
        aria-hidden="true"
      />
      {{ isRecording ? '停止录音' : '语音输入' }}
    </button>
    <p v-if="liveHint" class="agent-voice__live" role="status" aria-live="polite">{{ liveHint }}</p>
    <p v-if="errorText" class="agent-voice__error" role="alert">{{ errorText }}</p>
    <p v-if="!composer.supported" class="agent-voice__hint" role="note">{{ unsupportedHint }}</p>
  </div>
</template>

<style scoped>
.agent-voice {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  min-width: 0;
}

.agent-voice__toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--app-space-1);
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text-secondary);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.agent-voice__toggle:hover,
.agent-voice__toggle:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.agent-voice__toggle:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}

.agent-voice__toggle--recording {
  border-color: var(--el-color-danger);
  background: var(--app-surface);
  color: var(--el-color-danger);
}

.agent-voice__dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-danger);
}

.agent-voice__dot--recording {
  animation: agent-voice-pulse 1s ease-in-out infinite;
}

@keyframes agent-voice-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.4);
    opacity: 0.55;
  }
}

.agent-voice__live,
.agent-voice__hint,
.agent-voice__error {
  margin: 0;
  font-size: var(--app-font-aux);
  line-height: 1.5;
  word-break: break-word;
}

.agent-voice__live {
  color: var(--app-text-secondary);
}

.agent-voice__hint {
  color: var(--app-text-muted);
}

.agent-voice__error {
  color: var(--el-color-danger);
}

@media (max-width: 768px) {
  .agent-voice__toggle {
    width: 100%;
  }
}
</style>