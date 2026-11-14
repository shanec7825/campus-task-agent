<script lang="ts">
/**
 * 浏览集合类型（契约 `C-BROWSE-TABS@3`）：同一时刻只渲染其中一种。
 */
export type BrowseType = 'activity' | 'task'
</script>

<script setup lang="ts">
/**
 * 活动 / 任务双段胶囊（契约 `C-BROWSE-TABS@3`）。
 *
 * 受控组件：选中态由父级路由 `?type=` 决定，本组件只发事件；
 * `role="tablist"` + `role="tab"` + `aria-selected`，左右方向键切换并移动焦点。
 */
import { nextTick, ref } from 'vue'

const props = defineProps<{ modelValue: BrowseType }>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: BrowseType): void
  (e: 'change', value: BrowseType): void
}>()

const tabs: Array<{ value: BrowseType; label: string }> = [
  { value: 'activity', label: '活动' },
  { value: 'task', label: '任务' }
]

const tablistRef = ref<HTMLElement | null>(null)

function select(value: BrowseType): void {
  if (value === props.modelValue) return
  emit('update:modelValue', value)
  emit('change', value)
}

function handleKeydown(event: KeyboardEvent, index: number): void {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') return
  event.preventDefault()
  const target = index === 0 ? 1 : 0
  select(tabs[target].value)
  void nextTick(() => {
    tablistRef.value?.querySelectorAll<HTMLButtonElement>('[role="tab"]')[target]?.focus()
  })
}
</script>

<template>
  <div ref="tablistRef" class="hall-tabs" role="tablist" aria-label="浏览活动或任务">
    <button
      v-for="(tab, index) in tabs"
      :key="tab.value"
      type="button"
      role="tab"
      class="hall-tabs__tab"
      :class="{ 'hall-tabs__tab--active': modelValue === tab.value }"
      :aria-selected="modelValue === tab.value ? 'true' : 'false'"
      aria-controls="browse-collection"
      :tabindex="modelValue === tab.value ? 0 : -1"
      @click="select(tab.value)"
      @keydown="handleKeydown($event, index)"
    >
      <svg
        v-if="tab.value === 'activity'"
        class="hall-tabs__icon"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <rect x="3" y="5" width="18" height="16" rx="3" />
        <path d="M8 3v4M16 3v4M3 10h18" />
      </svg>
      <svg
        v-else
        class="hall-tabs__icon"
        viewBox="0 0 24 24"
        width="18"
        height="18"
        fill="none"
        stroke="currentColor"
        stroke-width="1.8"
        stroke-linecap="round"
        stroke-linejoin="round"
        aria-hidden="true"
      >
        <rect x="4" y="4" width="16" height="16" rx="3" />
        <path d="M8 9h8M8 13h8M8 17h5" />
      </svg>
      <span>{{ tab.label }}</span>
    </button>
  </div>
</template>

<style scoped>
.hall-tabs {
  display: inline-flex;
  align-self: flex-start;
  gap: 4px;
  padding: 4px;
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface-sunken);
}

.hall-tabs__tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  min-width: 88px;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-4);
  border: 0;
  border-radius: 999px;
  background: transparent;
  color: var(--app-text-secondary);
  font-size: var(--app-font-body, 15px);
  font-weight: 600;
  cursor: pointer;
}

.hall-tabs__tab--active {
  background: var(--app-surface);
  color: var(--app-text);
  box-shadow: var(--app-shadow-sm);
}

.hall-tabs__tab:focus-visible {
  outline: 2px solid var(--el-color-primary);
  outline-offset: 2px;
}

@media (max-width: 768px) {
  .hall-tabs {
    display: flex;
    width: 100%;
  }

  .hall-tabs__tab {
    flex: 1 1 0;
  }
}
</style>