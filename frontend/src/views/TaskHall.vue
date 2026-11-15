<script setup lang="ts">
/**
 * 事务列表（契约 `C-BROWSE-TABS@3` / `C-BROWSE-SPLIT@1`）。
 *
 * - 活动 / 任务双段胶囊：路由 `?type=activity|task` 决定唯一渲染的集合，缺省 `activity`；
 * - 两类筛选与滚动位置各存独立 sessionStorage 键，互不覆盖；切换类型清除不匹配的选中；
 * - 选中事项后结果区变为左单列卡片 + 右侧两列详情（`≥768px`），`<768px` 直接进入独立详情页；
 * - 卡片只读，报名 / 验收 / 图谱 / 成员仍在独立详情页，本页不提供写入；
 * - `variant="mine"` 复用同一实现作为「我的任务」页：范围锁定 `mine`，使用独立持久化键。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { listActivities } from '../api/activities'
import { ApiError } from '../api/client'
import { listTasks } from '../api/tasks'
import ActivityBrowseCard from '../components/browse/ActivityBrowseCard.vue'
import BrowseDetailPanel from '../components/browse/BrowseDetailPanel.vue'
import HallTabs, { type BrowseType } from '../components/browse/HallTabs.vue'
import TaskBrowseCard from '../components/browse/TaskBrowseCard.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import HoverPeek from '../components/common/HoverPeek.vue'
import LoadingState from '../components/common/LoadingState.vue'
import SegmentedTabs from '../components/common/SegmentedTabs.vue'
import { STATUS_MAP, statusText } from '../components/task/StatusTag.vue'
import { formatDeadline, quotaText } from '../components/task/TaskCard.vue'
import type { Activity, TaskItem } from '../types/models'

type ScopeValue = 'all' | 'mine'

interface HallViewState {
  status: string
  scope: ScopeValue
  type: string
  scrollTop: number
}

/** 两类集合各自一份筛选与滚动记录（契约 `C-BROWSE-TABS@3` 持久化键） */
const VIEW_KEYS: Record<'hall' | 'mine', Record<BrowseType, string>> = {
  hall: { activity: 'cta_hall_view_activity', task: 'cta_hall_view_task' },
  mine: { activity: 'cta_my_tasks_view_activity', task: 'cta_my_tasks_view_task' }
}

const props = withDefaults(defineProps<{ variant?: 'hall' | 'mine' }>(), { variant: 'hall' })
const isMineVariant = props.variant === 'mine'
const viewKeys = VIEW_KEYS[isMineVariant ? 'mine' : 'hall']

const route = useRoute()
const router = useRouter()

const activities = ref<Activity[]>([])
const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')
const filterDrawerOpen = ref(false)
const isCompact = ref(false)

function defaultView(): HallViewState {
  return {
    status: 'all',
    scope: isMineVariant ? 'mine' : 'all',
    type: 'all',
    scrollTop: 0
  }
}

function readView(type: BrowseType): HallViewState {
  const fallback = defaultView()
  try {
    const raw = window.sessionStorage.getItem(viewKeys[type])
    if (!raw) return fallback
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return fallback
    const candidate = parsed as Partial<HallViewState>
    return {
      status: typeof candidate.status === 'string' ? candidate.status : fallback.status,
      scope: isMineVariant ? 'mine' : candidate.scope === 'mine' ? 'mine' : 'all',
      type: typeof candidate.type === 'string' ? candidate.type : fallback.type,
      scrollTop:
        typeof candidate.scrollTop === 'number' && candidate.scrollTop > 0 ? candidate.scrollTop : 0
    }
  } catch {
    return fallback
  }
}

const viewStates = reactive<Record<BrowseType, HallViewState>>({
  activity: readView('activity'),
  task: readView('task')
})

/** 活动 / 任务集合由路由 query 唯一决定（缺省活动） */
const activeType = computed<BrowseType>(() => (route.query.type === 'task' ? 'task' : 'activity'))
const currentView = computed<HallViewState>(() => viewStates[activeType.value])

/** 状态过滤项直接由 StatusTag 的映射表生成，保证文案唯一来源 */
const statusOptions = Object.entries(STATUS_MAP).map(([value, meta]) => ({
  value,
  label: meta.text
}))

const typeOptions = [
  { value: 'open', label: '公开报名' },
  { value: 'assign', label: '指派' }
]

