<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import ThemeToggle from '../components/common/ThemeToggle.vue'
import { useSSE } from '../composables/useSSE'
import { PAGE_TITLES } from '../router'
import { listActivities } from '../api/activities'
import { listTasks } from '../api/tasks'
import { useAiChatStore } from '../stores/aiChat'
import { useNotificationsStore } from '../stores/notifications'
import { useUserStore } from '../stores/user'
import type { Activity, OrgMembership, TaskItem } from '../types/models'

/**
 * 应用外壳（契约 C-ROUTE-NAV@1 / C-FE-AI@1）。
 *
 * - ≥1025px：固定侧栏（品牌 / 主导航 / 管理入口 / 主题 / 用户与退出）+ 主内容列顶部组织上下文；
 *   侧栏可在 208px 与 72px 之间折叠，状态存 `cta_sidebar_collapsed`；
 * - 769–1024px：顶部横向导航 + 组织上下文，无侧栏；
 * - ≤768px：顶部标题栏（当前页标题 + 组织上下文）+ 四项底部导航（AI / 事务 / 消息 / 我的，每项 44×44）；
 * - 发布主入口仅出现在桌面展开态侧栏，手机端由工作台标题区承载；
 * - 未读消息数在底部导航以文字呈现（如「消息 3」）。
 */
interface NavItem {
  name: string
  path: string
  label: string
  short: string
}

const SIDEBAR_COLLAPSED_KEY = 'cta_sidebar_collapsed'
const MOBILE_NAMES = ['ai', 'hall', 'messages', 'profile']
/** 侧栏/抽屉最近条目上限：只减少预览数量，不隐藏正式列表数据 */
const RECENT_LIMIT = 5

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const notificationsStore = useNotificationsStore()
const aiChat = useAiChatStore()
const sse = useSSE()

const unread = computed<number>(() => notificationsStore.unread)
const displayName = computed<string>(() => userStore.user?.display_name || userStore.user?.username || '')
const isLoggedIn = computed<boolean>(() => userStore.isLoggedIn)
const canAdmin = computed<boolean>(() => userStore.isAdmin || userStore.isPublisher)
const collapsed = ref<boolean>(readCollapsed())
const mobileDrawerOpen = ref<boolean>(false)

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
  { name: 'ai', path: '/ai', label: 'AI 对话与通知', short: 'AI' },
  { name: 'hall', path: '/tasks', label: '任务大厅', short: '大厅' },
  { name: 'my-tasks', path: '/my-tasks', label: '我的任务', short: '我的' },
  { name: 'messages', path: '/messages', label: '消息', short: '消息' },
  { name: 'profile', path: '/profile', label: '个人主页', short: '个人' }
]

/** 管理者的额外入口；普通用户不渲染，直连接口仍由后端授权拒绝 */
const managerNav: NavItem[] = [
  {
    name: 'published-activities',
    path: '/published-activities',
    label: '我发布的活动',
    short: '发布'
  },
  { name: 'admin', path: '/admin', label: '发布者后台', short: '管理' }
]

const recentActivities = ref<Activity[]>([])
const recentTasks = ref<TaskItem[]>([])

const mobileNav = computed<NavItem[]>(() =>
  mainNav
    .filter((item) => MOBILE_NAMES.includes(item.name))
    .map((item) =>
      item.name === 'messages' && unread.value > 0
        ? { ...item, label: `${item.label} ${unread.value}` }
        : item
    )
)

function readCollapsed(): boolean {
  try {
    return typeof window !== 'undefined' && window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === '1'
  } catch {
    return false
  }
}

function toggleSidebar(): void {
  collapsed.value = !collapsed.value
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, collapsed.value ? '1' : '0')
  } catch {
    // 隐私模式下无法持久化时仅保留本次状态
  }
}

function isActive(name: string): boolean {
  const current = typeof route.name === 'string' ? route.name : ''
  if (name === 'hall') {
    return current === 'hall' || current === 'detail' || current === 'activity'
  }
  if (name === 'my-tasks') {
    return current === 'my-tasks'
  }
  if (name === 'published-activities') {
    return current === 'published-activities' || current === 'publish-activity'
  }
  return current === name
}

function navigate(item: NavItem): void {
  if (route.name !== item.name) void router.push({ name: item.name })
}

/** 最近条目：复用权限过滤后的列表摘要，不逐卡请求完整详情 */
async function loadRecent(): Promise<void> {
  if (!userStore.isLoggedIn) return
  try {
    const [activityResult, taskResult] = await Promise.all([
      listActivities({ scope: 'mine' }),
      listTasks({ scope: 'mine', include_sub: false })
    ])
    recentActivities.value = (activityResult?.items ?? []).slice(0, RECENT_LIMIT)
    recentTasks.value = (taskResult?.items ?? []).slice(0, RECENT_LIMIT)
  } catch {
    // 最近条目失败不阻塞主页面与主导航
    recentActivities.value = []
    recentTasks.value = []
  }
}

