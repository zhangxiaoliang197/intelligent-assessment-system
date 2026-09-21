<template>
  <!-- HTML Artifact 沙箱（态势图 HTML Artifact 渲染架构 §3 重设计）：
       就绪后一次性创建 iframe + Blob URL 标准导航（弃用 srcdoc swap），
       :key 整体重建；kit 上报 sit:layout 做零布局自检，失败 keyed 自愈（限 1 次） -->
  <div class="artifact-sandbox">
    <div v-if="frameUrl" class="artifact-frame-wrap">
      <iframe
        :key="frameKey"
        ref="frameRef"
        class="artifact-frame"
        :src="frameUrl"
        sandbox="allow-scripts"
        title="态势报告排版"
      ></iframe>
      <!-- 首帧自检通过前的加载骨架，避免用户看到空白 -->
      <div v-if="status === 'loading'" class="artifact-mask">
        <div class="artifact-spinner"></div>
        <div class="artifact-mask-text">态势报告渲染中…</div>
      </div>
    </div>
    <div v-else class="artifact-empty">排版产物为空</div>
    <!-- 两次构建仍零布局：给手动重试与父组件降级入口 -->
    <div v-if="status === 'error'" class="artifact-error">
      <span>态势报告渲染异常</span>
      <el-button size="small" type="primary" plain @click="manualRebuild">重新渲染</el-button>
      <el-button size="small" text @click="emit('render-failed')">切换简洁版式</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
// ── 导入 ──
import { ref, watch, onMounted, onBeforeUnmount } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { loadActiveTileLayers, type MapLayerConfig } from '@/utils/mapTileConfig'
import type { ChartSpec, DatasetSummary, MapLayer, Narrative } from '@/stores/situation'

// ── props：数据全部来自 store（图表 option 已按全量数据重建） ──
const props = defineProps<{
  /** 后端清洗校验后的整页 HTML（LLM 只写排版与 data-sit 占位符） */
  html: string
  charts: ChartSpec[]
  mapLayers: MapLayer[]
  datasets: DatasetSummary[]
  narrative: Narrative
}>()

const emit = defineEmits<{
  (e: 'render-failed'): void
}>()

const frameRef = ref<HTMLIFrameElement | null>(null)
// ── 渲染状态机：loading（首帧自检中）→ ready（布局已提交）/ error（两次仍失败） ──
const status = ref<'loading' | 'ready' | 'error'>('loading')
const frameUrl = ref('')       // 当前 Blob URL
const frameKey = ref(0)        // keyed 重建计数（换产物/自愈时整体换新 iframe 元素）

let tileLayers: MapLayerConfig[] = []
let pendingPayload: any = null
let attempt = 0                // 同一内容轮次的构建尝试次数（首次 1 + 自愈 1，共 2 次）
let failTimer: ReturnType<typeof setTimeout> | null = null
let rebuildTimer: ReturnType<typeof setTimeout> | null = null
// 同轮构建内已收到的成功信号（去重），记录当前 frameKey 防止旧帧消息串扰
let activeKey = -1
let goodLayoutSeen = false

// ── markdown 渲染（与 SituationLayoutRenderer 同管线：marked + DOMPurify） ──
function renderMarkdown(text: string): string {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
}

// ── 从 LLM HTML 中收集 kpi 占位符引用的数据集 id（DOMParser，不执行脚本） ──
function collectKpiRefs(html: string): string[] {
  const refs = new Set<string>()
  try {
    const doc = new DOMParser().parseFromString(html, 'text/html')
    doc.querySelectorAll('[data-sit="kpi"][data-ref]').forEach((el) => {
      const ref = el.getAttribute('data-ref')
      if (ref) refs.add(ref)
    })
  } catch (e) { /* 解析失败按无 kpi 处理 */ }
  return Array.from(refs)
}

