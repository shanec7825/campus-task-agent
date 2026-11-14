<script setup lang="ts">
/**
 * 事务列表（R3 / `C-CARD@2` / `C-FE-HALL@1` / `C-FE-PEEK@1` / `C-FE-HALL-RETURN@1`）。
 *
 * - 两个分区：活动（`GET /api/activities`）与任务（活动下第一层任务 + 独立任务）；
 * - 子任务不在本页重复铺满；
 * - 范围筛选同时作用于活动与任务（`scope=all|mine`）；
 * - 筛选：状态 / 范围 / 类型；≤768px 收进单个「筛选」按钮的底部抽屉；
 * - 桌面精确指针设备提供 200ms 悬浮预览；手机点击直接进入详情；
 * - 筛选与滚动位置保存在当前标签页 `sessionStorage`，从详情返回后恢复；
 * - 加载中不渲染空状态；本页不放发布入口（发布入口由外壳提供）；
 * - `variant="mine"` 复用同一实现作为独立「我的任务」页：范围锁定 `mine`，
 *   筛选与滚动位置使用独立键，不复制第二套查询逻辑。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { listActivities } from '../api/activities'
import { applyTask } from '../api/applications'
import { ApiError } from '../api/client'
import { listTasks } from '../api/tasks'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import HoverPeek from '../components/common/HoverPeek.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { STATUS_MAP, statusText } from '../components/task/StatusTag.vue'
import TaskCard, { formatDeadline, quotaText } from '../components/task/TaskCard.vue'
import { useUserStore } from '../stores/user'
import type { Activity, TaskItem } from '../types/models'

type ScopeValue = 'all' | 'mine'

interface HallViewState {
  status: string
  scope: ScopeValue
  type: string
  scrollTop: number
}

const HALL_VIEW_KEY = 'cta_hall_view'
const MY_TASKS_VIEW_KEY = 'cta_my_tasks_view'

const props = withDefaults(defineProps<{ variant?: 'hall' | 'mine' }>(), { variant: 'hall' })
/** 「我的任务」与大厅共用本组件，只锁定范围与文案 */
const isMineVariant = props.variant === 'mine'
const viewStorageKey = isMineVariant ? MY_TASKS_VIEW_KEY : HALL_VIEW_KEY

const router = useRouter()
const userStore = useUserStore()

function readHallView(): HallViewState {
  const fallback: HallViewState = {
    status: 'all',
    scope: isMineVariant ? 'mine' : 'all',
    type: 'all',
    scrollTop: 0
  }
  try {
    const raw = window.sessionStorage.getItem(viewStorageKey)
    if (!raw) return fallback
    const parsed: unknown = JSON.parse(raw)
    if (typeof parsed !== 'object' || parsed === null) return fallback
    const candidate = parsed as Partial<HallViewState>
    return {
      status: typeof candidate.status === 'string' ? candidate.status : 'all',
      scope: isMineVariant ? 'mine' : candidate.scope === 'mine' ? 'mine' : 'all',
      type: typeof candidate.type === 'string' ? candidate.type : 'all',
      scrollTop: typeof candidate.scrollTop === 'number' && candidate.scrollTop > 0 ? candidate.scrollTop : 0
    }
  } catch {
    return fallback
  }
}

const savedView = readHallView()
const activities = ref<Activity[]>([])
const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref(savedView.status)
const scope = ref<ScopeValue>(savedView.scope)
const typeFilter = ref(savedView.type)
const filterDrawerOpen = ref(false)
const applyingId = ref<number | null>(null)

/** 请求序号：快速切换筛选时只接受最后一次响应 */
let loadSeq = 0
/** 滚动写入节流定时器 */
let scrollWriteTimer: number | null = null
/** 加载期间用户已主动滚动时，不再用旧位置覆盖 */
let userScrolledDuringLoad = false
/** 页面已卸载：防止加载完成后的 scrollTo 作用到新页面 */
let disposed = false

/** 状态过滤项直接由 StatusTag 的映射表生成，保证文案唯一来源 */
const statusOptions = Object.entries(STATUS_MAP).map(([value, meta]) => ({
  value,
  label: meta.text
}))

