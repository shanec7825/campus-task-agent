<script setup lang="ts">
/**
 * 拆解建议卡片（T7 / 需求 R2.4-AC1~AC3）
 *
 * 一、编辑能力（发布前）：
 * - 可改 `title` / `description` / `sop_guide` / `quota` / 依赖；
 * - 可删除整条建议（删除后由父组件从草稿移除，该条不会创建）；
 * - 依赖只允许选择**前面**的兄弟项（避免自依赖与环）。
 *
 * 二、批量串行发布（`publishAll`，由 AiPanel 通过 ref 调用）：
 * 1. 主任务已由 AiPanel 创建并拿到 `parentId`；
 * 2. 按数组顺序 **串行 await** 创建子任务（`parent_id = parentId`）；
 * 3. `depends_on` 是建议数组下标，创建前映射为「已创建子任务的真实 id」；
 *    指向尚未创建 / 已被删除 / 已被置空的项 → `null`；
 * 4. 任一步失败**立即停止**后续创建，返回已创建数量与错误信息，
 *    由 AiPanel 提示「已创建 N 个」（禁止吞掉失败继续创建）。
 *
 * 三、勾选制（第三轮 B11）：
 * - 卡片顶部复选框「将 N 个子任务随主任务一起发布」**默认不勾选**；
 * - 勾选状态通过 `v-model:include` 交给 AiPanel，只有勾选时发布才调用 `publishAll`；
 * - 拆解建议变化（`tasks` 引用更新）时自动重置为未勾选，避免「上一轮的勾选」影响新建议。
 *
 * 注意：草稿仍然是 store 的唯一写入口，本组件不直接改 state。
 */
import { computed, ref, watch } from 'vue'

import { ApiError } from '../../api/client'
import { createTask } from '../../api/tasks'
import { useDraftStore } from '../../stores/draft'
import type { SubTaskSuggestion, TaskCreatePayload } from '../../types/models'

/** 批量发布结果（AiPanel 按同名结构消费） */
interface BatchPublishResult {
  created: number
  error: string | null
}

const props = withDefaults(
  defineProps<{
    tasks: SubTaskSuggestion[]
    disabled?: boolean
    /** 是否随主任务一起发布子任务（默认不勾选，B11） */
    include?: boolean
  }>(),
  { disabled: false, include: false }
)

const emit = defineEmits<{
  (e: 'update', index: number, patch: Partial<SubTaskSuggestion>): void
  (e: 'remove', index: number): void
  (e: 'update:include', value: boolean): void
}>()

/**
 * 复选框勾选变化：受控模式（`:model-value="include"` + `update:include`），
 * 状态真相在父组件 AiPanel（默认 false），子组件只负责上报。
 */
function onIncludeChange(value: string | number | boolean): void {
  emit('update:include', value === true)
}

/**
 * 拆解建议变化时重置勾选：新一批建议默认不随主任务发布，
 * 防止用户上一轮勾选后被「静默」应用到新建议上。
 */
watch(
  () => props.tasks,
  () => {
    if (props.include) emit('update:include', false)
  }
)

const draft = useDraftStore()

/** 本轮已创建的子任务 id（用于界面提示与失败定位） */
const publishedIds = ref<number[]>([])
const publishedCount = computed<number>(() => publishedIds.value.length)

function errorMessage(cause: unknown): string {
  if (cause instanceof ApiError) return `${cause.message}（code=${cause.code}）`
  if (cause instanceof Error) return cause.message
  return '未知错误'
}

/** 依赖下拉的当前值：null → ''，其余转字符串（el-option 的 value 统一为 string） */
function dependsValue(task: SubTaskSuggestion): string {
  return task.depends_on === null || task.depends_on === undefined ? '' : String(task.depends_on)
}

/** 依赖选项：只允许指向前面的兄弟项 */
function dependsOptions(index: number): Array<{ value: string; label: string }> {
  return props.tasks.slice(0, index).map((task, prevIndex) => ({
    value: String(prevIndex),
    label: `${prevIndex + 1}. ${task.title || '未命名子任务'}`
  }))
}

function onDependsChange(index: number, value: string): void {
  if (value === '') {
    emit('update', index, { depends_on: null })
    return
  }
  const parsed = Number(value)
  emit('update', index, { depends_on: Number.isFinite(parsed) ? parsed : null })
}

function onTitleChange(index: number, value: string): void {
  emit('update', index, { title: value })
}

function onDescriptionChange(index: number, value: string): void {
  emit('update', index, { description: value })
}

function onSopChange(index: number, value: string): void {
  emit('update', index, { sop_guide: value })
}

function onQuotaChange(index: number, value: number | undefined): void {
  emit('update', index, { quota: typeof value === 'number' && Number.isFinite(value) ? value : null })
}

/**
 * 串行创建全部子任务。
 *
 * @param parentId 主任务 id（由 AiPanel 先创建主任务后传入）
 * @returns 已成功创建的数量 + 首个错误信息（全部成功时 error 为 null）
 */
