<script setup lang="ts">
/**
 * 归档通知页（契约 C-ARCHIVE-PAGE@1）。
 *
 * 只读：数据来自既有 `notificationsStore.loadArchived()`，不提供取消归档。
 * 列表为单行圆角长条；关联任务的通知可整条点击进入任务详情。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'

import { ApiError } from '../api/client'
import { useNotificationsStore } from '../stores/notifications'
import type { NotificationItem } from '../types/models'

const router = useRouter()
const notificationsStore = useNotificationsStore()

const loading = ref(false)
const error = ref('')

const archivedItems = computed<NotificationItem[]>(() => notificationsStore.archivedItems)

function shortTime(value: string | null): string {
  if (!value) return '—'
  return value.slice(0, 16).replace('T', ' ')
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function loadArchived(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await notificationsStore.loadArchived()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

function openTask(item: NotificationItem): void {
  if (item.task_id === null) return
  void router.push({ name: 'detail', params: { id: item.task_id } })
}

onMounted(() => {
  void loadArchived()
})
</script>

<template>
  <section class="app-page archive-page" :aria-busy="loading ? 'true' : 'false'">
    <p v-if="loading" class="archive-line">加载中…</p>
    <div v-else-if="error" class="archive-error">
      <span class="archive-line">{{ error }}</span>
      <button type="button" class="archive-retry" @click="loadArchived">重试</button>
    </div>
    <p v-else-if="archivedItems.length === 0" class="archive-line">暂无归档</p>
    <ul v-else class="archive-list">
      <li v-for="item in archivedItems" :key="item.id" class="archive-item">
        <button
          v-if="item.task_id !== null"
          type="button"
          class="archive-item__main"
          @click="openTask(item)"
        >
          <span class="archive-item__title">{{ item.title }}</span>
          <span class="archive-item__time">{{ shortTime(item.created_at) }}</span>
        </button>
        <div v-else class="archive-item__main">
          <span class="archive-item__title">{{ item.title }}</span>
          <span class="archive-item__time">{{ shortTime(item.created_at) }}</span>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.archive-page {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.archive-line {
  margin: 0;
  padding: var(--app-space-2) var(--app-space-4);
  min-height: var(--app-touch);
  display: flex;
  align-items: center;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux);
}

.archive-error {
  display: flex;
  align-items: center;
  gap: var(--app-space-2);
}

.archive-retry {
  min-height: var(--app-touch);
  padding: 0 var(--app-space-4);
  border: 1px solid var(--app-border);
  border-radius: 999px;
  background: var(--app-surface);
  color: var(--app-text);
  font-size: var(--app-font-aux);
  cursor: pointer;
}

.archive-list {
  margin: 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
}

.archive-item {
  border-radius: 999px;
  padding: var(--app-space-2) var(--app-space-4);
  min-height: var(--app-touch);
  border: 1px solid var(--app-border);
  background: var(--app-surface);
  display: flex;
  align-items: center;
}

.archive-item__main {
  flex: 1 1 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-4);
  padding: 0;
  border: 0;
  background: none;
  color: inherit;
  font: inherit;
  text-align: left;
}

button.archive-item__main {
  cursor: pointer;
}

button.archive-item__main:hover .archive-item__title {
  color: var(--el-color-primary);
}

.archive-item__title {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.archive-item__time {
  flex: 0 0 auto;
  color: var(--app-text-muted);
  font-size: var(--app-font-aux);
}

@media (max-width: 768px) {
  .archive-item {
    padding: var(--app-space-2) var(--app-space-3);
  }
}
</style>