<script setup lang="ts" generic="T extends string">
/**
 * 通用胶囊分段控件（契约 `C-SEGMENTED@1`）。
 *
 * 受控组件：选中态完全由 `modelValue` 决定，点击只发事件；
 * `role="tablist"` + `role="tab"` + `aria-selected`，左右方向键循环切换并移动焦点。
 */
import { nextTick, ref } from 'vue'

const props = defineProps<{
  modelValue: T
  options: Array<{ value: T; label: string }>
  ariaLabel: string
  disabledValues?: string[]
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: T): void
  (e: 'change', value: T): void
}>()

const tablistRef = ref<HTMLElement | null>(null)

const activeIndex = () => props.options.findIndex((option) => option.value === props.modelValue)

/** 命中 `disabledValues` 的选项不可点击、不可被方向键选中 */
function isDisabled(value: T): boolean {
  return props.disabledValues?.includes(value) ?? false
}

function select(value: T): void {
  if (isDisabled(value) || value === props.modelValue) return
  emit('update:modelValue', value)
  emit('change', value)
}

function firstEnabledIndex(): number {
  return props.options.findIndex((option) => !isDisabled(option.value))
}

/** 当前项可聚焦时只留当前项；当前项禁用或缺省时留给首个可用项 */
function isTabStop(index: number): boolean {
  const current = activeIndex()
  if (current === index) return !isDisabled(props.options[index].value)
  const currentFocusable = current !== -1 && !isDisabled(props.options[current].value)
  return !currentFocusable && index === firstEnabledIndex()
}

/** 沿方向键方向找下一个可用项；全禁用时返回 -1 */
function nextEnabledIndex(index: number, delta: number): number {
  const count = props.options.length
  for (let step = 1; step <= count; step += 1) {
    const candidate = ((index + delta * step) % count + count) % count
    if (!isDisabled(props.options[candidate].value)) return candidate
  }
  return -1
}

function handleKeydown(event: KeyboardEvent, index: number): void {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
  event.preventDefault()
  const target = nextEnabledIndex(index, event.key === 'ArrowRight' ? 1 : -1)
  if (target === -1) return
  select(props.options[target].value)
  void nextTick(() => {
    tablistRef.value?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[target]?.focus()
  })
}
</script>

<template>
  <div ref="tablistRef" class="segmented-tabs" role="tablist" :aria-label="ariaLabel">
    <button
      v-for="(option, index) in options"
      :key="option.value"
      type="button"
      role="tab"
      class="segmented-tabs__tab"
      :class="{ 'segmented-tabs__tab--active': modelValue === option.value }"
      :aria-selected="modelValue === option.value ? 'true' : 'false'"
      :aria-disabled="isDisabled(option.value) ? 'true' : 'false'"
      :disabled="isDisabled(option.value)"
      :tabindex="isTabStop(index) ? 0 : -1"
      @click="select(option.value)"
      @keydown="handleKeydown($event, index)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.segmented-tabs {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-sunken);
}

.segmented-tabs__tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg, 14px);
  font-weight: 600;
  cursor: pointer;
}

.segmented-tabs__tab--active {
  background: var(--app-surface);
  color: var(--app-text);
  box-shadow: var(--app-shadow-sm);
}

.segmented-tabs__tab:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

.segmented-tabs__tab:disabled {
  color: var(--app-text-muted);
  cursor: not-allowed;
}

@media (max-width: 768px) {
  /* 窄屏项数多时横向滚动，避免被 flex 压缩到不可读 */
  .segmented-tabs {
    display: flex;
    width: 100%;
    overflow-x: auto;
    scrollbar-width: none;
  }

  .segmented-tabs::-webkit-scrollbar {
    display: none;
  }

  .segmented-tabs__tab {
    flex: 0 0 auto;
    font-size: var(--app-font-body, 15px);
    white-space: nowrap;
  }
}
</style>