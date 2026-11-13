<script setup lang="ts">
/**
 * 任务字段面板（契约 C-VOICEUI@1 / T8）
 *
 * - 每行左侧色条 / 边框使用 colorForField(field.key)（extra_tags.* 统一黄色）；
 * - 字段值可手改：数字类走 el-input-number（`@change` 提交），其余 el-input 走
 *   「本地缓冲 + 400ms 防抖 + 失焦立即提交」（B1）：输入时只更新 `draftBuffer[key]`
 *   （即时可见），防抖 400ms 后 emit('update-field', key, value, oldValue)；
 *   外部 `props.fields` 变化时只同步**非聚焦字段**的缓冲，绝不覆盖用户正在输入的内容；
 *   oldValue 取自**当前 props**（不是父组件二次计算），
 *   供 store 生成「用户：将…由「old」改为「new」」追溯块时避免并发编辑的旧值错位；
 * - `warned` 或命中 corrections 的字段在标签旁渲染红色 WarnBubble；
 * - `stylePrompt` 非空时以 el-tag 展示"风格要求：..."；
 * - 底部提供"新增扩展项"入口 emit('add-extra')，扩展项行可 emit('remove-extra', key)。
 */
import type { CSSProperties } from 'vue'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import type { DraftField } from '../../stores/draft'
import type { Ambiguity, Correction } from '../../types/models'
import { colorForField } from '../../utils/colorPool'
import WarnBubble from './WarnBubble.vue'

const props = withDefaults(
  defineProps<{
    fields: DraftField[]
    corrections: Correction[]
    ambiguities: Ambiguity[]
    stylePrompt: string | null
    readonly?: boolean
  }>(),
  { readonly: false }
)

const emit = defineEmits<{
  (e: 'update-field', key: string, value: string | number | null, oldValue: string | number | null): void
  (e: 'adopt', field: string, suggestion: string): void
  (e: 'add-extra'): void
  (e: 'remove-extra', key: string): void
}>()

/** 数值型字段键（其余按文本编辑） */
const NUMERIC_FIELD_KEYS = ['quota', 'volunteer_hours']

const EXTRA_PREFIX = 'extra_tags.'

/** 文本字段防抖提交间隔（毫秒）：输入即时可见，落 store 延迟 400ms */
const TEXT_COMMIT_DEBOUNCE_MS = 400

/** 文本字段本地输入缓冲：避免异步 review 回填把用户正在输入的内容重置 */
const draftBuffer = ref<Record<string, string>>({})

/** 当前聚焦字段键：聚焦期间不被外部 props 覆盖 */
const focusedKey = ref<string | null>(null)

/** 各字段的防抖提交定时器 */
const commitTimers: Record<string, ReturnType<typeof setTimeout>> = {}

const hasFields = computed(() => props.fields.length > 0)

/** 行样式：把字段色注入 CSS 变量，颜色值仍来自 colorForField（禁止硬编码） */
function rowStyle(key: string): CSSProperties {
  return { '--field-color': colorForField(key) }
}

function isNumberField(key: string): boolean {
  return NUMERIC_FIELD_KEYS.includes(key)
}

function isExtraKey(key: string): boolean {
  return key.startsWith(EXTRA_PREFIX)
}

function asText(value: string | number | null): string {
  return value === null || value === undefined ? '' : String(value)
}

