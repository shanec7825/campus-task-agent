<script setup lang="ts">
/**
 * 活动详情（契约 C-DETAIL-LAYOUT@1 / C-DETAIL-HEADER@1 / C-TASK-GROUPS@1 / C-ACTIVITY-FACTS@1）。
 *
 * 结构顺序固定：`DetailHeader`（活动名、状态与操作）→ 关键指标条 →
 * `.detail-grid`（主区：任务分组 / 依赖与时间图 / 资料；侧栏：活动属性 / 切换活动 / 进度说明）。
 * 整页可被浏览器助手直接阅读：根节点用 `section.app-page`（`AppLayout` 的
 * `main#main-content` 是全局唯一 `<main>`），加载态用 `aria-busy` 表达且不渲染空状态。
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { ElMessage } from 'element-plus'

import { getActivity, listActivities } from '../api/activities'
import { ApiError } from '../api/client'
import { createResource, listResources } from '../api/resources'
import AgentDock from '../components/ai/AgentDock.vue'
import ActivityInfoSection from '../components/activity/ActivityInfoSection.vue'
import DetailHeader from '../components/detail/DetailHeader.vue'
import PropertyList, { type PropertyItem } from '../components/detail/PropertyList.vue'
import TaskGraph from '../components/task/TaskGraph.vue'
import TaskGroupList from '../components/task/TaskGroupList.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useUserStore } from '../stores/user'
import type { ActivityDetail as ActivityDetailModel, ActivityTaskNode, ResourceItem } from '../types/models'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const activity = ref<ActivityDetailModel | null>(null)
const loading = ref(false)
const error = ref('')
/** 当前展开的任务 id（子任务行可见） */
const expanded = ref<number[]>([])

/** 请求序号：切换活动后丢弃晚到的旧响应 */
let requestSeq = 0

/** 活动切换候选（`scope=all`，服务端已叠可见性） */
const switchActivities = ref<{ id: number; title: string }[]>([])
const switchLoading = ref(false)

/** 活动资料（本活动） */
const resources = ref<ResourceItem[]>([])
const resourcesLoading = ref(false)
/** 关键词检索：结果可能跨活动，但始终限定在后端判定的权限范围 */
const resourceQuery = ref('')
const resourceSearching = ref(false)
const searchResults = ref<ResourceItem[]>([])
const searchPerformed = ref(false)
/** 新增 / 更新资料对话框 */
const resourceDialogVisible = ref(false)
const resourceSaving = ref(false)
const resourceForm = ref({
  title: '',
  url: '',
  summary: '',
  resource_type: 'link',
  resource_key: null as string | null,
  task_id: null as number | null,
  org_id: null as number | null
})

const activityId = computed<number>(() => Number(route.params.id))

/** 侧栏属性用：组织名缺失时按 org_id 从我的组织解析，避免显示「未加入组织」 */
const infoActivity = computed<ActivityDetailModel | null>(() => {
  const current = activity.value
  if (!current) return null
  if (current.org) return current
  const hit = userStore.orgs.find((membership) => membership.org_id === current.org_id)
  return hit?.name ? { ...current, org: hit.name } : current
})

/** 资料管理权：活动负责人或该活动组织的管理员（后端仍会再校验） */
const canManageResources = computed<boolean>(() => {
  if (!activity.value || !userStore.user) return false
  if (activity.value.owner_id === userStore.user.id) return true
  const orgId = activity.value.org_id
  if (orgId === null) return false
  return userStore.orgs.some(
    (membership) =>
      membership.org_id === orgId && membership.status === 'active' && membership.role === 'admin'
  )
})

function canEditResource(resource: ResourceItem): boolean {
  return canManageResources.value || resource.created_by === userStore.user?.id
}