function goActivity(id: number): void {
  mobileDrawerOpen.value = false
  if (route.name === 'activity' && Number(route.params.id) === id) return
  void router.push({ name: 'activity', params: { id } })
}

function goTask(id: number): void {
  mobileDrawerOpen.value = false
  if (route.name === 'detail' && Number(route.params.id) === id) return
  void router.push({ name: 'detail', params: { id } })
}

function goAllActivities(): void {
  mobileDrawerOpen.value = false
  void router.push({ name: 'my-tasks' })
}

function goHome(): void {
  if (route.name !== 'ai') void router.push({ name: 'ai' })
}


function openPublish(): void {
  void router.push({ name: 'publish' })
}

function navigateFromDrawer(item: NavItem): void {
  mobileDrawerOpen.value = false
  navigate(item)
}


function publishFromDrawer(): void {
  mobileDrawerOpen.value = false
  openPublish()
}

onMounted(async () => {
  // 会话已由路由守卫通过 Cookie 恢复（userStore.restore()）
  if (!userStore.isLoggedIn) return

  try {
    await notificationsStore.fetchList()
  } catch {
    // 未读数拉取失败不阻塞主页面
  }
  void loadRecent()
  sse.connect()
})

onBeforeUnmount(() => {
  sse.disconnect()
})

async function handleLogout(): Promise<void> {
  mobileDrawerOpen.value = false
  sse.disconnect()
  notificationsStore.reset()
  aiChat.reset()
  try {
    window.sessionStorage.removeItem('cta_hall_view')
    window.sessionStorage.removeItem('cta_my_tasks_view')
  } catch {
    // 隐私模式下无法清理时不影响退出
  }
  // 等待服务端撤销会话后再清空本地状态（失败时 store 内部也会清空）
  await userStore.logout()
  void router.replace({ name: 'login' })
}
</script>

