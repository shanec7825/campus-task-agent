<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ThemeToggle from '../components/common/ThemeToggle.vue'
import { useSSE } from '../composables/useSSE'
import { useNotificationsStore } from '../stores/notifications'
import { useUserStore } from '../stores/user'

/**
 * 应用外壳（契约 C-NAV@1）。
 *
 * - 桌面顶部导航 ≥769px；手机底部导航 ≤768px（发布者后台仅 publisher 可见）；
 * - 当前页链接带 `aria-current="page"`；
 * - 未读红点：`notificationsStore.unread`，点击跳 `/profile#notifications`；
 * - 退出：清理 SSE / 通知 / 用户后 replace 到登录页；
 * - 挂载时恢复会话、拉取通知并建立 SSE，卸载时断开。
 */
interface NavItem {
  path: string
  label: string
  testId: string
}

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const notificationsStore = useNotificationsStore()
const sse = useSSE()

const isPublisher = computed<boolean>(() => userStore.isPublisher)
const isLoggedIn = computed<boolean>(() => userStore.isLoggedIn)
const displayName = computed<string>(() => userStore.displayName)
const unread = computed<number>(() => notificationsStore.unread)

const navItems = computed<NavItem[]>(() => {
  const items: NavItem[] = [
    { path: '/tasks', label: '任务大厅', testId: 'mobile-nav-tasks' },
    { path: '/publish', label: '发布任务', testId: 'mobile-nav-publish' },
    { path: '/profile', label: '个人中心', testId: 'mobile-nav-profile' }
  ]
  if (isPublisher.value) {
    items.push({ path: '/admin', label: '发布者后台', testId: 'mobile-nav-admin' })
  }
  return items
})

function isActive(path: string): boolean {
  // 任务详情 `/tasks/:id` 仍归属任务大厅
  if (path === '/tasks') return route.path === '/tasks' || route.path.startsWith('/tasks/')
  return route.path === path
}

function navigate(path: string): void {
  if (route.path !== path) void router.push(path)
}

onMounted(async () => {
  if (!userStore.isLoggedIn) return

  // 刷新页面后恢复会话（token 在 localStorage，user 可能尚未加载）
  if (!userStore.user) {
    try {
      await userStore.fetchMe()
    } catch {
      // 401 已由 client 清理凭证并跳转登录页
      return
    }
  }
  if (!userStore.isLoggedIn) return

  try {
    await notificationsStore.fetchList()
  } catch {
    // 红点拉取失败不阻塞主页面
  }
  sse.connect()
})

onBeforeUnmount(() => {
  sse.disconnect()
})

function openNotifications(): void {
  void router.push({ name: 'profile', hash: '#notifications' })
}