/** 外链只允许 http/https，避免 javascript/data 链接被直接打开 */
function isHttpUrl(value: string | null): boolean {
  return Boolean(value && /^https?:\/\//i.test(value))
}

const progressText = computed<string>(() => {
  const progress = activity.value?.progress
  if (!progress) return ''
  const base = `${progress.percent}% · ${progress.completed_tasks}/${progress.total_tasks} 个任务已完成`
  return progress.cancelled_tasks > 0 ? `${base} · 已取消 ${progress.cancelled_tasks} 个` : base
})

/** 侧栏进度说明的字段行 */
const progressItems = computed<PropertyItem[]>(() => {
  const progress = activity.value?.progress
  if (!progress) return []
  return [
    { label: '整体进度', value: progressText.value },
    {
      label: '负责人确认',
      value: progress.awaiting_owner_confirm ? '待负责人确认' : '无需确认',
      tone: progress.awaiting_owner_confirm ? 'warning' : 'muted'
    }
  ]
})

/** 指标条：完成率、待处理、已逾期（只统计第一层任务） */
const stats = computed<{ label: string; value: string; hint: string }[]>(() => {
  const progress = activity.value?.progress
  const tasks = activity.value?.tasks ?? []
  return [
    {
      label: '完成率',
      value: `${progress?.percent ?? 0}%`,
      hint: `${progress?.completed_tasks ?? 0}/${progress?.total_tasks ?? 0} 个任务已完成`
    },
    {
      label: '待处理',
      value: String(
        tasks.filter((task) => task.status !== 'verified' && task.status !== 'cancelled').length
      ),
      hint: '未完成且未取消的任务'
    },
    {
      label: '已逾期',
      value: String(tasks.filter(isTaskOverdue).length),
      hint: '已过截止且未完成'
    }
  ]
})

function todayStamp(): string {
  const now = new Date()
  const month = String(now.getMonth() + 1).padStart(2, '0')
  const day = String(now.getDate()).padStart(2, '0')
  return `${now.getFullYear()}-${month}-${day}`
}

/** 截止早于今天且未完成（verified / cancelled 不计入逾期） */
function isTaskOverdue(task: ActivityTaskNode): boolean {
  if (!task.deadline || task.status === 'verified' || task.status === 'cancelled') return false
  return task.deadline.slice(0, 10) < todayStamp()
}

function activityStatusText(status: string): string {
  if (status === 'published') return '进行中'
  if (status === 'closed') return '已结束'
  return '未知'
}

function activityStatusTagType(status: string): 'success' | 'info' | 'warning' {
  if (status === 'published') return 'success'
  if (status === 'closed') return 'info'
  return 'warning'
}

/** 只有带子任务的第一层任务才参与「展开全部 / 收起全部」 */
const expandableIds = computed<number[]>(() =>
  (activity.value?.tasks ?? []).filter((task) => task.children.length > 0).map((task) => task.id)
)

const allExpanded = computed<boolean>(
  () => expandableIds.value.length > 0 && expandableIds.value.every((id) => expanded.value.includes(id))
)

/**
 * 切换器选项：最多 20 条，且当前活动必定在内。
 * 当前活动不在服务端前 20 条时置顶补入，避免「切换后看不到自己」。
 */
const switchOptions = computed<{ id: number; title: string }[]>(() => {
  const current = activity.value
  const options = switchActivities.value
  if (!current || options.some((option) => option.id === current.id)) return options
  return [{ id: current.id, title: current.title }, ...options.slice(0, 19)]
})

async function loadSwitchActivities(): Promise<void> {
  if (switchLoading.value) return
  switchLoading.value = true
  try {
    const { items } = await listActivities({ scope: 'all' })
    switchActivities.value = items.slice(0, 20).map((item) => ({ id: item.id, title: item.title }))
  } catch {
    // 选项加载失败只提示，不阻塞详情主体；此时只保留当前活动一个选项
    ElMessage.warning('活动列表加载失败，稍后可再试切换')
  } finally {
    switchLoading.value = false
  }
}

/** 保留 `from` / `q`，把当前活动替换为选中的活动 */
function switchActivity(event: Event): void {
  const target = event.target as HTMLSelectElement
  const nextId = Number(target.value)
  if (!Number.isFinite(nextId) || nextId === activityId.value) {
    target.value = String(activityId.value)
    return
  }
  const query: LocationQueryRaw = {}
  if (route.query.from !== undefined) query.from = route.query.from
  if (route.query.q !== undefined) query.q = route.query.q
  void router.replace({ name: 'activity', params: { id: String(nextId) }, query })
}


function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.slice(0, 16).replace('T', ' ')
}


