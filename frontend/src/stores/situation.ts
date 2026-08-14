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
  provenance?: Record<string, any>
  verification?: Record<string, any>
}

export interface MapLayer {
  layerId: string
  points?: any[]
  routes?: any[]
  areas?: any[]
  circles?: any[]
  heatmap?: any[]
  clusters?: any[]
  flows?: any[]
  flow?: any[]
  coverage?: { areas?: any[]; circles?: any[] }
  coverages?: any[]
  layerConfig: Record<string, any>
  datasetRef?: string
  fieldMapping?: {
    lngField?: string
    latField?: string
    nameField?: string
    routeIdField?: string
    orderField?: string
  }
  provenance?: Record<string, any>
  verification?: Record<string, any>
}

export interface DatasetSummary {
  datasetId: string
  source: string
  summary: string
  rows: number
  physicalDatasetId?: string
  schemaVersion?: number
  truncated?: boolean
  evidenceHash?: string
  execution?: Record<string, any>
  columns?: string[]
  data?: any[]
}

export interface Narrative {
  intro: string
  explanations: Array<{ chartId: string; text: string }>
  mapExplanation?: string
}

export interface Viewport {
  center: [number, number]
  zoom: number
}

// ── 执行步骤（SSE 事件转步骤，供 execution-panel 展示）──
export interface ExecStep {
  phase: 'plan' | 'step' | 'dataset' | 'chart' | 'map_layer' | 'narrative' | 'done' | 'error'
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

export interface ResultEvidence {
  evidenceHash?: string
  provenance?: Record<string, any>
  verification?: Record<string, any>
  execution?: Record<string, any>
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
  const narrative = ref<Narrative>({ intro: '', explanations: [] })
  const evidence = ref<ResultEvidence>({})
  const mapExplanation = ref('')

  // ── 联动共享状态（图表 ↔ 地图，ADR-04/13）──
  const selectedRegion = ref<string | null>(null)
  const selectedTimeRange = ref<[number, number] | null>(null)
  const filters = ref<Record<string, any>>({})
  const viewport = ref<Viewport>({ center: [35, 105], zoom: 4 })

  // ── SSE 句柄 ──
  const eventSource = ref<EventSource | null>(null)
  const errorMsg = ref('')
  const requestPending = ref(false)
  let streamReportId: string | null = null
  let generationEpoch = 0
  let generationController: AbortController | null = null
  let recoveryTimer: ReturnType<typeof setTimeout> | null = null
  let recoveryAttempts = 0

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
  function clearRecoveryTimer() {
    if (recoveryTimer) clearTimeout(recoveryTimer)
    recoveryTimer = null
    recoveryAttempts = 0
  }

