<script setup lang="ts">
/**
 * 消息页（契约 C-SEMANTIC@1；通知数据来自既有通知 store）。
 *
 * 通知集中在此页展示；未读数、单条已读与全部已读都经由 store 动作，
 * 由 store 同步后端计数，不在页面内自行推算未读总数。
 */
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'

import { ApiError } from '../api/client'
import EmptyState from '../components/common/EmptyState.vue'
import ErrorState from '../components/common/ErrorState.vue'
import LoadingState from '../components/common/LoadingState.vue'
import { useNotificationsStore } from '../stores/notifications'
import type { NotificationItem } from '../types/models'

type NoticeLevelType = 'info' | 'warning' | 'danger' | 'success'

const NOTICE_LEVELS: Record<string, { text: string; type: NoticeLevelType }> = {
  info: { text: '通知', type: 'info' },
  warning: { text: '提醒', type: 'warning' },
  urgent: { text: '紧急', type: 'danger' },
  overdue: { text: '逾期', type: 'danger' }
}

const router = useRouter()
const notificationsStore = useNotificationsStore()

const loading = ref(false)
const error = ref('')

const items = computed<NotificationItem[]>(() => notificationsStore.items)
const unreadCount = computed<number>(() => notificationsStore.unread)
const unreadIds = computed<number[]>(() =>
  notificationsStore.items.filter((item) => item.is_read === 0).map((item) => item.id)
)

function levelMeta(level: string): { text: string; type: NoticeLevelType } {
  return NOTICE_LEVELS[level] ?? NOTICE_LEVELS.info
}

function shortTime(value: string | null): string {
  if (!value) return '—'
  return value.length > 16 ? value.slice(0, 16) : value
}

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === -1) return '无法连接后端服务，请确认后端已在 8000 端口启动'
    return err.message || '请求失败'
  }
  return '请求失败，请稍后重试'
}

async function loadNotices(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    await notificationsStore.refresh()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    loading.value = false
  }
}

async function markRead(id: number): Promise<void> {
  try {
    await notificationsStore.markRead([id])
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

async function markAllRead(): Promise<void> {
  if (unreadIds.value.length === 0) return
  try {
    await notificationsStore.markRead([...unreadIds.value])
    ElMessage.success('已全部标记为已读')
  } catch (err) {
    ElMessage.error(errorMessage(err))
  }
}

function openTask(id: number): void {
  void router.push({ name: 'detail', params: { id } })
}

onMounted(() => {
  void loadNotices()
})
</script>

<template>
  <section class="app-page messages" :aria-busy="loading ? 'true' : 'false'">
    <header class="app-page-header">
      <div>
        <h1 class="app-page-title">消息</h1>
        <p class="app-page-subtitle">未读 {{ unreadCount }} 条 · 共 {{ items.length }} 条通知</p>
      </div>
      <div class="app-actions">
        <el-button
          class="header-button"
          :disabled="unreadIds.length === 0"
          :loading="loading"
          @click="markAllRead"
        >
          全部标为已读
        </el-button>
        <el-button class="header-button" :loading="loading" @click="loadNotices">刷新</el-button>
      </div>
    </header>

    <LoadingState v-if="loading" :rows="4" />
    <ErrorState
      v-else-if="error"
      :message="error"
      detail="通知列表加载失败，请稍后重试。"
      retryable
      @retry="loadNotices"
    />
    <template v-else>
      <EmptyState
        v-if="items.length === 0"
        title="暂无通知"
        description="任务被报名、提交、验收或临近截止时，这里会收到提醒。"
      />
      <section v-else class="app-section-card" aria-labelledby="messages-list-heading">
        <h2 id="messages-list-heading" class="section-title">
          通知列表
          <span v-if="unreadCount > 0" class="unread-count">未读 {{ unreadCount }} 条</span>
        </h2>
        <ul class="notice-list">
          <li
            v-for="item in items"
            :key="item.id"
            class="notice-item"
            :class="{ unread: item.is_read === 0 }"
          >
            <div class="notice-head">
              <el-tag :type="levelMeta(item.level).type" size="small" effect="light">
                {{ levelMeta(item.level).text }}
              </el-tag>
              <span class="notice-title">{{ item.title }}</span>
              <span v-if="item.is_read === 0" class="unread-flag">未读</span>
              <span class="notice-time">{{ shortTime(item.created_at) }}</span>
            </div>
            <p class="notice-content">{{ item.content }}</p>
            <div class="notice-actions">
              <el-button
                v-if="item.task_id !== null"
                class="notice-action"
                text
                type="primary"
                @click="openTask(item.task_id)"
              >
                查看任务
              </el-button>
              <el-button
                v-if="item.is_read === 0"
                class="notice-action"
                text
                @click="markRead(item.id)"
              >
                标记已读
              </el-button>
            </div>
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>

<style scoped>
.section-title {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
  margin: 0 0 var(--app-space-3);
  font-size: var(--app-font-section-title);
  font-weight: 600;
  line-height: 1.4;
  color: var(--app-text);
}

.unread-count {
  font-size: var(--app-font-aux);
  font-weight: 400;
  color: var(--app-text-muted);
}

.header-button {
  min-height: var(--app-touch);
}

.notice-list {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin: 0;
  padding: 0;
}

.notice-item {
  min-width: 0;
  padding: var(--app-space-3);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-sunken);
}

.notice-item.unread {
  border-color: var(--el-color-primary-light-7);
  background: var(--el-color-primary-light-9);
}

.notice-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--app-space-2);
}

.notice-title {
  font-size: var(--app-font-body);
  font-weight: 600;
  line-height: 1.5;
  color: var(--app-text);
  word-break: break-word;
}

.unread-flag {
  font-size: var(--app-font-aux);
  color: var(--el-color-danger);
}

.notice-time {
  margin-left: auto;
  font-size: var(--app-font-aux);
  color: var(--app-text-muted);
}

.notice-content {
  margin: var(--app-space-1) 0 0;
  font-size: var(--app-font-aux-lg);
  line-height: 1.7;
  color: var(--app-text-secondary);
  white-space: pre-wrap;
  word-break: break-word;
}

.notice-actions {
  display: flex;
  flex-wrap: wrap;
  gap: var(--app-space-1);
  margin-top: var(--app-space-1);
}

.notice-action {
  min-height: var(--app-touch);
}

@media (max-width: 768px) {
  .notice-time {
    margin-left: 0;
  }

  .notice-actions {
    width: 100%;
  }
}
</style>