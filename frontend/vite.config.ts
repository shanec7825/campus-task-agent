import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发端口固定 5173；所有 /api 请求（含 SSE）经代理转发到后端 8000
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    // 穿透访问白名单：zeronews 免费域名 *.takin.cc（含随机子域），
    // 否则 Vite dev server 会以 "Blocked request" 403 拦截非 localhost Host 头。
    allowedHosts: ['.takin.cc'],
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
})