// ── 组装注入 iframe 的数据 payload ──
function buildPayload(kpiRefs: string[]) {
  // 图表：chartId → { option }（store 中 option 已重建，直接使用）
  const charts: Record<string, { option: any }> = {}
  props.charts.forEach((c) => { charts[c.chartId] = { option: c.option } })

  // 地图：取第一个图层（后端收口后最多一个有效图层）；density 透传供沙箱内聚合决策
  const layer = props.mapLayers[0] || null
  const mapLayer = layer
    ? {
        points: layer.points || [],
        routes: layer.routes || [],
        areas: layer.areas || [],
        circles: layer.circles || [],
        density: (layer as any).density || '',
      }
    : null

  // KPI：仅注入被引用数据集的行（避免全量快照重复传输）
  const datasets: Record<string, { columns: string[]; rows: any[] }> = {}
  kpiRefs.forEach((id) => {
    const ds = props.datasets.find((d) => d.datasetId === id)
    if (ds) datasets[id] = { columns: ds.columns || [], rows: ds.rows || ds.data || [] }
  })

  // 文本：父页统一 markdown 渲染 + 消毒后注入
  const explanations: Record<string, string> = {}
  ;(props.narrative.explanations || []).forEach((e) => {
    explanations[e.chartId] = renderMarkdown(e.text)
  })

  return JSON.parse(JSON.stringify({
    charts,
    mapLayer,
    tileLayers,
    datasets,
    narrative: {
      introHtml: renderMarkdown(props.narrative.intro),
      explanations,
      mapExplanationHtml: renderMarkdown(props.narrative.mapExplanation || ''),
    },
  }))
}

// ── 组装文档：CSP meta + kit 基础样式 + vendor 脚本注入 LLM HTML ──
function buildDocument(html: string): string {
  const origin = window.location.origin
  const csp = [
    "default-src 'none'",
    `script-src ${origin}`,
    `style-src ${origin} 'unsafe-inline'`,
    `img-src ${origin} data: blob: https://*.is.autonavi.com https://*.autonavi.com`,
    `font-src ${origin} data:`,
    "connect-src 'none'",
  ].join('; ')
  // kit 基础样式：占位符渲染产物的兜底外观（LLM 自有样式优先生效）
  const baseStyle = `<style>
    .sit-kpi-row{display:flex;flex-wrap:wrap;gap:12px}
    .sit-kpi{flex:1;min-width:120px;text-align:center;padding:12px 8px;border-radius:8px;background:#f5f7fa}
    .sit-kpi-label{font-size:12px;color:#606266;margin-bottom:4px}
    .sit-kpi-value{font-size:22px;font-weight:700;color:#2563eb}
    .sit-explain{font-size:13px;line-height:1.7;color:#606266;margin-top:8px}
  </style>`
  // charset 必须位于 head 最前：Blob 文档不继承父页编码，LLM HTML 常缺 meta charset，
  // 缺省解码会使中文全部乱码（ECharts canvas 文本不受影响，仅 HTML 文本节点乱码）
  const headInject = `<meta charset="utf-8">`
    + `<meta http-equiv="Content-Security-Policy" content="${csp}">`
    + `<link rel="stylesheet" href="${origin}/vendor/leaflet.css">`
    + `<link rel="stylesheet" href="${origin}/vendor/MarkerCluster.css">`
    + `<link rel="stylesheet" href="${origin}/vendor/MarkerCluster.Default.css">` + baseStyle
  const bodyInject = `<script src="${origin}/vendor/gcoord.min.js"><\/script>`
    + `<script src="${origin}/vendor/echarts.min.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.markercluster.js"><\/script>`
    + `<script src="${origin}/vendor/situation-kit.js"><\/script>`

  const headMatch = html.match(/<head[^>]*>/i)
  const bodyClose = html.match(/<\/body\s*>/i)
  if (headMatch && bodyClose) {
    return (
      html.slice(0, headMatch.index! + headMatch[0].length) + headInject
      + html.slice(headMatch.index! + headMatch[0].length, bodyClose.index!)
      + bodyInject + html.slice(bodyClose.index!)
    )
  }
  // 非完整文档：包裹成完整结构
  return `<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">${headInject}</head><body>${html}${bodyInject}</body></html>`
}

// ── 看门狗：5 秒内未收到任何"布局已提交"信号 → 自愈或失败 ──
function armWatchdog() {
  if (failTimer) clearTimeout(failTimer)
  goodLayoutSeen = false
  failTimer = setTimeout(() => {
    if (activeKey !== frameKey.value || goodLayoutSeen) return
    handleZeroLayout()
  }, 5000)
}

function markGoodLayout(height?: number) {
  if (activeKey !== frameKey.value) return
  if (!goodLayoutSeen) {
    goodLayoutSeen = true
    status.value = 'ready'
  }
  if (failTimer) {
    clearTimeout(failTimer)
    failTimer = null
  }
  if (typeof height === 'number' && height > 0 && frameRef.value) {
    frameRef.value.style.height = Math.max(Math.ceil(height), 400) + 'px'
  }
}

