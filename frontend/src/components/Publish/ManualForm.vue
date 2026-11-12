<script setup lang="ts">
/**
 * 手动兜底发布表单（T7 / 需求 R2.1-AC1~AC3、R7-AC4）
 *
 * 设计要点：
 * 1. 纯 Element Plus 表单，**不依赖任何 AI 能力**：AI 不可用时仍可完整发布（R2.1-AC3）；
 * 2. `extras` 支持任意键值对动态增删，原样落库（R2.1-AC2）；
 * 3. `credit_reward` 与 `reminder_rule` 可配置，缺省 20 分 / 1 天前 + 当天 + 逾期提醒；
 * 4. 标题失焦时查询一次相似任务（R7-AC4），命中 > 阈值时展示提示条，
 *    「带入草稿」通过任务详情拉取结构化字段，**只覆盖时间/地点/名额，不覆盖标题**；
 * 5. 发布成功 → `createTask` → 跳转 `/tasks/:id`；失败保留表单内容并提示原因。
 */
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { ApiError } from '../../api/client'
import { findSimilar } from '../../api/kb'
import { createTask, getTask } from '../../api/tasks'
import type { SimilarItem } from '../../types/models'
import SimilarTip from './SimilarTip.vue'

/** 动态扩展项行 */
interface ExtraRow {
  /** 渲染 key：仅用于 v-for，不参与提交 */
  uid: number
  key: string
  value: string
}

const router = useRouter()

const form = reactive({
  title: '',
  description: '',
  requirements: '',
  start_time: null as string | null,
  deadline: null as string | null,
  location: '',
  quota: null as number | null,
  credit_reward: 20,
  reminder_days_before: 1,
  reminder_day_of: true,
  reminder_on_overdue: true
})

const extras = ref<ExtraRow[]>([])
const submitting = ref(false)

/** 相似任务提示（仅在 `items[0].similarity > threshold` 时有值） */
const similarItem = ref<SimilarItem | null>(null)
const similarThreshold = ref(0.6)

let extraSeq = 0
/** 上一次已查询过的标题，避免同一标题反复失焦触发请求 */
let lastSimilarQuery = ''

function newExtraRow(): ExtraRow {
  extraSeq += 1
  return { uid: extraSeq, key: '', value: '' }
}

function addExtraRow(): void {
  extras.value = [...extras.value, newExtraRow()]
}

function removeExtraRow(index: number): void {
  extras.value = extras.value.filter((_, rowIndex) => rowIndex !== index)
}

function errorMessage(cause: unknown): string {
  if (cause instanceof ApiError) return `${cause.message}（code=${cause.code}）`
  if (cause instanceof Error) return cause.message
  return '未知错误'
}

/** el-date-picker 的 modelValue 类型较宽，这里统一窄化为字符串 */
function onStartTimeChange(value: unknown): void {
  form.start_time = typeof value === 'string' && value !== '' ? value : null
}

function onDeadlineChange(value: unknown): void {
  form.deadline = typeof value === 'string' && value !== '' ? value : null
}

function onQuotaChange(value: number | undefined): void {
  form.quota = typeof value === 'number' && Number.isFinite(value) ? value : null
}

