<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ThemeToggle from '../components/common/ThemeToggle.vue'
import { useSSE } from '../composables/useSSE'
import { PAGE_TITLES } from '../router'
import { useNotificationsStore } from '../stores/notifications'
import { useUserStore } from '../stores/user'
import type { OrgMembership } from '../types/models'

/**
 * 应用外壳（契约 C-ROUTE-NAV@1）。
 *
 * - ≥1025px：固定侧栏（品牌 / 主导航 / 管理入口 / 主题 / 用户与退出）+ 主内容列顶部组织上下文；
 * - 769–1024px：顶部横向导航 + 组织上下文，无侧栏；
 * - ≤768px：顶部标题栏（当前页标题 + 组织上下文）+ 四项底部导航（每项 44×44）；
 * - 发布主入口仅出现在桌面侧栏，手机端由工作台标题区承载；
 * - 未读消息数在底部导航以文字呈现（如「消息 3」）。
 */
interface NavItem {
  name: string
  path: string
  label: string
}

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const notificationsStore = useNotificationsStore()
const sse = useSSE()

const unread = computed<number>(() => notificationsStore.unread)
const displayName = computed<string>(() => userStore.user?.display_name || userStore.user?.username || '')
const isLoggedIn = computed<boolean>(() => userStore.isLoggedIn)
const canAdmin = computed<boolean>(() => userStore.isAdmin || userStore.isPublisher)

const currentOrg = computed<OrgMembership | null>(() =>
  userStore.orgs.length > 0 ? userStore.orgs[0] : null
)
const orgName = computed<string>(() => currentOrg.value?.name || '未加入组织')
const roleText = computed<string>(() => {
  const role = currentOrg.value?.role
  if (role === 'admin') return '管理员'
  if (role === 'collaborator') return '协作者'
  if (role === 'member') return '成员'
  return ''
})
const pageTitle = computed<string>(() => {
  const name = typeof route.name === 'string' ? route.name : ''
  return PAGE_TITLES[name] ?? ''
})

const mainNav: NavItem[] = [
  { name: 'workbench', path: '/workbench', label: '工作台' },
  { name: 'hall', path: '/tasks', label: '事务' },
  { name: 'messages', path: '/messages', label: '消息' },
  { name: 'profile', path: '/profile', label: '我的' }
]

const mobileNav = computed<NavItem[]>(() =>
  mainNav.map((item) =>
    item.name === 'messages' && unread.value > 0
      ? { ...item, label: `${item.label} ${unread.value}` }
      : item
  )
)

function isActive(name: string): boolean {
  if (name === 'hall') {
    return route.name === 'hall' || route.name === 'detail' || route.name === 'activity'
  }
  return route.name === name
}

function navigate(item: NavItem): void {
  if (route.name !== item.name) void router.push({ name: item.name })
}

function goHome(): void {
  if (route.name !== 'workbench') void router.push({ name: 'workbench' })
}

function goAdmin(): void {
  if (route.name !== 'admin') void router.push({ name: 'admin' })
}

function openPublish(): void {
  void router.push({ name: 'publish' })
}

onMounted(async () => {
  // 会话已由路由守卫通过 Cookie 恢复（userStore.restore()）
  if (!userStore.isLoggedIn) return

  try {
    await notificationsStore.fetchList()
  } catch {
    // 未读数拉取失败不阻塞主页面
  }
  sse.connect()
})

onBeforeUnmount(() => {
  sse.disconnect()
})

