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
  <div class="empty-state">
    <el-empty :description="title" :image-size="72">
      <p v-if="description" class="empty-description">{{ description }}</p>
    </el-empty>
  </div>
</template>

<style scoped>
.empty-state {
  padding: 8px 0;
}

.empty-description {
  margin: 0;
  font-size: 14px;
  color: #909399;
  line-height: 1.6;
}
</style>