<template>
  <div class="app-shell">
    <aside
      id="app-sidebar"
      class="app-sidebar"
      :class="{ 'is-collapsed': collapsed }"
      data-testid="app-sidebar"
      aria-label="应用侧栏"
    >
      <div class="sidebar-head">
        <a class="brand" href="/ai" @click.prevent="goHome">
          {{ collapsed ? '校园' : '校园任务协同' }}
        </a>
        <button
          type="button"
          class="collapse-button"
          data-testid="sidebar-toggle"
          aria-controls="app-sidebar"
          :aria-label="collapsed ? '展开侧栏' : '收起侧栏'"
          :aria-expanded="!collapsed"
          :title="collapsed ? '展开侧栏' : '收起侧栏'"
          @click="toggleSidebar"
        >
          {{ collapsed ? '展开' : '收起' }}
        </button>
        <el-button
          v-if="!collapsed"
          class="publish-button"
          type="primary"
          data-testid="publish-button"
          @click="openPublish"
        >
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
          :aria-label="item.label"
          :aria-current="isActive(item.name) ? 'page' : undefined"
          :title="item.label"
          @click.prevent="navigate(item)"
        >
          {{ collapsed ? item.short : item.label }}
        </a>
      </nav>

      <div v-if="!collapsed" class="sidebar-recent" aria-label="最近条目">
        <div class="recent-group">
          <p class="recent-title">最近活动</p>
          <p v-if="recentActivities.length === 0" class="recent-empty">暂无相关活动</p>
          <a
            v-for="activity in recentActivities"
            :key="`recent-activity-${activity.id}`"
            :href="`/activities/${activity.id}`"
            class="recent-link"
            :title="activity.title"
            @click.prevent="goActivity(activity.id)"
          >
            {{ activity.title }}
          </a>
          <a href="/my-tasks" class="recent-all" @click.prevent="goAllActivities">
            查看全部活动
          </a>
        </div>
        <div class="recent-group">
          <p class="recent-title">最近任务</p>
          <p v-if="recentTasks.length === 0" class="recent-empty">暂无相关任务</p>
          <a
            v-for="task in recentTasks"
            :key="`recent-task-${task.id}`"
            :href="`/tasks/${task.id}`"
            class="recent-link"
            :title="task.title"
            @click.prevent="goTask(task.id)"
          >
            {{ task.title }}
          </a>
          <a href="/my-tasks" class="recent-all" @click.prevent="goAllActivities">
            查看全部任务
          </a>
        </div>
      </div>

      <nav v-if="canAdmin" class="sidebar-nav sidebar-admin" aria-label="管理">
        <a
          v-for="item in managerNav"
          :key="item.name"
          :href="item.path"
          class="nav-link"
          :class="{ 'is-active': isActive(item.name) }"
          :aria-label="item.label"
          :aria-current="isActive(item.name) ? 'page' : undefined"
          :title="item.label"
          @click.prevent="navigate(item)"
        >
          {{ collapsed ? item.short : item.label }}
        </a>
      </nav>

      <div class="sidebar-foot">
        <ThemeToggle />
        <p v-if="!collapsed" class="sidebar-user" :title="displayName">{{ displayName }}</p>
        <button
          type="button"
          class="text-button logout-button"
          data-testid="logout-button"
          aria-label="退出登录"
          @click="handleLogout"
        >
          {{ collapsed ? '退' : '退出' }}
        </button>
      </div>
    </aside>

    <header class="app-topbar" data-testid="app-header">
      <a class="brand" href="/ai" @click.prevent="goHome">
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
        <template v-if="canAdmin">
          <a
            v-for="item in managerNav"
            :key="item.name"
            :href="item.path"
            class="nav-link"
            :class="{ 'is-active': isActive(item.name) }"
            :aria-current="isActive(item.name) ? 'page' : undefined"
            @click.prevent="navigate(item)"
          >
            {{ item.label }}
          </a>
        </template>
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
      <button
        type="button"
        class="mobile-menu-button"
        data-testid="mobile-menu-button"
        aria-label="打开导航菜单"
        @click="mobileDrawerOpen = true"
      >
        菜单
      </button>
      <span class="mobile-title">{{ pageTitle }}</span>
      <p class="org-context org-context-mobile">
        <span class="org-name">{{ orgName }}</span>
        <span class="org-role">{{ roleText }}</span>
      </p>
    </header>

    <main id="main-content" class="app-content" :class="{ 'is-sidebar-collapsed': collapsed }">
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

    <el-drawer
      v-model="mobileDrawerOpen"
      direction="ltr"
      size="min(320px, 88vw)"
      title="导航"
      class="mobile-nav-drawer"
    >
      <div class="drawer-body">
        <nav class="drawer-nav" aria-label="完整导航">
          <a
            v-for="item in mainNav"
            :key="item.name"
            :href="item.path"
            class="drawer-link"
            :class="{ 'is-active': isActive(item.name) }"
            :aria-current="isActive(item.name) ? 'page' : undefined"
            @click.prevent="navigateFromDrawer(item)"
          >
            <span>{{ item.label }}</span>
            <span v-if="isActive(item.name)" class="drawer-current">当前</span>
          </a>
          <template v-if="canAdmin">
            <a
              v-for="item in managerNav"
              :key="item.name"
              :href="item.path"
              class="drawer-link"
              :class="{ 'is-active': isActive(item.name) }"
              :aria-current="isActive(item.name) ? 'page' : undefined"
              @click.prevent="navigateFromDrawer(item)"
            >
              <span>{{ item.label }}</span>
              <span v-if="isActive(item.name)" class="drawer-current">当前</span>
            </a>
          </template>
        </nav>

        <div class="drawer-recent" aria-label="最近条目">
          <div class="recent-group">
            <p class="recent-title">最近活动</p>
            <p v-if="recentActivities.length === 0" class="recent-empty">暂无相关活动</p>
            <a
              v-for="activity in recentActivities"
              :key="`drawer-activity-${activity.id}`"
              :href="`/activities/${activity.id}`"
              class="drawer-link drawer-link--recent"
              :title="activity.title"
              @click.prevent="goActivity(activity.id)"
            >
              <span>{{ activity.title }}</span>
            </a>
            <a
              href="/my-tasks"
              class="drawer-link drawer-link--recent"
              @click.prevent="goAllActivities"
            >
              <span>查看全部活动</span>
            </a>
          </div>
          <div class="recent-group">
            <p class="recent-title">最近任务</p>
            <p v-if="recentTasks.length === 0" class="recent-empty">暂无相关任务</p>
            <a
              v-for="task in recentTasks"
              :key="`drawer-task-${task.id}`"
              :href="`/tasks/${task.id}`"
              class="drawer-link drawer-link--recent"
              :title="task.title"
              @click.prevent="goTask(task.id)"
            >
              <span>{{ task.title }}</span>
            </a>
            <a
              href="/my-tasks"
              class="drawer-link drawer-link--recent"
              @click.prevent="goAllActivities"
            >
              <span>查看全部任务</span>
            </a>
          </div>
        </div>

        <div class="drawer-actions">
          <el-button type="primary" @click="publishFromDrawer">发布事务</el-button>
        </div>

        <div class="drawer-foot">
          <ThemeToggle />
          <p class="drawer-user">{{ displayName }}</p>
          <button type="button" class="text-button logout-button" @click="handleLogout">
            退出登录
          </button>
        </div>
      </div>
    </el-drawer>
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

