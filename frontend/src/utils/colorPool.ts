/**
 * 颜色池（契约 C-COLOR@1）
 *
 * 唯一颜色来源：组件只能 import 本文件或引用 color-pool.css 变量，禁止复制映射。
 * `FIELD_COLORS` / `WARN_COLOR` / `UNPARSED_COLOR` 与 4 个追溯色常量保留为浅色基线（静态检查依赖），
 * 组件实际渲染统一走下面的 CSS 变量，由 color-pool.css 在 `html.dark` 下切换为高对比变体。
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

/** 字段 → 主题感知 CSS 变量（键集合与 FIELD_COLORS 一致，浅/深色由 color-pool.css 决定） */
export const FIELD_CSS_VARS: Record<string, string> = {
  time: 'var(--c-time)',
  location: 'var(--c-location)',
  quota: 'var(--c-quota)',
  title: 'var(--c-title)',
  extra_tags: 'var(--c-extra)',
  requirements: 'var(--c-extra)',
  unresolved: 'var(--c-warn)',
  corrections: 'var(--c-warn)'
}

/** 追溯块 → 主题感知 CSS 变量 */
export const TRACE_CSS_VARS: Record<TraceKind, string> = {
  ai_applied: 'var(--c-ai-applied)',
  user_edit: 'var(--c-user-edit)',
  user_note: 'var(--c-user-note)',
  live: 'var(--c-live)'
}

/** 警示色（主题感知） */
export const WARN_CSS_COLOR = 'var(--c-warn)'

/** 未解析文本色（主题感知） */
export const UNPARSED_CSS_COLOR = 'var(--c-unparsed)'

/**
 * 取字段对应颜色变量。
 * - `extra_tags.` 前缀的键统一取扩展项色（黄色）
 * - 未知字段或空值 → `UNPARSED_CSS_COLOR`
 */
export function colorForField(field: string | null | undefined): string {
  if (!field) return UNPARSED_CSS_COLOR
  if (field.startsWith('extra_tags.')) return FIELD_CSS_VARS.extra_tags
  return FIELD_CSS_VARS[field] ?? UNPARSED_CSS_COLOR
}

/**
 * 取文字块颜色变量（契约 C-COLOR@1）。
 * - `raw` → 按字段色（与右侧字段面板同色）
 * - 其余追溯块 → `TRACE_CSS_VARS[kind]`
 */
export function colorForBlock(block: { kind: 'raw' | TraceKind; field: string | null }): string {
  if (block.kind === 'raw') return colorForField(block.field)
  return TRACE_CSS_VARS[block.kind] ?? UNPARSED_CSS_COLOR
}