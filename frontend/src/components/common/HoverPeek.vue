<script setup lang="ts">
/**
 * 悬浮预览容器（契约 `C-FE-PEEK@2`）。
 *
 * - 只在精确指针且支持 hover 的设备启用；触摸不注册预览，点击进入详情；
 * - 停留默认 200ms 后显示，快速划过不弹出；
 * - 卡片、8px 视觉间隙与面板同属一个联合区：间隙由 `::before` 命中桥接覆盖，
 *   离开联合区后再等 120ms 关闭，移回卡片或面板即取消关闭；
 * - 面板内滚动/点击不关闭；Esc 立即关闭；焦点离开联合区才关闭；
 * - 面板是非模态 `dialog`（`aria-modal="false"`，无焦点陷阱），自身 `tabindex="0"`
 *   以便键盘进入并滚动；可访问名称来自 `label`，不再使用只能描述静态文案的 tooltip 语义。
 */
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'

const CLOSE_BUFFER_MS = 120

const props = withDefaults(defineProps<{ delay?: number; label?: string }>(), {
  delay: 200,
  label: '卡片预览',
})

const open = ref(false)
const canHover = ref(false)
const rootEl = ref<HTMLElement | null>(null)
let openTimer: number | null = null
let closeTimer: number | null = null
let hoverQuery: MediaQueryList | null = null

function updateCapability(): void {
  canHover.value = hoverQuery?.matches === true
  if (!canHover.value) closeNow()
}

function clearOpenTimer(): void {
  if (openTimer !== null) {
    window.clearTimeout(openTimer)
    openTimer = null
  }
}

function clearCloseTimer(): void {
  if (closeTimer !== null) {
    window.clearTimeout(closeTimer)
    closeTimer = null
  }
}

function schedule(): void {
  if (!canHover.value) return
  clearOpenTimer()
  clearCloseTimer()
  openTimer = window.setTimeout(() => {
    open.value = true
    openTimer = null
  }, Math.max(0, props.delay))
}

function closeNow(): void {
  clearOpenTimer()
  clearCloseTimer()
  open.value = false
}

function isJointHovered(): boolean {
  return rootEl.value?.matches(':hover') === true
}

function hasInnerFocus(): boolean {
  const root = rootEl.value
  const active = typeof document === 'undefined' ? null : (document.activeElement as HTMLElement | null)
  if (!root || !active || !root.contains(active)) return false
  // 只有键盘焦点才阻止关闭；指针点击面板留下的焦点不应让预览“粘住”
  try {
    return active.matches(':focus-visible')
  } catch {
    return true
  }
}

function scheduleClose(): void {
  clearOpenTimer()
  clearCloseTimer()
  closeTimer = window.setTimeout(() => {
    closeTimer = null
    // 缓冲期内移回联合区或焦点仍在内，则保持打开
    if (isJointHovered() || hasInnerFocus()) return
    open.value = false
  }, CLOSE_BUFFER_MS)
}

function handleMouseLeave(): void {
  if (!open.value) {
    // 尚未打开：取消待开的停留计时，避免划过后面板迟到
    clearOpenTimer()
    return
  }
  scheduleClose()
}

function handleMouseEnter(): void {
  clearCloseTimer()
  if (open.value) return
  schedule()
}

function handleFocusIn(): void {
  if (!canHover.value) return
  clearOpenTimer()
  clearCloseTimer()
  open.value = true
}

function handleFocusOut(event: FocusEvent): void {
  const next = event.relatedTarget as Node | null
  const root = rootEl.value
  if (next && root?.contains(next)) return
  if (isJointHovered()) return
  closeNow()
}

function handleEsc(event: KeyboardEvent): void {
  if (event.key === 'Escape') closeNow()
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
  closeNow()
  if (typeof document !== 'undefined') document.removeEventListener('keydown', handleEsc)
  hoverQuery?.removeEventListener?.('change', updateCapability)
})

defineExpose({ close: closeNow })
</script>

<template>
  <div
    ref="rootEl"
    class="hover-peek"
    :class="{ 'hover-peek--open': open }"
    @mouseenter="handleMouseEnter"
    @mouseleave="handleMouseLeave"
    @focusin="handleFocusIn"
    @focusout="handleFocusOut"
    @keydown.esc="handleEsc"
  >
    <slot />
    <div
      v-if="open"
      class="hover-peek__panel"
      role="dialog"
      aria-modal="false"
      :aria-label="props.label"
      tabindex="0"
    >
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

/* 命中桥接：面板打开时用 8px 伪元素覆盖视觉间隙，鼠标经过间隙仍算在联合区内 */
.hover-peek--open::before {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: -8px;
  height: 8px;
  z-index: 29;
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
  .hover-peek--open::before {
    display: none;
  }

  .hover-peek__panel {
    display: none;
  }
}
</style>