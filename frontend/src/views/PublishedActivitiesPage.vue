<script setup lang="ts">
/**
 * 我发布的活动（`C-NAV-SCOPE@2`）。
 *
 * 数据来自 `GET /api/activities?scope=published`：服务端按 `owner_id` 过滤，
 * 只返回本人发布且本人可见的活动。组织管理员对别人活动的大厅范围仍由 `/tasks`
 * 与后台承担，本页不冒充。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { listActivities } from '../api/activities'
import { ApiError } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useUserStore } from '../stores/user'
import type { Activity } from '../types/models'

const router = useRouter()
const userStore = useUserStore()

const activities = ref<Activity[]>([])
const loading = ref(false)
const error = ref('')

const canPublish = computed<boolean>(() => userStore.isPublisher)

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

function dateText(value: string | null): string {
  if (!value) return '未设置'
  return value.length > 16 ? value.slice(0, 16) : value
}

function goDetail(id: number): void {
  void router.push({ name: 'activity', params: { id } })
}

function goPublish(): void {
  void router.push({ name: 'publish-activity' })
}

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    activities.value = (await listActivities({ scope: 'published' })).items
  } catch (err) {
    activities.value = []
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  void load()
})
</script>

<template>
  <section class="app-page published-page" :aria-busy="loading ? 'true' : 'false'">
    <header class="app-page-header published-page__header">
      <div class="published-page__heading">
        <h1 class="app-page-title">我发布的活动</h1>
        <p class="app-page-subtitle" aria-live="polite">
          <template v-if="loading">正在加载我发布的活动…</template>
          <template v-else>共 {{ activities.length }} 个活动 · 只显示本人发布的活动</template>
        </p>
      </div>
      <el-button
        v-if="canPublish"
        type="primary"
        class="published-page__publish"
        @click="goPublish"
      >
        发布活动
      </el-button>
    </header>

    <LoadingState v-if="loading" :rows="3" />

    <ErrorState
      v-else-if="error"
      :message="error"
      detail="我发布的活动加载失败，请检查后端服务后重试。"
      retryable
      @retry="load"
    />

    <EmptyState
      v-else-if="activities.length === 0"
      title="还没有你发布的活动"
      :description="
        canPublish
          ? '点击「发布活动」填写名称、时间地点与介绍，发布后可在本页进入详情继续拆分任务。'
          : '当前账号没有发布活动的权限；你参与或管理过的活动可在「我的任务」中查看。'
      "
    />

    <ul v-else class="published-list">
      <li v-for="activity in activities" :key="activity.id" class="published-item">
        <h2 class="published-item__title">
          <router-link :to="`/activities/${activity.id}`">{{ activity.title }}</router-link>
        </h2>
        <p class="published-item__meta">
          负责人 {{ activity.owner_name || '—' }} · 截止 {{ dateText(activity.deadline) }}
        </p>
        <p v-if="activity.location" class="published-item__meta">地点 {{ activity.location }}</p>
        <p class="published-item__progress">
          整体进度 {{ activity.progress.percent }}% ·
          {{ activity.progress.completed_tasks }}/{{ activity.progress.total_tasks }} 个任务已完成
        </p>
        <div class="published-item__actions">
          <el-button size="small" text type="primary" @click="goDetail(activity.id)">
            查看活动
          </el-button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.published-page {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
}

.published-page__header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--app-space-3);
}

.published-page__heading {
  min-width: 0;
}

.published-page__publish {
  min-height: var(--app-touch);
}

.published-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  gap: var(--app-space-4);
  margin: 0;
  padding: 0;
  list-style: none;
}

.published-item {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
  box-sizing: border-box;
  height: 100%;
  padding: var(--app-space-3) var(--app-space-4);
  background: var(--app-surface);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  box-shadow: var(--app-shadow-sm);
}

.published-item__title {
  margin: 0;
  font-size: var(--app-font-body);
  font-weight: 600;
  line-height: 1.4;
  word-break: break-word;
}

.published-item__title a {
  color: var(--app-text);
  text-decoration: none;
}

.published-item__title a:hover {
  color: var(--app-primary);
}

.published-item__meta,
.published-item__progress {
  margin: 0;
  font-size: var(--app-font-aux);
  line-height: 1.5;
  color: var(--app-text-secondary);
  word-break: break-word;
}

.published-item__progress {
  color: var(--app-text-muted);
}

.published-item__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: auto;
  padding-top: var(--app-space-2);
}

.published-item__actions :deep(.el-button) {
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .published-page__publish {
    width: 100%;
  }
}
</style>