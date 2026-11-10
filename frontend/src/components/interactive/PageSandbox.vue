<template>
  <!-- 智能交互页面沙箱：iframe sandbox 无同源权限 + CSP + postMessage 注入数据 -->
  <div ref="boxRef" class="page-sandbox">
    <iframe
      :key="frameKey"
      ref="frameRef"
      class="page-frame"
      :srcdoc="srcdoc"
      sandbox="allow-scripts"
      title="态势页面"
    ></iframe>

    <!-- 页面级浮层：阵营筛选 + 时间轴，固定在画布区底部、常驻展开；控件唯一真相源 -->
    <div
      v-if="dockVisible"
      class="ip-tl-dock"
      :style="{ left: dockLeft + 'px' }"
      role="region"
      aria-label="页面级控制条"
    >
      <!-- 阵营行：控制地图与图表；未检测到多于一个阵营时不显示 -->
      <div v-if="factionOptions.length" class="dock-faction">
        <span class="dock-label">阵营</span>
        <button
          v-for="opt in factionButtons"
          :key="opt.value"
          type="button"
          :class="['dock-chip', { active: activeFaction === opt.value }]"
          @click="pickFaction(opt.value)"
        >{{ opt.label }}</button>
      </div>
      <div v-if="dockState" class="dock-panel">
        <button type="button" class="dock-btn" @click="togglePlay">
          {{ dockState.playing ? '暂停' : '播放' }}
        </button>
        <input
          class="dock-range"
          type="range"
          min="0"
          max="1000"
          step="1"
          :value="sliderValue"
          aria-label="时间轴进度"
          @pointerdown="dragging = true"
          @pointerup="dragging = false"
          @pointercancel="dragging = false"
          @change="dragging = false"
          @input="onSeekInput"
        />
        <span class="dock-time">{{ dockState.time || '—' }}</span>
        <button type="button" class="dock-btn" @click="sendTimelineCmd('reset')">重置</button>
      </div>
    </div>

    <div v-if="!html" class="page-empty">
      <el-icon :size="36"><Document /></el-icon>
      <span>输入态势问题后，这里将生成可交互页面</span>
    </div>
  </div>
</template>

<script setup lang="ts">
// ── 智能交互页面沙箱（协议为 ipage:*）──
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { loadMapLayersConfig, type MapLayerConfig } from '@/utils/mapTileConfig'

const props = defineProps<{
  /** Guard 校验通过的完整单文件 HTML */
  html: string
  /** 运行时注入的数据包 dataBundle */
  bundle: any
}>()

const boxRef = ref<HTMLElement | null>(null)
const frameRef = ref<HTMLIFrameElement | null>(null)
const srcdoc = ref('')
// 每次装载新页面都更换 key，强制 Vue 以"最终 srcdoc"重建 iframe 元素。
// 不能用"先置空 srcdoc、同一微任务再赋正文"的 swap 写法：Chromium 会提交空白文档，
// 脚本在被丢弃的文档实例中执行，表现为 iframe 全白但高度/握手消息正常。
const frameKey = ref(0)
let tileLayers: MapLayerConfig[] = []
let fallbackTileLayers: MapLayerConfig[] = []
let pendingPayload: any = null

// ── 页面级浮层（阵营 + 时间轴；宿主是唯一控件来源，页内 SitTimeline 为无头时钟）──
// 浮层常驻展开，高度用于从 --ipage-vh 中扣除，避免遮挡页面结论区
const DOCK_HEIGHT = 48
const FACTION_ROW_HEIGHT = 32
const dockState = ref<any>(null)
const dragging = ref(false)
const dragRatio = ref(0)
const dockLeft = ref(0)
let dockPostTimer: ReturnType<typeof setTimeout> | null = null

