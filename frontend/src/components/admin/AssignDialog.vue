<script lang="ts">
/**
 * 指派弹窗（计划 T6：发布者后台指派）。
 *
 * 后端**未提供**用户列表接口（`C-AUTH@1` 只有 login/me），因此这里提供两种指派方式：
 * 1. 从「已知用户」下拉选择（候选来自任务列表里出现过的发布者/负责人）；
 * 2. 手动输入用户 ID（数字），并在界面中显式说明原因。
 */
export interface AssignCandidate {
  id: number
  name: string
}
</script>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

import type { TaskItem } from '../../types/models'

const props = withDefaults(
  defineProps<{
    visible: boolean
    task?: TaskItem | null
    candidates?: AssignCandidate[]
    loading?: boolean
  }>(),
  { task: null, candidates: () => [], loading: false }
)

const emit = defineEmits<{
  (e: 'update:visible', value: boolean): void
  (e: 'confirm', userId: number): void
}>()

type AssignMode = 'known' | 'manual'

const formRef = ref<FormInstance>()
const mode = ref<AssignMode>('known')
const form = reactive<{ userId: number | undefined }>({ userId: undefined })

const rules: FormRules = {
  userId: [
    { required: true, message: '请选择或输入用户 ID', trigger: 'change' },
    {
      validator: (_rule, value, callback) => {
        const parsed = Number(value)
        if (Number.isInteger(parsed) && parsed >= 1) callback()
        else callback(new Error('用户 ID 必须为不小于 1 的整数'))
      },
      trigger: 'change'
    }
  ]
}

// 每次打开弹窗重置表单与校验状态
watch(
  () => props.visible,
  (visible) => {
    if (!visible) return
    mode.value = 'known'
    form.userId = undefined
    formRef.value?.clearValidate()
  }
)

// 切换指派方式时清空上一次的选择，避免沿用无效 ID
watch(mode, () => {
  form.userId = undefined
  formRef.value?.clearValidate()
})

function close(): void {
  emit('update:visible', false)
}

async function submit(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  const userId = Number(form.userId)
  if (!Number.isInteger(userId) || userId < 1) return
  emit('confirm', userId)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    title="指派负责人"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="emit('update:visible', $event)"
    @closed="formRef?.clearValidate()"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="assign-form">
      <el-form-item label="任务">
        <span class="task-name">{{ task?.title ?? '—' }}</span>
        <el-tag v-if="task" size="small" effect="plain" class="task-id">#{{ task.id }}</el-tag>
      </el-form-item>

      <el-form-item label="指派方式">
        <el-radio-group v-model="mode" class="mode-switch">
          <el-radio-button value="known">从已知用户选择</el-radio-button>
          <el-radio-button value="manual">手动输入用户 ID</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item v-if="mode === 'known'" label="目标用户" prop="userId">
        <el-select
          v-model="form.userId"
          placeholder="请选择要指派的用户"
          filterable
          clearable
          class="user-select"
        >
          <el-option
            v-for="candidate in candidates"
            :key="candidate.id"
            :label="`${candidate.name}（ID ${candidate.id}）`"
            :value="candidate.id"
          />
        </el-select>
        <p v-if="candidates.length === 0" class="field-hint">
          当前任务列表中没有可参考的用户，请切换到「手动输入用户 ID」。
        </p>
      </el-form-item>

      <el-form-item v-else label="用户 ID" prop="userId">
        <el-input-number
          v-model="form.userId"
          :min="1"
          :step="1"
          :precision="0"
          placeholder="请输入用户 ID"
          class="manual-input"
        />
      </el-form-item>

      <el-alert type="info" :closable="false" show-icon class="api-hint">
        后端未提供用户列表接口（仅 login / me）：下拉候选来自任务中出现过的用户；若目标用户不在列表中，请直接填写其用户 ID（正整数）。
      </el-alert>
    </el-form>

    <template #footer>
      <el-button :disabled="loading" @click="close">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submit">确认指派</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.assign-form {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.assign-form :deep(.el-form-item__content) {
  flex-wrap: wrap;
}

.task-name {
  margin-right: 6px;
  font-weight: 500;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.task-id {
  color: var(--el-text-color-secondary);
}

.mode-switch {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.mode-switch :deep(.el-radio-button__inner) {
  white-space: normal;
}

.user-select,
.manual-input {
  width: 100%;
}

.field-hint {
  margin: 4px 0 0;
  font-size: 13px;
  color: var(--el-color-warning);
  line-height: 1.5;
}

.api-hint {
  margin-top: 4px;
}
</style>