<script setup lang="ts">
/**
 * 主题切换按钮（契约 C-THEME@1 / C-NAV@1）。
 *
 * 状态完全来自 `useTheme()`；切换只改主题，不触发路由重挂载。
 */
import { computed } from 'vue'

import { useTheme } from '../../composables/useTheme'

const { isDark, toggleTheme } = useTheme()

const label = computed<string>(() => (isDark.value ? '切换到浅色主题' : '切换到深色主题'))
</script>

<template>
  <button
    type="button"
    class="theme-toggle"
    data-testid="theme-toggle"
    :aria-label="label"
    :aria-pressed="isDark ? 'true' : 'false'"
    :title="label"
    @click="toggleTheme"
  >
    <span class="theme-toggle-icon" aria-hidden="true">{{ isDark ? '☀' : '☾' }}</span>
  </button>
</template>

<style scoped>
.theme-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  padding: 0;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
  color: var(--app-text);
  font-size: 16px;
  line-height: 1;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    color 0.2s ease,
    border-color 0.2s ease;
}

.theme-toggle:hover {
  background: var(--app-primary-soft);
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.theme-toggle-icon {
  display: block;
}
</style>