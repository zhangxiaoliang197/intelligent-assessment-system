import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, resolve(__dirname, '..'), '')
  const adminToken = env.ADMIN_API_TOKEN?.trim()
  const adminProxy: ProxyOptions = {
    target: 'http://127.0.0.1:10258',
    changeOrigin: true,
    configure(proxy) {
      proxy.on('proxyReq', (proxyReq) => {
        if (adminToken) proxyReq.setHeader('X-Admin-Token', adminToken)
      })
    }
  }

  return {
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
      // 开发代理会在 Node 服务端注入管理凭据，因此强制只监听回环地址。
      // ADMIN_API_TOKEN 不会进入 import.meta.env，也不会被打进浏览器 bundle。
      host: '127.0.0.1',
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
      '/api/ontology': {
        target: 'http://localhost:10256',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/situation': {
        target: 'http://localhost:10257',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, '')
      },
      '/api/admin': {
        ...adminProxy
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
  }
})
