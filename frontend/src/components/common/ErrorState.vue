<script setup lang="ts">
/**
 * 失败态（契约 C-UI-COMMON@1）。
 *
 * `retryable` 为真时渲染「重试」按钮并 emit `retry`，由调用方重新发起同一请求。
 */
withDefaults(
  defineProps<{ message: string; detail?: string; retryable?: boolean }>(),
  { detail: '', retryable: false }
)

const emit = defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div class="error-state" role="alert">
    <el-result icon="error" :title="message || '请求失败'" :sub-title="detail">
      <template v-if="retryable" #extra>
        <el-button type="primary" class="error-retry" data-test="retry" @click="emit('retry')">
          重试
        </el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.error-state {
  width: 100%;
  box-sizing: border-box;
  padding: 16px 8px;
}

.error-state :deep(.el-result) {
  padding: 24px 16px;
}

.error-state :deep(.el-result__title p) {
  margin-top: 8px;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.5;
  color: var(--app-text);
}

.error-state :deep(.el-result__subtitle p) {
  margin-top: 8px;
  font-size: 14px;
  line-height: 1.7;
  color: var(--app-text-secondary);
}

.error-retry {
  min-width: 132px;
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .error-state {
    padding: 12px 0;
  }

  .error-state :deep(.el-result) {
    padding: 16px 4px;
  }
}
</style>