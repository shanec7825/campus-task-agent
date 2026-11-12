<script setup lang="ts">
/**
 * 相似任务提示条（T7 / 需求 R2.5-AC4、R7-AC3）
 *
 * 展示位置：AI 模式「AI 解析」前、手动模式标题失焦后，均由父组件决定是否渲染
 * （父组件只在 `items[0].similarity > threshold` 时传入 item，本组件不做阈值判断）。
 *
 * 交互：
 * - 「带入草稿」→ emit('adopt')：只允许带入结构化字段，**不得覆盖用户已改的 title**
 *   （由父组件拉取任务详情后仅覆盖 time/location/quota 等字段）；
 * - 「关闭」→ emit('close')：父组件清空提示条。
 */
import { computed } from 'vue'

import type { SimilarItem } from '../../types/models'

const props = withDefaults(
  defineProps<{
    item: SimilarItem
    threshold?: number
  }>(),
  { threshold: 0.6 }
)

const emit = defineEmits<{
  (e: 'adopt'): void
  (e: 'close'): void
}>()

/** 相似度百分比（后端返回 0~1 的 4 位小数） */
const similarityPercent = computed<number>(() => Math.round(props.item.similarity * 100))

/** 历史任务缺失 task_id 时无法拉取结构化字段，带入按钮置灰并给出原因 */
const canAdopt = computed<boolean>(() => props.item.task_id !== null)

const publishedAt = computed<string>(() => {
  const raw = props.item.created_at
  if (!raw) return '未知发布时间'
  // 后端时间为 `YYYY-MM-DD HH:MM:SS`，展示到分钟即可
  return raw.length >= 16 ? raw.slice(0, 16) : raw
})

const adoptTip = computed<string>(() =>
  canAdopt.value ? '只带入时间 / 地点 / 名额等字段，不会覆盖标题' : '该历史任务缺少结构化信息，无法带入'
)
</script>

<template>
  <section class="similar-tip" role="status" aria-live="polite">
    <div class="similar-tip__main">
      <p class="similar-tip__title">
        <span class="similar-tip__icon" aria-hidden="true">✦</span>
        发现相似任务：{{ item.title }}
        <el-tag size="small" type="warning" effect="plain">相似度 {{ similarityPercent }}%</el-tag>
      </p>
      <p v-if="item.summary" class="similar-tip__summary">{{ item.summary }}</p>
      <p class="similar-tip__meta">发布日：{{ publishedAt }}（阈值 {{ Math.round(threshold * 100) }}%）</p>
    </div>

    <div class="similar-tip__actions">
      <el-tooltip :content="adoptTip" placement="top">
        <span>
          <el-button size="small" type="warning" plain :disabled="!canAdopt" @click="emit('adopt')">
            带入草稿
          </el-button>
        </span>
      </el-tooltip>
      <el-button size="small" text @click="emit('close')">关闭</el-button>
    </div>
  </section>
</template>

<style scoped>
.similar-tip {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border: 1px solid var(--el-color-warning-light-5);
  border-left: 4px solid var(--el-color-warning);
  border-radius: 10px;
  background: var(--el-color-warning-light-9);
}

.similar-tip__main {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.similar-tip__title {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.similar-tip__icon {
  color: var(--el-color-warning);
}

.similar-tip__summary {
  margin: 0;
  font-size: 14px;
  line-height: 1.5;
  color: var(--el-text-color-regular);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.similar-tip__meta {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.similar-tip__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: none;
}
</style>