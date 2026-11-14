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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { ApiError } from '../../api/client'
import { findSimilar } from '../../api/kb'
import { createTask, getTask, listTasks } from '../../api/tasks'
import {
  parseSubmissionAcceptance,
  SUBMISSION_FILE_EXTS,
  SUBMISSION_MODE_LABELS,
  SUBMISSION_MODES,
  submissionFileLabel
} from '../../types/models'
import type { SimilarItem, TaskCreatePayload, TaskItem } from '../../types/models'
import TaskContentSections from '../task/TaskContentSections.vue'
import SimilarTip from './SimilarTip.vue'

/** 动态扩展项行 */
interface ExtraRow {
  /** 渲染 key：仅用于 v-for，不参与提交 */
  uid: number
  key: string
  value: string
}

/** 成果要求草稿：`modes` 用 `string[]` 兼容 el-checkbox-group 的 v-model 类型 */
interface AcceptanceDraft {
  modes: string[]
  allowed_exts: string[]
  ai_precheck: boolean
}

/** `extras` 中的成果要求保留键，动态键值对不得占用 */
const ACCEPTANCE_EXTRA_KEY = 'acceptance'

/** 由活动详情进入发布页时携带的活动归属；`null` 表示创建独立任务 */
const props = withDefaults(
  defineProps<{ activityId?: number | null; task?: TaskItem | null }>(),
  { activityId: null, task: null }
)

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

/** 成果要求（`C-SUBMISSION-POLICY@1`）：写入 `extras.acceptance`，默认三种方式全允许 */
const acceptance = reactive<AcceptanceDraft>({
  modes: [...SUBMISSION_MODES],
  allowed_exts: [...SUBMISSION_FILE_EXTS],
  ai_precheck: false
})

/** 仅勾选「文件上传」时才要求选择允许的文件类型 */
const fileModeEnabled = computed<boolean>(() => acceptance.modes.includes('file'))

function resetAcceptance(): void {
  acceptance.modes = [...SUBMISSION_MODES]
  acceptance.allowed_exts = [...SUBMISSION_FILE_EXTS]
  acceptance.ai_precheck = false
}

/** 编辑既有任务时回显成果要求；未配置或结构非法时回到「三种方式全允许」 */
function hydrateAcceptance(source: TaskItem | null): void {
  const stored = parseSubmissionAcceptance(source?.extras ?? null)
  if (!stored) {
    resetAcceptance()
    return
  }
  acceptance.modes = [...stored.modes]
  acceptance.allowed_exts = [...stored.allowed_exts]
  acceptance.ai_precheck = stored.ai_precheck
}

watch(() => props.task, (value) => hydrateAcceptance(value ?? null), { immediate: true })

/** 同活动前置任务（仅活动入口下加载；加载失败不阻塞发布） */
const dependencyOptions = ref<TaskItem[]>([])
const selectedDependencies = ref<number[]>([])
const dependencyLoading = ref(false)
const dependencyError = ref('')

/** 任务内容区块（与详情页共用同一字段语义） */
const contentModel = computed(() => ({
  description: form.description.trim() === '' ? null : form.description,
  start_time: form.start_time,
  deadline: form.deadline,
  location: form.location.trim() === '' ? null : form.location,
  quota: form.quota
}))

type ContentField = 'description' | 'start_time' | 'deadline' | 'location' | 'quota'

function onContentField(key: ContentField, value: string | number | null): void {
  if (key === 'quota') {
    form.quota = typeof value === 'number' && Number.isFinite(value) ? value : null
    return
  }
  const text = typeof value === 'string' ? value : ''
  if (key === 'description') form.description = text
  else if (key === 'location') form.location = text
  else if (key === 'start_time') form.start_time = text !== '' ? text : null
  else if (key === 'deadline') form.deadline = text !== '' ? text : null
}

/** 活动入口下加载同活动第一层任务，作为可多选前置 */
async function loadDependencyOptions(): Promise<void> {
  selectedDependencies.value = []
  dependencyOptions.value = []
  dependencyError.value = ''
  const activityId = props.activityId
  if (activityId === null || !Number.isFinite(activityId) || activityId <= 0) return
  dependencyLoading.value = true
  try {
    const result = await listTasks({ activity_id: activityId })
    dependencyOptions.value = result.items.filter(
      (item) => item.parent_id === null && item.activity_id === activityId && item.status !== 'cancelled'
    )
  } catch {
    dependencyError.value = '无法加载同活动任务，本次可不设置前置依赖继续发布。'
  } finally {
    dependencyLoading.value = false
  }
}

watch(() => props.activityId, () => void loadDependencyOptions())

