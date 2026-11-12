<script setup lang="ts">
import { useRoute } from 'vue-router'

import AppLayout from './layouts/AppLayout.vue'

// 登录页不套布局；其余页面统一使用 AppLayout（C-SHELL@1）
const route = useRoute()
</script>

<template>
  <AppLayout v-if="route.name !== 'login'">
    <router-view />
  </AppLayout>
  <router-view v-else />
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
  background: #f5f7fa;
  color: #303133;
}
</style>