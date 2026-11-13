<script setup lang="ts">
/**
 * 悬浮预览容器（契约 `C-FE-PEEK@1`）。
 *
 * - 只在精确指针且支持 hover 的设备启用；触摸设备不注册预览；
 * - 停留默认 200ms 后显示，快速划过不弹出；
 * - 离开容器立即关闭；预览面板是容器子元素，移入预览不会关闭；
 * - 键盘焦点可打开，Esc 关闭；间隙不触发（事件只绑定容器）。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{ delay?: number }>(), { delay: 200 })

const open = ref(false)
const canHover = ref(false)
let timer: number | null = null
let hoverQuery: MediaQueryList | null = null

function updateCapability(): void {
  canHover.value = hoverQuery?.matches === true
  if (!canHover.value) open.value = false
}

function clearTimer(): void {
  if (timer !== null) {
    window.clearTimeout(timer)
    timer = null
  }
}

function schedule(): void {
  if (!canHover.value) return
  clearTimer()
  timer = window.setTimeout(() => {
    open.value = true
    timer = null
  }, Math.max(0, props.delay))
}

function close(): void {
  clearTimer()
  open.value = false
}

function handleFocusIn(): void {
  if (canHover.value) {
    clearTimer()
    open.value = true
  }
}

function handleFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget as Node | null
  const current = event.currentTarget as HTMLElement | null
  if (next && current?.contains(next)) return
  close()
}

function handleEsc(event: KeyboardEvent): void {
  if (event.key === 'Escape') close()
}

watch(open, (value) => {
  if (typeof document === 'undefined') return
  if (value) document.addEventListener('keydown', handleEsc)
  else document.removeEventListener('keydown', handleEsc)
})

onMounted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return
  hoverQuery = window.matchMedia('(hover: hover) and (pointer: fine)')
  updateCapability()
  hoverQuery.addEventListener?.('change', updateCapability)
})

onBeforeUnmount(() => {
  clearTimer()
  if (typeof document !== 'undefined') document.removeEventListener('keydown', handleEsc)
  hoverQuery?.removeEventListener?.('change', updateCapability)
})
</script>

<template>
  <div
    class="hover-peek"
    @mouseenter="schedule"
    @mouseleave="close"
    @focusin="handleFocusIn"
    @focusout="handleFocusOut"
    @keydown.esc="close"
  >
    <slot />
    <div v-if="open" class="hover-peek__panel" role="tooltip">
      <slot name="preview" />
    </div>
  </div>
</template>

<style scoped>
.hover-peek {
  position: relative;
  min-width: 0;
  height: 100%;
}

.hover-peek__panel {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  right: 0;
  z-index: 30;
  box-sizing: border-box;
  max-height: min(360px, 60vh);
  overflow-y: auto;
  padding: var(--app-space-3);
  background: var(--app-surface-raised);
  border: 1px solid var(--app-border-strong);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-md);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  line-height: 1.65;
}

@media (hover: none), (pointer: coarse) {
  .hover-peek__panel {
    display: none;
  }
}
</style>