onMounted(() => {
  void loadDependencyOptions()
})

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
    if (key === ACCEPTANCE_EXTRA_KEY) {
      ElMessage.error(`扩展项键名「${ACCEPTANCE_EXTRA_KEY}」为成果要求保留键，请改用其它键名`)
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
  selectedDependencies.value = []
  similarItem.value = null
  lastSimilarQuery = ''
  resetAcceptance()
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

  if (acceptance.modes.length === 0) {
    ElMessage.error('请至少选择一种成果提交方式')
    return
  }
  if (fileModeEnabled.value && acceptance.allowed_exts.length === 0) {
    ElMessage.error('选择文件提交时，请至少选择一种允许的文件类型')
    return
  }
  extrasPayload[ACCEPTANCE_EXTRA_KEY] = {
    modes: [...acceptance.modes],
    allowed_exts: [...acceptance.allowed_exts],
    ai_precheck: acceptance.ai_precheck
  }

  if (form.start_time && form.deadline && form.deadline < form.start_time) {
    ElMessage.error('截止时间不能早于开始时间')
    return
  }

  // 手动表单的「要求」按 C-DATA@1 映射表并入 description（顺序：描述 → 要求）
  const descriptionParts = [form.description.trim(), form.requirements.trim()].filter(
    (part) => part !== ''
  )

  const payload: TaskCreatePayload = {
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
  }
  // 仅活动入口进入时携带归属；独立任务不发送该键（C-FE-ACTIVITY-PUBLISH@1）
  if (props.activityId !== null && Number.isFinite(props.activityId) && props.activityId > 0) {
    payload.activity_id = props.activityId
  }
  // 多前置（`C-TASK-GRAPH@1`）：只在确有选择时发送，避免空数组覆盖既有依赖
  if (selectedDependencies.value.length > 0) {
    payload.depends_on_ids = [...selectedDependencies.value]
  }

  submitting.value = true
  try {
    const task = await createTask(payload)
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

      <TaskContentSections
        :model="contentModel"
        editable
        @update:field="onContentField"
      />

      <el-form-item v-if="props.activityId !== null" label="前置依赖（可多选）">
        <div class="manual-form__dependencies">
          <el-select
            v-model="selectedDependencies"
            multiple
            collapse-tags
            collapse-tags-tooltip
            :loading="dependencyLoading"
            placeholder="选择同活动任务；全部完成后当前任务才可报名"
            class="manual-form__dependency-select"
          >
            <el-option
              v-for="item in dependencyOptions"
              :key="item.id"
              :label="item.title"
              :value="item.id"
            />
          </el-select>
          <p class="manual-form__tip">
            可多选；前置未全部完成时报名返回「前置任务尚未完成」。跨活动任务不会出现在这里。
          </p>
          <p v-if="dependencyError" class="manual-form__dependency-error">{{ dependencyError }}</p>
        </div>
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

      <el-form-item label="成果要求">
        <div class="manual-form__acceptance">
          <div class="manual-form__acceptance-row">
            <span class="manual-form__acceptance-label">提交方式（可多选）</span>
            <el-checkbox-group v-model="acceptance.modes" class="manual-form__checks">
              <el-checkbox v-for="mode in SUBMISSION_MODES" :key="mode" :value="mode">
                {{ SUBMISSION_MODE_LABELS[mode] }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <div class="manual-form__acceptance-row">
            <span class="manual-form__acceptance-label">允许文件类型</span>
            <el-checkbox-group
              v-model="acceptance.allowed_exts"
              :disabled="!fileModeEnabled"
              class="manual-form__checks"
            >
              <el-checkbox v-for="ext in SUBMISSION_FILE_EXTS" :key="ext" :value="ext">
                {{ submissionFileLabel(ext) }}
              </el-checkbox>
            </el-checkbox-group>
          </div>
          <p class="manual-form__tip">
            未勾选「文件上传」时忽略文件类型；学生只能按所选方式提交成果。
          </p>
          <div class="manual-form__acceptance-row">
            <span class="manual-form__acceptance-label">AI 成果预审</span>
            <el-switch v-model="acceptance.ai_precheck" />
            <span class="manual-form__tip">开启后学生提交会自动运行预审；预审不等于人工验收。</span>
          </div>
        </div>
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
  border-radius: var(--app-radius-sm);
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

/* 日期选择器始终占满表单列宽：移动端点击区域更大，也不会把后面的字段挤出视口 */
.manual-form__picker {
  width: 100%;
  min-width: 0;
}

.manual-form__extras {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.manual-form__dependencies {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: 100%;
}

.manual-form__acceptance {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.manual-form__acceptance-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 16px;
}

.manual-form__acceptance-label {
  min-width: 112px;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-secondary);
}

.manual-form__checks {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
}

.manual-form__checks :deep(.el-checkbox) {
  margin-right: 0;
}

.manual-form__dependency-select {
  width: 100%;
}

.manual-form__dependency-error {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  color: var(--el-color-danger);
  word-break: break-word;
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
  border-top: 1px solid var(--app-border);
}

.manual-form__tip {
  font-size: 13px;
  color: var(--app-text-secondary);
}

@media (max-width: 768px) {
  /* 移动端单栏：日期/时间控件宽度已在上方统一 100% */
  .manual-form__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .manual-form__extra-row {
    flex-direction: column;
    align-items: stretch;
  }

  .manual-form__extra-row .el-button {
    align-self: flex-start;
  }

  .manual-form__switches {
    flex-wrap: wrap;
    gap: 8px 16px;
  }

  .manual-form__acceptance-row {
    flex-direction: column;
    align-items: flex-start;
  }

  .manual-form__acceptance-label {
    min-width: 0;
  }

  .manual-form__checks :deep(.el-checkbox) {
    min-height: var(--app-touch);
  }

  .manual-form__footer {
    flex-direction: column;
    align-items: stretch;
  }

  .manual-form__footer .el-button {
    width: 100%;
  }
}
</style>