async function handleLogout(): Promise<void> {
  sse.disconnect()
  notificationsStore.reset()
  // 等待服务端撤销会话后再清空本地状态（失败时 store 内部也会清空）
  await userStore.logout()
  void router.replace({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <aside class="app-sidebar" data-testid="app-sidebar" aria-label="应用侧栏">
      <div class="sidebar-head">
        <a class="brand" href="/workbench" @click.prevent="goHome">
          校园任务协同
        </a>
        <el-button class="publish-button" type="primary" data-testid="publish-button" @click="openPublish">
          发布事务
        </el-button>
      </div>

      <nav class="sidebar-nav" data-testid="desktop-nav" aria-label="主导航">
        <a
          v-for="item in mainNav"
          :key="item.name"
          :href="item.path"
          class="nav-link"
          :class="{ 'is-active': isActive(item.name) }"
          :aria-current="isActive(item.name) ? 'page' : undefined"
          @click.prevent="navigate(item)"
        >
          {{ item.label }}
        </a>
      </nav>

      <nav v-if="canAdmin" class="sidebar-nav sidebar-admin" aria-label="管理">
        <a
          href="/admin"
          class="nav-link"
          :class="{ 'is-active': isActive('admin') }"
          :aria-current="isActive('admin') ? 'page' : undefined"
          @click.prevent="goAdmin"
        >
          管理
        </a>
      </nav>

      <div class="sidebar-foot">
        <ThemeToggle />
        <p class="sidebar-user" :title="displayName">{{ displayName }}</p>
        <button type="button" class="text-button logout-button" data-testid="logout-button" @click="handleLogout">
          退出
        </button>
      </div>
    </aside>

    <header class="app-topbar" data-testid="app-header">
      <a class="brand" href="/workbench" @click.prevent="goHome">
        校园任务协同
      </a>

      <nav class="topbar-nav" aria-label="主导航">
        <a
          v-for="item in mainNav"
          :key="item.name"
          :href="item.path"
          class="nav-link"
          :class="{ 'is-active': isActive(item.name) }"
          :aria-current="isActive(item.name) ? 'page' : undefined"
          @click.prevent="navigate(item)"
        >
          {{ item.label }}
        </a>
        <a
          v-if="canAdmin"
          href="/admin"
          class="nav-link"
          :class="{ 'is-active': isActive('admin') }"
          :aria-current="isActive('admin') ? 'page' : undefined"
          @click.prevent="goAdmin"
        >
          管理
        </a>
      </nav>

      <!-- 平板形态没有侧栏，发布主入口由顶栏承载（≥1025px 由侧栏承载） -->
      <el-button
        class="publish-button-topbar"
        type="primary"
        data-testid="publish-button-topbar"
        @click="openPublish"
      >
        发布事务
      </el-button>

      <div class="topbar-actions">
        <p class="org-context">
          <span class="org-name">{{ orgName }}</span>
          <span class="org-role">{{ roleText }}</span>
        </p>
        <ThemeToggle />
        <span class="username">{{ displayName }}</span>
        <button type="button" class="text-button logout-button" @click="handleLogout">退出</button>
      </div>
    </header>

    <header class="app-mobile-bar" data-testid="app-mobile-header">
      <span class="mobile-title">{{ pageTitle }}</span>
      <p class="org-context org-context-mobile">
        <span class="org-name">{{ orgName }}</span>
        <span class="org-role">{{ roleText }}</span>
      </p>
    </header>

    <main id="main-content" class="app-content">
      <div class="app-context-bar" data-testid="org-context">
        <span class="org-name">{{ orgName }}</span>
        <span class="org-role">{{ roleText }}</span>
      </div>

      <div class="app-main-inner">
        <!-- App.vue 传入 router-view；单独使用时回退到自带 router-view -->
        <slot>
          <router-view />
        </slot>
      </div>
    </main>

    <nav class="app-bottom-nav" data-testid="mobile-bottom-nav" aria-label="底部导航">
      <a
        v-for="item in mobileNav"
        :key="item.name"
        :href="item.path"
        class="bottom-nav-item"
        :class="{ 'is-active': isActive(item.name) }"
        :data-testid="`mobile-nav-${item.name}`"
        :aria-current="isActive(item.name) ? 'page' : undefined"
        @click.prevent="navigate(item)"
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

/* ---- 手机（≤768px 默认形态） ---- */
.app-sidebar,
.app-topbar {
  display: none;
}

.app-mobile-bar {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--app-space-3);
  min-height: 56px;
  padding: var(--app-space-2) var(--app-space-4);
  background: var(--app-surface);
  border-bottom: 1px solid var(--app-border);
}

.mobile-title {
  margin: 0;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  color: var(--app-text);
}

.org-context {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: var(--app-space-1);
  margin: 0;
}

.org-context-mobile {
  flex-direction: column;
  align-items: flex-end;
  gap: 0;
  text-align: right;
}

.org-name {
  color: var(--app-text);
  font-size: var(--app-font-aux);
}

.org-role {
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux);
}

.app-content {
  padding: var(--app-space-4) 0;
  padding-bottom: calc(
    var(--app-bottom-nav-height) + var(--app-safe-bottom) + var(--app-space-4)
  );
}

.app-main-inner {
  max-width: var(--app-content-max);
  margin: 0 auto;
}

/* 组织上下文行只在桌面侧栏形态下出现 */
.app-context-bar {
  display: none;
}

.app-bottom-nav {
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

.bottom-nav-item {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  padding: 0 var(--app-space-1);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux);
  text-decoration: none;
  text-align: center;
}

.bottom-nav-item.is-active {
  color: var(--app-primary);
  font-weight: 600;
}

/* ---- 平板（769–1024px）：顶部横向导航，无侧栏 ---- */
@media (min-width: 769px) {
  .app-mobile-bar {
    display: none;
  }

  .app-bottom-nav {
    display: none;
  }

  .app-topbar {
    position: sticky;
    top: 0;
    z-index: 10;
    display: flex;
    align-items: center;
    gap: var(--app-space-5);
    box-sizing: border-box;
    height: var(--app-header-height);
    padding: 0 var(--app-space-5);
    background: var(--app-surface);
    border-bottom: 1px solid var(--app-border);
  }

  .topbar-nav {
    display: flex;
    flex: 1;
    align-items: center;
    gap: var(--app-space-2);
    min-width: 0;
    overflow-x: auto;
  }

  .topbar-actions {
    display: flex;
    align-items: center;
    gap: var(--app-space-3);
    margin-left: auto;
  }

  .app-content {
    padding: var(--app-space-5) 0;
    padding-bottom: var(--app-space-5);
  }
}

/* ---- 桌面（≥1025px）：固定侧栏 208px + 主内容列 ---- */
@media (min-width: 1025px) {
  .app-topbar {
    display: none;
  }

  .app-sidebar {
    position: fixed;
    top: 0;
    left: 0;
    z-index: 20;
    display: flex;
    flex-direction: column;
    gap: var(--app-space-4);
    box-sizing: border-box;
    width: 208px;
    height: 100vh;
    padding: var(--app-space-4);
    background: var(--app-surface);
    border-right: 1px solid var(--app-border);
  }

  .sidebar-head {
    display: flex;
    flex-direction: column;
    gap: var(--app-space-3);
  }

  .publish-button {
    width: 100%;
    min-height: var(--app-touch);
  }

  .sidebar-nav {
    display: flex;
    flex-direction: column;
    gap: var(--app-space-1);
  }

  .sidebar-admin {
    padding-top: var(--app-space-3);
    border-top: 1px solid var(--app-border);
  }

  .sidebar-foot {
    display: flex;
    align-items: center;
    gap: var(--app-space-2);
    margin-top: auto;
    padding-top: var(--app-space-3);
    border-top: 1px solid var(--app-border);
  }

  .sidebar-user {
    flex: 1;
    min-width: 0;
    margin: 0;
    overflow: hidden;
    color: var(--app-text);
    font-size: var(--app-font-aux-lg);
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .app-content {
    margin-left: 208px;
    padding: var(--app-space-5) 0;
    padding-bottom: var(--app-space-6);
  }

  .app-context-bar {
    display: flex;
    align-items: baseline;
    gap: var(--app-space-2);
    max-width: var(--app-content-max);
    margin: 0 auto var(--app-space-4);
    padding: 0 var(--app-space-5);
  }
}

/* ---- 公共导航与文本按钮 ---- */
.brand {
  color: var(--app-text);
  font-size: 16px;
  font-weight: 600;
  text-decoration: none;
  white-space: nowrap;
}

.nav-link {
  display: inline-flex;
  align-items: center;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border-radius: var(--app-radius-sm);
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
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

.text-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-text-secondary);
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
  transition:
    background-color 0.2s ease,
    color 0.2s ease;
}

.text-button:hover {
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
  font-size: var(--app-font-aux-lg);
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ---- 360px 临界：收紧间距，触控目标保持 44×44 ---- */
@media (max-width: 360px) {
  .app-mobile-bar {
    gap: var(--app-space-2);
    padding: var(--app-space-2) var(--app-space-3);
  }

  .mobile-title {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .app-topbar {
    gap: var(--app-space-3);
    padding: 0 var(--app-space-3);
  }

  .topbar-actions {
    gap: var(--app-space-1);
  }

  .username {
    display: none;
  }
}
</style>