// ── 阵营选项：从数据包自动推导（地理要素 + 表格阵营列），≥2 个才显示 ──
const FACTION_ALIAS: Record<string, string> = {
  red: '红方', blue: '蓝方', 红方: '红方', 蓝方: '蓝方',
}
function normalizeFactionValue(v: unknown): string {
  const s = String(v ?? '').trim()
  return FACTION_ALIAS[s] || FACTION_ALIAS[s.toLowerCase()] || ''
}
const factionOptions = computed<string[]>(() => {
  const found = new Set<string>()
  const add = (v: unknown) => {
    const f = normalizeFactionValue(v)
    if (f) found.add(f)
  }
  for (const ds of props.bundle?.datasets || []) {
    const geo = ds?.geoFeatures || {}
    for (const key of ['units', 'points', 'tracks', 'circles']) {
      for (const item of geo[key] || []) add(item?.faction)
    }
    for (const row of ds?.rows || []) {
      for (const col of Object.keys(row || {})) {
        if (/^(阵营|faction)$/i.test(col)) add(row[col])
      }
    }
  }
  const order = ['红方', '蓝方']
  return Array.from(found).sort((a, b) => {
    const ia = order.indexOf(a), ib = order.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
})
const activeFaction = ref('')
const factionButtons = computed(() => [
  { value: '', label: '全部' },
  ...factionOptions.value.map((f) => ({ value: f, label: f })),
])

// 数据包带 2 个以上时间桶时，页面一定存在页面级时间轴
const hasTimeline = computed(() => {
  const buckets = props.bundle?.timeline?.buckets
  return Array.isArray(buckets) && buckets.length >= 2
})
// 有阵营行或时间轴时都需要浮层
const dockVisible = computed(() => hasTimeline.value || factionOptions.value.length > 0)
const dockHeightPx = computed(() =>
  (factionOptions.value.length ? FACTION_ROW_HEIGHT : 0) + (hasTimeline.value ? DOCK_HEIGHT : 0),
)
const dockRatio = computed(() =>
  dragging.value ? dragRatio.value : Number(dockState.value?.ratio ?? 0),
)
const sliderValue = computed(() => Math.round(dockRatio.value * 1000))

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

// ── 视口基准与时间轴命令：iframe 自动撑高时页内 100vh 等于内容高，不能用来算"一屏" ──
// 基准取"最近的滚动容器可视高度"，而不是 iframe 顶部位置：父页滚动时后者会失真
function computeViewportHeight(): number {
  const box = boxRef.value
  const dock = dockVisible.value ? dockHeightPx.value : 0
  if (!box) return Math.max(360, Math.floor(window.innerHeight - 72 - 12 - dock))
  let host: HTMLElement | null = box.parentElement
  while (host && host !== document.body) {
    const overflowY = getComputedStyle(host).overflowY
    if (overflowY === 'auto' || overflowY === 'scroll') break
    host = host.parentElement
  }
  const scroller = host && host !== document.body ? host : document.documentElement
  const style = getComputedStyle(scroller)
  const padTop = parseFloat(style.paddingTop) || 0
  const padBottom = parseFloat(style.paddingBottom) || 0
  const hostRect = scroller.getBoundingClientRect()
  const boxRect = box.getBoundingClientRect()
  // 画布上方可能还有修订进度条/技能提示条，可用高度要扣掉这部分偏移
  const offset = Math.max(0, boxRect.top - (hostRect.top + padTop))
  const visible = hostRect.height - padTop - padBottom - offset
  // 时间轴浮层常驻底部，一屏布局要给浮层让出高度
  return Math.max(360, Math.floor(Math.min(visible, window.innerHeight - 12) - dock))
}

// 浮层水平居中基准：画布区（不是整窗），左侧对话栏折叠/展开后需要重算
function updateDockLeft() {
  const frame = frameRef.value
  if (!frame) return
  const rect = frame.getBoundingClientRect()
  dockLeft.value = Math.round(rect.left + rect.width / 2)
}

function syncViewport() {
  updateDockLeft()
  frameRef.value?.contentWindow?.postMessage(
    { type: 'ipage:viewport', height: computeViewportHeight() }, '*',
  )
}

// 画布尺寸/位置变化时防抖重算，避免 iframe 内容撑高触发高频消息
function scheduleSyncViewport() {
  if (dockPostTimer) clearTimeout(dockPostTimer)
  dockPostTimer = setTimeout(syncViewport, 150)
}

function sendTimelineCmd(action: string, value?: number) {
  frameRef.value?.contentWindow?.postMessage(
    { type: 'ipage:timeline-cmd', action, value }, '*',
  )
}

function togglePlay() {
  sendTimelineCmd(dockState.value?.playing ? 'pause' : 'play')
}

function onSeekInput(e: Event) {
  const ratio = Number((e.target as HTMLInputElement).value) / 1000
  dragRatio.value = ratio
  sendTimelineCmd('seek', ratio)
}

// ── 阵营筛选：下发到 iframe，地图与图表同时生效 ──
function sendFaction(value: string) {
  frameRef.value?.contentWindow?.postMessage({ type: 'ipage:faction', value }, '*')
}

function pickFaction(value: string) {
  if (activeFaction.value === value) return
  activeFaction.value = value
  sendFaction(value)
}

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
    // 一屏布局基准：页面用 var(--ipage-vh) 分配页头/KPI/主区/结论，避免页内 100vh 自我循环；
    // 浮层常驻时再给 body 补底部留白，保证滚动到底时结论/明细表不被浮层遮住
    + `<style>:root{--ipage-vh:${computeViewportHeight()}px;--ipage-dock-h:${dockVisible.value ? dockHeightPx.value : 0}px}`
    + `body{padding-bottom:var(--ipage-dock-h,0)!important}</style>`
    + `<script src="${origin}/vendor/gcoord.min.js"><\/script>`
    + `<script src="${origin}/vendor/echarts.min.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.markercluster.js"><\/script>`
    // turf 必须在 page-kit 之前：page-kit 的能力圈扫掠留痕依赖 window.turf.buffer
    + `<script src="${origin}/vendor/turf.min.js"><\/script>`
    // 版本号用于强制刷新运行时缓存：新增图例图层开关与阵营联动后，旧缓存会缺失接口
    + `<script src="${origin}/vendor/page-kit.js?v=20261109-3"><\/script>`

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
    // 新文档就绪后补发视口高度，覆盖首帧注入时元素尚未布局的情况；
    // 阵营状态也在就绪后重放一次，避免页面初始化期间的切换丢失
    updateDockLeft()
    scheduleSyncViewport()
    if (activeFaction.value) sendFaction(activeFaction.value)
  } else if (msg.type === 'ipage:height' && typeof msg.height === 'number') {
    const h = Math.max(Math.ceil(msg.height), 480)
    if (frameRef.value) frameRef.value.style.height = h + 'px'
  } else if (msg.type === 'ipage:timeline') {
    // 页内时钟广播的状态：宿主浮层只做展示与下发，不另建时钟
    dockState.value = {
      index: msg.index,
      total: msg.total,
      ratio: Number(msg.ratio) || 0,
      time: String(msg.time || ''),
      playing: !!msg.playing,
    }
    if (!dragging.value) dragRatio.value = Number(msg.ratio) || 0
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
  // 换页即丢弃旧时钟状态，等新页面广播
  dockState.value = null
  dragging.value = false
  dragRatio.value = 0
  // 换页即重置阵营筛选（新页面默认"全部"）
  activeFaction.value = ''
  if (!props.html) {
    srcdoc.value = ''
    return
  }
  if (!tileLayers.length) {
    try {
      const layersConfig = await loadMapLayersConfig()
      tileLayers = layersConfig.primary
      fallbackTileLayers = layersConfig.fallback
    } catch {
      tileLayers = []
      fallbackTileLayers = []
    }
  }
  // 深拷贝切断响应式代理（postMessage 结构化克隆本身也会处理）
  pendingPayload = JSON.parse(JSON.stringify({
    data: props.bundle || { question: '', datasets: [] },
    tileLayers,
    fallbackTileLayers,
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

let dockObserver: ResizeObserver | null = null

watch(() => [props.html, props.bundle], rebuild, { deep: false })
onMounted(() => {
  window.addEventListener('message', onMessage)
  window.addEventListener('message', onWindowMessage)
  window.addEventListener('resize', scheduleSyncViewport)
  // 画布区尺寸变化（左栏折叠、技能提示条出现）也要重算浮层位置与视口高度
  if (window.ResizeObserver && boxRef.value) {
    dockObserver = new ResizeObserver(scheduleSyncViewport)
    dockObserver.observe(boxRef.value)
  }
  rebuild()
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  window.removeEventListener('message', onWindowMessage)
  window.removeEventListener('resize', scheduleSyncViewport)
  if (dockObserver) dockObserver.disconnect()
  if (dockPostTimer) clearTimeout(dockPostTimer)
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
/* ── 页面级浮层（阵营 + 时间轴）：常驻展开，固定在画布区底部，不随页面滚动 ── */
.ip-tl-dock {
  position: fixed;
  bottom: 0;
  z-index: 1200;
  box-sizing: border-box;
  width: min(760px, calc(100vw - 24px));
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.97);
  border: 1px solid #e2e8f0;
  border-bottom: none;
  border-radius: 10px 10px 0 0;
  box-shadow: 0 -2px 12px rgba(15, 23, 42, 0.14);
}
/* 阵营行：与时间轴同一浮层，置于进度线下方 */
.dock-faction {
  display: flex;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 4px 12px 0;
  font-size: 12px;
  color: #1e293b;
}
.dock-label {
  color: #64748b;
  margin-right: 2px;
}
.dock-chip {
  padding: 2px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 999px;
  background: #fff;
  color: #334155;
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
}
.dock-chip:hover { background: #f1f5f9; }
.dock-chip.active {
  border-color: #1d4ed8;
  background: #1d4ed8;
  color: #fff;
}
.dock-panel {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px 10px;
  font-size: 12px;
  color: #1e293b;
}
/* 有阵营行时进一步压缩间距，避免浮层过高 */
.dock-faction + .dock-panel { padding-top: 4px; }
.dock-btn {
  padding: 3px 9px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  font-size: 12px;
  white-space: nowrap;
  cursor: pointer;
}
.dock-btn:hover { background: #f1f5f9; }
.dock-range {
  flex: 1;
  min-width: 80px;
  accent-color: #1d4ed8;
  cursor: pointer;
}
.dock-time {
  color: #475569;
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
@media (max-width: 640px) {
  .ip-tl-dock { width: calc(100vw - 16px); }
  .dock-btn { padding: 3px 7px; }
  .dock-panel { gap: 6px; padding: 10px 8px 8px; }
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