function asNumber(value: string | number | null): number | undefined {
  if (typeof value === 'number') return Number.isFinite(value) ? value : undefined
  if (value === null || value === undefined || String(value).trim() === '') return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

/** 取字段当前值（来自 props，保证是用户操作瞬间的旧值） */
function currentValue(key: string): string | number | null {
  const field = props.fields.find((item) => item.key === key)
  return field ? field.value : null
}

/** 文本字段显示值：本地缓冲优先（输入即时可见），否则回落到 props 值 */
function displayText(field: DraftField): string {
  const buffered = draftBuffer.value[field.key]
  return buffered === undefined ? asText(field.value) : buffered
}

function clearCommitTimer(key: string): void {
  const timer = commitTimers[key]
  if (timer === undefined) return
  clearTimeout(timer)
  delete commitTimers[key]
}

/**
 * 提交本地缓冲值（防抖终点 / 失焦立即调用）。
 * 与 props 当前值一致时不发事件，避免产生「无变化」追溯块。
 */
function commitText(key: string): void {
  clearCommitTimer(key)
  const buffered = draftBuffer.value[key]
  if (buffered === undefined) return
  const oldValue = currentValue(key)
  if (buffered === asText(oldValue)) return
  emit('update-field', key, buffered, oldValue)
}

/** 输入：只更新本地缓冲 + 400ms 防抖提交（不即时 emit，避免每次按键都写 store） */
function onTextInput(key: string, value: string): void {
  draftBuffer.value = { ...draftBuffer.value, [key]: value ?? '' }
  clearCommitTimer(key)
  commitTimers[key] = setTimeout(() => commitText(key), TEXT_COMMIT_DEBOUNCE_MS)
}

function onTextFocus(key: string): void {
  focusedKey.value = key
}

/** 失焦：立即提交并取消防抖；随后允许外部 props 重新同步缓冲 */
function onTextBlur(key: string): void {
  commitText(key)
  focusedKey.value = null
}

/**
 * 外部字段变化同步：非聚焦字段直接跟随 props；
 * 聚焦字段保留用户输入（若缓冲已有值），不被异步 review / 解析回填覆盖。
 * 同时清理已删除字段的缓冲。
 */
watch(
  () => props.fields,
  (list) => {
    const next: Record<string, string> = {}
    for (const field of list) {
      if (field.key === focusedKey.value && draftBuffer.value[field.key] !== undefined) {
        next[field.key] = draftBuffer.value[field.key]
      } else {
        next[field.key] = asText(field.value)
      }
    }
    draftBuffer.value = next
  },
  { deep: true, immediate: true }
)

onBeforeUnmount(() => {
  for (const key of Object.keys(commitTimers)) clearCommitTimer(key)
})

function onNumberChange(key: string, value: number | undefined): void {
  const next = typeof value === 'number' && Number.isFinite(value) ? value : null
  emit('update-field', key, next, currentValue(key))
}

/** corrections 命中：target 等于字段键，或字段键为 extra_tags.<target> */
function correctionFor(key: string): Correction | null {
  const hit = props.corrections.find(
    (item) => item.target === key || key === `${EXTRA_PREFIX}${item.target}`
  )
  return hit ?? null
}

/** ambiguities 命中：field 等于字段键 */
function ambiguityFor(key: string): Ambiguity | null {
  const hit = props.ambiguities.find((item) => item.field === key)
  return hit ?? null
}

function ambiguityQuestion(key: string): string {
  return ambiguityFor(key)?.question ?? ''
}

function ambiguitySuggestion(key: string): string | null {
  return ambiguityFor(key)?.suggestion ?? null
}

function correctionQuestionFor(key: string): string {
  const correction = correctionFor(key)
  if (!correction) return ''
  return buildCorrectionQuestion(correction)
}

function correctionNewValue(key: string): string | null {
  return correctionFor(key)?.new_value ?? null
}

/** "检测到更正：{old}→{new}，待确认" */
function buildCorrectionQuestion(correction: Correction): string {
  const oldValue = correction.old_value ?? '原值'
  return `检测到更正：${oldValue}→${correction.new_value}，待确认`
}

function onAdoptAmbiguity(key: string, suggestion: string): void {
  emit('adopt', key, suggestion)
}

function onAdoptCorrection(key: string, suggestion: string): void {
  emit('adopt', key, suggestion)
}
</script>

<template>
  <div class="field-panel">
    <div v-if="stylePrompt" class="field-panel__style">
      <el-tag type="warning" effect="plain" size="small">风格要求：{{ stylePrompt }}</el-tag>
    </div>

    <el-empty v-if="!hasFields" description="暂未解析出任务字段" :image-size="56" />

    <div
      v-for="field in fields"
      :key="field.key"
      class="field-row"
      :class="{ 'is-warned': field.warned || correctionFor(field.key) !== null }"
      :style="rowStyle(field.key)"
    >
      <div class="field-row__label">
        <span class="field-row__name" :title="field.key">{{ field.label }}</span>

        <WarnBubble
          v-if="ambiguityFor(field.key)"
          kind="ambiguity"
          :question="ambiguityQuestion(field.key)"
          :suggestion="ambiguitySuggestion(field.key)"
          @adopt="onAdoptAmbiguity(field.key, $event)"
        />
        <WarnBubble
          v-if="correctionFor(field.key)"
          kind="correction"
          :question="correctionQuestionFor(field.key)"
          :suggestion="correctionNewValue(field.key)"
          @adopt="onAdoptCorrection(field.key, $event)"
        />
      </div>

      <div class="field-row__value">
        <el-input-number
          v-if="isNumberField(field.key)"
          :model-value="asNumber(field.value)"
          :min="0"
          :disabled="readonly"
          size="small"
          controls-position="right"
          @change="onNumberChange(field.key, $event)"
        />
        <el-input
          v-else
          :model-value="displayText(field)"
          :disabled="readonly"
          size="small"
          :placeholder="`请输入${field.label}`"
          @input="onTextInput(field.key, $event)"
          @focus="onTextFocus(field.key)"
          @blur="onTextBlur(field.key)"
        />
        <el-button
          v-if="isExtraKey(field.key) && !readonly"
          link
          type="danger"
          size="small"
          @click="emit('remove-extra', field.key)"
        >
          删除
        </el-button>
      </div>
    </div>

    <div v-if="!readonly" class="field-panel__footer">
      <el-button size="small" plain @click="emit('add-extra')">+ 新增扩展项</el-button>
    </div>
  </div>
</template>

<style scoped>
.field-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.field-panel__style {
  display: flex;
}

.field-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border: 1px solid color-mix(in srgb, var(--field-color) 40%, var(--app-border));
  border-left: 3px solid var(--field-color);
  border-radius: var(--app-radius-sm);
  background: color-mix(in srgb, var(--field-color) 8%, var(--app-surface));
}

.field-row__label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex: none;
  min-width: 104px;
  color: var(--field-color);
  font-weight: 600;
  font-size: 14px;
}

.field-row__name {
  max-width: 92px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.field-row__value {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 1;
  min-width: 0;
}

.field-panel__footer {
  display: flex;
  padding-top: 2px;
}

/* 移动端：标签换行显示完整字段名，值区占满整行，触控区域更大 */
@media (max-width: 768px) {
  .field-row {
    flex-direction: column;
    align-items: stretch;
    gap: 6px;
    padding: 8px 10px;
  }

  .field-row__label {
    min-width: 0;
  }

  .field-row__name {
    max-width: none;
    white-space: normal;
  }

  .field-row__value {
    width: 100%;
    flex-wrap: wrap;
  }

  .field-row__value .el-input,
  .field-row__value .el-input-number {
    width: 100%;
  }
}
</style>