function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === 4040) return err.message || '活动不存在'
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function toggleTask(id: number): void {
  expanded.value = expanded.value.includes(id)
    ? expanded.value.filter((item) => item !== id)
    : [...expanded.value, id]
}

function toggleAll(): void {
  expanded.value = allExpanded.value ? [] : [...expandableIds.value]
}

/** 从大厅/我的任务/我发布的活动进入时按来源返回，直接打开时回大厅（站内路径白名单） */
function backToHall(): void {
  const back = window.history.state?.back
  if (isInternalBack(back)) {
    router.back()
    return
  }
  void router.push({ name: 'hall' })
}

function isInternalBack(value: unknown): value is string {
  return (
    typeof value === 'string' &&
    value.startsWith('/') &&
    !value.startsWith('//') &&
    !value.startsWith('/login') &&
    !value.startsWith('/register') &&
    !value.startsWith('/reset-password')
  )
}

function goPublish(): void {
  void router.push({ name: 'publish' })
}

/** 携带活动归属进入发布页（C-FE-ACTIVITY-PUBLISH@1） */
function publishUnderActivity(): void {
  void router.push({ name: 'publish', query: { activity: String(activityId.value) } })
}

async function loadResources(seq?: number): Promise<void> {
  if (!activity.value) {
    resources.value = []
    return
  }
  resourcesLoading.value = true
  try {
    const items = (await listResources({ activity_id: activity.value.id, limit: 50 })).items
    if (seq !== undefined && seq !== requestSeq) return
    resources.value = items
  } catch {
    if (seq === undefined || seq === requestSeq) resources.value = []
  } finally {
    if (seq === undefined || seq === requestSeq) resourcesLoading.value = false
  }
}

async function runResourceSearch(): Promise<void> {
  const query = resourceQuery.value.trim()
  if (!query) {
    searchResults.value = []
    searchPerformed.value = false
    return
  }
  resourceSearching.value = true
  try {
    searchResults.value = (await listResources({ q: query, limit: 20 })).items
    searchPerformed.value = true
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    resourceSearching.value = false
  }
}

function clearResourceSearch(): void {
  resourceQuery.value = ''
  searchResults.value = []
  searchPerformed.value = false
}

function openResourceDialog(resource?: ResourceItem): void {
  if (!canManageResources.value && !(resource && canEditResource(resource))) return
  resourceForm.value = resource
    ? {
        title: resource.title,
        url: resource.url,
        summary: resource.summary ?? '',
        resource_type: resource.resource_type,
        resource_key: resource.resource_key,
        task_id: resource.task_id,
        org_id: resource.org_id
      }
    : {
        title: '',
        url: '',
        summary: '',
        resource_type: 'link',
        resource_key: null,
        task_id: null,
        org_id: null
      }
  resourceDialogVisible.value = true
}

async function saveResource(): Promise<void> {
  if (!activity.value || resourceSaving.value) return
  const title = resourceForm.value.title.trim()
  const url = resourceForm.value.url.trim()
  if (!title || !url) {
    ElMessage.warning('请填写资料标题与原始链接')
    return
  }
  resourceSaving.value = true
  try {
    await createResource({
      title,
      url,
      summary: resourceForm.value.summary.trim() || null,
      resource_type: resourceForm.value.resource_type,
      activity_id: activity.value.id,
      task_id: resourceForm.value.task_id,
      org_id: resourceForm.value.org_id,
      resource_key: resourceForm.value.resource_key
    })
    resourceDialogVisible.value = false
    ElMessage.success(resourceForm.value.resource_key ? '已保存新版本' : '资料已添加')
    await Promise.all([loadResources(), runResourceSearch()])
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    resourceSaving.value = false
  }
}

async function load(): Promise<void> {
  if (!Number.isFinite(activityId.value) || activityId.value <= 0) {
    error.value = '活动编号无效'
    return
  }
  const current = ++requestSeq
  loading.value = true
  error.value = ''
  try {
    const result = await getActivity(activityId.value)
    if (current !== requestSeq) return
    activity.value = result
    const validIds = new Set(expandableIds.value)
    expanded.value = expanded.value.filter((id) => validIds.has(id))
    await loadResources(current)
  } catch (err) {
    if (current !== requestSeq) return
    activity.value = null
    resources.value = []
    error.value = errorMessage(err)
  } finally {
    if (current === requestSeq) loading.value = false
  }
}

