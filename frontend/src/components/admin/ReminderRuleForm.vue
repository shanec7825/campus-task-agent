<script lang="ts">
/**
 * 催办规则表单（计划 T6 实现要点 3 / R5-AC2~AC4）。
 *
 * 输出 `{days_before:number, day_of:boolean, on_overdue:boolean}`，提交前用 `el-form`
 * 校验 `days_before >= 0`；校验不通过不 emit `submit`。
 */
export const DEFAULT_REMINDER_RULE = { days_before: 1, day_of: true, on_overdue: true }
</script>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import type { FormInstance, FormRules } from 'element-plus'

import type { ReminderRule } from '../../types/models'

const props = withDefaults(
  defineProps<{ modelValue: ReminderRule; loading?: boolean }>(),
  { loading: false }
)

const emit = defineEmits<{
  (e: 'update:modelValue', value: ReminderRule): void
  (e: 'submit', value: ReminderRule): void
}>()

const formRef = ref<FormInstance>()
const form = reactive<ReminderRule>({
  days_before: props.modelValue?.days_before ?? DEFAULT_REMINDER_RULE.days_before,
  day_of: props.modelValue?.day_of ?? DEFAULT_REMINDER_RULE.day_of,
  on_overdue: props.modelValue?.on_overdue ?? DEFAULT_REMINDER_RULE.on_overdue
})

// 父组件重置规则（切换任务 / 重新打开弹窗）时同步到表单
watch(
  () => props.modelValue,
  (value) => {
    form.days_before = value?.days_before ?? DEFAULT_REMINDER_RULE.days_before
    form.day_of = value?.day_of ?? DEFAULT_REMINDER_RULE.day_of
    form.on_overdue = value?.on_overdue ?? DEFAULT_REMINDER_RULE.on_overdue
  },
  { deep: true }
)

// 表单变更即回写父组件，保证 v-model 行为完整
watch(
  form,
  () => {
    emit('update:modelValue', { ...form })
  },
  { deep: true }
)

const rules: FormRules = {
  days_before: [
    { required: true, message: '请填写截止前提醒天数', trigger: 'change' },
    {
      validator: (_rule, value, callback) => {
        const parsed = Number(value)
        if (Number.isInteger(parsed) && parsed >= 0) callback()
        else callback(new Error('截止前提醒天数必须为不小于 0 的整数'))
      },
      trigger: 'change'
    }
  ]
}

async function submit(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  emit('submit', { ...form })
}
</script>

<template>
  <el-form ref="formRef" :model="form" :rules="rules" label-width="120px" class="reminder-form">
    <el-form-item label="提前提醒天数" prop="days_before">
      <el-input-number v-model="form.days_before" :min="0" :max="365" :step="1" :precision="0" />
      <span class="field-hint">距截止时间超过 24 小时且剩余天数 ≤ 该值时提醒（warning）</span>
    </el-form-item>

    <el-form-item label="截止当天提醒">
      <el-switch v-model="form.day_of" active-text="开启" inactive-text="关闭" />
      <span class="field-hint">剩余 0~24 小时时提醒（urgent）</span>
    </el-form-item>

    <el-form-item label="逾期提醒">
      <el-switch v-model="form.on_overdue" active-text="开启" inactive-text="关闭" />
      <span class="field-hint">已过截止时间时提醒负责人与发布者，并触发一次逾期扣分（overdue）</span>
    </el-form-item>

    <el-form-item>
      <el-button type="primary" :loading="props.loading" @click="submit">保存催办规则</el-button>
    </el-form-item>
  </el-form>
</template>

<style scoped>
.reminder-form {
  padding-top: 4px;
}

.field-hint {
  margin-left: 12px;
  font-size: 13px;
  color: #909399;
  line-height: 1.6;
}
</style>