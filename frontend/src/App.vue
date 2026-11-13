<script setup lang="ts">
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import { useRoute } from 'vue-router'

import AppLayout from './layouts/AppLayout.vue'

// 登录页不套布局；其余页面统一使用 AppLayout（C-SHELL@1）
const route = useRoute()
</script>

<template>
  <el-config-provider :locale="zhCn">
    <AppLayout v-if="route.name !== 'login'">
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
  font-family: 'Helvetica Neue', Helvetica, 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei',
    Arial, sans-serif;
  background: var(--app-bg);
  color: var(--app-text);
}
</style>