/** 胶囊筛选选项（契约 `C-TASKHALL-FILTER@1`）：值域与 `currentView` 一致，首位补「全部」 */
const SCOPE_OPTIONS: Array<{ value: ScopeValue; label: string }> = [
  { value: 'all', label: '全部' },
  { value: 'mine', label: '我的' }
]

const STATUS_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'all', label: '全部' },
  ...statusOptions
]

const TYPE_FILTER_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'all', label: '全部' },
  ...typeOptions
]

/** 任务集合 = 活动下第一层任务 + 独立任务；子任务不重复铺满 */
const visibleTasks = computed<TaskItem[]>(() =>
  tasks.value.filter(
    (task) =>
      task.parent_id === null &&
      (currentView.value.type === 'all' || task.claim_type === currentView.value.type)
  )
)

/** 活动标题映射：任务卡与预览显示所属活动，不新增后端字段 */
const activityTitleById = computed<Map<number, string>>(
  () => new Map(activities.value.map((activity) => [activity.id, activity.title]))
)

const hasFilter = computed<boolean>(() => {
  const state = currentView.value
  const scopeFiltered = !isMineVariant && state.scope !== 'all'
  if (activeType.value === 'activity') return scopeFiltered
  return scopeFiltered || state.status !== 'all' || state.type !== 'all'
})

const emptyTitle = computed<string>(() => {
  if (activeType.value === 'activity') {
    return currentView.value.scope === 'mine' ? '暂无与你相关的活动' : '暂无活动'
  }
  if (hasFilter.value) return '没有符合条件的任务'
  return isMineVariant ? '还没有与你相关的任务' : '暂无任务'
})

const emptyDescription = computed<string>(() => {
  if (activeType.value === 'activity') {
    return '活动发布后会出现在这里；点击卡片可在右侧查看摘要，或打开完整活动详情。'
  }
  if (hasFilter.value) return '试着切换状态、范围或类型筛选，或点击「刷新」重新加载。'
  return isMineVariant
    ? '你还没有需要执行或管理的任务；报名通过或成为负责人后，任务会出现在这里。'
    : '还没有人发布任务，可以在发布页创建第一个事务。'
})

/** 当前筛选摘要：不依赖按钮高亮即可读到「现在筛了什么」 */
const activeFilterText = computed<string>(() => {
  const state = currentView.value
  if (activeType.value === 'activity') {
    if (!isMineVariant && state.scope === 'mine') return '范围：我的任务与活动'
    return isMineVariant ? '我的全部活动' : '全部活动'
  }
  const parts: string[] = []
  if (state.status !== 'all') parts.push(`状态：${statusText(state.status)}`)
  if (!isMineVariant && state.scope !== 'all') parts.push('范围：我的任务与活动')
  if (state.type !== 'all') {
    const matched = typeOptions.find((option) => option.value === state.type)
    parts.push(`类型：${matched?.label ?? state.type}`)
  }
  return parts.length > 0 ? parts.join(' · ') : isMineVariant ? '我的全部任务与活动' : '全部事务'
})

const subtitle = computed<string>(() => {
  if (loading.value) return `正在加载${activeType.value === 'activity' ? '活动' : '任务'}…`
  return activeType.value === 'activity'
    ? `共 ${activities.value.length} 个活动`
    : `共 ${visibleTasks.value.length} 个任务`
})

/** 选中态完全来自 query：`selectedType` 与当前集合不一致时不生效 */
const detailType = computed<BrowseType | null>(() => {
  const raw = route.query.selectedType
  if (raw !== 'activity' && raw !== 'task') return null
  return raw === activeType.value ? raw : null
})

const detailId = computed<number | null>(() => {
  const raw = Array.isArray(route.query.selectedId) ? route.query.selectedId[0] : route.query.selectedId
  const value = Number(raw)
  return Number.isInteger(value) && value > 0 ? value : null
})

/** 分栏只在 ≥768px 生效；移动端点击粒子直接进独立详情页 */
const splitSelection = computed<{ type: BrowseType; id: number } | null>(() => {
  const type = detailType.value
  const id = detailId.value
  if (type === null || id === null || isCompact.value) return null
  return { type, id }
})

function isSelected(type: BrowseType, id: number): boolean {
  return splitSelection.value?.type === type && splitSelection.value?.id === id
}

