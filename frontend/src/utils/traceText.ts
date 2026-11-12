/**
 * 追溯块文案（契约 C-TRACE@1 / C-AGENT@2）。
 *
 * 约束：
 * - 纯函数、零运行时依赖（仅 `import type`），可被 `tsc` 单独编译后用 Node 直接执行；
 * - `source='ai'` 的输出必须与后端 `applied_texts` **逐字一致**（T8 交叉断言）；
 * - 中文全角标点：冒号「：」、引号「「」」、逗号「，」，前缀与正文之间无空格。
 */
import type { Change } from '../types/models'

/** 字段中文名（唯一来源；与后端 `diffing.FIELD_LABELS` 保持一致） */
export const FIELD_LABELS: Record<string, string> = {
  title: '标题',
  time: '时间',
  deadline: '截止时间',
  location: '地点',
  details: '详情',
  quota: '名额',
  volunteer_hours: '志愿时长',
  notes: '备注',
  requirements: '要求'
}

const EXTRA_PREFIX = 'extra_tags.'

/** 扩展项字段路径 → 裸键名；非扩展项原样返回 */
export function tagKeyOf(field: string): string {
  return field.startsWith(EXTRA_PREFIX) ? field.slice(EXTRA_PREFIX.length) : field
}

/**
 * 字段路径 → 展示标签。
 * - `extra_tags.工作内容` → `工作内容`
 * - 9 个标量字段 → 中文名
 * - `extra_tags` → `扩展项`
 * - 未收录的键原样返回（不吞掉用户自定义的扩展项名）
 */
export function formatFieldLabel(field: string): string {
  if (!field) return ''
  if (field.startsWith(EXTRA_PREFIX)) return field.slice(EXTRA_PREFIX.length)
  if (field === 'extra_tags') return '扩展项'
  return FIELD_LABELS[field] ?? field
}

/** 值的展示形态：null / undefined / 空白串统一为空串，其余转字符串后去首尾空白 */
function valueText(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return ''
  return String(value).trim()
}

/**
 * 单条变更 → 追溯文案。
 *
 * 模板（逐字）：
 * - AI + set + 无旧值：`AI建议：补充{label}为「{new}」`
 * - AI + set + 有旧值：`AI建议：将{label}由「{old}」改为「{new}」`
 * - AI + add_tag：`AI建议：新增扩展项「{key}」，内容为「{new}」`
 * - 用户 + add_tag：`用户：新建扩展项「{key}」，内容为「{new}」`
 * - 用户 + set + 无旧值：`用户：新建{label}，内容为「{new}」`
 * - 用户 + set + 有旧值：`用户：将{label}由「{old}」改为「{new}」`
 * - remove_tag：`用户：删除扩展项「{key}」（原「{old}」）`（无旧值时省略括号）
 * - 新值为空：`用户：清空{label}（原「{old}」）`
 */
export function formatChangeText(change: Change): string {
  const label = formatFieldLabel(change.field)
  const key = tagKeyOf(change.field)
  const oldText = valueText(change.old_value)
  const newText = valueText(change.new_value)
  const isAi = change.source === 'ai'

  if (change.op === 'add_tag') {
    return isAi
      ? `AI建议：新增扩展项「${key}」，内容为「${newText}」`
      : `用户：新建扩展项「${key}」，内容为「${newText}」`
  }

  if (change.op === 'remove_tag') {
    return oldText
      ? `用户：删除扩展项「${key}」（原「${oldText}」）`
      : `用户：删除扩展项「${key}」`
  }

  if (!newText) {
    return `用户：清空${label}（原「${oldText}」）`
  }

  if (isAi) {
    return oldText
      ? `AI建议：将${label}由「${oldText}」改为「${newText}」`
      : `AI建议：补充${label}为「${newText}」`
  }

  return oldText
    ? `用户：将${label}由「${oldText}」改为「${newText}」`
    : `用户：新建${label}，内容为「${newText}」`
}