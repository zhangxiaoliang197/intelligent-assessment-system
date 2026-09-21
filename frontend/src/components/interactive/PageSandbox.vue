<template>
  <!-- 智能交互页面沙箱：iframe sandbox 无同源权限 + CSP + postMessage 注入数据 -->
  <div class="page-sandbox">
    <iframe
      :key="frameKey"
      ref="frameRef"
      class="page-frame"
      :srcdoc="srcdoc"
      sandbox="allow-scripts"
      title="态势页面"
    ></iframe>
    <div v-if="!html" class="page-empty">
      <el-icon :size="36"><Document /></el-icon>
      <span>输入态势问题后，这里将生成可交互页面</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// ── 智能交互页面沙箱（独立于 situation ArtifactSandbox，协议为 ipage:*）──
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { loadActiveTileLayers } from '@/utils/mapTileConfig'

const props = defineProps<{
  /** Guard 校验通过的完整单文件 HTML */
  html: string
  /** 运行时注入的数据包 dataBundle */
  bundle: any
}>()

const frameRef = ref<HTMLIFrameElement | null>(null)
const srcdoc = ref('')
// 每次装载新页面都更换 key，强制 Vue 以"最终 srcdoc"重建 iframe 元素。
// 不能用"先置空 srcdoc、同一微任务再赋正文"的 swap 写法：Chromium 会提交空白文档，
// 脚本在被丢弃的文档实例中执行，表现为 iframe 全白但高度/握手消息正常。
const frameKey = ref(0)
let tileLayers: any[] = []
let pendingPayload: any = null

// ── 基础类：业务页面可直接使用，也可被其自定义 <style> 覆盖 ──
const BASE_STYLE = `
  *{box-sizing:border-box}
  body{margin:0;font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;color:#1f2937;background:#f4f6fa}
  .ip-card{background:#fff;border-radius:12px;padding:16px 18px;box-shadow:0 1px 4px rgba(15,23,42,.08);min-width:0}
  .ip-title{font-size:15px;font-weight:600;color:#0f172a;margin:0 0 10px}
  .ip-kpi-row{display:flex;flex-wrap:wrap;gap:12px}
  .ip-kpi{flex:1;min-width:130px;padding:14px 16px;background:#f8fafc;border-radius:10px;text-align:center}
  .ip-kpi .v{font-size:24px;font-weight:700;color:#1d4ed8}
  .ip-kpi .l{font-size:12px;color:#64748b;margin-top:4px}
  .ip-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}
  @media(max-width:900px){.ip-grid{grid-template-columns:1fr}}
`

// ── 归一化 LLM 产物：剥离寒暄前言/Markdown 围栏，截取完整文档窗口 ──
function normalizePageHtml(raw: string): string {
  let t = (raw || '').trim()
  const fence = t.match(/```(?:html|HTML)?\s*\n([\s\S]*?)```/)
  if (fence) t = fence[1].trim()
  t = t.replace(/```(?:html|HTML)?/g, '')
  const startMatch = t.match(/<!DOCTYPE\s+html/i) || t.match(/<html[\s>]/i)
  const closes = [...t.matchAll(/<\/html\s*>/gi)]
  const closeEnd = closes.length ? closes[closes.length - 1].index! + closes[closes.length - 1][0].length : -1
  if (startMatch && closeEnd >= startMatch.index!) return t.slice(startMatch.index, closeEnd).trim()
  if (startMatch) return t.slice(startMatch.index).trim()
  return t
}

// ── 组装 srcdoc：CSP（connect-src 'none'）+ vendor 注入到 LLM HTML ──
function buildSrcdoc(rawHtml: string): string {
  const pageHtml = normalizePageHtml(rawHtml)
  const origin = window.location.origin
  // 安全边界说明：iframe sandbox 未授予 allow-same-origin（内容为 opaque origin），
  // connect-src 'none' 封死一切网络请求；LLM 业务逻辑以内联脚本形式存在，
  // 因此 script-src 必须放行 'unsafe-inline'（同源外部脚本仅限 /vendor 白名单资产）。
  const csp = [
    "default-src 'none'",
    `script-src ${origin} 'unsafe-inline'`,
    `style-src ${origin} 'unsafe-inline'`,
    `img-src ${origin} data: blob: https://*.is.autonavi.com https://*.autonavi.com`,
    `font-src ${origin} data:`,
    "connect-src 'none'",
  ].join('; ')

  // vendor 脚本必须放在 <head>：head 中的经典脚本按序同步执行，先于 body 内
  // LLM 业务内联脚本完成 Sit* 全局定义；若放在 </body> 前，业务脚本会先执行，
  // 此时 SitApp 未定义，bootstrap 注册被静默跳过 → 整页空白且无报错。
  const headInject =
    `<meta http-equiv="Content-Security-Policy" content="${csp}">`
    + `<link rel="stylesheet" href="${origin}/vendor/leaflet.css">`
    + `<link rel="stylesheet" href="${origin}/vendor/MarkerCluster.css">`
    + `<link rel="stylesheet" href="${origin}/vendor/MarkerCluster.Default.css">`
    + `<style>${BASE_STYLE}</style>`
    + `<script src="${origin}/vendor/gcoord.min.js"><\/script>`
    + `<script src="${origin}/vendor/echarts.min.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.markercluster.js"><\/script>`
    // turf 必须在 page-kit 之前：page-kit 的能力圈扫掠留痕依赖 window.turf.buffer
    + `<script src="${origin}/vendor/turf.min.js"><\/script>`
    + `<script src="${origin}/vendor/page-kit.js"><\/script>`

  const headMatch = pageHtml.match(/<head[^>]*>/i)
  if (headMatch) {
    return (
      pageHtml.slice(0, headMatch.index! + headMatch[0].length) + headInject
      + pageHtml.slice(headMatch.index! + headMatch[0].length)
    )
  }
  return `<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">${headInject}</head><body>${pageHtml}</body></html>`
}

