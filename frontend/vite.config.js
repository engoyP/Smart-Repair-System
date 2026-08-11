import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 4173,   // Hyper-V/WSL2 保留区间每次重启随机变动（曾占 5173/3000），4173 当前安全；长期方案见 start_all.ps1
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:18080',
        changeOrigin: true
      },
      '/dingtalk': {
        target: 'http://127.0.0.1:18080',
        changeOrigin: true
      }
    }
  }
})