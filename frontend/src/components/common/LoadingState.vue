<script setup lang="ts">
/**
 * 加载态（契约 C-UI-COMMON@1）。
 *
 * 骨架屏，`rows` 控制骨架行数（默认 3）；不含业务逻辑。
 */
withDefaults(defineProps<{ rows?: number }>(), { rows: 3 })
</script>

<template>
  <div class="loading-state" role="status" aria-live="polite">
    <p class="loading-text">加载中…</p>
    <el-skeleton :rows="rows" animated />
  </div>
</template>

<style scoped>
.loading-state {
  width: 100%;
  box-sizing: border-box;
  padding: 12px 4px;
}

.loading-text {
  margin: 0 0 12px;
  font-size: 14px;
  line-height: 1.6;
  color: var(--app-text-muted);
}

.loading-state :deep(.el-skeleton) {
  --el-skeleton-color: var(--app-surface-sunken);
  --el-skeleton-to-color: var(--app-border);
}

@media (max-width: 768px) {
  .loading-state {
    padding: 8px 0;
  }
}
</style>