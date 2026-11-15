<script lang="ts">
/**
 * 属性面板条目（契约 `C-PROPERTY-LIST@1`）。
 *
 * 值格式化与空值回退由调用方完成：组件只按 `tone` 换颜色，不发请求、不解析日期。
 */
export interface PropertyItem {
  label: string
  value: string
  tone?: 'default' | 'muted' | 'success' | 'warning' | 'danger'
}
</script>

<script setup lang="ts">
withDefaults(defineProps<{ items: PropertyItem[]; columns?: 1 | 2 }>(), { columns: 1 })
</script>

<template>
  <dl class="property-list" :class="`property-list--cols-${columns}`">
    <div v-for="(item, index) in items" :key="index" class="property-list__item">
      <dt class="property-list__label">{{ item.label }}</dt>
      <dd
        class="property-list__value"
        :class="`property-list__value--${item.tone ?? 'default'}`"
      >
        {{ item.value }}
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.property-list {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--app-space-2) var(--app-space-4);
  margin: 0;
}

.property-list--cols-2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.property-list__item {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-width: 0;
  padding-bottom: var(--app-space-2);
  border-bottom: 1px solid var(--app-border);
}

.property-list__item:last-child {
  border-bottom: none;
}

.property-list__label {
  flex: none;
  font-size: var(--app-font-label);
  line-height: 1.6;
  color: var(--app-text-muted);
}

.property-list__value {
  margin: 0;
  min-width: 0;
  font-size: var(--app-font-body);
  line-height: 1.6;
  text-align: right;
  color: var(--app-text);
  word-break: break-word;
}

.property-list__value--muted {
  color: var(--app-text-muted);
}

.property-list__value--success {
  color: var(--el-color-success);
}

.property-list__value--warning {
  color: var(--el-color-warning);
}

.property-list__value--danger {
  color: var(--el-color-danger);
}

@media (max-width: 768px) {
  .property-list--cols-2 {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>