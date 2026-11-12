<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useSSE } from '../composables/useSSE'
import { useNotificationsStore } from '../stores/notifications'
import { useUserStore } from '../stores/user'

/**
 * 应用布局（契约 C-SHELL@1，T5 为最终 owner）。
 *
 * - 顶部导航：任务大厅 / 发布任务 / 个人中心 / 发布者后台（仅 publisher）；
 * - 未读红点：`notificationsStore.unread`，点击跳 `/profile#notifications`；
 * - 挂载时拉取通知并建立 SSE，卸载时断开（disconnect 后不再重连）。
 */
const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const notificationsStore = useNotificationsStore()
const sse = useSSE()

const isPublisher = computed<boolean>(() => userStore.isPublisher)
const isLoggedIn = computed<boolean>(() => userStore.isLoggedIn)
const displayName = computed<string>(() => userStore.displayName)
const unread = computed<number>(() => notificationsStore.unread)

const activeMenu = computed<string>(() => {
  if (route.path.startsWith('/tasks')) return '/tasks'
  return route.path
})

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
  <el-container class="app-layout">
    <el-header class="app-header">
      <div class="brand">校园任务协同</div>

      <el-menu :default-active="activeMenu" mode="horizontal" router class="app-nav">
        <el-menu-item index="/tasks">任务大厅</el-menu-item>
        <el-menu-item index="/publish">发布任务</el-menu-item>
        <el-menu-item index="/profile">个人中心</el-menu-item>
        <el-menu-item v-if="isPublisher" index="/admin">发布者后台</el-menu-item>
      </el-menu>

      <div class="header-right">
        <!-- 未读通知红点：点击跳个人中心通知区 -->
        <el-badge :value="unread" :hidden="unread === 0" :max="99" class="notify-badge">
          <el-button text @click="openNotifications">通知</el-button>
        </el-badge>
        <template v-if="isLoggedIn">
          <span class="username">{{ displayName }}</span>
          <el-button text type="danger" @click="handleLogout">退出</el-button>
        </template>
      </div>
    </el-header>

    <el-main class="app-main">
      <!-- App.vue 传入 router-view；单独使用时回退到自带 router-view -->
      <slot>
        <router-view />
      </slot>
    </el-main>
  </el-container>
</template>

<style scoped>
.app-layout {
  min-height: 100vh;
}

.app-header {
  display: flex;
  align-items: center;
  gap: 24px;
  background: #ffffff;
  border-bottom: 1px solid #e4e7ed;
}

.brand {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
}

.app-nav {
  flex: 1;
  border-bottom: none;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.notify-badge {
  margin-right: 4px;
}

.username {
  font-size: 15px;
  color: #606266;
  white-space: nowrap;
}

.app-main {
  padding: 20px 24px;
}
</style>