const typeOptions = [
  { value: 'open', label: '公开报名' },
  { value: 'assign', label: '指派' }
]

const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)

/** 任务区 = 活动下第一层任务 + 独立任务；子任务不重复铺满 */
const visibleTasks = computed<TaskItem[]>(() =>
  tasks.value.filter(
    (task) =>
      task.parent_id === null &&
      (typeFilter.value === 'all' || task.claim_type === typeFilter.value)
  )
)

const activityTaskCount = computed<number>(
  () => visibleTasks.value.filter((task) => task.activity_id !== null).length
)
const independentTaskCount = computed<number>(
  () => visibleTasks.value.filter((task) => task.activity_id === null).length
)

/** 活动标题映射：任务卡显示所属活动，不新增后端字段 */
const activityTitleById = computed<Map<number, string>>(
  () => new Map(activities.value.map((activity) => [activity.id, activity.title]))
)

const hasFilter = computed<boolean>(
  () => statusFilter.value !== 'all' || (!isMineVariant && scope.value !== 'all') || typeFilter.value !== 'all'
)

const emptyTitle = computed<string>(() => {
  if (hasFilter.value) return '没有符合条件的任务'
  return isMineVariant ? '还没有与你相关的任务' : '暂无任务'
})
const emptyDescription = computed<string>(() => {
  if (hasFilter.value) return '试着切换状态、范围或类型筛选，或点击「刷新」重新加载。'
  return isMineVariant
    ? '你还没有需要执行或管理的任务；报名通过或成为负责人后，任务会出现在这里。'
    : '还没有人发布任务，可以在发布页创建第一个事务。'
})

/** 当前筛选摘要：不依赖按钮高亮即可读到「现在筛了什么」 */
const activeFilterText = computed<string>(() => {
  const parts: string[] = []
  if (statusFilter.value !== 'all') parts.push(`状态：${statusText(statusFilter.value)}`)
  if (!isMineVariant && scope.value !== 'all') parts.push('范围：我的任务与活动')
  if (typeFilter.value !== 'all') {
    const matched = typeOptions.find((option) => option.value === typeFilter.value)
    parts.push(`类型：${matched?.label ?? typeFilter.value}`)
  }
  return parts.length > 0 ? parts.join(' · ') : isMineVariant ? '我的全部任务与活动' : '全部事务'
})

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function taskQuery(): { status?: string; scope: 'all' | 'mine'; include_sub: boolean } {
  return {
    status: statusFilter.value === 'all' ? undefined : statusFilter.value,
    scope: scope.value,
    include_sub: true
  }
}

function writeHallView(): void {
  try {
    window.sessionStorage.setItem(
      viewStorageKey,
      JSON.stringify({
        status: statusFilter.value,
        scope: scope.value,
        type: typeFilter.value,
        scrollTop: Math.max(0, Math.round(window.scrollY))
      } satisfies HallViewState)
    )
  } catch {
    // 隐私模式下无法持久化时仅保留本次内存状态
  }
}

/** 滚动时 200ms 节流写入，避免每帧同步写 sessionStorage；刷新前由 beforeunload 兜底 */
function scheduleWrite(): void {
  if (scrollWriteTimer !== null) window.clearTimeout(scrollWriteTimer)
  scrollWriteTimer = window.setTimeout(() => {
    scrollWriteTimer = null
    writeHallView()
  }, 200)
}

function handleScroll(): void {
  if (!loading.value) scheduleWrite()
}

/** 只有用户主动滚轮 / 触摸 / 翻页键才取消恢复；浏览器保留详情页 scrollY 不算主动滚动 */
function markUserScroll(): void {
  if (loading.value) userScrolledDuringLoad = true
}

function markUserKeyScroll(event: KeyboardEvent): void {
  if ([' ', 'PageDown', 'PageUp', 'ArrowDown', 'ArrowUp', 'End', 'Home'].includes(event.key)) {
    markUserScroll()
  }
}

function handleBeforeUnload(): void {
  writeHallView()
}

