import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'path'

export default defineConfig({
  plugins: [
    vue(),
    AutoImport({
      resolvers: [ElementPlusResolver()],
      imports: ['vue', 'vue-router', 'pinia'],
      dts: 'src/auto-imports.d.ts'
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: 'src/components.d.ts'
    })
  ],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src')
    }
  },
  server: {
    port: 10086,
    host: '0.0.0.0',
    proxy: {
      '/api/config': {
        target: 'http://localhost:10253',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/qa': {
        target: 'http://localhost:10253',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/knowledge': {
        target: 'http://localhost:10252',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/indicator': {
        target: 'http://localhost:10254',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/evaluation': {
        target: 'http://localhost:10253',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/attachment': {
        target: 'http://localhost:10253',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/image': {
        target: 'http://localhost:10253',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/model': {
        target: 'http://localhost:10253',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      // 注：规范端口为 10256（与 docker-compose/Dockerfile/部署脚本一致）。
      // 本机 10256 被 Windows 幽灵 socket 占用（进程已退出但端口未释放），
      // 故开发期临时指向 10257 上运行的同一服务；生产容器内仍用 10256。
      '/api/ontology': {
        target: 'http://localhost:10257',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/admin': {
        target: 'http://localhost:10258',
        changeOrigin: true
      },
      '/tiles': {
        target: 'http://localhost:9090',
        changeOrigin: true
      },
      '/geowebcache': {
        target: 'http://localhost:9090',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    sourcemap: false
  }
})