  function reset() {
    generationEpoch += 1
    generationController?.abort()
    generationController = null
    closeStream()
    clearRecoveryTimer()
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
    narrative.value = { intro: '', explanations: [] }
    evidence.value = {}
    mapExplanation.value = ''
    selectedRegion.value = null
    selectedTimeRange.value = null
    filters.value = {}
    errorMsg.value = ''
    executionSteps.value = []
    requestPending.value = false
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
    generationEpoch += 1
    generationController?.abort()
    generationController = null
    closeStream()
    clearRecoveryTimer()
    const snapshot = data.snapshot || data
    // 先完整清空产物和联动状态，再一次性 hydrate，避免旧 SSE/筛选/视口污染历史报告。
    datasets.value = []
    activeDatasetId.value = null
    charts.value = []
    mapLayers.value = []
    narrative.value = { intro: '', explanations: [] }
    selectedRegion.value = null
    selectedTimeRange.value = null
    filters.value = {}
    viewport.value = { center: [35, 105], zoom: 4 }
    evidence.value = {}
    executionSteps.value = []
    errorMsg.value = ''
    requestPending.value = false
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
    narrative.value = snapshot.narrative || { intro: '', explanations: [] }
    mapExplanation.value = snapshot.map?.explanation || snapshot.mapExplanation || ''
    selectedRegion.value = snapshot.selectedRegion || snapshot.context?.selectedRegion || null
    selectedTimeRange.value = snapshot.selectedTimeRange || snapshot.context?.selectedTimeRange || null
    filters.value = snapshot.filters || snapshot.context?.filters || {}
    if (snapshot.viewport?.center?.length === 2) viewport.value = snapshot.viewport
    evidence.value = {
      evidenceHash: snapshot.evidenceHash,
      provenance: snapshot.provenance,
      verification: snapshot.verification,
      execution: snapshot.execution || snapshot.executionPlan,
    }
    if (Array.isArray(snapshot.execution)) {
      executionSteps.value = snapshot.execution.map((step: any) => ({
        phase: 'step' as const,
        description: `${step.sequence ? `${step.sequence}. ` : ''}${step.name || step.operator || '执行步骤'}`,
        status: step.status === 'error' ? 'error' as const : 'completed' as const,
        detail: `输入 ${step.inputRows ?? 0} 行，输出 ${step.outputRows ?? 0} 行`,
        ts: Date.now(),
      }))
    }
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
        evidence.value.execution = data?.plan || data?.executionPlan || data || evidence.value.execution
        if (!executionSteps.value.some((step) => step.phase === 'plan' && step.description === desc)) {
          pushStep('plan', desc, 'completed', data?.plan ? JSON.stringify(data.plan).slice(0, 200) : '')
        }
        break
      }
      case 'step': {
        const sequence = Number(data?.sequence || 0)
        const description = `${sequence ? `${sequence}. ` : ''}${data?.name || data?.operator || '执行步骤'}`
        const detail = `输入 ${data?.inputRows ?? 0} 行，输出 ${data?.outputRows ?? 0} 行`
        const existing = executionSteps.value.findIndex(
          (item) => item.phase === 'step' && item.description === description,
        )
        const step: ExecStep = {
          phase: 'step', description, status: data?.status === 'error' ? 'error' : 'completed',
          detail, ts: Date.now(),
        }
        if (existing >= 0) executionSteps.value.splice(existing, 1, step)
        else executionSteps.value.push(step)
        const current = Array.isArray(evidence.value.execution) ? evidence.value.execution : []
        evidence.value.execution = [
          ...current.filter((item: any) => Number(item?.sequence || 0) !== sequence),
          data,
        ].sort((a: any, b: any) => Number(a?.sequence || 0) - Number(b?.sequence || 0))
        break
      }
      case 'dataset': {
        const ds: DatasetSummary = {
          datasetId: data.datasetId,
          source: data.source,
          summary: data.summary,
          rows: data.rows || 0,
          physicalDatasetId: data.physicalDatasetId || '',
          schemaVersion: data.schemaVersion,
          truncated: Boolean(data.truncated),
          evidenceHash: data.evidenceHash || '',
          execution: data.execution || {},
          columns: data.columns || [],
          data: data.data || [],
        }
        const existingIndex = datasets.value.findIndex((item) => item.datasetId === ds.datasetId)
        if (existingIndex >= 0) datasets.value.splice(existingIndex, 1, ds)
        else datasets.value.push(ds)
        if (!activeDatasetId.value) activeDatasetId.value = ds.datasetId
        if (existingIndex < 0) pushStep('dataset', `获取数据集 ${ds.datasetId}（${ds.rows} 行）`, 'completed', ds.summary)
        break
      }
      case 'chart': {
        const ds = datasets.value.find((d) => d.datasetId === data.datasetRef)
        const fieldMapping = data.fieldMapping || undefined
        const option = fieldMapping && ds?.data?.length
          ? rebuildChartOption({ type: data.type, option: data.option, fieldMapping }, ds)
          : data.option
        const chart: ChartSpec = {
          chartId: data.chartId,
          type: data.type,
          title: data.title,
          option,
          datasetRef: data.datasetRef || '',
          fieldMapping,
          provenance: data.provenance || {},
          verification: data.verification || {},
        }
        const existingIndex = charts.value.findIndex((item) => item.chartId === chart.chartId)
        if (existingIndex >= 0) charts.value.splice(existingIndex, 1, chart)
        else charts.value.push(chart)
        if (existingIndex < 0) pushStep('chart', `生成图表：${data.title || data.chartId}`, 'completed')
        break
      }
      case 'chart_update': {
        const c = charts.value.find((x) => x.chartId === data.chartId)
        if (c) {
          c.option = data.option
          if (data.provenance) c.provenance = data.provenance
          if (data.verification) c.verification = data.verification
        }
        break
      }
      case 'map_layer': {
        const ds = datasets.value.find((d) => d.datasetId === data.datasetRef)
        const mapLayer: MapLayer = {
          ...rebuildMapLayer({
            layerId: data.layerId,
            points: data.points || [],
            routes: data.routes || [],
            areas: data.areas || [],
            circles: data.circles || [],
            heatmap: data.heatmap || [],
            clusters: data.clusters || [],
            flows: data.flows || [],
            flow: data.flow || [],
            coverage: data.coverage,
            coverages: data.coverages || [],
            layerConfig: data.layerConfig || {},
            datasetRef: data.datasetRef || '',
            fieldMapping: data.fieldMapping || undefined,
          }, ds),
          provenance: data.provenance || {},
          verification: data.verification || {},
        }
        const existingIndex = mapLayers.value.findIndex((item) => item.layerId === mapLayer.layerId)
        if (existingIndex >= 0) mapLayers.value.splice(existingIndex, 1, mapLayer)
        else mapLayers.value.push(mapLayer)
        if (existingIndex < 0) pushStep('map_layer', `生成地图图层：${data.layerId}`, 'completed')
        break
      }
      case 'map_update': {
        const lyr = mapLayers.value.find((x) => x.layerId === data.layerId)
        if (lyr) {
          if (data.points) lyr.points = data.points
          if (data.routes) lyr.routes = data.routes
          if (data.areas) lyr.areas = data.areas
          if (data.circles) lyr.circles = data.circles
          if (data.heatmap) lyr.heatmap = data.heatmap
          if (data.clusters) lyr.clusters = data.clusters
          if (data.flows) lyr.flows = data.flows
          if (data.flow) lyr.flow = data.flow
          if (data.coverage) lyr.coverage = data.coverage
          if (data.coverages) lyr.coverages = data.coverages
          if (data.layerConfig) lyr.layerConfig = { ...lyr.layerConfig, ...data.layerConfig }
          if (data.provenance) lyr.provenance = data.provenance
          if (data.verification) lyr.verification = data.verification
        }
        break
      }
      case 'narrative':
        narrative.value = {
          intro: data.intro || '',
          explanations: data.explanations || [],
          mapExplanation: data.mapExplanation || '',
        }
        mapExplanation.value = data.mapExplanation || ''
        // 回填每个图表的 explanation
        const expMap = new Map<string, string>(
          (data.explanations || []).map((e: any) => [e.chartId as string, e.text as string])
        )
        charts.value.forEach((c) => {
          if (expMap.has(c.chartId)) c.explanation = expMap.get(c.chartId)
        })
        if (!executionSteps.value.some((step) => step.phase === 'narrative')) {
          pushStep('narrative', '撰写态势介绍', 'completed')
        }
        break
      case 'done':
        evidence.value = {
          evidenceHash: data.evidenceHash || evidence.value.evidenceHash,
          provenance: data.provenance || evidence.value.provenance,
          verification: data.verification || evidence.value.verification,
          execution: data.execution || data.executionPlan || evidence.value.execution,
        }
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
    if (requestPending.value || isGenerating.value) return false
    if (q) query.value = q
    if (!query.value.trim()) return
    // 重置产物字段与步骤，保留 query/source（不清历史列表）
    const _query = query.value
    const _source = source.value
    const _skill = activeSkill.value
    const _skillParameters = skillParameters.value
    const _selectedRegion = selectedRegion.value
    const _selectedTimeRange = selectedTimeRange.value
    const _filters = { ...filters.value }
    const _viewport = { ...viewport.value, center: [...viewport.value.center] as [number, number] }
    reset()
    query.value = _query
    source.value = _source
    activeSkill.value = _skill
    skillParameters.value = _skillParameters
    selectedRegion.value = _selectedRegion
    selectedTimeRange.value = _selectedTimeRange
    filters.value = _filters
    viewport.value = _viewport
    const epoch = generationEpoch
    status.value = 'generating'
    requestPending.value = true
    generationController = new AbortController()
    try {
      const resp: any = await api.post('/situation/generate', {
        query: query.value,
        source: source.value,
        skillId: activeSkill.value?.id || '',
        skillParameters: skillParameters.value,
        dataSourceId: dataSourceId.value,
        context: {
          selectedRegion: selectedRegion.value,
          selectedTimeRange: selectedTimeRange.value,
          filters: filters.value,
          viewport: viewport.value,
        },
      }, { signal: generationController.signal })
      if (epoch !== generationEpoch) return false
      if (!resp || resp.success === false) throw new Error(resp?.message || '生成请求失败')
      const data = resp.data || resp
      if (!data.reportId) throw new Error('生成服务未返回 reportId')
      reportId.value = data.reportId
      if (data.skill) {
        activeSkill.value = {
          id: data.skill.id,
          name: data.skill.name,
          category: data.skill.category || activeSkill.value?.category || '态势 Skill',
          description: activeSkill.value?.description || '使用专业 Skill 编排生成',
        }
        evidence.value.execution = data.skill.executionPlan || data.executionPlan
      }
      subscribeSSE(data.reportId, epoch)
      return true
    } catch (error: any) {
      if (epoch !== generationEpoch) return false
      errorMsg.value = error?.serverMessage || error?.message || '生成请求失败'
      status.value = 'failed'
      pushStep('error', `错误：${errorMsg.value}`, 'error')
      throw error
    } finally {
      if (epoch === generationEpoch) {
        requestPending.value = false
        generationController = null
      }
    }
  }