async function loadAll(): Promise<void> {
  const seq = ++loadSeq
  loading.value = true
  error.value = ''
  try {
    const [taskResult, activityResult] = await Promise.all([
      listTasks(taskQuery()),
      listActivities({ scope: scope.value })
    ])
    if (seq !== loadSeq) return
    tasks.value = taskResult?.items ?? []
    activities.value = activityResult?.items ?? []
  } catch (err) {
    if (seq !== loadSeq) return
    tasks.value = []
    activities.value = []
    error.value = errorMessage(err)
  } finally {
    if (seq === loadSeq) loading.value = false
  }
}

/** 筛选变化：活动与任务共用范围，必须同时重载 */
function handleFilterChange(): void {
  writeHallView()
  void loadAll()
}

/** 清空筛选并重新加载（无筛选时为空操作） */
function resetFilters(): void {
  if (!hasFilter.value) return
  statusFilter.value = 'all'
  scope.value = isMineVariant ? 'mine' : 'all'
  typeFilter.value = 'all'
  writeHallView()
  void loadAll()
}

function goDetail(id: number): void {
  void router.push({ name: 'detail', params: { id } })
}

function goActivity(id: number): void {
  void router.push({ name: 'activity', params: { id } })
}

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.length > 16 ? value.slice(0, 16) : value
}

/** 报名（A1）：返回 `ApplyResult`，成功后本卡片的 `my_application_status` 变为 `pending` */
async function handleApply(task: TaskItem): Promise<void> {
  if (applyingId.value !== null) return
  applyingId.value = task.id
  try {
    const result = await applyTask(task.id)
    // 返回值是 ApplyResult，任务数据在 `result.task`（不得当作 TaskItem）
    const taskTitle = result.task?.title ?? task.title
    ElMessage.success(`已报名《${taskTitle}》，等待发布者审核`)
    await loadAll()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    applyingId.value = null
  }
}

onMounted(async () => {
  disposed = false
  window.addEventListener('scroll', handleScroll, { passive: true })
  window.addEventListener('beforeunload', handleBeforeUnload)
  window.addEventListener('wheel', markUserScroll, { passive: true })
  window.addEventListener('touchmove', markUserScroll, { passive: true })
  window.addEventListener('keydown', markUserKeyScroll)
  await loadAll()
  await nextTick()
  if (disposed) return
  if (savedView.scrollTop > 0 && !userScrolledDuringLoad) {
    window.scrollTo({ top: savedView.scrollTop, behavior: 'auto' })
  }
})

onBeforeUnmount(() => {
  disposed = true
  loadSeq += 1
  window.removeEventListener('scroll', handleScroll)
  window.removeEventListener('beforeunload', handleBeforeUnload)
  window.removeEventListener('wheel', markUserScroll)
  window.removeEventListener('touchmove', markUserScroll)
  window.removeEventListener('keydown', markUserKeyScroll)
  if (scrollWriteTimer !== null) {
    window.clearTimeout(scrollWriteTimer)
    scrollWriteTimer = null
  }
  writeHallView()
})
</script>

