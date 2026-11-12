/**
 * 路由表（契约 C-SHELL@1）
 *
 * 6 个业务路由 + `/` 重定向；登录页是唯一公开页。
 * 会话守卫：无 token 且目标非 `login` → 跳 `login`（带 redirect 回跳参数）。
 * 全局 401：由 `client` 的 unauthorizedHandler 统一跳登录。
 */
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'

import { getToken, setUnauthorizedHandler } from '../api/client'

export const routes: RouteRecordRaw[] = [
  {
    name: 'login',
    path: '/login',
    component: () => import('../views/LoginPage.vue'),
    meta: { public: true }
  },
  {
    name: 'publish',
    path: '/publish',
    component: () => import('../views/PublishPage.vue')
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
    name: 'profile',
    path: '/profile',
    component: () => import('../views/Profile.vue')
  },
  {
    name: 'admin',
    path: '/admin',
    component: () => import('../views/AdminConsole.vue')
  },
  {
    path: '/',
    redirect: '/tasks'
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 任意接口返回 401 / code=4010 时，由 client 调用此处理器跳到登录页（保留回跳地址）
setUnauthorizedHandler(() => {
  const current = router.currentRoute.value
  if (current.name === 'login') return
  const redirect = current.fullPath && current.fullPath !== '/' ? { redirect: current.fullPath } : undefined
  void router.replace({ name: 'login', query: redirect })
})

router.beforeEach((to) => {
  const token = getToken()

  // 未登录访问受保护页面 → 登录页
  if (!token && to.name !== 'login') {
    return { name: 'login', query: { redirect: to.fullPath } }
  }

  // 已登录不再停留在登录页
  if (token && to.name === 'login') {
    return { name: 'hall' }
  }

  return true
})

const PAGE_TITLES: Record<string, string> = {
  login: '登录',
  hall: '任务大厅',
  detail: '任务详情',
  publish: '发布任务',
  profile: '个人中心',
  admin: '发布者后台'
}

router.afterEach((to) => {
  const title = typeof to.name === 'string' ? PAGE_TITLES[to.name] : undefined
  document.title = title ? `${title} · 校园任务协同` : '校园任务协同'
})

export default router