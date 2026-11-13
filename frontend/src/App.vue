<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useRoute } from 'vue-router'

import AppLayout from './layouts/AppLayout.vue'

// 公开页（登录 / 邀请注册 / 重置密码）不套业务布局；其余页面统一使用 AppLayout（C-FE-AUTH@1）
const route = useRoute()
</script>

<template>
  <el-config-provider :locale="zhCn">
    <AppLayout v-if="!route.meta.public">
      <router-view />
    </AppLayout>
    <router-view v-else />
  </el-config-provider>
</template>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
}

body {
  font-family: system-ui, -apple-system, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB',
    'Microsoft YaHei', sans-serif;
  background: var(--app-bg);
  color: var(--app-text);
}
</style>