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
  <div class="error-state">
    <el-result icon="error" :title="message || '请求失败'" :sub-title="detail">
      <template v-if="retryable" #extra>
        <el-button type="primary" data-test="retry" @click="emit('retry')">重试</el-button>
      </template>
    </el-result>
  </div>
</template>

<style scoped>
.error-state {
  padding: 8px 0;
}

.error-state :deep(.el-result__title) {
  margin-top: 8px;
}
</style>