async function publishAll(parentId: number): Promise<BatchPublishResult> {
  publishedIds.value = []
  /** 建议数组下标 → 已创建子任务的真实 id（depends_on 映射依据） */
  const createdIds = new Map<number, number>()
  let created = 0

  // 以 store 当前数组为准：父组件删除的建议不会出现在这里（R2.4-AC3）
  const total = draft.suggestedSubTasks.length

  for (let index = 0; index < total; index += 1) {
    const suggestion = draft.suggestedSubTasks[index]
    if (!suggestion) break

    // depends_on 映射：仅在“前置建议已成功创建”时取真实 id，否则置 null
    const dependsIndex = suggestion.depends_on
    const dependsOnId =
      dependsIndex === null || dependsIndex === undefined
        ? null
        : createdIds.get(dependsIndex) ?? null

    let payload: TaskCreatePayload
    try {
      payload = draft.toSubTaskPayload(index, parentId)
    } catch (cause) {
      // 建议被并发删除等极端情况：停止后续，保留已创建结果
      return { created, error: errorMessage(cause) }
    }
    payload.depends_on = dependsOnId

    try {
      const task = await createTask(payload)
      createdIds.set(index, task.id)
      publishedIds.value = [...publishedIds.value, task.id]
      created += 1
    } catch (cause) {
      // 任一步失败：停止后续创建（不得继续创建依赖混乱的子任务）
      return { created, error: errorMessage(cause) }
    }
  }

  return { created, error: null }
}

defineExpose({ publishAll })
</script>

<template>
  <section class="subtask-card">
    <header class="subtask-card__header">
      <div class="subtask-card__heading">
        <h4 class="subtask-card__title">拆解建议（{{ tasks.length }} 个子任务）</h4>
        <p class="subtask-card__hint">
          可编辑内容与依赖，删除的条目不会创建；确认发布时按顺序<b>串行</b>创建，依赖会映射为真实任务 id。
        </p>
      </div>
      <el-tag v-if="publishedCount > 0" type="success" effect="plain" size="small">
        已创建 {{ publishedCount }} 个
      </el-tag>
    </header>

    <!-- 勾选制（B11）：受控，默认不勾选，只有勾选后发布才创建子任务 -->
    <el-checkbox
      :model-value="include"
      :disabled="disabled"
      class="subtask-card__include"
      @change="onIncludeChange"
    >
      将 {{ tasks.length }} 个子任务随主任务一起发布
    </el-checkbox>

    <el-empty v-if="tasks.length === 0" description="暂无拆解建议" :image-size="48" />

    <article v-for="(task, index) in tasks" :key="index" class="subtask-card__item">
      <header class="subtask-card__item-header">
        <span class="subtask-card__index">子任务 {{ index + 1 }}</span>
        <el-button
          link
          type="danger"
          size="small"
          :disabled="disabled"
          @click="emit('remove', index)"
        >
          删除
        </el-button>
      </header>

      <div class="subtask-card__field">
        <span class="subtask-card__label">标题</span>
        <el-input
          :model-value="task.title"
          size="small"
          maxlength="80"
          :disabled="disabled"
          placeholder="子任务标题"
          @change="onTitleChange(index, $event)"
        />
      </div>

      <div class="subtask-card__field">
        <span class="subtask-card__label">说明</span>
        <el-input
          :model-value="task.description"
          type="textarea"
          :rows="2"
          size="small"
          maxlength="500"
          :disabled="disabled"
          placeholder="子任务说明"
          @change="onDescriptionChange(index, $event)"
        />
      </div>

      <div class="subtask-card__field">
        <span class="subtask-card__label">实施步骤</span>
        <el-input
          :model-value="task.sop_guide"
          type="textarea"
          :rows="3"
          size="small"
          maxlength="1000"
          :disabled="disabled"
          placeholder="每行一步，建议 3~6 步"
          @change="onSopChange(index, $event)"
        />
      </div>

      <div class="subtask-card__row">
        <div class="subtask-card__field">
          <span class="subtask-card__label">名额</span>
          <el-input-number
            :model-value="task.quota ?? undefined"
            :min="1"
            size="small"
            controls-position="right"
            :disabled="disabled"
            @change="onQuotaChange(index, $event)"
          />
        </div>

        <div class="subtask-card__field">
          <span class="subtask-card__label">前置依赖</span>
          <el-select
            :model-value="dependsValue(task)"
            size="small"
            :disabled="disabled || index === 0"
            placeholder="无依赖"
            @change="onDependsChange(index, $event)"
          >
            <el-option label="无依赖" value="" />
            <el-option
              v-for="option in dependsOptions(index)"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </el-select>
        </div>
      </div>

      <p class="subtask-card__depends">
        {{ task.depends_on === null || task.depends_on === undefined
          ? '无前置依赖'
          : `依赖第 ${task.depends_on + 1} 个子任务完成后才能认领` }}
      </p>
    </article>
  </section>
</template>

<style scoped>
.subtask-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-bg-color);
}

.subtask-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.subtask-card__heading {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.subtask-card__title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.subtask-card__hint {
  margin: 0;
  font-size: 13px;
  line-height: 1.5;
  color: var(--el-text-color-secondary);
}

/* 勾选制复选框：与卡片内容左对齐，突出「默认不勾选」的主操作 */
.subtask-card__include {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--el-fill-color-lighter);
  font-weight: 600;
}

.subtask-card__item {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-light);
}

.subtask-card__item-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.subtask-card__index {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-color-primary);
}

.subtask-card__field {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.subtask-card__label {
  flex: none;
  width: 64px;
  padding-top: 4px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.subtask-card__row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.subtask-card__depends {
  margin: 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}
</style>