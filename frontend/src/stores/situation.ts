/**
 * 态势图 Pinia store（ADR-13 同源数据核心）。
 *
 * 所有 SSE 事件经 applyEvent 落到 store，图表/地图组件响应式渲染——
 * 这就是「图表与地图同源 + 联动」的落点（见 docs/situation-map/05 §3）。
 *
 * 字段对齐 docs/situation-map/04 §4 Report 结构与 06 章插槽契约。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'

export interface ChartSpec {
  chartId: string
  type: string
  title: string
  option: any
  explanation?: string
  datasetRef?: string
}

export interface MapLayer {
  layerId: string
  points?: any[]
  routes?: any[]
  areas?: any[]
  circles?: any[]
  layerConfig: Record<string, any>
}

export interface DatasetSummary {
  datasetId: string
  source: string
  summary: string
  rows: number
}

export interface Narrative {
  intro: string
  explanations: Array<{ chartId: string; text: string }>
}

export interface Viewport {
  center: [number, number]
  zoom: number
}

export type SituationStatus = 'idle' | 'generating' | 'ready' | 'partial' | 'failed'

export const useSituationStore = defineStore('situation', () => {
  // ── 元数据 ──
  const reportId = ref<string | null>(null)
  const status = ref<SituationStatus>('idle')
  const query = ref('')
  const source = ref<'manual' | 'qa' | 'indicator' | 'evaluation'>('manual')
  const title = ref('')

  // ── 统一态势数据集（图表与地图同源）──
  const datasets = ref<DatasetSummary[]>([])
  const activeDatasetId = ref<string | null>(null)
  const charts = ref<ChartSpec[]>([])
  const mapLayers = ref<MapLayer[]>([])
  const narrative = ref<Narrative>({ intro: '', explanations: [] })

  // ── 联动共享状态（图表 ↔ 地图，ADR-04/13）──
  const selectedRegion = ref<string | null>(null)
  const selectedTimeRange = ref<[number, number] | null>(null)
  const filters = ref<Record<string, any>>({})
  const viewport = ref<Viewport>({ center: [35, 105], zoom: 4 })

  // ── SSE 句柄 ──
  const eventSource = ref<EventSource | null>(null)
  const errorMsg = ref('')

  const activeDataset = computed(() =>
    datasets.value.find((d) => d.datasetId === activeDatasetId.value) || null
  )

  const isGenerating = computed(() => status.value === 'generating')

  // ── 重置 ──
  function reset() {
    reportId.value = null
    status.value = 'idle'
    query.value = ''
    source.value = 'manual'
    title.value = ''
    datasets.value = []
    activeDatasetId.value = null
    charts.value = []
    mapLayers.value = []
    narrative.value = { intro: '', explanations: [] }
    selectedRegion.value = null
    selectedTimeRange.value = null
    filters.value = {}
    errorMsg.value = ''
    closeStream()
  }

  // ── 从草稿态初始化 ──
  function initFromDraft(draft: any) {
    if (!draft) return
    const ctx = draft.context || {}
    query.value = ctx.query || ''
    source.value = draft.source || 'manual'
    if (ctx.indicatorIds?.length || ctx.evaluationId) {
      filters.value = { ...filters.value, ...ctx }
    }
  }

  // ── 从已有产物加载（历史/分享）──
  function loadReport(data: any) {
    const snapshot = data.snapshot || data
    reportId.value = data.reportId || snapshot.reportId || null
    title.value = data.title || snapshot.title || ''
    query.value = data.query || snapshot.query || ''
    source.value = (data.source || snapshot.source || 'manual') as any
    status.value = (data.status || snapshot.status || 'ready') as SituationStatus
    charts.value = snapshot.charts || []
    mapLayers.value = snapshot.map?.layers || []
    narrative.value = snapshot.narrative || { intro: '', explanations: [] }
    datasets.value = snapshot.datasets || []
    if (datasets.value.length && !activeDatasetId.value) {
      activeDatasetId.value = datasets.value[0].datasetId
    }
  }

  // ── SSE 事件落库（核心）──
  function applyEvent(eventType: string, data: any) {
    switch (eventType) {
      case 'plan':
        // 规划阶段，仅记录（可选用于展示生成进度）
        break
      case 'dataset': {
        const ds: DatasetSummary = {
          datasetId: data.datasetId,
          source: data.source,
          summary: data.summary,
          rows: data.rows || 0,
        }
        datasets.value.push(ds)
        if (!activeDatasetId.value) activeDatasetId.value = ds.datasetId
        break
      }
      case 'chart':
        charts.value.push({
          chartId: data.chartId,
          type: data.type,
          title: data.title,
          option: data.option,
          datasetRef: data.datasetRef || '',
        })
        break
      case 'chart_update': {
        const c = charts.value.find((x) => x.chartId === data.chartId)
        if (c) c.option = data.option
        break
      }
      case 'map_layer':
        mapLayers.value.push({
          layerId: data.layerId,
          points: data.points || [],
          routes: data.routes || [],
          areas: data.areas || [],
          circles: data.circles || [],
          layerConfig: data.layerConfig || {},
        })
        break
      case 'map_update': {
        const lyr = mapLayers.value.find((x) => x.layerId === data.layerId)
        if (lyr) {
          if (data.points) lyr.points = data.points
          if (data.routes) lyr.routes = data.routes
          if (data.areas) lyr.areas = data.areas
          if (data.circles) lyr.circles = data.circles
        }
        break
      }
      case 'narrative':
        narrative.value = {
          intro: data.intro || '',
          explanations: data.explanations || [],
        }
        // 回填每个图表的 explanation
        const expMap = new Map<string, string>(
          (data.explanations || []).map((e: any) => [e.chartId as string, e.text as string])
        )
        charts.value.forEach((c) => {
          if (expMap.has(c.chartId)) c.explanation = expMap.get(c.chartId)
        })
        break
      case 'done':
        status.value = (data.status as SituationStatus) || 'ready'
        closeStream()
        break
      case 'error':
        errorMsg.value = data.message || '生成异常'
        if (data.fatal) status.value = 'failed'
        break
    }
  }

  // ── 发起生成 ──
  async function generate(q?: string) {
    if (q) query.value = q
    if (!query.value.trim()) return
    // 重置产物字段，保留 query/source
    const _query = query.value
    const _source = source.value
    reset()
    query.value = _query
    source.value = _source
    status.value = 'generating'

    const resp: any = await api.post('/situation/generate', {
      query: query.value,
      source: source.value,
    })
    if (!resp || resp.success === false) return
    const data = resp.data || resp
    reportId.value = data.reportId
    subscribeSSE(data.reportId)
  }

  // ── 订阅 SSE ──
  function subscribeSSE(rid: string) {
    closeStream()
    const es = new EventSource(`/api/situation/stream/${rid}`)
    eventSource.value = es

    const types = ['plan', 'dataset', 'chart', 'chart_update', 'map_layer', 'map_update', 'narrative']
    types.forEach((t) => {
      es.addEventListener(t, (e: MessageEvent) => {
        try {
          applyEvent(t, JSON.parse(e.data))
        } catch (err) {
          console.error('SSE 解析失败', t, err)
        }
      })
    })
    es.addEventListener('done', (e: MessageEvent) => {
      try {
        applyEvent('done', JSON.parse(e.data))
      } catch (err) {
        console.error('done 解析失败', err)
      }
    })
    es.addEventListener('error', () => {
      // EventSource 自身错误（断连），仅提示，由浏览器自动重连
      if (es.readyState === EventSource.CLOSED) {
        if (status.value === 'generating') status.value = 'failed'
      }
    })
  }

  function closeStream() {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
    }
  }

  // ── 主动刷新 ──
  async function refresh() {
    if (!reportId.value) return
    await api.post(`/situation/refresh/${reportId.value}`)
  }

  // ── 联动 action（地图组件通过 action 写共享状态，触发图表 watcher）──
  function setSelectedRegion(payload: string | null) {
    selectedRegion.value = payload
  }
  function setSelectedTimeRange(range: [number, number] | null) {
    selectedTimeRange.value = range
  }
  function setViewport(vp: Viewport) {
    viewport.value = vp
  }
  function toggleLayer(layerId: string, visible: boolean) {
    const lyr = mapLayers.value.find((x) => x.layerId === layerId)
    if (lyr) lyr.layerConfig.visible = visible
  }

  return {
    // state
    reportId, status, query, source, title,
    datasets, activeDatasetId, charts, mapLayers, narrative,
    selectedRegion, selectedTimeRange, filters, viewport,
    eventSource, errorMsg,
    // getters
    activeDataset, isGenerating,
    // actions
    reset, initFromDraft, loadReport, applyEvent, generate,
    subscribeSSE, closeStream, refresh,
    setSelectedRegion, setSelectedTimeRange, setViewport, toggleLayer,
  }
})
