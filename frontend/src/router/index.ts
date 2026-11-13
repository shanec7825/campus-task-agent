/**
 * 路由表（契约 C-FE-AUTH@1 / C-ROUTE-NAV@1）
 *
 * 9 个业务路由 + 公开页（登录 / 注册 / 重置密码）+ 兼容重定向
 * （`/`→工作台、`/hall`→事务、`/notifications`→消息）。
 * 会话守卫：首次导航先 `userStore.restore()`；未登录访问受保护页 → 登录页（带内部 redirect）。
 * 全局 401：由 `client` 的 unauthorizedHandler 统一跳登录（会话恢复期间由守卫自行处理）。
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { setUnauthorizedHandler } from '../api/client'
import { useUserStore } from '../stores/user'

/** 回跳地址只接受站内路径，其余一律回退工作台 */
export function resolveSafeRedirect(raw: unknown): string {
  const value = Array.isArray(raw) ? raw[0] : raw
  if (typeof value === 'string' && value.startsWith('/') && !value.startsWith('//')) {
    return value
  }
  return '/workbench'
}

export const routes: RouteRecordRaw[] = [
  {
    name: 'login',
    path: '/login',
    component: () => import('../views/LoginPage.vue'),
    meta: { public: true }
  },
  {
    name: 'register',
    path: '/register',
    component: () => import('../views/RegisterPage.vue'),
    meta: { public: true }
  },
  {
    name: 'reset-password',
    path: '/reset-password',
    component: () => import('../views/ResetPassword.vue'),
    meta: { public: true }
  },
  {
    name: 'workbench',
    path: '/workbench',
    component: () => import('../views/Workbench.vue')
  },
  {
    name: 'hall',
    path: '/tasks',
    component: () => import('../views/TaskHall.vue')
  },
  {
    name: 'detail',
    path: '/tasks/:id',
    component: () => import('../views/TaskDetail.vue'),
    props: true
  },
  {
    name: 'activity',
    path: '/activities/:id',
    component: () => import('../views/ActivityDetail.vue'),
    props: true
  },
  {
    name: 'messages',
    path: '/messages',
    component: () => import('../views/Messages.vue')
  },
  {
    name: 'profile',
    path: '/profile',
    component: () => import('../views/Profile.vue')
  },
  {
    name: 'publish',
    path: '/publish',
    component: () => import('../views/PublishPage.vue')
  },
  {
    name: 'admin',
    path: '/admin',
    component: () => import('../views/AdminConsole.vue'),
    meta: { requiresManager: true }
  },
  {
    path: '/',
    redirect: '/workbench'
  },
  {
    path: '/hall',
    redirect: '/tasks'
  },
  {
    path: '/notifications',
    redirect: '/messages'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

/** 会话恢复进行中：此时出现的 401 由守卫自己跳转，避免重复导航 */
let restoringSession = false

// 任意接口返回 401 / code=4010 时，由 client 调用此处理器跳到登录页（保留回跳地址）
setUnauthorizedHandler(() => {
  if (restoringSession) return
  const current = router.currentRoute.value
  if (current.name === 'login') return
  const redirect =
    current.fullPath && current.fullPath !== '/' ? { redirect: current.fullPath } : undefined
  void router.replace({ name: 'login', query: redirect })
})

router.beforeEach(async (to) => {
  const userStore = useUserStore()

  if (!userStore.checked) {
    restoringSession = true
    try {
      await userStore.restore()
    } finally {
      restoringSession = false
    }
  }

  if (!userStore.isLoggedIn) {
    // 未登录访问受保护页面 → 登录页（回跳地址取完整路径）
    if (to.meta.public !== true) {
      return { name: 'login', query: { redirect: to.fullPath } }
    }
    return true
  }

  // 已登录不再停留在登录 / 注册页；重置密码页需在会话仍有效时访问（重置完成后才撤销会话）
  if (to.name === 'login' || to.name === 'register') {
    return { name: 'workbench' }
  }

  // 管理页仅组织管理员或协作者可进入
  if (to.meta.requiresManager === true && !(userStore.isAdmin || userStore.isPublisher)) {
    return { name: 'workbench' }
  }

  return true
})

export const PAGE_TITLES: Record<string, string> = {
  login: '登录',
  register: '注册',
  'reset-password': '重置密码',
  workbench: '工作台',
  hall: '事务',
  detail: '任务详情',
  activity: '活动详情',
  messages: '消息',
  publish: '发布任务',
  profile: '个人中心',
  admin: '发布者后台'
}

router.afterEach((to) => {
  const title = typeof to.name === 'string' ? PAGE_TITLES[to.name] : undefined
  document.title = title ? `${title} · 校园任务协同` : '校园任务协同'
})

export default router