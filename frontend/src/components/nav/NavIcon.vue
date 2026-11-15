<script lang="ts">
/**
 * 导航图标（契约 C-NAV-GROUPS@3）。
 *
 * 本地内联 SVG，不引入图标依赖；颜色继承 `currentColor`，
 * 尺寸由调用方通过 `size` 控制。图标默认装饰性，可访问名称由外层链接/按钮提供。
 */
export type NavIconName =
  | 'ai'
  | 'hall'
  | 'my-tasks'
  | 'library'
  | 'messages'
  | 'profile'
  | 'admin'
  | 'search'
  | 'new-chat'
  | 'recent'
  | 'history'
  | 'theme'
  | 'archive'
  | 'panel-left'
  | 'panel-right'
  | 'chevron-down'
  | 'chevron-right'
  | 'task'
  | 'activity'
  | 'user'
  | 'calendar'
  | 'clock'
  | 'check'
  | 'link'
  | 'flag'
</script>

<script setup lang="ts">
withDefaults(defineProps<{ name: NavIconName; size?: number }>(), { size: 20 })
</script>

<template>
  <svg
    class="nav-icon"
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.6"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
  >
    <template v-if="name === 'ai'">
      <path d="M12 3.5l1.7 4.6 4.6 1.7-4.6 1.7L12 16l-1.7-4.5-4.6-1.7 4.6-1.7z" />
      <path d="M18.3 15.6l.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7z" />
    </template>
    <template v-else-if="name === 'hall'">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M9 20v-5h6v5" />
    </template>
    <template v-else-if="name === 'my-tasks'">
      <path d="M4 6.5l1.5 1.5L8.5 5" />
      <path d="M11 7h9" />
      <path d="M4 12.5l1.5 1.5L8.5 11" />
      <path d="M11 13h9" />
      <path d="M4 18.5l1.5 1.5L8.5 17" />
      <path d="M11 19h9" />
    </template>
    <template v-else-if="name === 'library'">
      <path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H20v18H6.5A2.5 2.5 0 0 1 4 18.5z" />
      <path d="M8 3v18" />
    </template>
    <template v-else-if="name === 'messages'">
      <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4z" />
    </template>
    <template v-else-if="name === 'profile'">
      <circle cx="12" cy="8" r="3.5" />
      <path d="M5 20a7 7 0 0 1 14 0" />
    </template>
    <template v-else-if="name === 'admin'">
      <path d="M12 3l7 3v6c0 4.4-3 7.4-7 9-4-1.6-7-4.6-7-9V6z" />
    </template>
    <template v-else-if="name === 'search'">
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4 4" />
    </template>
    <template v-else-if="name === 'new-chat'">
      <path d="M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H9l-5 4z" />
      <path d="M12 7v6" />
      <path d="M9 10h6" />
    </template>
    <template v-else-if="name === 'recent'">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4.5l3 1.5" />
    </template>
    <template v-else-if="name === 'history'">
      <path d="M4 12a8 8 0 1 0 2.5-5.8" />
      <path d="M4 5v4h4" />
      <path d="M12 8v4.5l3 1.5" />
    </template>
    <template v-else-if="name === 'archive'">
      <rect x="4" y="7" width="16" height="13" rx="2" />
      <path d="M4 7l1.5-3h13L20 7" />
      <path d="M9.5 12h5" />
    </template>
    <template v-else-if="name === 'panel-left'">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M9 5v14" />
    </template>
    <template v-else-if="name === 'panel-right'">
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M15 5v14" />
    </template>
    <template v-else-if="name === 'theme'">
      <circle cx="12" cy="12" r="4" />
      <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
    </template>
    <template v-else-if="name === 'chevron-down'">
      <path d="M6 9.5l6 6 6-6" />
    </template>
    <template v-else-if="name === 'chevron-right'">
      <path d="M9.5 6l6 6-6 6" />
    </template>
    <template v-else-if="name === 'task'">
      <rect x="4" y="4" width="16" height="16" rx="3" />
      <path d="M8 12l2.5 2.5L16 9" />
    </template>
    <template v-else-if="name === 'activity'">
      <rect x="3.5" y="7" width="17" height="11" rx="2" />
      <path d="M12 7v11" />
    </template>
    <template v-else-if="name === 'user'">
      <circle cx="12" cy="8" r="4" />
      <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
    </template>
    <template v-else-if="name === 'calendar'">
      <rect x="4" y="5" width="16" height="15" rx="3" />
      <path d="M8 3v4M16 3v4M4 10h16" />
    </template>
    <template v-else-if="name === 'clock'">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 7.5V12l3 2" />
    </template>
    <template v-else-if="name === 'check'">
      <path d="M5 12.5l4.5 4.5L19 7" />
    </template>
    <template v-else-if="name === 'link'">
      <path d="M10 13.5a4 4 0 0 0 5.7 0l2.6-2.6a4 4 0 0 0-5.7-5.7l-1.1 1.2" />
      <path d="M14 10.5a4 4 0 0 0-5.7 0l-2.6 2.6a4 4 0 0 0 5.7 5.7l1.1-1.2" />
    </template>
    <template v-else-if="name === 'flag'">
      <path d="M6 21V4" />
      <path d="M6 4.5h10.5l-1.8 3.6 1.8 3.6H6" />
    </template>
  </svg>
</template>

<style scoped>
.nav-icon {
  display: block;
  flex-shrink: 0;
}
</style>