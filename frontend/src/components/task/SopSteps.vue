<script setup lang="ts">
/**
 * SOP 实施指导（计划 T6 验收 ⑤）。
 *
 * `sop_guide` 为多行文本，按行渲染为步骤清单：自动去掉行首序号/圆点（`1.`、`1、`、`①`、`- `、`* `），
 * 空行丢弃；无有效内容时显示「暂无实施指导」。
 */
import { computed } from 'vue'

import EmptyState from '../common/EmptyState.vue'

const props = defineProps<{ guide: string | null | undefined }>()

/** 行首编号 / 项目符号 */
const LEADING_MARK_RE = /^(?:步骤\s*)?(?:\d+\s*[.、)）]|[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]|[-*•])\s*/

const steps = computed<string[]>(() => {
  const raw = (props.guide ?? '').replace(/\r\n/g, '\n').trim()
  if (!raw) return []
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => line.replace(LEADING_MARK_RE, '').trim())
    .filter((line) => line.length > 0)
})
</script>

<template>
  <div class="sop-steps">
    <EmptyState
      v-if="steps.length === 0"
      title="暂无实施指导"
      description="发布者未提供操作步骤，可直接联系发布者确认具体要求。"
    />

    <ol v-else class="step-list">
      <li v-for="(step, index) in steps" :key="index" class="step-item">
        <span class="step-index">{{ index + 1 }}</span>
        <span class="step-text">{{ step }}</span>
      </li>
    </ol>
  </div>
</template>

<style scoped>
.step-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.step-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f7f9fc;
}

.step-index {
  flex-shrink: 0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #409eff;
  color: #ffffff;
  font-size: 13px;
  font-weight: 600;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.step-text {
  font-size: 14px;
  color: #303133;
  line-height: 1.7;
  word-break: break-word;
}
</style>