// ── 零布局自愈：keyed 整体重建 1 次；仍失败 → error 态并通知父组件可降级 ──
function handleZeroLayout() {
  if (attempt < 2) {
    // keyed 重建（reason=heal）
    void mount('heal')
  } else {
    status.value = 'error'
    emit('render-failed')
  }
}

// ── 与沙箱握手：ready → 注入数据；height/layout → 首帧自检凭据 ──
function onMessage(e: MessageEvent) {
  const msg = e.data || {}
  if (e.source !== frameRef.value?.contentWindow) return
  if (msg.type === 'sit:ready') {
    // kit 未收到数据前会周期性重发 ready，每次都重发数据（render 幂等）
    if (pendingPayload) {
      frameRef.value?.contentWindow?.postMessage({ type: 'sit:data', payload: pendingPayload }, '*')
    }
  } else if (msg.type === 'sit:height' && typeof msg.height === 'number' && msg.height > 0) {
    markGoodLayout(msg.height)
  } else if (msg.type === 'sit:layout') {
    // body 已有非零高度即视为布局提交成功（槽位个别为 0 可能是无数据 KPI，不阻断）
    if (typeof msg.bodyH === 'number' && msg.bodyH > 0) {
      markGoodLayout(msg.bodyH)
    }
  }
}

// ── 构建并挂载（一次性 Blob 导航 + keyed 新元素；不再 srcdoc swap） ──
async function mount(reason: 'initial' | 'props' | 'heal' | 'manual') {
  if (!props.html) {
    revokeCurrent()
    status.value = 'loading'
    return
  }
  // heal 延续当前轮次计数（第 2 次构建）；initial/props/manual 都是新内容轮次，重新计数
  if (reason !== 'heal') attempt = 0
  attempt += 1

  if (!tileLayers.length) {
    try {
      tileLayers = await loadActiveTileLayers()
    } catch (e) {
      tileLayers = []
    }
  }
  pendingPayload = buildPayload(collectKpiRefs(props.html))

  // 新 Blob URL 走标准 navigation commit，规避 sandbox srcdoc 首帧零布局怪癖；
  // frameKey 自增强制 Vue 换全新 iframe 元素（旧元素随 v-if/key 销毁，不产生 srcdoc 横跳）
  const doc = buildDocument(props.html)
  revokeCurrent()
  frameUrl.value = URL.createObjectURL(new Blob([doc], { type: 'text/html' }))
  frameKey.value += 1
  activeKey = frameKey.value
  status.value = 'loading'
  armWatchdog()
}

function revokeCurrent() {
  if (frameUrl.value) {
    try { URL.revokeObjectURL(frameUrl.value) } catch (e) { /* 已释放忽略 */ }
    frameUrl.value = ''
  }
}

function manualRebuild() {
  void mount('manual')
}

// props 任意变化（流式阶段逐图推送）→ 防抖重建，避免连续 SSE 造成频繁换帧
watch(
  () => [props.html, props.charts, props.mapLayers, props.datasets, props.narrative],
  () => {
    if (rebuildTimer) clearTimeout(rebuildTimer)
    rebuildTimer = setTimeout(() => void mount('props'), 250)
  },
  { deep: false },
)

onMounted(() => {
  window.addEventListener('message', onMessage)
  void mount('initial')
})

onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  if (failTimer) clearTimeout(failTimer)
  if (rebuildTimer) clearTimeout(rebuildTimer)
  revokeCurrent()
})
</script>

<style scoped>
.artifact-sandbox {
  width: 100%;
  min-height: 400px;
  position: relative;
}
.artifact-frame-wrap {
  position: relative;
  width: 100%;
}
.artifact-frame {
  width: 100%;
  min-height: 60vh;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #ffffff;
  display: block;
}
.artifact-empty {
  padding: 40px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
.artifact-mask {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  background: rgba(255, 255, 255, 0.75);
  border-radius: 8px;
  z-index: 2;
}
.artifact-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid #dbe4f0;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: artifact-spin 0.8s linear infinite;
}
.artifact-mask-text {
  font-size: 13px;
  color: #606266;
}
.artifact-error {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 16px;
  margin-top: 8px;
  font-size: 13px;
  color: #f56c6c;
  background: #fef0f0;
  border-radius: 8px;
}
@keyframes artifact-spin {
  to { transform: rotate(360deg); }
}
</style>
