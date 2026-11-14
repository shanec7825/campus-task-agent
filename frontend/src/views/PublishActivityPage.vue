<script setup lang="ts">
/**
 * 发布中心：活动 + 多任务一次原子发布（`C-BATCH-PUBLISH@1`）。
 *
 * - 仅组织 admin/collaborator 进入（路由 `requiresManager`）；服务端仍会再次校验组织发布权。
 * - 预览复用 `ActivityInfoSection`，与活动详情使用同一组字段与顺序。
 * - 任务行的依赖与父任务只能引用本批次 `key`（跨批次引用走单任务页）。
 * - 任一任务校验失败不提交；失败展示服务端 `msg` 且不跳转。
 */
import { computed, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { publishActivityBatch } from '../api/activities'
import { ApiError } from '../api/client'
import ActivityInfoSection from '../components/activity/ActivityInfoSection.vue'
import { useUserStore } from '../stores/user'
import type { Activity, ActivityBatchTaskDraft } from '../types/models'

/** 页面内的任务编辑行；`key` 由前端自动生成，`uid` 仅用于稳定渲染 */
interface TaskRowDraft {
  uid: number
  key: string
  title: string
  deadline: string
  quota: number | null
  claim_type: 'open' | 'assign'
  sop_guide: string
  credit_reward: number
  depends_on_keys: string[]
  parent_key: string | null
}

const router = useRouter()
const userStore = useUserStore()

const saving = ref(false)
const form = reactive({
  title: '',
  description: '',
  location: '',
  start_time: '',
  deadline: '',
  org_id: null as number | null
})

const taskRows = ref<TaskRowDraft[]>([])
let nextUid = 0

/** 只列出本人有发布权的组织；成员组织不冒充可选 */
const publishableOrgs = computed(() =>
  userStore.orgs.filter(
    (org) =>
      org.status === 'active' && (org.role === 'admin' || org.role === 'collaborator')
  )
)

const selectedOrgName = computed<string>(() => {
  if (form.org_id === null) return ''
  return publishableOrgs.value.find((org) => org.org_id === form.org_id)?.name ?? ''
})

const submitLabel = computed<string>(() =>
  taskRows.value.length > 0 ? '发布活动与任务' : '发布活动'
)

/** 预览对象：字段来源与详情一致，任务数量取当前草稿行数 */
const preview = computed<Activity>(() => ({
  id: 0,
  title: form.title.trim() || '活动名称预览',
  description: form.description.trim() || null,
  location: form.location.trim() || null,
  start_time: form.start_time || null,
  deadline: form.deadline || null,
  owner_id: userStore.user?.id ?? 0,
  owner_name: userStore.displayName || '我',
  org: selectedOrgName.value || null,
  org_id: form.org_id,
  status: 'published',
  created_at: '',
  progress: {
    total_tasks: taskRows.value.length,
    completed_tasks: 0,
    cancelled_tasks: 0,
    subtask_total: taskRows.value.filter((row) => normalizeParentKey(row.parent_key) !== null)
      .length,
    subtask_completed: 0,
    percent: 0,
    awaiting_owner_confirm: false
  }
}))

/**
 * 父任务字段统一归一：`el-select` 清空（未设 value-on-clear）会给出 `undefined`，
 * 其他来源也可能给出空串；除有效 key 外一律视为 `null`。
 */
function normalizeParentKey(value: string | null | undefined): string | null {
  return typeof value === 'string' && value !== '' ? value : null
}

/** 层级：顶层任务 0，子任务 1；依赖只在同层之间可选 */
function taskDepth(row: TaskRowDraft): 0 | 1 {
  return normalizeParentKey(row.parent_key) === null ? 0 : 1
}

function onParentChange(row: TaskRowDraft, value: unknown): void {
  row.parent_key = normalizeParentKey(typeof value === 'string' ? value : null)
}

function clearParent(row: TaskRowDraft): void {
  row.parent_key = null
}

/** 批内 key 自动生成：取未被占用的最小 `tN`，删除行后不重排既有 key */
function nextTaskKey(): string {
  const used = new Set(taskRows.value.map((row) => row.key))
  let index = 0
  while (used.has(`t${index}`)) index += 1
  return `t${index}`
}

function addTaskRow(): void {
  taskRows.value.push({
    uid: nextUid++,
    key: nextTaskKey(),
    title: '',
    deadline: '',
    quota: null,
    claim_type: 'open',
    sop_guide: '',
    credit_reward: 20,
    depends_on_keys: [],
    parent_key: null
  })
}

/** 删除行时同步清理其他行对它的引用，避免把已删除的 key 提交上去 */
function removeTaskRow(uid: number): void {
  const row = taskRows.value.find((item) => item.uid === uid)
  if (!row) return
  taskRows.value = taskRows.value.filter((item) => item.uid !== uid)
  for (const other of taskRows.value) {
    other.depends_on_keys = other.depends_on_keys.filter((key) => key !== row.key)
    if (normalizeParentKey(other.parent_key) === row.key) other.parent_key = null
  }
}

/** 行标签：`key · 标题`，标题为空时只显示 key */
function taskLabel(row: TaskRowDraft): string {
  const title = row.title.trim()
  return title ? `${row.key} · ${title}` : row.key
}

/** 依赖候选只含同层级任务：顶层只连顶层，子任务只连子任务 */
function dependencyOptions(row: TaskRowDraft): TaskRowDraft[] {
  const depth = taskDepth(row)
  return taskRows.value.filter((item) => item.uid !== row.uid && taskDepth(item) === depth)
}

/** 只有顶层任务（自身无父任务）才能被选为父任务；V1 最多两层 */
function parentOptions(row: TaskRowDraft): TaskRowDraft[] {
  return taskRows.value.filter(
    (item) => item.uid !== row.uid && normalizeParentKey(item.parent_key) === null
  )
}

/** 已被其他行选为父任务的行不能再挂到别的父任务下，否则会突破两层上限 */
function hasChildren(row: TaskRowDraft): boolean {
  return taskRows.value.some((item) => normalizeParentKey(item.parent_key) === row.key)
}

function onQuotaChange(row: TaskRowDraft, value: number | null | undefined): void {
  row.quota = typeof value === 'number' && Number.isFinite(value) ? value : null
}

function onCreditChange(row: TaskRowDraft, value: number | null | undefined): void {
  row.credit_reward = typeof value === 'number' && Number.isFinite(value) ? value : 0
}

/** 依赖成环检测：返回环路上的 key（首尾相同），无环返回 null */
function findDependencyCycle(): string[] | null {
  const byKey = new Map(taskRows.value.map((row) => [row.key, row]))
  const state = new Map<string, number>()
  const path: string[] = []

  const visit = (key: string): string[] | null => {
    const row = byKey.get(key)
    if (!row) return null
    const current = state.get(key) ?? 0
    if (current === 1) {
      const start = path.indexOf(key)
      return [...path.slice(start), key]
    }
    if (current === 2) return null
    state.set(key, 1)
    path.push(key)
    for (const dependency of row.depends_on_keys) {
      const cycle = visit(dependency)
      if (cycle) return cycle
    }
    path.pop()
    state.set(key, 2)
    return null
  }

  for (const row of taskRows.value) {
    const cycle = visit(row.key)
    if (cycle) return cycle
  }
  return null
}

/** 任务区前端校验：返回第一条错误文案，全部通过返回 null */
function validateTasks(): string | null {
  for (const row of taskRows.value) {
    const title = row.title.trim()
    if (!title) return `任务「${row.key}」缺少标题`
    if (form.start_time && row.deadline && row.deadline < form.start_time) {
      return `任务「${title}」的截止时间不能早于活动开始时间`
    }
  }


  for (const row of taskRows.value) {
    const depth = taskDepth(row)
    for (const key of row.depends_on_keys) {
      if (key === row.key) return `任务「${row.title.trim()}」不能依赖自己`
      const candidate = taskRows.value.find((item) => item.key === key)
      if (!candidate) {
        return `任务「${row.title.trim()}」的前置任务已不存在，请重新选择`
      }
      if (taskDepth(candidate) !== depth) {
        return `任务「${row.title.trim()}」只能依赖同层级任务，「${taskLabel(candidate)}」层级不同，请重新选择`
      }
    }
    const parentKey = normalizeParentKey(row.parent_key)
    if (parentKey === null) continue
    const parent = taskRows.value.find((item) => item.key === parentKey)
    if (!parent) return `任务「${row.title.trim()}」的父任务已不存在，请重新选择`
    if (normalizeParentKey(parent.parent_key) !== null) {
      return `任务「${row.title.trim()}」的父任务「${parent.title.trim() || parent.key}」已是子任务，V1 最多两层`
    }
  }

  const cycle = findDependencyCycle()
  if (cycle) {
    const labels = cycle.map((key) => {
      const row = taskRows.value.find((item) => item.key === key)
      return row ? taskLabel(row) : key
    })
    return `任务依赖存在循环：${labels.join(' → ')}`
  }
  return null
}

function buildTaskDrafts(): ActivityBatchTaskDraft[] {
  return taskRows.value.map((row) => ({
    key: row.key,
    title: row.title.trim(),
    deadline: row.deadline || null,
    quota: row.quota,
    claim_type: row.claim_type,
    sop_guide: row.sop_guide.trim() || null,
    credit_reward: row.credit_reward,
    depends_on_keys: [...row.depends_on_keys],
    parent_key: normalizeParentKey(row.parent_key)
  }))
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function submit(): Promise<void> {
  if (saving.value) return
  const title = form.title.trim()
  if (!title) {
    ElMessage.warning('请填写活动名称')
    return
  }
  if (form.start_time && form.deadline && form.deadline < form.start_time) {
    ElMessage.warning('截止时间不能早于举办开始时间')
    return
  }
  const taskError = validateTasks()
  if (taskError) {
    ElMessage.warning(taskError)
    return
  }

  saving.value = true
  try {
    const result = await publishActivityBatch({
      activity: {
        title,
        description: form.description.trim() || null,
        location: form.location.trim() || null,
        start_time: form.start_time || null,
        deadline: form.deadline || null,
        org_id: form.org_id
      },
      tasks: buildTaskDrafts()
    })
    const taskCount = result.tasks.length
    ElMessage.success(
      taskCount > 0
        ? `活动《${result.activity.title}》与 ${taskCount} 个任务已发布`
        : `活动《${result.activity.title}》已发布`
    )
    void router.push({ name: 'activity', params: { id: result.activity.id } })
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <section class="app-page publish-activity">
    <header class="app-page-header">
      <div>
        <h1 class="app-page-title">发布活动</h1>
        <p class="app-page-subtitle">
          一次填写活动与全部任务；提交时整体校验并原子写入，任一失败不会留下活动或任务。不添加任务也可以只发布活动。
        </p>
      </div>
    </header>

    <div class="publish-activity__grid">
      <form class="app-section-card publish-activity__form" @submit.prevent="submit">
        <el-form label-position="top">
          <el-form-item label="活动名称" required>
            <el-input v-model="form.title" maxlength="120" show-word-limit />
          </el-form-item>
          <el-form-item label="介绍">
            <el-input v-model="form.description" type="textarea" :rows="4" maxlength="2000" />
          </el-form-item>
          <el-form-item label="地点">
            <el-input v-model="form.location" maxlength="200" />
          </el-form-item>
          <el-form-item label="举办开始时间">
            <el-input v-model="form.start_time" type="datetime-local" />
          </el-form-item>
          <el-form-item label="活动截止时间">
            <el-input v-model="form.deadline" type="datetime-local" />
          </el-form-item>
          <el-form-item label="归属组织">
            <el-select v-model="form.org_id" clearable placeholder="不归属组织（仅本人可发布任务）">
              <el-option
                v-for="org in publishableOrgs"
                :key="org.org_id"
                :label="`${org.name} · ${org.role === 'admin' ? '管理员' : '协作者'}`"
                :value="org.org_id"
              />
            </el-select>
          </el-form-item>
        </el-form>

        <section class="publish-activity__tasks" aria-label="任务编辑">
          <header class="publish-activity__tasks-header">
            <div class="publish-activity__tasks-heading">
              <h2 class="publish-activity__tasks-title">任务</h2>
              <p class="publish-activity__tasks-hint">
                依赖与父任务只能引用本批次的其他任务；父子关系最多两层。
              </p>
            </div>
            <el-button
              plain
              aria-label="添加任务"
              :disabled="saving"
              @click="addTaskRow"
            >
              添加任务
            </el-button>
          </header>

          <p v-if="taskRows.length === 0" class="publish-activity__tasks-empty">
            尚未添加任务，本次将只发布活动本体。
          </p>

          <article
            v-for="(row, index) in taskRows"
            :key="row.uid"
            class="publish-activity__task-card"
          >
            <header class="publish-activity__task-header">
              <span class="publish-activity__task-index">任务 {{ index + 1 }}</span>
              <span class="publish-activity__task-key">批内 key：{{ row.key }}</span>
              <el-button
                text
                type="danger"
                :aria-label="`删除任务 ${index + 1}`"
                :disabled="saving"
                @click="removeTaskRow(row.uid)"
              >
                删除
              </el-button>
            </header>

            <el-form label-position="top" class="publish-activity__task-form">
              <el-form-item label="任务标题" required>
                <el-input
                  v-model="row.title"
                  maxlength="80"
                  show-word-limit
                  placeholder="例如：迎新晚会场地布置"
                />
              </el-form-item>

              <div class="publish-activity__task-grid">
                <el-form-item label="任务截止时间">
                  <el-input
                    v-model="row.deadline"
                    type="datetime-local"
                    class="publish-activity__task-control"
                  />
                </el-form-item>
                <el-form-item label="名额">
                  <el-input-number
                    :model-value="row.quota"
                    :min="1"
                    :max="999"
                    controls-position="right"
                    class="publish-activity__task-control"
                    @change="onQuotaChange(row, $event)"
                  />
                </el-form-item>
                <el-form-item label="完成奖励积分">
                  <el-input-number
                    :model-value="row.credit_reward"
                    :min="0"
                    :max="1000"
                    controls-position="right"
                    class="publish-activity__task-control"
                    @change="onCreditChange(row, $event)"
                  />
                </el-form-item>
                <el-form-item label="认领方式">
                  <el-select v-model="row.claim_type" class="publish-activity__task-control">
                    <el-option label="开放认领" value="open" />
                    <el-option label="指派（请到单任务发布页）" value="assign" disabled />
                  </el-select>
                </el-form-item>
              </div>

              <el-form-item label="SOP / 完成说明">
                <el-input
                  v-model="row.sop_guide"
                  type="textarea"
                  :rows="2"
                  maxlength="500"
                  show-word-limit
                  placeholder="可留空；填写后随任务一起发布"
                />
              </el-form-item>

              <div class="publish-activity__task-grid">
                <el-form-item label="前置依赖（同批次）">
                  <el-select
                    v-model="row.depends_on_keys"
                    multiple
                    collapse-tags
                    collapse-tags-tooltip
                    class="publish-activity__task-control"
                    aria-label="前置依赖（同批次同层级任务）"
                    placeholder="可多选；只列同层级任务，前置全部完成后才可报名"
                  >
                    <el-option
                      v-for="candidate in dependencyOptions(row)"
                      :key="candidate.key"
                      :label="taskLabel(candidate)"
                      :value="candidate.key"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="父任务（同批次顶层任务）">
                  <el-select
                    :model-value="row.parent_key"
                    clearable
                    class="publish-activity__task-control"
                    aria-label="父任务（同批次顶层任务）"
                    :disabled="hasChildren(row)"
                    @update:model-value="onParentChange(row, $event)"
                    @clear="clearParent(row)"
                    :placeholder="
                      hasChildren(row)
                        ? '已被其他任务选为父任务，不能再挂到别的任务下'
                        : '不设父任务（顶层）'
                    "
                  >
                    <el-option
                      v-for="candidate in parentOptions(row)"
                      :key="candidate.key"
                      :label="taskLabel(candidate)"
                      :value="candidate.key"
                    />
                  </el-select>
                </el-form-item>
              </div>
            </el-form>
          </article>
        </section>

        <div class="publish-activity__actions">
          <el-button :disabled="saving" @click="router.push({ name: 'published-activities' })">
            返回我发布的活动
          </el-button>
          <el-button type="primary" native-type="submit" :loading="saving">
            {{ submitLabel }}
          </el-button>
        </div>
      </form>

      <div class="publish-activity__preview" aria-label="活动预览">
        <p class="publish-activity__preview-hint">预览与活动详情共用同一字段区块</p>
        <ActivityInfoSection :activity="preview" title-tag="h2" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.publish-activity {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.publish-activity__grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: var(--app-space-4);
  align-items: start;
}

.publish-activity__form {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.publish-activity__tasks {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
  padding-top: var(--app-space-4);
  border-top: 1px solid var(--app-border);
}

.publish-activity__tasks-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
  flex-wrap: wrap;
}

.publish-activity__tasks-heading {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  min-width: 0;
}

.publish-activity__tasks-title {
  margin: 0;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  color: var(--app-text);
}

.publish-activity__tasks-hint,
.publish-activity__tasks-empty {
  margin: 0;
  font-size: var(--app-font-aux);
  line-height: 1.5;
  color: var(--app-text-muted);
}

.publish-activity__tasks-empty {
  padding: var(--app-space-3);
  border: 1px dashed var(--app-border-strong);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.publish-activity__task-card {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
}

.publish-activity__task-header {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  flex-wrap: wrap;
}

.publish-activity__task-index {
  font-weight: 600;
  color: var(--app-text);
}

.publish-activity__task-key {
  flex: 1;
  min-width: 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.publish-activity__task-form {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

.publish-activity__task-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 var(--app-space-4);
}

.publish-activity__task-control {
  width: 100%;
  min-width: 0;
}

.publish-activity__preview {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.publish-activity__preview-hint {
  margin: 0;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.publish-activity__actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--app-space-2);
}

.publish-activity__actions :deep(.el-button) {
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .publish-activity__grid {
    grid-template-columns: 1fr;
  }

  .publish-activity__task-grid {
    grid-template-columns: 1fr;
  }

  /* 任务区控件保证 ≥ 44px 触控高度 */
  .publish-activity__tasks :deep(.el-input__wrapper),
  .publish-activity__tasks :deep(.el-select__wrapper),
  .publish-activity__tasks :deep(.el-input-number) {
    min-height: var(--app-touch);
  }

  .publish-activity__tasks-header {
    flex-direction: column;
    align-items: stretch;
  }

  .publish-activity__tasks-header :deep(.el-button) {
    width: 100%;
  }

  .publish-activity__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .publish-activity__actions :deep(.el-button) {
    width: 100%;
  }
}
</style>