function handleLogout(): void {
  sse.disconnect()
  notificationsStore.reset()
  userStore.logout()
  void router.replace({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <header class="app-header" data-testid="app-header">
      <div class="app-header-inner">
        <a class="brand" href="/tasks" @click.prevent="navigate('/tasks')">校园任务协同</a>

        <nav class="desktop-nav" data-testid="desktop-nav" aria-label="主导航">
          <a
            v-for="item in navItems"
            :key="item.path"
            :href="item.path"
            class="nav-link"
            :class="{ 'is-active': isActive(item.path) }"
            :aria-current="isActive(item.path) ? 'page' : undefined"
            @click.prevent="navigate(item.path)"
          >
            {{ item.label }}
          </a>
        </nav>

        <div class="header-actions">
          <ThemeToggle />

          <!-- 未读通知红点：点击跳个人中心通知区 -->
          <el-badge :value="unread" :hidden="unread === 0" :max="99" class="notify-badge">
            <button
              type="button"
              class="notify-button"
              data-testid="notify-button"
              :aria-label="unread > 0 ? `通知，${unread} 条未读` : '通知'"
              @click="openNotifications"
            >
              通知
            </button>
          </el-badge>

          <template v-if="isLoggedIn">
            <span class="username app-desktop-only">{{ displayName }}</span>
            <button
              type="button"
              class="logout-button"
              data-testid="logout-button"
              @click="handleLogout"
            >
              退出
            </button>
          </template>
        </div>
      </div>
    </header>

    <main class="app-main">
      <div class="app-main-inner">
        <!-- App.vue 传入 router-view；单独使用时回退到自带 router-view -->
        <slot>
          <router-view />
        </slot>
      </div>
    </main>

    <nav class="mobile-nav" data-testid="mobile-bottom-nav" aria-label="底部导航">
      <a
        v-for="item in navItems"
        :key="item.path"
        :href="item.path"
        class="mobile-nav-item"
        :class="{ 'is-active': isActive(item.path) }"
        :data-testid="item.testId"
        :aria-current="isActive(item.path) ? 'page' : undefined"
        @click.prevent="navigate(item.path)"
      >
        {{ item.label }}
      </a>
    </nav>
  </div>
</template>

<style scoped>
.app-shell {
  min-height: 100vh;
  background: var(--app-bg);
  color: var(--app-text);
}

.app-header {
  position: sticky;
  top: 0;
  z-index: 10;
  height: var(--app-header-height);
  background: var(--app-surface);
  border-bottom: 1px solid var(--app-border);
}

.app-header-inner {
  display: flex;
  align-items: center;
  gap: 20px;
  height: 100%;
  max-width: var(--app-content-max);
  margin: 0 auto;
  padding: 0 24px;
}

.brand {
  font-size: 16px;
  font-weight: 600;
  color: var(--app-text);
  text-decoration: none;
  white-space: nowrap;
}

.desktop-nav {
  display: flex;
  flex: 1;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.nav-link {
  display: inline-flex;
  align-items: center;
  padding: 8px 14px;
  border-radius: var(--app-radius-sm);
  color: var(--app-text-secondary);
  font-size: 14px;
  text-decoration: none;
  white-space: nowrap;
  transition:
    background-color 0.2s ease,
    color 0.2s ease;
}

.nav-link:hover {
  background: var(--app-surface-sunken);
  color: var(--app-text);
}

.nav-link.is-active {
  background: var(--app-primary-soft);
  color: var(--app-primary);
  font-weight: 600;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.notify-badge {
  display: inline-flex;
}

.notify-button,
.logout-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 44px;
  min-height: 44px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text-secondary);
  font-size: 14px;
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    color 0.2s ease;
}

.notify-button:hover,
.logout-button:hover {
  background: var(--app-surface-sunken);
  color: var(--app-text);
}

.logout-button {
  color: var(--el-color-danger);
}

.username {
  max-width: 160px;
  overflow: hidden;
  color: var(--app-text-secondary);
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.app-main {
  /* 横向留白交给路由页自身的 .app-page，避免双重 padding 挤压窄屏 */
  padding: 24px 0;
  padding-bottom: calc(
    var(--app-bottom-nav-height) + var(--app-safe-bottom) + var(--app-space-4, 16px)
  );
}

.app-main-inner {
  max-width: var(--app-content-max);
  margin: 0 auto;
}

.mobile-nav {
  display: none;
}

@media (max-width: 768px) {
  .app-header-inner {
    gap: 12px;
    padding: 0 16px;
  }

  .desktop-nav {
    display: none;
  }

  .username {
    display: none;
  }

  .app-main {
    padding: 16px 0;
    padding-bottom: calc(
      var(--app-bottom-nav-height) + var(--app-safe-bottom) + var(--app-space-4, 16px)
    );
  }

  .mobile-nav {
    position: fixed;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 20;
    display: flex;
    align-items: stretch;
    box-sizing: border-box;
    height: calc(var(--app-bottom-nav-height) + var(--app-safe-bottom));
    padding-bottom: var(--app-safe-bottom);
    background: var(--app-surface-raised);
    border-top: 1px solid var(--app-border);
    box-shadow: var(--app-shadow-sm);
  }

  .mobile-nav-item {
    display: flex;
    flex: 1;
    align-items: center;
    justify-content: center;
    min-width: var(--app-touch);
    min-height: var(--app-touch);
    color: var(--app-text-secondary);
    font-size: 13px;
    text-decoration: none;
    text-align: center;
  }

  .mobile-nav-item.is-active {
    color: var(--app-primary);
    font-weight: 600;
  }
}

@media (max-width: 360px) {
  /* 320px 临界：收紧间距让品牌可收缩，动作按钮保持 44×44 触控尺寸 */
  .app-header-inner {
    gap: 6px;
    padding: 0 10px;
  }

  .brand {
    min-width: 0;
    max-width: 96px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .header-actions {
    gap: 6px;
  }

  .notify-button,
  .logout-button {
    padding: 0 8px;
  }
}
</style>