<template>
  <section class="app-page hall" :aria-busy="loading ? 'true' : 'false'">
    <header class="app-page-header hall-header">
      <div class="hall-heading">
        <h1 class="app-page-title">{{ isMineVariant ? '我的任务' : '任务大厅' }}</h1>
        <p class="app-page-subtitle" aria-live="polite">
          <template v-if="loading">正在加载{{ isMineVariant ? '我的' : '' }}事务…</template>
          <template v-else>
            共 {{ activities.length }} 个活动 · {{ activityTaskCount }} 个活动任务 ·
            {{ independentTaskCount }} 个独立任务
          </template>
        </p>
      </div>
      <el-button class="hall-refresh" :loading="loading" @click="loadAll">刷新</el-button>
    </header>

    <LoadingState v-if="loading" :rows="4" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="事务列表加载失败，请检查后端服务后重试。"
      retryable
      @retry="loadAll"
    />

    <template v-else>
      <section class="hall-region hall-region--activities" aria-labelledby="hall-activities-heading">
        <div class="region-head">
          <h2 id="hall-activities-heading" class="region-title">活动</h2>
          <span class="region-count">{{ activities.length }} 个</span>
        </div>

        <p v-if="activities.length === 0" class="region-empty">
          {{ scope === 'mine' ? '暂无与你相关的活动' : '暂无活动' }}
        </p>

        <ul v-else class="activity-list">
          <li v-for="activity in activities" :key="activity.id">
            <HoverPeek class="peek-item">
              <article class="activity-item">
                <h3 class="activity-title">
                  <router-link :to="`/activities/${activity.id}`">{{ activity.title }}</router-link>
                </h3>
                <p class="activity-progress">
                  整体进度 {{ activity.progress.percent }}% ·
                  {{ activity.progress.completed_tasks }}/{{ activity.progress.total_tasks }} 个任务已完成
                </p>
                <p class="activity-meta">
                  负责人 {{ activity.owner_name || '—' }} · 截止
                  {{ formatDeadline(activity.deadline) }}
                </p>
                <div class="activity-actions">
                  <el-button size="small" text type="primary" @click="goActivity(activity.id)">
                    查看活动
                  </el-button>
                </div>
              </article>

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
                <p class="preview-hint">点击进入活动详情查看任务树</p>
              </template>
            </HoverPeek>
          </li>
        </ul>
      </section>

      <section class="hall-region hall-region--tasks" aria-labelledby="hall-tasks-heading">
        <div class="region-head">
          <h2 id="hall-tasks-heading" class="region-title">任务</h2>
          <span class="region-count">{{ visibleTasks.length }} 个</span>
        </div>

        <div class="filter-mobile-row">
          <span class="app-muted">当前筛选：{{ activeFilterText }}</span>
          <el-button @click="filterDrawerOpen = true">筛选</el-button>
        </div>

        <section class="app-section-card filter-panel" aria-label="事务筛选">
          <div class="filter-row">
            <span class="filter-label">状态</span>
            <el-radio-group v-model="statusFilter" class="filter-group" @change="handleFilterChange">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button v-for="option in statusOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <div v-if="!isMineVariant" class="filter-row">
            <span class="filter-label">范围</span>
            <el-radio-group v-model="scope" class="filter-group" @change="handleFilterChange">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button value="mine">我的任务与活动</el-radio-button>
            </el-radio-group>
          </div>

          <div class="filter-row">
            <span class="filter-label">类型</span>
            <el-radio-group v-model="typeFilter" class="filter-group" @change="handleFilterChange">
              <el-radio-button value="all">全部</el-radio-button>
              <el-radio-button v-for="option in typeOptions" :key="option.value" :value="option.value">
                {{ option.label }}
              </el-radio-button>
            </el-radio-group>
          </div>

          <div class="filter-current">
            <span class="app-muted">当前筛选：{{ activeFilterText }}</span>
            <el-button v-if="hasFilter" text type="primary" size="small" @click="resetFilters">
              清除筛选
            </el-button>
          </div>
        </section>

        <EmptyState
          v-if="visibleTasks.length === 0"
          :title="emptyTitle"
          :description="emptyDescription"
        />

        <div v-else class="task-grid">
          <HoverPeek v-for="task in visibleTasks" :key="task.id" class="peek-item">
            <TaskCard
              :task="task"
              :current-user-id="currentUserId"
              :applying="applyingId === task.id"
              :activity-title="
                task.activity_id !== null ? activityTitleById.get(task.activity_id) : undefined
              "
              @apply="handleApply"
              @open="goDetail"
              @manage="goDetail"
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
              <p class="preview-hint">点击「查看详情」进入任务页</p>
            </template>
          </HoverPeek>
        </div>
      </section>
    </template>

    <el-drawer v-model="filterDrawerOpen" direction="btt" size="70%" title="筛选">
      <div class="drawer-filters">
        <div class="filter-row">
          <span class="filter-label">状态</span>
          <el-radio-group v-model="statusFilter" class="filter-group" @change="handleFilterChange">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="option in statusOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
        </div>

        <div v-if="!isMineVariant" class="filter-row">
          <span class="filter-label">范围</span>
          <el-radio-group v-model="scope" class="filter-group" @change="handleFilterChange">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button value="mine">我的任务与活动</el-radio-button>
          </el-radio-group>
        </div>

        <div class="filter-row">
          <span class="filter-label">类型</span>
          <el-radio-group v-model="typeFilter" class="filter-group" @change="handleFilterChange">
            <el-radio-button value="all">全部</el-radio-button>
            <el-radio-button v-for="option in typeOptions" :key="option.value" :value="option.value">
              {{ option.label }}
            </el-radio-button>
          </el-radio-group>
        </div>

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
  gap: 12px;
}

