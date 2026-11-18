import { defineConfig, loadEnv, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'
import { resolve, relative, isAbsolute, extname } from 'path'
import { createReadStream, statSync } from 'node:fs'

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
      {
        name: 'serve-built-ontosphere',
        configureServer(server) {
          // The vendored source folder has the same name. Always serve its production
          // build here, before Vite can interpret the upstream index as a Vue entry.
          const root = resolve(__dirname, 'public/ontosphere')
          const mime: Record<string, string> = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.json': 'application/json', '.wasm': 'application/wasm', '.svg': 'image/svg+xml', '.png': 'image/png', '.webp': 'image/webp', '.ttl': 'text/turtle', '.woff2': 'font/woff2' }
          server.middlewares.use('/ontosphere', (req, res) => {
            try {
              const pathname = decodeURIComponent(new URL(req.url || '/', 'http://localhost').pathname)
              const target = resolve(root, `.${pathname.endsWith('/') ? `${pathname}index.html` : pathname}`)
              const within = relative(root, target)
              if (within.startsWith('..') || isAbsolute(within) || !statSync(target).isFile()) throw new Error('missing asset')
              res.setHeader('Content-Type', mime[extname(target)] || 'application/octet-stream')
              res.setHeader('Cross-Origin-Opener-Policy', 'same-origin')
              res.setHeader('Cross-Origin-Embedder-Policy', 'credentialless')
              res.setHeader('Cache-Control', 'no-cache')
              createReadStream(target).pipe(res)
            } catch { res.statusCode = 404; res.end('Ontosphere asset missing. Run npm run build:ontology.') }
          })
        }
      },
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
      headers: {
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'credentialless'
      },
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
      '/api/ipage': {
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
      },
      // 高德瓦片同源代理（开发环境）：/amap-tiles/vec|anno/{z}/{x}/{y}.png → 高德瓦片服务
      '/amap-tiles/vec': {
        target: 'https://webrd01.is.autonavi.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(
          /^\/amap-tiles\/vec\/(\d+)\/(\d+)\/(\d+)\.png/,
          '/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x=$2&y=$3&z=$1'
        )
      },
      '/amap-tiles/anno': {
        target: 'https://webst01.is.autonavi.com',
        changeOrigin: true,
        rewrite: (path) => path.replace(
          /^\/amap-tiles\/anno\/(\d+)\/(\d+)\/(\d+)\.png/,
          '/appmaptile?style=8&x=$2&y=$3&z=$1'
        )
      }
      }
    },
    preview: { headers: { 'Cross-Origin-Opener-Policy': 'same-origin', 'Cross-Origin-Embedder-Policy': 'credentialless' } },
    build: {
      outDir: 'dist',
      assetsDir: 'assets',
      sourcemap: false
    }
  }
})