// ── 握手：kit 周期重发 ipage:ready，每次都重放数据（幂等）──
function onMessage(e: MessageEvent) {
  const msg = e.data || {}
  if (e.source !== frameRef.value?.contentWindow) return
  if (msg.type === 'ipage:ready') {
    if (pendingPayload) {
      frameRef.value?.contentWindow?.postMessage(
        { type: 'ipage:data', payload: pendingPayload }, '*',
      )
    }
  } else if (msg.type === 'ipage:height' && typeof msg.height === 'number') {
    const h = Math.max(Math.ceil(msg.height), 480)
    if (frameRef.value) frameRef.value.style.height = h + 'px'
  } else if (msg.type === 'ipage:error') {
    console.warn('[ipage] 沙箱内业务错误:', msg.message)
  }
}

let errorNotifiedAt = 0
function notifySandboxError(msg: string) {
  const now = Date.now()
  if (now - errorNotifiedAt < 4000) return
  errorNotifiedAt = now
  ElMessage.warning(`页面部分内容渲染异常：${msg || '未知错误'}`)
}

async function rebuild() {
  if (!props.html) {
    srcdoc.value = ''
    return
  }
  if (!tileLayers.length) {
    try {
      tileLayers = await loadActiveTileLayers()
    } catch {
      tileLayers = []
    }
  }
  // 深拷贝切断响应式代理（postMessage 结构化克隆本身也会处理）
  pendingPayload = JSON.parse(JSON.stringify({
    data: props.bundle || { question: '', datasets: [] },
    tileLayers,
  }))
  const composed = buildSrcdoc(props.html)
  // 同一次 patch 内换 key + 赋最终 srcdoc：新 iframe 元素出生即携带完整文档，
  // 规避 Chromium 对"空 srcdoc → 正文"快速连改时提交空白文档的问题。
  srcdoc.value = composed
  frameKey.value++
}

// 沙箱错误也上抛提示（onMessage 中集中处理）
function onWindowMessage(e: MessageEvent) {
  if (e.source !== frameRef.value?.contentWindow) return
  if ((e.data || {}).type === 'ipage:error') notifySandboxError(e.data.message)
}

watch(() => [props.html, props.bundle], rebuild, { deep: false })
onMounted(() => {
  window.addEventListener('message', onMessage)
  window.addEventListener('message', onWindowMessage)
  rebuild()
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  window.removeEventListener('message', onWindowMessage)
})
</script>

<style scoped>
.page-sandbox {
  width: 100%;
  min-height: 480px;
}
.page-frame {
  width: 100%;
  min-height: 70vh;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  display: block;
}
.page-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 320px;
  color: #94a3b8;
  font-size: 14px;
  border: 1px dashed #cbd5e1;
  border-radius: 10px;
  background: #f8fafc;
}
</style>