  // ── 订阅 SSE ──
  function subscribeSSE(rid: string, epoch = generationEpoch) {
    closeStream()
    clearRecoveryTimer()
    const es = new EventSource(`/api/situation/stream/${rid}`)
    eventSource.value = es
    streamReportId = rid

    const types = ['plan', 'dataset', 'chart', 'chart_update', 'map_layer', 'map_update', 'narrative']
    types.forEach((t) => {
      es.addEventListener(t, (e: MessageEvent) => {
        try {
          if (epoch !== generationEpoch || streamReportId !== rid) return
          applyEvent(t, JSON.parse(e.data))
        } catch (err) {
          console.error('SSE 解析失败', t, err)
        }
      })
    })
    es.addEventListener('done', (e: MessageEvent) => {
      try {
        if (epoch !== generationEpoch || streamReportId !== rid) return
        applyEvent('done', JSON.parse(e.data))
      } catch (err) {
        console.error('done 解析失败', err)
      }
    })
    es.addEventListener('error', (event: Event) => {
      if (epoch !== generationEpoch || streamReportId !== rid || status.value !== 'generating') return
      // 后端业务错误也使用 event:error；它是 MessageEvent，先落库再决定是否等 done。
      if (event instanceof MessageEvent && event.data) {
        try {
          applyEvent('error', JSON.parse(event.data))
        } catch (error) {
          console.error('error 事件解析失败', error)
        }
        return
      }
      // EventSource 会自动重连；同时轮询持久化报告，覆盖代理不支持 SSE 重连或 done 丢失的情况。
      scheduleReportRecovery(rid, epoch)
    })
  }