onMounted(() => {
  void load()
  void loadSwitchActivities()
})

watch(
  () => route.params.id,
  () => {
    expanded.value = []
    clearResourceSearch()
    void load()
  }
)
</script>

<template>
  <section class="app-page activity-detail" :aria-busy="loading ? 'true' : 'false'">
    <LoadingState v-if="loading" :rows="6" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="无法加载活动详情，请确认活动是否存在或检查后端服务。"
      retryable
      @retry="load"
    />

    <template v-else-if="activity">
      <!-- 头部：活动名 + 状态胶囊 + 页面操作（唯一主操作在此活动下新建任务） -->
      <DetailHeader kicker="活动" :title="activity.title" :subtitle="activity.description">
        <template #badges>
          <el-tag
            :type="activityStatusTagType(activity.status)"
            effect="light"
            disable-transitions
          >
            {{ activityStatusText(activity.status) }}
          </el-tag>
        </template>
        <template #actions>
          <el-button @click="backToHall">返回列表</el-button>
          <el-button type="primary" @click="publishUnderActivity">在此活动下新建任务</el-button>
          <el-button @click="goPublish">发布相关事务</el-button>
        </template>
      </DetailHeader>

      <section class="activity-stats" aria-label="活动关键指标">
        <div v-for="stat in stats" :key="stat.label" class="activity-stat">
          <span class="activity-stat__label">{{ stat.label }}</span>
          <span class="activity-stat__value">{{ stat.value }}</span>
          <span class="activity-stat__hint">{{ stat.hint }}</span>
        </div>
      </section>

      <div class="detail-grid">
        <div class="detail-grid__main">
          <section class="app-section-card" aria-labelledby="activity-tasks-heading">
            <div class="section-head">
              <h2 id="activity-tasks-heading" class="section-title">任务</h2>
              <button
                v-if="expandableIds.length > 0"
                type="button"
                class="expand-all"
                :aria-expanded="allExpanded ? 'true' : 'false'"
                aria-controls="activity-task-groups"
                @click="toggleAll"
              >
                {{ allExpanded ? '收起全部' : '展开全部' }}
              </button>
            </div>
            <div id="activity-task-groups">
              <TaskGroupList
                :tasks="activity.tasks"
                :expanded="expanded"
                @toggle="toggleTask"
              />
            </div>
          </section>

          <section class="app-section-card" aria-labelledby="activity-graph-heading">
            <div class="section-head">
              <h2 id="activity-graph-heading" class="section-title">依赖与时间图</h2>
              <span class="graph-hint">依赖层级、前置关系与工作区间；缺日期任务归入未排期</span>
            </div>
            <TaskGraph
              :nodes="activity.graph.nodes"
              :edges="activity.graph.edges"
              mode="full"
            />
          </section>

          <section class="app-section-card" aria-labelledby="activity-resources-heading">
            <div class="section-head">
              <h2 id="activity-resources-heading" class="section-title">资料与往期参考</h2>
              <button
                v-if="canManageResources"
                type="button"
                class="expand-all"
                @click="openResourceDialog()"
              >
                添加资料
              </button>
            </div>

            <form class="resource-search" role="search" @submit.prevent="runResourceSearch">
              <label class="resource-search-label" for="resource-query">检索我权限内的资料</label>
              <div class="resource-search-row">
                <input
                  id="resource-query"
                  v-model="resourceQuery"
                  type="search"
                  class="resource-search-input"
                  placeholder="例如：往届推文模板"
                />
                <button type="submit" class="expand-all" :disabled="resourceSearching">
                  {{ resourceSearching ? '检索中…' : '检索' }}
                </button>
                <button
                  v-if="searchPerformed"
                  type="button"
                  class="expand-all"
                  @click="clearResourceSearch"
                >
                  清除
                </button>
              </div>
            </form>

            <h3 class="resource-subtitle">本活动资料</h3>
            <p v-if="resourcesLoading" class="resource-hint">正在加载资料…</p>
            <p v-else-if="resources.length === 0" class="resource-hint">本活动还没有资料。</p>
            <ul v-else class="resource-list">
              <li v-for="resource in resources" :key="resource.id" class="resource-item">
                <div class="resource-head">
                  <span class="resource-title">{{ resource.title }}</span>
                  <el-tag size="small" effect="plain">v{{ resource.version }}</el-tag>
                  <span class="resource-meta">
                    {{ resource.created_by_name }} · {{ dateText(resource.created_at) }}
                  </span>
                </div>
                <p v-if="resource.summary" class="resource-summary">{{ resource.summary }}</p>
                <div class="resource-actions">
                  <a
                    v-if="isHttpUrl(resource.url)"
                    class="resource-link"
                    :href="resource.url"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    打开原始链接
                  </a>
                  <el-button
                    v-if="canEditResource(resource)"
                    size="small"
                    text
                    type="primary"
                    @click="openResourceDialog(resource)"
                  >
                    更新版本
                  </el-button>
                </div>
              </li>
            </ul>

            <div v-if="searchPerformed" class="resource-search-results">
              <h3 class="resource-subtitle">检索结果（{{ searchResults.length }}）</h3>
              <p v-if="searchResults.length === 0" class="resource-hint">
                权限内没有匹配资料；无权限资料不会出现在这里。
              </p>
              <ul v-else class="resource-list">
                <li v-for="resource in searchResults" :key="resource.id" class="resource-item">
                  <div class="resource-head">
                    <span class="resource-title">{{ resource.title }}</span>
                    <el-tag size="small" effect="plain">v{{ resource.version }}</el-tag>
                    <span class="resource-meta">
                      {{ resource.activity_title || '未绑定活动' }} · {{ resource.created_by_name }}
                    </span>
                  </div>
                  <p v-if="resource.summary" class="resource-summary">{{ resource.summary }}</p>
                  <div class="resource-actions">
                    <a
                      v-if="isHttpUrl(resource.url)"
                      class="resource-link"
                      :href="resource.url"
                      target="_blank"
                      rel="noopener noreferrer"
                    >
                      打开原始链接
                    </a>
                  </div>
                </li>
              </ul>
            </div>
          </section>
        </div>

        <aside class="detail-grid__side" aria-label="活动属性与进度">
          <section class="app-section-card" aria-labelledby="activity-facts-heading">
            <h2 id="activity-facts-heading" class="section-title">活动属性</h2>
            <ActivityInfoSection v-if="infoActivity" :activity="infoActivity" variant="facts" />
          </section>

          <section class="app-section-card" aria-labelledby="activity-switch-heading">
            <h2 id="activity-switch-heading" class="section-title">切换活动</h2>
            <div class="activity-detail__switch">
              <select
                class="activity-detail__select"
                aria-label="切换活动"
                :value="String(activityId)"
                :disabled="switchLoading"
                @change="switchActivity"
              >
                <option v-for="option in switchOptions" :key="option.id" :value="String(option.id)">
                  {{ option.title }}
                </option>
              </select>
            </div>
          </section>

          <section class="app-section-card" aria-labelledby="activity-progress-heading">
            <h2 id="activity-progress-heading" class="section-title">进度说明</h2>
            <PropertyList :items="progressItems" />
          </section>
        </aside>
      </div>

      <AgentDock
        :context-label="`活动：${activity.title}`"
        :scope-type="'activity'"
        :scope-id="activity?.id"
      />
    </template>

    <el-dialog
      v-model="resourceDialogVisible"
      :title="resourceForm.resource_key ? '更新资料版本' : '添加资料'"
      width="min(560px, calc(100vw - 32px))"
      :close-on-click-modal="false"
    >
      <el-form label-position="top">
        <el-form-item label="资料标题" required>
          <el-input v-model="resourceForm.title" maxlength="120" />
        </el-form-item>
        <el-form-item label="原始链接" required>
          <el-input v-model="resourceForm.url" maxlength="1000" placeholder="https://example.com/..." />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input
            v-model="resourceForm.summary"
            type="textarea"
            :rows="3"
            maxlength="2000"
            show-word-limit
            placeholder="说明这份资料适合参考什么，以及有哪些本届差异。"
          />
        </el-form-item>
        <el-form-item label="资料类型">
          <el-select v-model="resourceForm.resource_type">
            <el-option label="链接" value="link" />
            <el-option label="文档" value="document" />
            <el-option label="说明" value="note" />
          </el-select>
        </el-form-item>
        <el-alert
          v-if="resourceForm.resource_key"
          type="info"
          :closable="false"
          title="保存后会在同一资料下生成新版本，旧版本保留。"
        />
      </el-form>
      <template #footer>
        <el-button :disabled="resourceSaving" @click="resourceDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="resourceSaving" @click="saveResource">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.activity-detail {
  max-width: var(--app-detail-max);
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--app-detail-gap);
}

