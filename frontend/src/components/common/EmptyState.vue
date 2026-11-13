<script setup lang="ts">
/**
 * 空态（契约 C-UI-COMMON@1）。
 *
 * 统一空列表展示，不含业务逻辑；默认文案「暂无数据」。
 */
withDefaults(defineProps<{ title?: string; description?: string }>(), {
  title: '暂无数据',
  description: ''
})
</script>

<template>
  <div class="empty-state" role="status">
    <el-empty :description="title" :image-size="72">
      <p v-if="description" class="empty-description">{{ description }}</p>
    </el-empty>
  </div>
</template>

<style scoped>
.empty-state {
  display: flex;
  justify-content: center;
  width: 100%;
  box-sizing: border-box;
  padding: 24px 12px;
  text-align: center;
}

.empty-state :deep(.el-empty) {
  padding: 8px 0;
}

.empty-state :deep(.el-empty__description p) {
  margin: 0;
  font-size: 15px;
  line-height: 1.6;
  color: var(--app-text-secondary);
}

.empty-description {
  max-width: 36em;
  margin: 4px auto 0;
  font-size: 14px;
  line-height: 1.7;
  color: var(--app-text-muted);
}

@media (max-width: 768px) {
  .empty-state {
    padding: 20px 4px;
  }
}
</style>