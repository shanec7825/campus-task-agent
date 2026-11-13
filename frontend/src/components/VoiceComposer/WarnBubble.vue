<script setup lang="ts">
/**
 * 问号气泡（契约 C-VOICEUI@1 / T8）
 *
 * 用于两类提示：
 * - kind='ambiguity'：审核助手追问（question + 可选 suggestion）→ emit('adopt', suggestion)
 * - kind='correction'：检测到更正（question 已由 FieldPanel 拼成"检测到更正：旧→新，待确认"）
 *
 * 角标统一使用警示红 --c-warn；点击展开，不自动弹出、不影响父级块点击。
 */
import { ref } from 'vue'

const props = withDefaults(
  defineProps<{
    question: string
    suggestion?: string | null
    kind?: 'ambiguity' | 'correction'
  }>(),
  { suggestion: null, kind: 'ambiguity' }
)

const emit = defineEmits<{
  (e: 'adopt', suggestion: string): void
}>()

const visible = ref(false)

function onAdopt(): void {
  if (!props.suggestion) return
  visible.value = false
  emit('adopt', props.suggestion)
}
</script>

<template>
  <el-popover v-model:visible="visible" trigger="click" placement="top" :width="260">
    <template #reference>
      <span
        class="warn-bubble"
        :class="`is-${kind}`"
        role="button"
        tabindex="0"
        :aria-label="question"
        @click.stop
        @keydown.enter.stop.prevent="visible = !visible"
      >?</span>
    </template>

    <div class="warn-bubble__panel">
      <p class="warn-bubble__kind">
        {{ kind === 'correction' ? '检测到更正' : '待确认' }}
      </p>
      <p class="warn-bubble__question">{{ question }}</p>
      <template v-if="suggestion">
        <p class="warn-bubble__suggestion">采纳建议：{{ suggestion }}</p>
        <div class="warn-bubble__actions">
          <el-button size="small" type="primary" @click="onAdopt">采纳</el-button>
        </div>
      </template>
    </div>
  </el-popover>
</template>

<style scoped>
.warn-bubble {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: 1px solid var(--c-warn);
  color: var(--c-warn);
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  cursor: pointer;
  outline: none;
  user-select: none;
  background: color-mix(in srgb, var(--c-warn) 12%, transparent);
  transition: background-color 0.15s ease, transform 0.15s ease;
}

.warn-bubble:hover,
.warn-bubble:focus-visible {
  background: color-mix(in srgb, var(--c-warn) 26%, transparent);
  transform: scale(1.08);
}

.warn-bubble:focus-visible {
  outline: 2px solid var(--c-warn);
  outline-offset: 2px;
}

/* 更正类角标：实心红底，与普通追问区分；文字色跟随主题背景以保证对比度 */
.warn-bubble.is-correction {
  background: var(--c-warn);
  color: var(--app-bg);
}

.warn-bubble__panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.warn-bubble__kind {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
  color: var(--c-warn);
}

.warn-bubble__question {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--c-unparsed);
}

.warn-bubble__suggestion {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--c-unparsed);
}

.warn-bubble__actions {
  display: flex;
  justify-content: flex-end;
}

/*
 * 移动端：44×44 触控热区占用真实布局空间（不再用溢出的伪元素扩大可点区域，
 * 避免侵入相邻字段行造成误触）；16px 视觉角标由 ::before 居中绘制。
 */
@media (max-width: 768px) {
  .warn-bubble {
    position: relative;
    width: var(--app-touch, 44px);
    height: var(--app-touch, 44px);
    border: 0;
    border-radius: 50%;
    background: transparent;
    color: transparent;
    font-size: 0;
  }

  .warn-bubble::before {
    content: '?';
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    display: flex;
    align-items: center;
    justify-content: center;
    width: 16px;
    height: 16px;
    border: 1px solid var(--c-warn);
    border-radius: 50%;
    color: var(--c-warn);
    background: color-mix(in srgb, var(--c-warn) 12%, transparent);
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
  }

  .warn-bubble:hover,
  .warn-bubble:focus-visible {
    background: transparent;
    transform: none;
  }

  .warn-bubble:hover::before,
  .warn-bubble:focus-visible::before {
    background: color-mix(in srgb, var(--c-warn) 26%, transparent);
    transform: translate(-50%, -50%) scale(1.08);
  }

  .warn-bubble.is-correction {
    background: transparent;
    color: transparent;
  }

  .warn-bubble.is-correction::before,
  .warn-bubble.is-correction:hover::before,
  .warn-bubble.is-correction:focus-visible::before {
    background: var(--c-warn);
    color: var(--app-bg);
  }
}
</style>