.activity-stats {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--app-detail-gap);
}

.activity-stat {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  min-width: 0;
  padding: var(--app-space-3) var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface);
}

.activity-stat__label {
  font-size: var(--app-font-label);
  color: var(--app-text-muted);
}

.activity-stat__value {
  font-size: var(--app-font-section-title);
  font-weight: 700;
  line-height: 1.2;
  color: var(--app-text);
}

.activity-stat__hint {
  font-size: var(--app-font-aux);
  color: var(--app-text-secondary);
  word-break: break-word;
}

.detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) var(--app-sidebar-width);
  gap: var(--app-detail-gap);
  align-items: start;
}

.detail-grid__main,
.detail-grid__side {
  display: flex;
  flex-direction: column;
  gap: var(--app-detail-gap);
  min-width: 0;
}

.section-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-2);
}

.section-title {
  margin: 0;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  color: var(--app-text);
}

.activity-detail__switch {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
  min-width: 0;
  margin-top: var(--app-space-2);
}

.activity-detail__select {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 100%;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
}

.activity-detail__select:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 1px;
}

.expand-all {
  min-height: var(--app-touch);
  min-width: var(--app-touch);
  padding: 0 14px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.expand-all:hover,
.expand-all:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.graph-hint {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
  word-break: break-word;
}

.resource-search {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 12px;
}

.resource-search-label {
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-secondary);
}

