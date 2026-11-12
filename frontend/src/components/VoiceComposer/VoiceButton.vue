<script setup lang="ts">
/**
 * 语音按钮（契约 C-VOICEUI@2 / T5）
 *
 * 对外契约（与 P1 完全一致，不得新增必需 prop）：
 * props：`recording` / `supported` / `disabled`
 * emits：`toggle` / `error`
 *
 * 本轮仅做**内部适配**：
 * - 读取 `composer.liveText`，录音中实时展示当前 interim 文本（用户反馈第 4 条的直接可见证据）；
 * - 其余交互（start/stop 切换、错误上报、不支持提示）沿用 P1。
 */
import { computed, watch } from 'vue'

import { UNSUPPORTED_MESSAGE, useVoiceComposer } from '../../composables/useVoiceComposer'

const props = withDefaults(
  defineProps<{
    recording: boolean
    supported: boolean
    disabled?: boolean
  }>(),
  { disabled: false }
)

const emit = defineEmits<{
  (e: 'toggle', recording: boolean): void
  (e: 'error', message: string): void
}>()

const composer = useVoiceComposer()

/** 外部 props 与内部 composable 任一为真都视为录音中（避免双状态源不一致） */
const isRecording = computed(() => props.recording || composer.recording.value)

/** 真正可录音：外部声明支持 + 当前浏览器确实支持 */
const canRecord = computed(() => props.supported && composer.supported && !props.disabled)

const hint = computed(() => {
  if (!props.supported || !composer.supported) return UNSUPPORTED_MESSAGE
  if (props.disabled) return '当前状态不可录音'
  return ''
})

/**
 * 录音中的实时文本提示（仅内部展示，不新增 prop）：
 * interim 帧由 composable 以 ≤200ms 节流推送到 `liveText`，因此这里能逐字跟上说话内容。
 */
const liveHint = computed(() => {
  if (!isRecording.value) return ''
  const text = composer.liveText.value.trim()
  return text ? `识别中：${text}` : '正在聆听，请开始说话…'
})

function onClick(): void {
  if (!canRecord.value) return

  try {
    if (isRecording.value) {
      composer.stop()
      emit('toggle', false)
    } else {
      composer.start()
      emit('toggle', composer.recording.value)
    }
  } catch (cause) {
    emit('error', cause instanceof Error ? cause.message : UNSUPPORTED_MESSAGE)
  }
}

// composable 内部错误（识别错误 / 切片请求失败）统一上报给页面
watch(
  () => composer.error.value,
  (message) => {
    if (message) emit('error', message)
  }
)
</script>

<template>
  <div class="voice-button">
    <el-button
      :type="isRecording ? 'danger' : 'primary'"
      :plain="!isRecording"
      :disabled="!canRecord"
      size="large"
      round
      @click="onClick"
    >
      <span class="voice-button__dot" :class="{ 'is-recording': isRecording }" aria-hidden="true" />
      {{ isRecording ? '停止录音' : '开始语音' }}
    </el-button>
    <p v-if="liveHint" class="voice-button__live" role="status" aria-live="polite">
      {{ liveHint }}
    </p>
    <p v-if="hint" class="voice-button__hint" role="note">{{ hint }}</p>
  </div>
</template>

<style scoped>
.voice-button {
  display: inline-flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.voice-button__dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  margin-right: 6px;
  border-radius: 50%;
  background: var(--c-warn);
  vertical-align: middle;
}

.voice-button__dot.is-recording {
  animation: voice-pulse 1s ease-in-out infinite;
}

@keyframes voice-pulse {
  0%,
  100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.45);
    opacity: 0.55;
  }
}

/* 实时识别文本：颜色取自 Element Plus 语义变量，不硬编码色值 */
.voice-button__live {
  max-width: 320px;
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
  word-break: break-all;
}

.voice-button__hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.4;
  color: var(--c-warn);
}
</style>