let loadSeq = 0
let scrollWriteTimer: number | null = null
let userScrolledDuringLoad = false
let disposed = false
/** 打开分栏前的滚动位置：关闭后回到原处 */
let restoreScrollTop: number | null = null

function updateCompact(): void {
  isCompact.value = window.innerWidth < 768
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function writeView(type: BrowseType): void {
  const state = viewStates[type]
  try {
    window.sessionStorage.setItem(
      viewKeys[type],
      JSON.stringify({
        status: state.status,
        scope: state.scope,
        type: state.type,
        scrollTop: Math.max(0, Math.round(window.scrollY))
      } satisfies HallViewState)
    )
  } catch {
    // 隐私模式无法持久化时只保留本次内存状态
  }
}

function cancelPendingWrite(): void {
  if (scrollWriteTimer !== null) {
    window.clearTimeout(scrollWriteTimer)
    scrollWriteTimer = null
  }
}

/** 滚动时 200ms 节流写入；分栏期间不覆盖原列表位置 */
function scheduleWrite(): void {
  cancelPendingWrite()
  scrollWriteTimer = window.setTimeout(() => {
    scrollWriteTimer = null
    writeView(activeType.value)
  }, 200)
}

function handleScroll(): void {
  if (loading.value || splitSelection.value !== null) return
  scheduleWrite()
}

/** 只有用户主动滚轮 / 触摸 / 翻页键才取消恢复 */
function markUserScroll(): void {
  if (loading.value) userScrolledDuringLoad = true
}

function markUserKeyScroll(event: KeyboardEvent): void {
  if ([' ', 'PageDown', 'PageUp', 'ArrowDown', 'ArrowUp', 'End', 'Home'].includes(event.key)) {
    markUserScroll()
  }
}

function handleBeforeUnload(): void {
  writeView(activeType.value)
}

async function loadCurrent(): Promise<void> {
  const seq = ++loadSeq
  const type = activeType.value
  const state = viewStates[type]
  loading.value = true
  error.value = ''
  try {
    if (type === 'activity') {
      const result = await listActivities({ scope: state.scope })
      if (seq !== loadSeq) return
      activities.value = result?.items ?? []
      tasks.value = []
    } else {
      const [taskResult, activityResult] = await Promise.all([
        listTasks({
          status: state.status === 'all' ? undefined : state.status,
          scope: state.scope,
          include_sub: true
        }),
        listActivities({ scope: state.scope })
      ])
      if (seq !== loadSeq) return
      tasks.value = taskResult?.items ?? []
      activities.value = activityResult?.items ?? []
    }
  } catch (err) {
    if (seq !== loadSeq) return
    activities.value = []
    tasks.value = []
    error.value = errorMessage(err)
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

async function restoreScrollFor(type: BrowseType): Promise<void> {
  await nextTick()
  if (disposed || userScrolledDuringLoad) {
    userScrolledDuringLoad = false
    return
  }
  const top = viewStates[type].scrollTop
  if (top > 0) window.scrollTo({ top, behavior: 'auto' })
}

function handleFilterChange(): void {
  writeView(activeType.value)
  // 筛选变化后原选中可能已不在结果集内，清掉失效的 selectedType/selectedId
  clearSelectionQuery()
  void loadCurrent()
}

function resetFilters(): void {
  if (!hasFilter.value) return
  const state = viewStates[activeType.value]
  state.status = 'all'
  state.scope = isMineVariant ? 'mine' : 'all'
  state.type = 'all'
  writeView(activeType.value)
  void loadCurrent()
}

/** 路由 query 的浅拷贝：显式收窄为 `string | null`，避免展开后推断成只含单个键的字面量 */
function copyQuery(): Record<string, string | null> {
  const result: Record<string, string | null> = {}
  for (const [key, raw] of Object.entries(route.query)) {
    if (Array.isArray(raw)) {
      const first = raw[0]
      if (first !== undefined && first !== null) result[key] = first
      continue
    }
    result[key] = raw ?? null
  }
  return result
}

function clearSelectionQuery(): void {
  if (route.query.selectedType === undefined && route.query.selectedId === undefined) return
  const query = copyQuery()
  delete query.selectedType
  delete query.selectedId
  void router.replace({ query })
}

/** 切换集合：写回当前集合状态，清除不匹配的选中，交由路由驱动重新加载 */
function changeType(value: BrowseType): void {
  if (value === activeType.value) return
  cancelPendingWrite()
  writeView(activeType.value)
  filterDrawerOpen.value = false
  const query = copyQuery()
  query.type = value
  delete query.selectedType
  delete query.selectedId
  void router.replace({ query })
}

function selectCard(type: BrowseType, id: number): void {
  if (isCompact.value) {
    void router.push({ name: type === 'activity' ? 'activity' : 'detail', params: { id } })
    return
  }
  if (restoreScrollTop === null) restoreScrollTop = Math.max(0, Math.round(window.scrollY))
  const query = copyQuery()
  const target = {
    query: { ...query, selectedType: type, selectedId: String(id) }
  }
  // 从列表进入详情形成一条历史（返回可回列表）；已在详情中切卡只替换当前条目
  if (detailId.value === null) void router.push(target)
  else void router.replace(target)
}

function closeDetail(): void {
  clearSelectionQuery()
}

watch(detailId, (value, previous) => {
  if (value !== null || previous === null || restoreScrollTop === null) return
  const top = restoreScrollTop
  restoreScrollTop = null
  void nextTick(() => {
    if (!disposed) window.scrollTo({ top, behavior: 'auto' })
  })
})

watch(activeType, (next) => {
  if (route.query.selectedType !== undefined && route.query.selectedType !== next) {
    clearSelectionQuery()
  }
  void loadCurrent().then(() => restoreScrollFor(next))
})

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.slice(0, 16).replace('T', ' ')
}

onMounted(async () => {
  disposed = false
  updateCompact()
  window.addEventListener('resize', updateCompact)
  window.addEventListener('scroll', handleScroll, { passive: true })
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('wheel', markUserScroll, { passive: true })
  window.addEventListener('touchmove', markUserScroll, { passive: true })
  window.addEventListener('keydown', markUserKeyScroll)
  if (detailId.value === null && (route.query.selectedType !== undefined || route.query.selectedId !== undefined)) {
    clearSelectionQuery()
  }
  await loadCurrent()
  await restoreScrollFor(activeType.value)
})

onBeforeUnmount(() => {
  disposed = true
  loadSeq += 1
  window.removeEventListener('resize', updateCompact)
  window.removeEventListener('scroll', handleScroll)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('wheel', markUserScroll)
  window.removeEventListener('touchmove', markUserScroll)
  window.removeEventListener('keydown', markUserKeyScroll)
  cancelPendingWrite()
  if (splitSelection.value === null) writeView(activeType.value)
})
</script>

<template>
  <section class="app-page hall" :aria-busy="loading ? 'true' : 'false'">
    <header class="app-page-header hall-header">
      <div class="hall-heading">
        <h1 class="app-page-title">{{ isMineVariant ? '我的任务' : '任务大厅' }}</h1>
        <p class="app-page-subtitle" aria-live="polite">{{ subtitle }}</p>
      </div>
      <el-button class="hall-refresh" :loading="loading" @click="loadCurrent">刷新</el-button>
    </header>

    <HallTabs :model-value="activeType" @update:model-value="changeType" />

    <LoadingState v-if="loading" :rows="4" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="事务列表加载失败，请检查后端服务后重试。"
      retryable
      @retry="loadCurrent"
    />

    <template v-else>
      <div v-if="activeType === 'task' || !isMineVariant" class="filter-mobile-row">
        <span class="app-muted">当前筛选：{{ activeFilterText }}</span>
        <el-button @click="filterDrawerOpen = true">筛选</el-button>
      </div>

      <section
        v-if="activeType === 'task' || !isMineVariant"
        class="app-section-card filter-panel"
        aria-label="事务筛选"
      >
        <div v-if="!isMineVariant" class="filter-row">
          <span class="filter-label">范围</span>
          <SegmentedTabs
            v-model="currentView.scope"
            :options="SCOPE_OPTIONS"
            aria-label="范围"
            @change="handleFilterChange"
          />
        </div>

        <template v-if="activeType === 'task'">
          <div class="filter-row">
            <span class="filter-label">状态</span>
            <SegmentedTabs
              v-model="currentView.status"
              :options="STATUS_FILTER_OPTIONS"
              aria-label="状态"
              @change="handleFilterChange"
            />
          </div>

          <div class="filter-row">
            <span class="filter-label">类型</span>
            <SegmentedTabs
              v-model="currentView.type"
              :options="TYPE_FILTER_OPTIONS"
              aria-label="类型"
              @change="handleFilterChange"
            />
          </div>
        </template>

        <div class="filter-current">
          <span class="app-muted">当前筛选：{{ activeFilterText }}</span>
          <el-button v-if="hasFilter" text type="primary" size="small" @click="resetFilters">
            清除筛选
          </el-button>
        </div>
      </section>

      <div
        id="browse-collection"
        role="tabpanel"
        :aria-label="activeType === 'activity' ? '活动列表' : '任务列表'"
        class="hall-results"
        :class="{ 'hall-results--split': splitSelection !== null }"
      >
        <div class="hall-results__list">
          <template v-if="activeType === 'activity'">
            <div v-if="activities.length === 0" class="hall-results__empty">
              <EmptyState :title="emptyTitle" :description="emptyDescription" />
            </div>

            <template v-else>
              <HoverPeek v-for="activity in activities" :key="activity.id" class="peek-item">
                <ActivityBrowseCard
                  :activity="activity"
                  :selected="isSelected('activity', activity.id)"
                  @select="selectCard('activity', $event)"
                />

                <template #preview>
                  <p class="preview-title">{{ activity.title }}</p>
                  <p v-if="activity.description" class="preview-desc">{{ activity.description }}</p>
                  <dl class="preview-facts">
                    <div>
                      <dt>举办</dt>
                      <dd>{{ dateText(activity.start_time) }} 至 {{ dateText(activity.deadline) }}</dd>
                    </div>
                    <div>
                      <dt>地点</dt>
                      <dd>{{ activity.location || '未设置' }}</dd>
                    </div>
                    <div>
                      <dt>负责人</dt>
                      <dd>{{ activity.owner_name || '—' }}</dd>
                    </div>
                    <div>
                      <dt>任务</dt>
                      <dd>
                        {{ activity.progress.completed_tasks }}/{{ activity.progress.total_tasks }} 已完成 ·
                        {{ activity.progress.percent }}%
                      </dd>
                    </div>
                  </dl>
                  <p class="preview-hint">点击卡片可在右侧查看摘要</p>
                </template>
              </HoverPeek>
            </template>
          </template>

          <template v-else>
            <div v-if="visibleTasks.length === 0" class="hall-results__empty">
              <EmptyState :title="emptyTitle" :description="emptyDescription" />
            </div>

            <template v-else>
              <HoverPeek v-for="task in visibleTasks" :key="task.id" class="peek-item">
                <TaskBrowseCard
                  :task="task"
                  :activity-title="
                    task.activity_id !== null ? activityTitleById.get(task.activity_id) : undefined
                  "
                  :selected="isSelected('task', task.id)"
                  @select="selectCard('task', $event)"
                />

                <template #preview>
                  <p class="preview-title">{{ task.title }}</p>
                  <p class="preview-desc">
                    {{ task.description || '暂无描述，打开详情查看完整要求。' }}
                  </p>
                  <dl class="preview-facts">
                    <div v-if="task.activity_id !== null">
                      <dt>所属活动</dt>
                      <dd>
                        {{ activityTitleById.get(task.activity_id) || `活动 #${task.activity_id}` }}
                      </dd>
                    </div>
                    <div>
                      <dt>截止</dt>
                      <dd>{{ formatDeadline(task.deadline) }}</dd>
                    </div>
                    <div>
                      <dt>名额</dt>
                      <dd>{{ quotaText(task) }}</dd>
                    </div>
                    <div v-if="task.location">
                      <dt>地点</dt>
                      <dd>{{ task.location }}</dd>
                    </div>
                    <div>
                      <dt>发布者</dt>
                      <dd>{{ task.publisher_name || '—' }}</dd>
                    </div>
                  </dl>
                  <p class="preview-hint">点击卡片可在右侧查看摘要</p>
                </template>
              </HoverPeek>
            </template>
          </template>
        </div>

        <BrowseDetailPanel
          v-if="splitSelection"
          :type="splitSelection?.type ?? 'activity'"
          :id="splitSelection?.id ?? 0"
          class="hall-results__detail"
          @close="closeDetail"
        />
      </div>
    </template>

    <el-drawer v-model="filterDrawerOpen" direction="btt" size="70%" title="筛选">
      <div class="drawer-filters">
        <div v-if="!isMineVariant" class="filter-row">
          <span class="filter-label">范围</span>
          <SegmentedTabs
            v-model="currentView.scope"
            :options="SCOPE_OPTIONS"
            aria-label="范围"
            @change="handleFilterChange"
          />
        </div>

        <template v-if="activeType === 'task'">
          <div class="filter-row">
            <span class="filter-label">状态</span>
            <SegmentedTabs
              v-model="currentView.status"
              :options="STATUS_FILTER_OPTIONS"
              aria-label="状态"
              @change="handleFilterChange"
            />
          </div>

          <div class="filter-row">
            <span class="filter-label">类型</span>
            <SegmentedTabs
              v-model="currentView.type"
              :options="TYPE_FILTER_OPTIONS"
              aria-label="类型"
              @change="handleFilterChange"
            />
          </div>
        </template>

        <p class="app-muted">当前筛选：{{ activeFilterText }}</p>
      </div>

      <div class="drawer-footer">
        <el-button :disabled="!hasFilter" @click="resetFilters">清除筛选</el-button>
        <el-button @click="filterDrawerOpen = false">完成</el-button>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.hall-header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}

.hall-heading {
  min-width: 0;
}

.hall-results {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--app-space-4);
  align-items: start;
}

