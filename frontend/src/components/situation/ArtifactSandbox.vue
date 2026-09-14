<template>
  <!-- HTML Artifact 沙箱（态势图 HTML Artifact 渲染架构 §3）：
       iframe sandbox 无同源权限 + 不可变 meta CSP + postMessage 数据注入 -->
  <div class="artifact-sandbox">
    <iframe
      ref="frameRef"
      class="artifact-frame"
      :srcdoc="srcdoc"
      sandbox="allow-scripts"
      title="态势报告排版"
    ></iframe>
    <div v-if="!srcdoc" class="artifact-empty">排版产物为空</div>
  </div>
</template>

<script setup lang="ts">
// ── 导入 ──
import { ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
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

const frameRef = ref<HTMLIFrameElement | null>(null)
const srcdoc = ref('')
let tileLayers: MapLayerConfig[] = []
let pendingPayload: any = null

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

  // 地图：取第一个图层（后端收口后最多一个有效图层）
  const layer = props.mapLayers[0] || null
  const mapLayer = layer
    ? {
        points: layer.points || [],
        routes: layer.routes || [],
        areas: layer.areas || [],
        circles: layer.circles || [],
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

// ── 组装 srcdoc：CSP meta + kit 基础样式 + vendor 脚本注入 LLM HTML ──
function buildSrcdoc(html: string): string {
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
  const headInject = `<meta http-equiv="Content-Security-Policy" content="${csp}">`
    + `<link rel="stylesheet" href="${origin}/vendor/leaflet.css">` + baseStyle
  const bodyInject = `<script src="${origin}/vendor/gcoord.min.js"><\/script>`
    + `<script src="${origin}/vendor/echarts.min.js"><\/script>`
    + `<script src="${origin}/vendor/leaflet.js"><\/script>`
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

// ── 与沙箱握手：kit 就绪 → 注入数据 ──
function onMessage(e: MessageEvent) {
  const msg = e.data || {}
  if (e.source !== frameRef.value?.contentWindow) return
  if (msg.type === 'sit:ready') {
    // kit 未收到数据前会周期性重发 ready，因此这里每次都重发数据；
    // payload 不清空（render 内部有防重入守卫，重放幂等），彻底避免握手竞态丢数据
    if (pendingPayload) {
      frameRef.value?.contentWindow?.postMessage({ type: 'sit:data', payload: pendingPayload }, '*')
    }
  }
}

async function rebuild() {
  if (!props.html) {
    srcdoc.value = ''
    return
  }
  if (!tileLayers.length) {
    tileLayers = await loadActiveTileLayers()
  }
  const payload = buildPayload(collectKpiRefs(props.html))
  pendingPayload = payload
  // 先清空再设置 srcdoc（remove + set）：Chromium/WebView2 对首次直接设置的
  // sandbox srcdoc iframe 存在不触发首帧绘制的怪癖，swap 强制重新提交文档
  srcdoc.value = ''
  await nextTick()
  srcdoc.value = buildSrcdoc(props.html)
}

watch(() => [props.html, props.charts, props.mapLayers, props.narrative], rebuild, { deep: false })
onMounted(() => { window.addEventListener('message', onMessage); rebuild() })
onBeforeUnmount(() => { window.removeEventListener('message', onMessage) })
</script>

<style scoped>
.artifact-sandbox {
  width: 100%;
  min-height: 400px;
}
.artifact-frame {
  width: 100%;
  min-height: 60vh;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  background: #f5f7fa;
  display: block;
}
.artifact-empty {
  padding: 40px;
  text-align: center;
  color: #909399;
  font-size: 13px;
}
</style>
