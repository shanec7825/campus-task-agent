<script setup lang="ts">
/**
 * 任务内容区块（契约 `C-FE-PUBLISH-CONTENT@1`）。
 *
 * 发布页（`ManualForm`）与任务详情（`TaskDetail`）共用同一字段语义与顺序：
 * 描述 → 工作区间（开始 / 截止）→ 地点 → 需求人数。
 *
 * - `editable=false`：只读展示，缺失值明确显示「未设置」，不补默认值；
 * - `editable=true`：输出 `update:field` 事件，由父级表单写回，组件不持有业务状态；
 * - 标题由页面各自承担（发布页是输入项，详情页是 `h1`），避免重复标题层级。
 */
import { computed, ref } from 'vue'

const props = withDefaults(
  defineProps<{
    model: {
      description: string | null
      start_time: string | null
      deadline: string | null
      location: string | null
      quota: number | null
    }
    editable?: boolean
  }>(),
  { editable: false }
)

/** 只读态保留长描述折叠，避免详情首屏被长文本占满（审查 S8） */
const descriptionExpanded = ref(false)
const descriptionText = computed<string>(() =>
  props.model.description && props.model.description.trim() !== ''
    ? props.model.description
    : '暂无任务描述'
)
const descriptionIsLong = computed<boolean>(
  () => descriptionText.value.length > 240 || descriptionText.value.split('\n').length > 8
)

type ContentField = 'description' | 'start_time' | 'deadline' | 'location' | 'quota'

const emit = defineEmits<{
  (e: 'update:field', key: ContentField, value: string | number | null): void
}>()

function textValue(value: string | null): string {
  return value && value.trim() !== '' ? value : ''
}

function onText(key: ContentField, value: unknown): void {
  emit('update:field', key, typeof value === 'string' && value !== '' ? value : null)
}

function onQuota(value: number | undefined): void {
  emit('update:field', 'quota', typeof value === 'number' && Number.isFinite(value) ? value : null)
}

function display(value: string | null): string {
  if (!value) return '未设置'
  return value.slice(0, 16).replace('T', ' ')
}
</script>

<template>
  <section class="task-content" :class="{ 'task-content--readonly': !editable }">
    <template v-if="editable">
      <el-form-item label="任务描述">
        <el-input
          :model-value="textValue(model.description)"
          type="textarea"
          :rows="4"
          maxlength="2000"
          show-word-limit
          placeholder="任务背景、内容、注意事项…"
          @update:model-value="onText('description', $event)"
        />
      </el-form-item>

      <div class="task-content__grid">
        <el-form-item label="开始时间">
          <el-date-picker
            :model-value="model.start_time ?? ''"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择开始时间"
            class="task-content__picker"
            @update:model-value="onText('start_time', $event)"
          />
        </el-form-item>

        <el-form-item label="截止时间">
          <el-date-picker
            :model-value="model.deadline ?? ''"
            type="datetime"
            value-format="YYYY-MM-DD HH:mm:ss"
            placeholder="选择截止时间"
            class="task-content__picker"
            @update:model-value="onText('deadline', $event)"
          />
        </el-form-item>

        <el-form-item label="地点">
          <el-input
            :model-value="textValue(model.location)"
            maxlength="60"
            placeholder="例如：教三 302"
            @update:model-value="onText('location', $event)"
          />
        </el-form-item>

        <el-form-item label="需求人数">
          <el-input-number
            :model-value="model.quota ?? undefined"
            :min="1"
            :max="999"
            controls-position="right"
            placeholder="可选"
            @change="onQuota"
          />
        </el-form-item>
      </div>
    </template>

    <template v-else>
      <div class="task-content__block">
        <h2 class="task-content__heading">任务要求</h2>
        <p
          class="task-content__description"
          :class="{ 'is-collapsed': descriptionIsLong && !descriptionExpanded }"
        >
          {{ descriptionText }}
        </p>
        <el-button
          v-if="descriptionIsLong"
          text
          type="primary"
          size="small"
          class="task-content__toggle"
          @click="descriptionExpanded = !descriptionExpanded"
        >
          {{ descriptionExpanded ? '收起' : '展开全部' }}
        </el-button>
      </div>

      <dl class="task-content__facts">
        <div class="task-content__fact">
          <dt>开始时间</dt>
          <dd>{{ display(model.start_time) }}</dd>
        </div>
        <div class="task-content__fact">
          <dt>截止时间</dt>
          <dd>{{ display(model.deadline) }}</dd>
        </div>
        <div class="task-content__fact">
          <dt>地点</dt>
          <dd>{{ model.location || '未设置' }}</dd>
        </div>
        <div class="task-content__fact">
          <dt>需求人数</dt>
          <dd>{{ model.quota === null ? '不限' : `${model.quota} 人` }}</dd>
        </div>
      </dl>
    </template>
  </section>
</template>

<style scoped>
.task-content {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.task-content__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.task-content__picker {
  width: 100%;
  min-width: 0;
}

.task-content__block {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.task-content__heading {
  margin: 0;
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  color: var(--app-text-muted);
}

.task-content__description {
  margin: 0;
  font-size: var(--app-font-body);
  color: var(--app-text-secondary);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.task-content__description.is-collapsed {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 6;
  overflow: hidden;
  white-space: normal;
}

.task-content__toggle {
  align-self: flex-start;
  margin-top: 2px;
  padding: 0;
}

.task-content__facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
  margin: 12px 0 0;
}

.task-content__fact {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.task-content__fact dt {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.task-content__fact dd {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

@media (max-width: 768px) {
  .task-content__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .task-content__facts {
    grid-template-columns: 1fr;
  }
}
</style>