.mobile-menu-button {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  min-width: var(--app-touch);
  min-height: var(--app-touch);
  padding: 0 var(--app-space-2);
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-sm);
  background: var(--app-surface-raised);
  color: var(--app-text);
  font-family: inherit;
  font-size: var(--app-font-aux-lg);
  cursor: pointer;
}

.mobile-menu-button:hover,
.mobile-menu-button:focus-visible {
  border-color: var(--app-border-strong);
  color: var(--app-primary);
}

.mobile-title {
  flex: 1;
  min-width: 0;
  margin: 0;
  overflow: hidden;
  font-size: var(--app-font-section-title);
  font-weight: 600;
  color: var(--app-text);
  text-overflow: ellipsis;
  white-space: nowrap;
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

.drawer-body {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-4);
  min-height: 100%;
}

.drawer-nav {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-1);
}

.drawer-link {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: var(--app-touch);
  padding: 0 var(--app-space-3);
  border-radius: var(--app-radius-sm);
  color: var(--app-text-secondary);
  font-size: var(--app-font-body);
  text-decoration: none;
}

.drawer-link:hover {
  background: var(--app-surface-sunken);
  color: var(--app-text);
}

.drawer-link.is-active {
  background: var(--app-primary-soft);
  color: var(--app-primary);
  font-weight: 600;
}

.drawer-current {
  color: var(--app-primary);
  font-size: var(--app-font-aux);
}

.drawer-recent {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-3);
}

.drawer-link--recent {
  font-size: var(--app-font-aux);
}

.drawer-link--recent span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.drawer-actions :deep(.el-button) {
  width: 100%;
  min-height: var(--app-touch);
}

.drawer-foot {
  display: flex;
  flex-direction: column;
  gap: var(--app-space-2);
  margin-top: auto;
  padding-top: var(--app-space-3);
  border-top: 1px solid var(--app-border);
}

.drawer-user {
  margin: 0;
  color: var(--app-text);
  font-size: var(--app-font-body);
  word-break: break-word;
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
    transition: width 0.2s ease, padding 0.2s ease;
  }

  .app-sidebar.is-collapsed {
    width: 72px;
    padding: var(--app-space-4) var(--app-space-2);
  }

  .sidebar-head {
    display: flex;
    flex-direction: column;
    gap: var(--app-space-3);
  }

  .app-sidebar.is-collapsed .sidebar-head {
    align-items: center;
  }

  .collapse-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    min-height: var(--app-touch);
    padding: 0 var(--app-space-2);
    border: 1px solid var(--app-border);
    border-radius: var(--app-radius-sm);
    background: var(--app-surface-raised);
    color: var(--app-text-secondary);
    font-size: var(--app-font-aux-lg);
    cursor: pointer;
  }

  .collapse-button:hover {
    background: var(--app-surface-sunken);
    color: var(--app-text);
  }

  .app-sidebar.is-collapsed .collapse-button {
    width: var(--app-touch);
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

  .app-sidebar.is-collapsed .nav-link {
    justify-content: center;
    padding: 0;
  }


  .sidebar-admin {
    padding-top: var(--app-space-3);
    border-top: 1px solid var(--app-border);
  }

  /* 最近条目：有限量预览 + 查看全部；长标题省略但保留 title 全文 */
  .sidebar-recent {
    display: flex;
    flex-direction: column;
    gap: var(--app-space-3);
    min-height: 0;
    overflow-y: auto;
  }

  .recent-group {
    display: flex;
    flex-direction: column;
    gap: 2px;
    min-width: 0;
  }

  .recent-title {
    margin: 0 0 2px;
    font-size: var(--app-font-aux);
    color: var(--app-text-muted);
  }

  .recent-empty {
    margin: 0;
    font-size: var(--app-font-aux);
    color: var(--app-text-muted);
  }

  .recent-link {
    display: block;
    min-width: 0;
    padding: 6px var(--app-space-2);
    border-radius: var(--app-radius-sm);
    color: var(--app-text-secondary);
    font-size: var(--app-font-aux);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .recent-link:hover,
  .recent-link:focus-visible {
    background: var(--app-surface-sunken);
    color: var(--app-text);
  }

  .recent-all {
    align-self: flex-start;
    min-height: var(--app-touch);
    padding: 0 var(--app-space-2);
    color: var(--app-primary);
    font-size: var(--app-font-aux);
    line-height: var(--app-touch);
    text-decoration: none;
  }

  .recent-all:hover {
    text-decoration: underline;
  }

  .sidebar-foot {
    display: flex;
    align-items: center;
    gap: var(--app-space-2);
    margin-top: auto;
    padding-top: var(--app-space-3);
    border-top: 1px solid var(--app-border);
  }

  .app-sidebar.is-collapsed .sidebar-foot {
    flex-direction: column;
    align-items: center;
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
    transition: margin-left 0.2s ease;
  }

  .app-content.is-sidebar-collapsed {
    margin-left: 72px;
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