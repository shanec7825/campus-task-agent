<script setup lang="ts">
/**
 * 详情页头部（契约 `C-DETAIL-HEADER@1`）。
 *
 * 只负责呈现：标题层级、副标题与三个固定插槽（状态胶囊 / 属性 chips / 操作）。
 * 不请求数据、不格式化日期；`type="primary"` 由调用方只给唯一主操作。
 */
withDefaults(
  defineProps<{
    kicker?: string | null
    title: string
    subtitle?: string | null
  }>(),
  { kicker: null, subtitle: null }
)
</script>

<template>
  <header class="detail-header">
    <div class="detail-header__body">
      <p v-if="kicker" class="detail-header__kicker">{{ kicker }}</p>
      <h1 class="detail-header__title">{{ title }}</h1>
      <p v-if="subtitle" class="detail-header__subtitle">{{ subtitle }}</p>
      <div v-if="$slots.badges" class="detail-header__badges">
        <slot name="badges" />
      </div>
      <div v-if="$slots.meta" class="detail-header__meta">
        <slot name="meta" />
      </div>
    </div>
    <div v-if="$slots.actions" class="detail-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.detail-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3) var(--app-space-5);
  padding-bottom: var(--app-space-4);
  margin-bottom: var(--app-space-5);
  border-bottom: 1px solid var(--app-border);
}

.detail-header__body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  min-width: 0;
  flex: 1 1 320px;
}

.detail-header__kicker {
  margin: 0;
  font-size: var(--app-font-label);
  line-height: 1.5;
  color: var(--app-text-muted);
}

.detail-header__title {
  margin: 0;
  font-size: var(--app-font-page-title);
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: -0.01em;
  color: var(--app-text);
  word-break: break-word;
}

.detail-header__subtitle {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
  word-break: break-word;
}

.detail-header__badges,
.detail-header__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.detail-header__actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  flex-shrink: 0;
}

@media (max-width: 768px) {
  .detail-header {
    flex-direction: column;
    align-items: stretch;
  }

  .detail-header__actions {
    width: 100%;
    flex-direction: column;
    align-items: stretch;
  }

  .detail-header__actions :deep(.el-button) {
    width: 100%;
    min-height: var(--app-touch);
    margin-left: 0;
  }
}
</style>