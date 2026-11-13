<script setup lang="ts">
/**
 * 彩色文字块（契约 C-VOICEUI@1 / C-TRACE@1）
 *
 * 只读展示容器：**禁止**用原生 input/textarea 承载多块（原生控件无法按片段染色）。
 *
 * - `kind='raw'`：纯展示，点击只 emit('select') 供父级做高亮 / 视觉定位；
 *   颜色 = `colorForBlock` → `colorForField(block.field)`（与右侧字段面板同色）。
 * - `kind !== 'raw'`（ai_applied / user_edit / user_note / live）：**只读**，
 *   额外用一个 el-tooltip 展示 `meta.reason`（无 reason 时展示块文本）；
 *   颜色取 `TRACE_COLORS`，`live` 额外使用虚线下边框。
 *
 * 第四轮（C3）：块内编辑（编辑浮层 + 输入框 + document 外部点击监听）整体移除。
 * 文本修正途径收敛为「右侧字段面板 + 增量解析」，块只承担展示与选中高亮。
 */
import { computed } from 'vue'

import type { Block } from '../../stores/draft'
import { colorForBlock } from '../../utils/colorPool'

const props = withDefaults(
  defineProps<{
    block: Block
    active?: boolean
  }>(),
  { active: false }
)

const emit = defineEmits<{
  (e: 'select', block: Block): void
}>()

/** 追溯块 = 非 raw：只读，追加 kind 染色与 tooltip 说明 */
const isTraceBlock = computed<boolean>(() => props.block.kind !== 'raw')

/** 块色：唯一颜色源 utils/colorPool（raw 走字段色，追溯块走 TRACE_COLORS） */
const blockStyle = computed(() => ({ '--block-color': colorForBlock(props.block) }))

/** 追溯块的 tooltip：优先展示 change.reason（AI 为什么要改），否则展示块文本 */
const tooltipContent = computed<string>(() => {
  const reason = props.block.meta?.reason
  return reason && reason.trim() !== '' ? reason : props.block.text
})

/** 点击只做选中高亮（不再进入编辑态）；追溯块与 raw 块统一走这一入口 */
function onSelect(): void {
  emit('select', props.block)
}
</script>

<template>
  <!--
    纯展示块：raw 与追溯块共用同一 span 结构，避免样式/无障碍属性分叉。
    非 raw 块叠加 el-tooltip 展示 meta.reason；raw 块上 tooltip 处于 disabled 状态。
  -->
  <el-tooltip
    :content="tooltipContent"
    :disabled="!isTraceBlock"
    placement="top"
    :show-after="120"
  >
    <span
      class="block-text"
      :class="[
        `is-kind-${block.kind}`,
        {
          'is-active': active,
          'is-pending': block.status === 'pending',
          'is-live': block.kind === 'live'
        }
      ]"
      :style="blockStyle"
      :role="isTraceBlock ? 'note' : 'button'"
      :tabindex="isTraceBlock ? undefined : 0"
      :aria-label="isTraceBlock ? `追溯块：${block.text}` : `文字块：${block.text}`"
      @click="onSelect"
      @keydown.enter.prevent="onSelect"
      @keydown.space.prevent="onSelect"
    >{{ block.text }}</span>
  </el-tooltip>
</template>

<style scoped>
.block-text {
  display: inline-block;
  padding: 1px 5px;
  margin: 2px 0;
  border-radius: 6px;
  border-bottom: 2px solid var(--block-color);
  color: var(--block-color);
  font-size: 16px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  cursor: pointer;
  outline: none;
  transition: box-shadow 0.18s ease, transform 0.18s ease, background-color 0.18s ease;
}

/* 追溯块只读：仅缩小字号，光标与 raw 块统一为 pointer（点击只做高亮定位） */
.block-text.is-kind-ai_applied,
.block-text.is-kind-user_edit,
.block-text.is-kind-user_note,
.block-text.is-kind-live {
  font-size: 15px;
}

.block-text:hover,
.block-text:focus-visible,
.block-text.is-active {
  background: color-mix(in srgb, var(--block-color) 12%, transparent);
}

/* 键盘可达：全局 :focus-visible 规则之外再补一圈块色描边，避免 outline: none 丢失焦点提示 */
.block-text:focus-visible {
  outline: 2px solid var(--block-color);
  outline-offset: 2px;
}

.block-text.is-pending {
  border-bottom-style: dashed;
}

/* 语音 interim：虚线下边框（颜色取 colorForBlock，即 --c-live） */
.block-text.is-live {
  border-bottom-style: dashed;
  opacity: 0.85;
}

/* 追溯块背景非常淡，避免与 raw 数据块抢视觉；raw 块保持无底色 */
.block-text.is-kind-ai_applied,
.block-text.is-kind-user_edit,
.block-text.is-kind-user_note {
  background: color-mix(in srgb, var(--block-color) 8%, transparent);
}
</style>