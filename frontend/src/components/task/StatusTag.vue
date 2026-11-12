<script lang="ts">
/**
 * 任务状态标签（契约 C-UI-COMMON@1 / 计划 2.3.1）。
 *
 * 本组件是**唯一**的状态文案与颜色来源：任何页面/组件展示任务状态都必须走
 * `StatusTag` 或复用这里导出的 `statusMeta/statusText`，禁止各自硬编码文案。
 * 7 个状态全覆盖，未知状态兜底为「未知」。
 */
export type StatusTagType = 'primary' | 'success' | 'info' | 'warning' | 'danger'

export interface StatusMeta {
  /** 中文文案 */
  text: string
  /** Element Plus `el-tag` 的 type */
  type: StatusTagType
}

export const STATUS_MAP: Record<string, StatusMeta> = {
  published: { text: '待认领', type: 'info' },
  claimed: { text: '已认领', type: 'primary' },
  in_progress: { text: '进行中', type: 'warning' },
  submitted: { text: '待验收', type: 'warning' },
  verified: { text: '已完成', type: 'success' },
  overdue: { text: '已逾期', type: 'danger' },
  cancelled: { text: '已取消', type: 'info' }
}

/** 未知状态的兜底展示 */
export const UNKNOWN_STATUS: StatusMeta = { text: '未知', type: 'info' }

/** 按状态字符串取文案与颜色；空值/未知状态返回兜底项 */
export function statusMeta(status: string | null | undefined): StatusMeta {
  if (!status) return UNKNOWN_STATUS
  return STATUS_MAP[status] ?? UNKNOWN_STATUS
}

/** 只取状态文案（用于置灰原因、提示语等纯文本场景） */
export function statusText(status: string | null | undefined): string {
  return statusMeta(status).text
}
</script>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ status: string; size?: 'large' | 'default' | 'small' }>(),
  { size: 'default' }
)

const meta = computed<StatusMeta>(() => statusMeta(props.status))
</script>

<template>
  <el-tag
    :type="meta.type"
    :size="size"
    effect="light"
    disable-transitions
    class="status-tag"
    :data-status="status"
  >
    {{ meta.text }}
  </el-tag>
</template>

<style scoped>
.status-tag {
  flex-shrink: 0;
  font-weight: 500;
}
</style>