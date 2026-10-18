import { readFileSync } from 'node:fs'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
// 读取 package.json 版本号，与构建时间戳一起注入 __APP_BUILD_INFO__ 供前端诊断包使用
const _pkg = JSON.parse(readFileSync(new URL('./package.json', import.meta.url), 'utf-8'))

export default defineConfig({
  plugins: [vue()],
  // zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取
  // 构建信息常量注入：上传失败诊断包标识前端构建版本（前端代码以 typeof 守卫兼容）
  define: {
    __APP_BUILD_INFO__: JSON.stringify({ version: _pkg.version, buildTime: Date.now() })
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/ws': {
        target: 'ws://localhost:8000',
        ws: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    // 确保每次构建生成唯一的文件名
    rollupOptions: {
      output: {
        // 使用内容哈希 + 时间戳确保文件名唯一
        entryFileNames: `assets/[name]-[hash]-${Date.now()}.js`,
        chunkFileNames: `assets/[name]-[hash]-${Date.now()}.js`,
        assetFileNames: `assets/[name]-[hash]-${Date.now()}.[ext]`
      }
    }
  }
})