.hall-results__list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  /* 所有卡片等高：同列表内不因标题/元信息长短出现高度差（R-06） */
  grid-auto-rows: 1fr;
  gap: var(--app-space-4);
  align-items: stretch;
}

.hall-results__empty {
  grid-column: 1 / -1;
}

.hall-results__detail {
  min-width: 0;
}

/* 宽桌面三列短卡片 */
@media (min-width: 1200px) {
  .hall-results__list {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

/* 选中后：左侧单列卡片 + 右侧占原两列的详情 */
@media (min-width: 768px) {
  .hall-results--split {
    grid-template-columns: minmax(0, 1fr) minmax(0, 2fr);
  }

  .hall-results--split .hall-results__list {
    grid-template-columns: minmax(0, 1fr);
  }
}

/* 手机单列；点击卡片直接进独立详情页 */
@media (max-width: 767px) {
  .hall-results__list {
    grid-template-columns: minmax(0, 1fr);
  }
}

.peek-item {

  height: 100%;
  min-width: 0;
}

.filter-mobile-row {
  display: none;
}

.filter-panel {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  padding: var(--app-space-3) var(--app-space-4);
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}

.filter-label {
  flex-shrink: 0;
  width: 32px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg, 14px);
}


.filter-current {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  padding-top: var(--app-space-2);
  border-top: 1px dashed var(--app-border);
  font-size: var(--app-font-aux, 13px);
}

.preview-title {
  margin: 0 0 6px;
  color: var(--app-text);
  font-size: var(--app-font-body, 15px);
  font-weight: 600;
  word-break: break-word;
}

.preview-desc {
  margin: 0 0 var(--app-space-2);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg, 14px);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.preview-facts {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  margin: 0;
}

.preview-facts > div {
  display: flex;
  align-items: baseline;
  gap: var(--app-space-2);
}

.preview-facts dt {
  flex-shrink: 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux, 13px);
}

.preview-facts dd {
  margin: 0;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux, 13px);
  word-break: break-word;
}

.preview-hint {
  margin: var(--app-space-2) 0 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux, 13px);
}

.drawer-filters {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.drawer-footer {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: var(--app-space-5);
}

.drawer-footer :deep(.el-button) {
  flex: 1 1 0;
  margin-left: 0;
}

@media (max-width: 768px) {
  .hall-refresh {
    min-width: var(--app-touch);
    min-height: var(--app-touch);
  }

  .filter-mobile-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: var(--app-space-2);
    font-size: var(--app-font-aux, 13px);
  }

  .filter-panel {
    display: none;
  }

  .filter-mobile-row :deep(.el-button),
  .drawer-footer :deep(.el-button) {
    min-height: var(--app-touch);
  }

  .filter-label {
    width: auto;
    font-size: var(--app-font-body, 15px);
  }

}
</style>