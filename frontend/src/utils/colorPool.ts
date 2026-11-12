/**
 * 颜色池（契约 C-SHELL@1 / C-TRACE@1）
 *
 * 唯一颜色来源：T7 / T8 只能 import 本文件，禁止复制映射。
 * 色值需与 src/styles/color-pool.css 中的 CSS 变量保持一致。
 */

/** 固定字段 → 色值映射（7 个色值，含两个同色语义键；本轮不得修改） */
export const FIELD_COLORS: Record<string, string> = {
  time: '#3B82F6',
  location: '#22C55E',
  quota: '#F97316',
  title: '#8B5CF6',
  extra_tags: '#EAB308',
  requirements: '#EAB308',
  unresolved: '#EF4444',
  corrections: '#EF4444'
}

/** 警示角标色 */
export const WARN_COLOR = '#EF4444'

/** 未解析文本色 */
export const UNPARSED_COLOR = '#374151'

/** 追溯块类型（与 `BlockKind` 去掉 `raw` 后一致；此处独立声明，保持本文件零依赖） */
export type TraceKind = 'ai_applied' | 'user_edit' | 'user_note' | 'live'

/** 4 个追溯色（唯一色源；与 CSS 变量 `--c-ai-applied/--c-user-edit/--c-user-note/--c-live` 同值） */
export const TRACE_COLORS: Record<TraceKind, string> = {
  ai_applied: '#8B5CF6', // 紫：AI 建议被采纳
  user_edit: '#0891B2', // 青：用户右侧手改
  user_note: '#6B7280', // 灰：用户在左侧补充的原话
  live: '#3B82F6' // 蓝：语音 interim（虚线）
}

/**
 * 取字段对应颜色。
 * - `extra_tags.` 前缀的键统一取扩展项色（黄色）
 * - 未知字段或空值 → `UNPARSED_COLOR`
 */
export function colorForField(field: string | null | undefined): string {
  if (!field) return UNPARSED_COLOR
  if (field.startsWith('extra_tags.')) return FIELD_COLORS.extra_tags
  return FIELD_COLORS[field] ?? UNPARSED_COLOR
}

/**
 * 取文字块颜色（契约 C-TRACE@1 B）。
 * - `raw` → 按字段色（与右侧字段面板同色）
 * - `live` → 追溯蓝
 * - 其余追溯块 → `TRACE_COLORS[kind]`
 */
export function colorForBlock(block: { kind: 'raw' | TraceKind; field: string | null }): string {
  if (block.kind === 'raw') return colorForField(block.field)
  return TRACE_COLORS[block.kind] ?? UNPARSED_COLOR
}