<script setup lang="ts">
/**
 * 任务大厅（计划 T6 / R10-AC4 / R16-AC15）。
 *
 * - 卡片列表：标题 / 简介 / 名额进度 / 积分 / 截止 / 状态与报名状态标签 / 发布者；
 * - 过滤：状态（7 个状态 + 全部）、范围（全部 / 我的）；
 * - 报名：`applyBlockReason` 不为空时按钮置灰并给出原因（满额显示「名额已满」）；
 *   成功后提示「已报名，等待发布者审核」，按钮变为「已报名」；
 * - 三态：loading / error（可重试）/ empty，请求结束在 `finally` 中复位。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { applyTask } from '../api/applications'
import { ApiError } from '../api/client'
import { listTasks } from '../api/tasks'
import { STATUS_MAP } from '../components/task/StatusTag.vue'
import TaskCard from '../components/task/TaskCard.vue'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useUserStore } from '../stores/user'
import type { TaskItem } from '../types/models'

const router = useRouter()
const userStore = useUserStore()

const tasks = ref<TaskItem[]>([])
const loading = ref(false)
const error = ref('')
const statusFilter = ref('all')
const scope = ref('all')
const applyingId = ref<number | null>(null)

/** 状态过滤项直接由 StatusTag 的映射表生成，保证文案唯一来源 */
const statusOptions = Object.entries(STATUS_MAP).map(([value, meta]) => ({
  value,
  label: meta.text
}))

const currentUserId = computed<number | null>(() => userStore.user?.id ?? null)
const hasFilter = computed<boolean>(() => statusFilter.value !== 'all' || scope.value !== 'all')
const emptyTitle = computed<string>(() => (hasFilter.value ? '没有符合条件的任务' : '暂无任务'))
const emptyDescription = computed<string>(() =>
  hasFilter.value
    ? '试着切换状态或范围筛选，或点击「刷新」重新加载。'
    : '还没有人发布任务，去「发布任务」页创建第一个任务吧。'
)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listTasks({
      status: statusFilter.value === 'all' ? undefined : statusFilter.value,
      scope: scope.value === 'mine' ? 'mine' : 'all',
      include_sub: true
    })
    tasks.value = result?.items ?? []
  } catch (err) {
    tasks.value = []
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function goDetail(id: number): void {
  void router.push({ name: 'detail', params: { id } })
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
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    applyingId.value = null
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="hall">
    <header class="page-header">
      <div>
        <h2 class="page-title">任务大厅</h2>
        <p class="page-subtitle">
          共 {{ tasks.length }} 个任务 · 报名通过后可在任务详情页更新进度、签到并提交完成
        </p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </header>

    <el-card shadow="never" class="filter-bar">
      <div class="filter-row">
        <span class="filter-label">状态</span>
        <el-radio-group v-model="statusFilter" size="small" @change="load">
          <el-radio-button value="all">全部</el-radio-button>
          <el-radio-button v-for="option in statusOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </el-radio-button>
        </el-radio-group>
      </div>
      <div class="filter-row">
        <span class="filter-label">范围</span>
        <el-radio-group v-model="scope" size="small" @change="load">
          <el-radio-button value="all">全部任务</el-radio-button>
          <el-radio-button value="mine">我的任务</el-radio-button>
        </el-radio-group>
        <span class="filter-hint">「我的任务」= 我发布的 + 我报名通过的任务</span>
      </div>
    </el-card>

    <LoadingState v-if="loading" :rows="4" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="任务列表加载失败，请检查后端服务后重试。"
      retryable
      @retry="load"
    />

    <EmptyState v-else-if="tasks.length === 0" :title="emptyTitle" :description="emptyDescription" />

    <div v-else class="task-grid">
      <TaskCard
        v-for="task in tasks"
        :key="task.id"
        :task="task"
        :current-user-id="currentUserId"
        :applying="applyingId === task.id"
        @apply="handleApply"
        @open="goDetail"
      />
    </div>
  </section>
</template>

<style scoped>
.hall {
  max-width: 1200px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.page-title {
  margin: 0 0 4px;
  font-size: 20px;
  color: #303133;
}

.page-subtitle {
  margin: 0;
  font-size: 14px;
  color: #909399;
}

.filter-bar {
  border-radius: 10px;
}

.filter-bar :deep(.el-card__body) {
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
  font-size: 14px;
  color: #606266;
  width: 32px;
  flex-shrink: 0;
}

.filter-hint {
  font-size: 13px;
  color: #c0c4cc;
}

.task-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 16px;
}
</style>