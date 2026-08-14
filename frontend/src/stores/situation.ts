/**
 * 态势图 Pinia store（ADR-13 同源数据核心）。
 *
 * 所有 SSE 事件经 applyEvent 落到 store，图表/地图组件响应式渲染——
 * 这就是「图表与地图同源 + 联动」的落点（见 docs/situation-map/05 §3）。
 *
 * 字段对齐 docs/situation-map/04 §4 Report 结构与 06 章插槽契约。
 *
 * 对话式工作区（仿指标分析）：单次提问=一份产物，对话区基于当前 query+产物
 * 渲染一轮（user 消息 + ai 消息）；历史列表来自后端持久化产物。
 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/services/api'
import type { SituationSkillSummary } from '@/types/situationSkill'

export interface ChartSpec {
  chartId: string
  type: string
  title: string
  option: any
  explanation?: string
  datasetRef?: string
  fieldMapping?: { xField?: string; yFields?: string[] }
}

export interface MapLayer {
  layerId: string
  points?: any[]
  routes?: any[]
  areas?: any[]
  circles?: any[]
  layerConfig: Record<string, any>
  datasetRef?: string
  fieldMapping?: {
    lngField?: string
    latField?: string
    nameField?: string
    routeIdField?: string
    orderField?: string
  }
}

export interface DatasetSummary {
  datasetId: string
  source: string
  summary: string
  rows: number
  columns?: string[]
  data?: any[]
}

export interface Narrative {
  intro: string
  mapExplanation?: string
}

export interface Viewport {
  center: [number, number]
  zoom: number
}

// ── 执行步骤（SSE 事件转步骤，供 execution-panel 展示）──
export interface ExecStep {
  phase: 'plan' | 'dataset' | 'chart' | 'map_layer' | 'narrative' | 'done' | 'error'
  description: string
  status: 'in_progress' | 'completed' | 'error'
  detail?: string
  ts: number
}

// ── 历史产物元信息（后端 /situation/reports 列表项）──
export interface ReportMeta {
  reportId: string
  title: string
  query: string
  source: string
  status: string
  createTime?: string
}

export type SituationStatus = 'idle' | 'generating' | 'ready' | 'partial' | 'failed'

// ── 全量渲染重建：用完整数据集 + LLM 字段映射重建图表/地图，替代 LLM 内联样本 ──
function toNum(v: any): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

function rebuildChartOption(
  chart: { type: string; option: any; fieldMapping?: { xField?: string; yFields?: string[] } },
  ds: DatasetSummary,
): any {
  const fm = chart.fieldMapping
  if (!fm || !fm.xField || !ds.data?.length) return chart.option
  const rows = ds.data
  const xField = fm.xField
  const yFields = fm.yFields || []
  const opt = JSON.parse(JSON.stringify(chart.option || {}))
  const type = chart.type

  if (type === 'pie') {
    const yf = yFields[0]
    if (yf) {
      opt.series = [{
        type: 'pie',
        data: rows.map((r) => ({ name: String(r[xField] ?? ''), value: toNum(r[yf]) })),
      }]
    }
    return opt
  }
  if (type === 'scatter') {
    const yf = yFields[0]
    if (yf) {
      opt.series = [{
        type: 'scatter',
        data: rows.map((r) => [toNum(r[xField]), toNum(r[yf])]),
      }]
    }
    return opt
  }
  // bar / line / 其它分类轴图表
  if (yFields.length) {
    const categories = rows.map((r) => String(r[xField] ?? ''))
    if (opt.xAxis && typeof opt.xAxis === 'object') opt.xAxis.data = categories
    else opt.xAxis = { type: 'category', data: categories }
    opt.series = yFields.map((yf: string) => ({
      name: yf,
      type: type === 'line' ? 'line' : 'bar',
      data: rows.map((r) => toNum(r[yf])),
    }))
  }
  return opt
}

function rebuildMapLayer(layer: MapLayer, ds: DatasetSummary | undefined): MapLayer {
  const fm = layer.fieldMapping
  if (!fm || !fm.lngField || !fm.latField || !ds?.data?.length) return layer
  const rows = ds.data
  const { lngField, latField, nameField, routeIdField, orderField } = fm
  const clone: MapLayer = JSON.parse(JSON.stringify(layer))

  if (routeIdField) {
    // 轨迹数据：按轨迹ID分组，组内按排序字段排序，生成 routes
    const groups = new Map<string, any[]>()
    for (const r of rows) {
      const rid = String(r[routeIdField] ?? 'default')
      if (!groups.has(rid)) groups.set(rid, [])
      groups.get(rid)!.push(r)
    }
    const routes: any[] = []
    for (const [rid, pts] of groups) {
      if (orderField) {
        pts.sort((a, b) => toNum(a[orderField]) - toNum(b[orderField]))
      }
      const name = nameField ? String(pts[0]?.[nameField] ?? rid) : rid
      routes.push({
        name,
        points: pts.map((p) => ({ lng: toNum(p[lngField]), lat: toNum(p[latField]) })),
      })
    }
    clone.routes = routes
    clone.points = []
  } else {
    // 标点数据：逐行生成 points
    const nf = nameField ?? ''
    clone.points = rows.map((r) => ({
      name: nf ? String(r[nf] ?? '') : '',
      lng: toNum(r[lngField]),
      lat: toNum(r[latField]),
      raw: String(r[nf] ?? `${r[lngField]},${r[latField]}`),
    }))
  }
  return clone
}

export const useSituationStore = defineStore('situation', () => {
  // ── 元数据 ──
  const reportId = ref<string | null>(null)
  const status = ref<SituationStatus>('idle')
  const query = ref('')
  const source = ref<'manual' | 'qa' | 'indicator' | 'evaluation'>('manual')
  const title = ref('')
  const activeSkill = ref<SituationSkillSummary | null>(null)
  const skillParameters = ref<Record<string, unknown>>({})

  // ── 统一态势数据集（图表与地图同源）──
  const datasets = ref<DatasetSummary[]>([])
  const activeDatasetId = ref<string | null>(null)
  const charts = ref<ChartSpec[]>([])
  const mapLayers = ref<MapLayer[]>([])
  const narrative = ref<Narrative>({ intro: '' })
  const mapExplanation = ref('')

  // ── 联动共享状态（图表 ↔ 地图，ADR-04/13）──
  const selectedRegion = ref<string | null>(null)
  const selectedTimeRange = ref<[number, number] | null>(null)
  const filters = ref<Record<string, any>>({})
  const viewport = ref<Viewport>({ center: [35, 105], zoom: 4 })

  // ── SSE 句柄 ──
  const eventSource = ref<EventSource | null>(null)
  const errorMsg = ref('')

  // ── 对话式工作区状态 ──
  const history = ref<ReportMeta[]>([])           // 后端历史产物列表
  const executionSteps = ref<ExecStep[]>([])      // 执行步骤面板

  // ── 数据源（仿指标分析，态势图顶部选择器；real_generate 按此过滤数据集 schema）──
  const dataSources = ref<Array<{ id: string; name: string; type?: string; status?: string }>>([])
  const dataSourceId = ref<string>('')
  const dataSourceName = ref<string>('')

  const activeDataset = computed(() =>
    datasets.value.find((d) => d.datasetId === activeDatasetId.value) || null
  )

  const isGenerating = computed(() => status.value === 'generating')

  // 执行步骤进度（completed / total）
  const stepProgress = computed(() => {
    const total = executionSteps.value.length
    const done = executionSteps.value.filter((s) => s.status === 'completed').length
    return { total, done, percent: total === 0 ? 0 : Math.round((done / total) * 100) }
  })

  // ── 执行步骤追加（内部 helper）──
  function pushStep(
    phase: ExecStep['phase'],
    description: string,
    status: ExecStep['status'] = 'completed',
    detail?: string
  ) {
    executionSteps.value.push({ phase, description, status, detail, ts: Date.now() })
  }

  // ── 重置（清产物 + 步骤；不清历史列表）──
  function reset() {
    reportId.value = null
    status.value = 'idle'
    query.value = ''
    source.value = 'manual'
    title.value = ''
    activeSkill.value = null
    skillParameters.value = {}
    datasets.value = []
    activeDatasetId.value = null
    charts.value = []
    mapLayers.value = []
    narrative.value = { intro: '' }
    mapExplanation.value = ''
    selectedRegion.value = null
    selectedTimeRange.value = null
    filters.value = {}
    errorMsg.value = ''
    executionSteps.value = []
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
    const skillId = data.skillId || snapshot.skillId || ''
    const skillName = data.skillName || snapshot.skillName || ''
    activeSkill.value = skillId ? {
      id: skillId,
      name: skillName || skillId,
      category: data.skillCategory || snapshot.skillCategory || '态势 Skill',
      description: '该历史产物由此 Skill 生成',
    } : null
    skillParameters.value = snapshot.skillParameters || {}
    status.value = (data.status || snapshot.status || 'ready') as SituationStatus
    datasets.value = snapshot.datasets || []
    // 历史产物：用完整数据集 + fieldMapping 重建图表/地图，替代 LLM 内联样本
    const dsMap = new Map(datasets.value.map((d) => [d.datasetId, d]))
    charts.value = (snapshot.charts || []).map((c: any) => {
      const ds = dsMap.get(c.datasetRef)
      const fieldMapping = c.fieldMapping || undefined
      const option = fieldMapping && ds?.data?.length
        ? rebuildChartOption({ type: c.type, option: c.option, fieldMapping }, ds)
        : c.option
      return { ...c, option, fieldMapping }
    })
    mapLayers.value = (snapshot.map?.layers || snapshot.mapLayers || []).map((l: any) => {
      const ds = dsMap.get(l.datasetRef)
      return rebuildMapLayer(l, ds)
    })
    narrative.value = snapshot.narrative || { intro: '' }
    mapExplanation.value = snapshot.map?.explanation || snapshot.mapExplanation || ''
    executionSteps.value = []   // 历史产物不回放步骤
    if (datasets.value.length && !activeDatasetId.value) {
      activeDatasetId.value = datasets.value[0].datasetId
    }
  }

  // ── 加载历史列表 ──
  async function fetchHistory() {
    try {
      const resp: any = await api.get('/situation/reports')
      if (resp && resp.success !== false) {
        const list = resp.data?.items || resp.data || resp.items || []
        history.value = Array.isArray(list) ? list : []
      }
    } catch (e) {
      console.warn('历史列表加载失败', e)
    }
  }

  // ── 删除历史产物 ──
  async function deleteHistory(targetId: string) {
    await api.delete(`/situation/reports/${targetId}`)
    history.value = history.value.filter((h) => h.reportId !== targetId)
    if (targetId === reportId.value) {
      reset()
    }
  }

  // ── 加载数据源列表（调 qa-service /evaluation/data-sources，仿指标分析）──
  async function fetchDataSources() {
    try {
      const resp: any = await api.get('/evaluation/data-sources')
      const list = resp?.dataSources || resp?.data?.dataSources || []
      if (Array.isArray(list) && list.length) {
        dataSources.value = list
        // 默认选中第一个可用数据源
        if (!dataSourceId.value && list[0]?.id) {
          dataSourceId.value = list[0].id
          dataSourceName.value = list[0].name || ''
        }
      }
    } catch (e) {
      console.warn('数据源列表加载失败', e)
    }
  }

  // ── 切换数据源 ──
  function setDataSource(id: string) {
    dataSourceId.value = id
    const found = dataSources.value.find((d) => d.id === id)
    dataSourceName.value = found?.name || ''
  }

  // ── SSE 事件落库（核心）──
  function applyEvent(eventType: string, data: any) {
    switch (eventType) {
      case 'plan': {
        // 规划阶段：记录生成方案
        const chartCount = data?.plan?.charts?.length ?? data?.chartCount
        const mapCount = data?.plan?.mapLayers?.length ?? data?.mapCount
        const desc =
          chartCount != null || mapCount != null
            ? `规划生成方案：${chartCount ?? 0} 张图表 + ${mapCount ?? 0} 个地图图层`
            : '规划生成方案'
        pushStep('plan', desc, 'completed', data?.plan ? JSON.stringify(data.plan).slice(0, 200) : '')
        break
      }
      case 'dataset': {
        const ds: DatasetSummary = {
          datasetId: data.datasetId,
          source: data.source,
          summary: data.summary,
          rows: data.rows || 0,
          columns: data.columns || [],
          data: data.data || [],
        }
        datasets.value.push(ds)
        if (!activeDatasetId.value) activeDatasetId.value = ds.datasetId
        pushStep('dataset', `获取数据集 ${ds.datasetId}（${ds.rows} 行）`, 'completed', ds.summary)
        break
      }
      case 'chart': {
        const ds = datasets.value.find((d) => d.datasetId === data.datasetRef)
        const fieldMapping = data.fieldMapping || undefined
        const option = fieldMapping && ds?.data?.length
          ? rebuildChartOption({ type: data.type, option: data.option, fieldMapping }, ds)
          : data.option
        charts.value.push({
          chartId: data.chartId,
          type: data.type,
          title: data.title,
          option,
          explanation: data.explanation || '',
          datasetRef: data.datasetRef || '',
          fieldMapping,
        })
        pushStep('chart', `生成图表：${data.title || data.chartId}`, 'completed')
        break
      }
      case 'chart_update': {
        const c = charts.value.find((x) => x.chartId === data.chartId)
        if (c) c.option = data.option
        break
      }
      case 'map_layer': {
        const ds = datasets.value.find((d) => d.datasetId === data.datasetRef)
        const layer = rebuildMapLayer({
          layerId: data.layerId,
          points: data.points || [],
          routes: data.routes || [],
          areas: data.areas || [],
          circles: data.circles || [],
          layerConfig: data.layerConfig || {},
          datasetRef: data.datasetRef || '',
          fieldMapping: data.fieldMapping || undefined,
        }, ds)
        mapLayers.value.push(layer)
        pushStep('map_layer', `生成地图图层：${data.layerId}`, 'completed')
        break
      }
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
          mapExplanation: data.mapExplanation || '',
        }
        mapExplanation.value = data.mapExplanation || ''
        pushStep('narrative', '撰写态势介绍', 'completed')
        break
      case 'done':
        status.value = (data.status as SituationStatus) || 'ready'
        pushStep('done', '生成完成', 'completed')
        closeStream()
        break
      case 'error':
        errorMsg.value = data.message || '生成异常'
        if (data.fatal) status.value = 'failed'
        pushStep('error', `错误：${data.message || '生成异常'}`, 'error')
        break
    }
  }

  // ── 发起生成 ──
  async function generate(q?: string) {
    if (q) query.value = q
    if (!query.value.trim()) return
    // 重置产物字段与步骤，保留 query/source（不清历史列表）
    const _query = query.value
    const _source = source.value
    const _skill = activeSkill.value
    const _skillParameters = skillParameters.value
    reset()
    query.value = _query
    source.value = _source
    activeSkill.value = _skill
    skillParameters.value = _skillParameters
    status.value = 'generating'

    const resp: any = await api.post('/situation/generate', {
      query: query.value,
      source: source.value,
      skillId: activeSkill.value?.id || '',
      skillParameters: skillParameters.value,
      dataSourceId: dataSourceId.value,
    })
    if (!resp || resp.success === false) return
    const data = resp.data || resp
    reportId.value = data.reportId
    if (data.skill) {
      activeSkill.value = {
        id: data.skill.id,
        name: data.skill.name,
        category: data.skill.category || activeSkill.value?.category || '态势 Skill',
        description: activeSkill.value?.description || '使用专业 Skill 编排生成',
      }
    }
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
  function setActiveSkill(skill: SituationSkillSummary | null) {
    const changed = activeSkill.value?.id !== skill?.id
    activeSkill.value = skill
    if (!skill) {
      skillParameters.value = {}
    } else if (changed) {
      skillParameters.value = Object.fromEntries(
        (skill.parameters || [])
          .filter((parameter) => parameter.default !== undefined && parameter.default !== '')
          .map((parameter) => [parameter.key, parameter.default]),
      )
    }
  }
  function setSkillParameters(parameters: Record<string, unknown>) {
    skillParameters.value = { ...parameters }
  }

  return {
    // state
    reportId, status, query, source, title, activeSkill, skillParameters,
    datasets, activeDatasetId, charts, mapLayers, narrative, mapExplanation,
    selectedRegion, selectedTimeRange, filters, viewport,
    eventSource, errorMsg,
    history, executionSteps,
    dataSources, dataSourceId, dataSourceName,
    // getters
    activeDataset, isGenerating, stepProgress,
    // actions
    reset, initFromDraft, loadReport, applyEvent, generate,
    subscribeSSE, closeStream, refresh, fetchHistory, deleteHistory,
    fetchDataSources, setDataSource,
    setSelectedRegion, setSelectedTimeRange, setViewport, toggleLayer,
    setActiveSkill, setSkillParameters,
  }
})
