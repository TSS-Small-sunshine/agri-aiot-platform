import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 所有可调参数走环境变量（VITE_* 前缀由 Vite 注入）
const API_TARGET = process.env.VITE_API_TARGET || 'http://127.0.0.1:8000'
const DEV_PORT = Number(process.env.VITE_DEV_PORT || 5173)
const PREVIEW_PORT = Number(process.env.VITE_PREVIEW_PORT || 4173)

export default defineConfig({
  // 相对路径：后端同端口托管在子路径时也不会 404
  base: './',
  plugins: [vue()],
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    // 单 chunk 上限 1.5MB（echarts 按需引入后远低于此值）
    chunkSizeWarningLimit: 1500
  },
  server: {
    host: '127.0.0.1',
    port: DEV_PORT,
    strictPort: false,
    // Windows 上编辑器/工具的原子写会生成 .<name>.<pid>.tmpdir 临时目录，
    // chokidar 监听其删除会抛 EBUSY 直接打挂 dev server，这里忽略掉
    watch: {
      ignored: ['**/.*.tmpdir/**', '**/*.tmp', '**/.git/**']
    },
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        ws: false
      }
    }
  },
  preview: {
    host: '127.0.0.1',
    port: PREVIEW_PORT
  }
})