.resource-search-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.resource-search-input {
  flex: 1 1 220px;
  min-width: 0;
  min-height: var(--app-touch);
  padding: 0 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-body);
}

.resource-search-input:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 1px;
}

.resource-subtitle {
  margin: 14px 0 0;
  font-size: var(--app-font-aux-lg);
  font-weight: 600;
  color: var(--app-text);
}

.resource-search-results {
  margin-top: 16px;
  padding-top: 12px;
  border-top: 1px solid var(--app-border);
}

.resource-hint {
  margin: 8px 0 0;
  font-size: var(--app-font-aux-lg);
  color: var(--app-text-muted);
  line-height: 1.6;
}

.resource-list {
  list-style: none;
  margin: 10px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.resource-item {
  padding: 12px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.resource-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 8px;
}

.resource-title {
  font-size: var(--app-font-body);
  font-weight: 600;
  color: var(--app-text);
  word-break: break-word;
}

.resource-meta {
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.resource-summary {
  margin: 6px 0 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.6;
  color: var(--app-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.resource-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 8px;
}

.resource-link {
  font-size: var(--app-font-aux-lg);
  color: var(--app-primary);
}

@media (max-width: 1080px) {
  .detail-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 768px) {
  .activity-detail {
    gap: var(--app-space-3);
  }

  .activity-stats {
    grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
    gap: var(--app-space-2);
  }

  .activity-stat {
    padding: var(--app-space-2) var(--app-space-3);
  }

  .detail-grid {
    gap: var(--app-space-3);
  }

  .detail-grid__main,
  .detail-grid__side {
    gap: var(--app-space-3);
  }

  .section-head :deep(.expand-all),
  .section-head .expand-all {
    width: 100%;
  }

  .resource-search-input {
    flex-basis: 100%;
  }

  .resource-search-row .expand-all {
    flex: 1 1 auto;
  }
}
</style>