.hall-heading {
  min-width: 0;
}

.hall-region {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.region-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.region-title {
  margin: 0;
  font-size: var(--app-font-section-title, 19px);
  font-weight: 600;
  line-height: 1.3;
  color: var(--app-text);
}

.region-count {
  font-size: var(--app-font-aux, 13px);
  color: var(--app-text-muted);
}

.region-empty {
  margin: 0;
  padding: 12px 14px;
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
  font-size: var(--app-font-aux-lg, 14px);
  color: var(--app-text-secondary);
}

.activity-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  gap: 16px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.peek-item {
  height: 100%;
}

.activity-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  height: 100%;
  box-sizing: border-box;
  padding: 12px 14px;
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-sm);
}

.activity-title {
  margin: 0;
  font-size: var(--el-font-size-medium);
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}

.activity-title a {
  color: var(--app-text);
  text-decoration: none;
}

.activity-title a:hover {
  color: var(--app-primary);
}

.activity-progress,
.activity-meta {
  margin: 0;
  font-size: var(--app-font-aux, 13px);
  line-height: 1.5;
  color: var(--app-text-secondary);
}

.activity-meta {
  color: var(--app-text-muted);
}

.activity-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: auto;
  padding-top: 8px;
}

.activity-actions :deep(.el-button) {
  min-height: var(--app-touch);
}

.filter-mobile-row {
  display: none;
}

.filter-panel {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px 16px;
}

.filter-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
}

.filter-label {
  font-size: var(--app-font-aux-lg, 14px);
  color: var(--app-text-secondary);
  width: 32px;
  flex-shrink: 0;
}

.filter-group {
  flex-wrap: wrap;
  min-width: 0;
}

.filter-current {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  font-size: var(--app-font-aux, 13px);
  border-top: 1px dashed var(--app-border);
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr));
  gap: 16px;
}

.preview-title {
  margin: 0 0 6px;
  color: var(--app-text);
  font-size: var(--app-font-body, 15px);
  font-weight: 600;
  word-break: break-word;
}

.preview-desc {
  margin: 0 0 8px;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg, 14px);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
}

.preview-facts {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0;
}

.preview-facts > div {
  display: flex;
  align-items: baseline;
  gap: 8px;
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
  margin: 8px 0 0;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux, 13px);
}

.drawer-filters {
  display: flex;
  flex-direction: column;
  gap: 16px;
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

/* 手机：筛选收进单个「筛选」按钮的底部抽屉；任务前置以保证首屏可见 */
@media (max-width: 768px) {
  .hall-header {
    order: 0;
  }

  .hall-region--tasks {
    order: 1;
  }

  .hall-region--activities {
    order: 2;
  }

  .hall-refresh {
    min-width: var(--app-touch);
    min-height: var(--app-touch);
  }

  .filter-mobile-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    font-size: var(--app-font-aux, 13px);
  }

  .filter-panel {
    display: none;
  }

  .filter-mobile-row :deep(.el-button),
  .drawer-footer :deep(.el-button) {
    min-height: var(--app-touch);
  }

  .activity-title a {
    display: inline-flex;
    align-items: center;
    min-height: var(--app-touch);
  }

  .filter-label {
    width: auto;
    font-size: var(--app-font-body, 15px);
  }

  .filter-group {
    width: 100%;
  }

  .filter-group :deep(.el-radio-button) {
    flex: 1 1 auto;
  }

  .filter-group :deep(.el-radio-button__inner) {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: var(--app-touch);
    padding: 0 12px;
    font-size: var(--app-font-body, 15px);
  }
}
</style>