function onCreditChange(value: number | undefined): void {
  form.credit_reward = typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function onDaysBeforeChange(value: number | undefined): void {
  form.reminder_days_before = typeof value === 'number' && Number.isFinite(value) ? value : 0
}

/**
 * 标题失焦 → 查询相似任务（R7-AC4）。
 * 相似检索属于辅助能力：失败时静默跳过，绝不阻塞手动发布（R2.1-AC3）。
 */
async function onTitleBlur(): Promise<void> {
  const title = form.title.trim()
  if (!title || title === lastSimilarQuery) return
  lastSimilarQuery = title
  try {
    const result = await findSimilar(title)
    similarThreshold.value = result.threshold
    const top = result.items[0]
    similarItem.value = top && top.similarity > result.threshold ? top : null
  } catch {
    similarItem.value = null
  }
}

/**
 * 带入相似任务的结构化字段。
 * 只覆盖时间 / 地点 / 名额，**不覆盖用户已填写的标题**（T7 验收 ④）。
 */
async function adoptSimilar(item: SimilarItem): Promise<void> {
  if (item.task_id === null) {
    ElMessage.info('该历史任务缺少结构化信息，无法带入')
    similarItem.value = null
    return
  }
  try {
    const detail = await getTask(item.task_id)
    if (detail.start_time) form.start_time = detail.start_time
    if (detail.deadline) form.deadline = detail.deadline
    if (detail.location) form.location = detail.location
    if (detail.quota !== null) form.quota = detail.quota
    similarItem.value = null
    ElMessage.success('已带入起止时间 / 地点 / 名额，标题保持不变')
  } catch (cause) {
    ElMessage.error(`带入失败：${errorMessage(cause)}`)
  }
}

/** 收集动态扩展项：空键名+空值忽略；空键名有值、键名重复均阻断提交 */
function collectExtras(): Record<string, unknown> | null {
  const result: Record<string, unknown> = {}
  for (const row of extras.value) {
    const key = row.key.trim()
    const value = row.value.trim()
    if (!key) {
      if (value) {
        ElMessage.error('扩展项的键名不能为空')
        return null
      }
      continue
    }
    if (Object.prototype.hasOwnProperty.call(result, key)) {
      ElMessage.error(`扩展项键名重复：${key}`)
      return null
    }
    result[key] = value
  }
  return result
}

function resetForm(): void {
  form.title = ''
  form.description = ''
  form.requirements = ''
  form.start_time = null
  form.deadline = null
  form.location = ''
  form.quota = null
  form.credit_reward = 20
  form.reminder_days_before = 1
  form.reminder_day_of = true
  form.reminder_on_overdue = true
  extras.value = []
  similarItem.value = null
  lastSimilarQuery = ''
}

async function handleSubmit(): Promise<void> {
  if (submitting.value) return

  const title = form.title.trim()
  if (!title) {
    ElMessage.error('请填写任务标题')
    return
  }

  const extrasPayload = collectExtras()
  if (!extrasPayload) return

  if (form.start_time && form.deadline && form.deadline < form.start_time) {
    ElMessage.error('截止时间不能早于开始时间')
    return
  }

  // 手动表单的「要求」按 C-DATA@1 映射表并入 description（顺序：描述 → 要求）
  const descriptionParts = [form.description.trim(), form.requirements.trim()].filter(
    (part) => part !== ''
  )

  submitting.value = true
  try {
    const task = await createTask({
      title,
      description: descriptionParts.length > 0 ? descriptionParts.join('\n') : null,
      location: form.location.trim() || null,
      start_time: form.start_time,
      deadline: form.deadline,
      quota: form.quota,
      extras: extrasPayload,
      reminder_rule: {
        days_before: form.reminder_days_before,
        day_of: form.reminder_day_of,
        on_overdue: form.reminder_on_overdue
      },
      credit_reward: form.credit_reward
    })
    ElMessage.success(`发布成功：${task.title}`)
    resetForm()
    void router.push(`/tasks/${task.id}`)
  } catch (cause) {
    ElMessage.error(`发布失败：${errorMessage(cause)}`)
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="manual-form">
    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="手动兜底模式"
      description="不依赖 AI：填写完整信息即可发布；AI 不可用时此模式仍可正常使用。"
      class="manual-form__alert"
    />

    <SimilarTip
      v-if="similarItem"
      :item="similarItem"
      :threshold="similarThreshold"
      @adopt="adoptSimilar(similarItem)"
      @close="similarItem = null"
    />

    <el-form label-width="96px" label-position="top" class="manual-form__body">
      <el-form-item label="任务标题" required>
        <el-input
          v-model="form.title"
          maxlength="80"
          show-word-limit
          placeholder="例如：秋之韵晚会场地布置"
          @blur="onTitleBlur"
        />
      </el-form-item>

      <div class="manual-form__grid">
        <el-form-item label="开始时间">
          <el-date-picker
            :model-value="form.start_time ?? ''"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择开始时间"
            class="manual-form__picker"
            @update:model-value="onStartTimeChange"
          />
        </el-form-item>

        <el-form-item label="截止时间">
          <el-date-picker
            :model-value="form.deadline ?? ''"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择截止时间"
            class="manual-form__picker"
            @update:model-value="onDeadlineChange"
          />
        </el-form-item>

        <el-form-item label="地点">
          <el-input v-model="form.location" maxlength="60" placeholder="例如：教三 302" />
        </el-form-item>

        <el-form-item label="需求人数">
          <el-input-number
            :model-value="form.quota ?? undefined"
            :min="1"
            :max="999"
            controls-position="right"
            placeholder="可选"
            @change="onQuotaChange"
          />
        </el-form-item>
      </div>

      <el-form-item label="任务描述">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          placeholder="任务背景、内容、注意事项…"
        />
      </el-form-item>

      <el-form-item label="完成要求">
        <el-input
          v-model="form.requirements"
          type="textarea"
          :rows="2"
          maxlength="500"
          show-word-limit
          placeholder="对完成质量的要求（发布时并入任务描述）"
        />
      </el-form-item>

      <el-form-item label="扩展项（任意键值对）">
        <div class="manual-form__extras">
          <div v-for="(row, index) in extras" :key="row.uid" class="manual-form__extra-row">
            <el-input v-model="row.key" placeholder="键名，如：工作内容" maxlength="30" />
            <el-input v-model="row.value" placeholder="值，如：搬桌椅" maxlength="120" />
            <el-button type="danger" text @click="removeExtraRow(index)">删除</el-button>
          </div>
          <el-button plain size="small" @click="addExtraRow">+ 新增扩展项</el-button>
        </div>
      </el-form-item>

      <div class="manual-form__grid">
        <el-form-item label="完成奖励积分">
          <el-input-number
            :model-value="form.credit_reward"
            :min="0"
            :max="1000"
            controls-position="right"
            @change="onCreditChange"
          />
        </el-form-item>

        <el-form-item label="提前提醒（天）">
          <el-input-number
            :model-value="form.reminder_days_before"
            :min="0"
            :max="30"
            controls-position="right"
            @change="onDaysBeforeChange"
          />
        </el-form-item>
      </div>

      <el-form-item label="催办规则">
        <div class="manual-form__switches">
          <el-checkbox v-model="form.reminder_day_of">截止当天提醒</el-checkbox>
          <el-checkbox v-model="form.reminder_on_overdue">逾期提醒双方</el-checkbox>
        </div>
      </el-form-item>
    </el-form>

    <footer class="manual-form__footer">
      <el-button type="primary" size="large" :loading="submitting" @click="handleSubmit">
        发布任务
      </el-button>
      <span class="manual-form__tip">发布成功后跳转到任务详情页</span>
    </footer>
  </div>
</template>

<style scoped>
.manual-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.manual-form__alert {
  border-radius: 10px;
}

.manual-form__body {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.manual-form__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.manual-form__picker {
  width: 100%;
}

.manual-form__extras {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.manual-form__extra-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.manual-form__switches {
  display: flex;
  align-items: center;
  gap: 24px;
}

.manual-form__footer {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-top: 8px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.manual-form__tip {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .manual-form__grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>