  function scheduleReportRecovery(rid: string, epoch: number) {
    if (recoveryTimer || epoch !== generationEpoch) return
    recoveryTimer = setTimeout(async () => {
      recoveryTimer = null
      if (epoch !== generationEpoch || status.value !== 'generating') return
      try {
        const resp: any = await api.get(`/situation/reports/${encodeURIComponent(rid)}`)
        const report = resp?.data || resp
        if (report?.status && report.status !== 'generating' && report.snapshot) {
          loadReport(report)
          return
        }
      } catch {
        // 生成未持久化或暂时不可达，按上限退避重试。
      }
      recoveryAttempts += 1
      if (recoveryAttempts >= 8) {
        errorMsg.value = '生成连接已中断，后台状态暂不可确认，请稍后从历史记录重新打开'
        status.value = 'partial'
        closeStream()
        return
      }
      scheduleReportRecovery(rid, epoch)
    }, Math.min(15000, 1200 * (recoveryAttempts + 1)))
  }

  function closeStream() {
    if (eventSource.value) {
      eventSource.value.close()
      eventSource.value = null
    }
    streamReportId = null
    clearRecoveryTimer()
  }

  async function cancelGeneration() {
    if (!isGenerating.value && !requestPending.value) return
    const rid = reportId.value
    generationEpoch += 1
    generationController?.abort()
    generationController = null
    closeStream()
    clearRecoveryTimer()
    requestPending.value = false
    status.value = 'failed'
    errorMsg.value = '已取消生成'
    pushStep('error', '用户取消生成', 'error')
    if (!rid) return
    try {
      await api.post(`/situation/cancel/${encodeURIComponent(rid)}`)
    } catch (error: any) {
      // 兼容尚未部署 cancel endpoint 的旧服务；404/405 表示前端已取消订阅。
      const code = error?.response?.status
      if (code !== 404 && code !== 405) console.warn('后台取消请求失败', error)
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
    datasets, activeDatasetId, charts, mapLayers, narrative, evidence, mapExplanation,
    selectedRegion, selectedTimeRange, filters, viewport,
    eventSource, errorMsg, requestPending,
    history, executionSteps,
    dataSources, dataSourceId, dataSourceName,
    // getters
    activeDataset, isGenerating, stepProgress,
    // actions
    reset, initFromDraft, loadReport, applyEvent, generate,
    subscribeSSE, closeStream, cancelGeneration, refresh, fetchHistory, deleteHistory,
    fetchDataSources, setDataSource,
    setSelectedRegion, setSelectedTimeRange, setViewport, toggleLayer,
    setActiveSkill, setSkillParameters,
  }
})
