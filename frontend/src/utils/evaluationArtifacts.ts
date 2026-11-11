/**
 * 评估分析结果 → 态势页面产物归一化工具。
 *
 * 评估分析的 result 有多种形态（skill / air_superiority / combat_effectiveness /
 * indicator_calculation / general），本模块统一把它们整理成后端可直接消费的
 * EvaluationArtifactPayload：
 *  - 只保留有数据行的步骤；
 *  - 行数据按前端上限截断（与 qa-service 的 _MAX_RESULT_ROWS=500 对齐）；
 *  - 自动识别图表能力与经纬度/航迹/范围圈能力，供选择框展示。
 */

// ── 类型契约（与后端 ArtifactItem / EvaluationArtifacts 对齐）──
export interface ArtifactMarker {
  name: string
  lng: number
  lat: number
  props?: Record<string, any>
}

export interface ArtifactRoute {
  name: string
  points: Array<{ lng: number; lat: number }>
}

export interface ArtifactArea {
  name: string
  lng: number
  lat: number
  radiusKm: number
  props?: Record<string, any>
}

export interface ArtifactGeo {
  markers?: ArtifactMarker[]
  routes?: ArtifactRoute[]
  areas?: ArtifactArea[]
}

export interface EvaluationArtifactItem {
  artifactId: string
  name: string
  purpose: string
  mode: 'aggregate' | 'detail'
  columns: string[]
  rows: Array<Record<string, any>>
  totalRows: number
  truncated: boolean
  chartHint?: {
    vizType: 'bar' | 'line' | 'pie'
    xAxis: string
    yAxis: string[]
    chartTitle: string
  }
  geo?: ArtifactGeo
}

export interface EvaluationArtifactPayload {
  sourceSessionId: string
  question: string
  title: string
  dataSourceId: string
  skillId?: string
  skillName?: string
  conclusion: string
  presentation: { kpi: boolean; chart: boolean; map: boolean; table: boolean }
  items: EvaluationArtifactItem[]
}

export interface ArtifactContext {
  question: string
  dataSourceId: string
  /** 数据源名称（仅用于弹窗展示，不进入请求体） */
  dataSourceName?: string
  sourceSessionId?: string
  skillId?: string
  skillName?: string
}

export interface ArtifactSelection {
  itemIds: string[]
  includeConclusion: boolean
  presentation: { kpi: boolean; chart: boolean; map: boolean; table: boolean }
  title: string
}

/** 多轮对话中的一轮评估（按出现顺序编号，1 起） */
export interface EvaluationArtifactRound {
  roundIndex: number
  question: string
  context: ArtifactContext
  result: any
}

/** 用户在弹窗中对某一轮的勾选结果 */
export interface RoundSelection {
  round: EvaluationArtifactRound
  /** 该轮勾选的产物 id（归一化后的原始 id，未加轮次前缀） */
  itemIds: string[]
  /** 是否带入该轮综合结论 */
  includeConclusion: boolean
}

/** 单元格最大字符数（与后端 _MAX_TEXT_LEN 对齐） */
const MAX_CELL_CHARS = 200
/** 单条产物最大行数（与 qa-service 的 _MAX_RESULT_ROWS 对齐） */
const MAX_ROWS = 500

// ── 列名识别（复用评估页地图检测的口径）──
const LNG_PATTERN = /^(?:.*_)?(?:经度|lng|longitude|lon)(?:_|$)/i
const LAT_PATTERN = /^(?:.*_)?(?:纬度|lat|latitude)(?:_|$)/i
const NAME_PATTERN = /^(?:.*_)?(?:名称|地点|位置|区域|地区|城市|地名|name|location|place|region|city|site)$/i
const RADIUS_PATTERN = /(?:radius|半径)/i
const SEQ_PATTERN = /^(?:.*_)?(?:seq|序号)$/i
const ENTITY_PATTERN = /(?:aircraft_id|entity_id|实体编号|目标编号|飞机编号)$/i

/** 数值解析（失败返回 null） */
function toNumber(value: any): number | null {
  if (value === null || value === undefined || typeof value === 'boolean') return null
  const n = Number(String(value).replace(/,/g, '').trim())
  return Number.isFinite(n) ? n : null
}

/** 清洗单元格：标量保留，长文本截断，对象转 JSON 字符串 */
function safeScalar(value: any): any {
  if (value === null || value === undefined || typeof value === 'boolean' || typeof value === 'number') {
    return value
  }
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > MAX_CELL_CHARS ? `${text.slice(0, MAX_CELL_CHARS)}…` : text
}

/** 校验并清洗行数据（统一为对象数组） */
function cleanRows(columns: string[], rawRows: any[]): Array<Record<string, any>> {
  const rows: Array<Record<string, any>> = []
  for (const raw of rawRows.slice(0, MAX_ROWS)) {
    if (!raw || typeof raw !== 'object') continue
    const source = Array.isArray(raw)
      ? Object.fromEntries(columns.map((col, index) => [col, raw[index]]))
      : raw
    const cleaned: Record<string, any> = {}
    for (const [key, value] of Object.entries(source)) {
      cleaned[String(key)] = safeScalar(value)
    }
    rows.push(cleaned)
  }
  return rows
}

/** 从首行推导列名 */
function deriveColumns(columns: any, rows: Array<Record<string, any>>): string[] {
  if (Array.isArray(columns) && columns.length) return columns.map(String)
  return rows[0] ? Object.keys(rows[0]) : []
}

/** 是否存在至少一个数值列 */
function hasNumericColumn(columns: string[], rows: Array<Record<string, any>>): boolean {
  return columns.some((col) => rows.some((row) => toNumber(row[col]) !== null))
}

/** 是否存在非数值类目列 */
function hasCategoryColumn(columns: string[], rows: Array<Record<string, any>>): boolean {
  return columns.some((col) => rows.some((row) => (
    row[col] !== null && row[col] !== undefined && toNumber(row[col]) === null
  )))
}

/** 识别该步骤可用的图表/地图能力 */
export function detectGeo(columns: string[], rows: Array<Record<string, any>>): ArtifactGeo | undefined {
  const lngColumn = columns.find((col) => LNG_PATTERN.test(col))
  const latColumn = columns.find((col) => LAT_PATTERN.test(col))
  if (!lngColumn || !latColumn) return undefined

  const nameColumn = columns.find((col) => NAME_PATTERN.test(col))
  const radiusColumn = columns.find((col) => RADIUS_PATTERN.test(col))
  const seqColumn = columns.find((col) => SEQ_PATTERN.test(col))
  const entityColumn = columns.find((col) => ENTITY_PATTERN.test(col) || /(?:^|_)id$|编号$/i.test(col))

  /** 从行里提取业务属性（剔除坐标列） */
  const buildProps = (row: Record<string, any>): Record<string, any> | undefined => {
    const props: Record<string, any> = {}
    for (const [key, value] of Object.entries(row)) {
      if (key === lngColumn || key === latColumn) continue
      if (value !== null && value !== undefined && value !== '') props[key] = value
    }
    return Object.keys(props).length ? props : undefined
  }

  // ① 固定范围圈：存在半径列
  if (radiusColumn) {
    const areas: ArtifactArea[] = []
    for (const row of rows) {
      const lng = toNumber(row[lngColumn])
      const lat = toNumber(row[latColumn])
      const radiusKm = toNumber(row[radiusColumn])
      if (lng === null || lat === null || radiusKm === null) continue
      areas.push({
        name: String((nameColumn && row[nameColumn]) || '范围区域'),
        lng, lat, radiusKm,
        props: buildProps(row),
      })
    }
    if (areas.length) return { areas }
  }

  // ② 航迹：存在序号 + 实体编号列
  if (seqColumn && entityColumn) {
    const groups = new Map<string, Array<{ seq: number; lng: number; lat: number }>>()
    for (const row of rows) {
      const lng = toNumber(row[lngColumn])
      const lat = toNumber(row[latColumn])
      const seq = toNumber(row[seqColumn])
      if (lng === null || lat === null) continue
      const entity = String(row[entityColumn] ?? '目标')
      const list = groups.get(entity) || []
      list.push({ seq: seq ?? list.length, lng, lat })
      groups.set(entity, list)
    }
    const routes: ArtifactRoute[] = []
    groups.forEach((points, entity) => {
      points.sort((a, b) => a.seq - b.seq)
      if (points.length >= 2) {
        routes.push({
          name: entity,
          points: points.map((point) => ({ lng: point.lng, lat: point.lat })),
        })
      }
    })
    if (routes.length) return { routes }
  }

  // ③ 默认标点
  const markers: ArtifactMarker[] = []
  for (const row of rows) {
    const lng = toNumber(row[lngColumn])
    const lat = toNumber(row[latColumn])
    if (lng === null || lat === null) continue
    markers.push({
      name: String((nameColumn && row[nameColumn]) || `坐标点 ${markers.length + 1}`),
      lng, lat,
      props: buildProps(row),
    })
  }
  return markers.length ? { markers } : undefined
}

/** 单个产物的呈现能力 */
export function itemCapabilities(item: EvaluationArtifactItem): {
  chart: boolean
  map: boolean
  table: boolean
} {
  const hasGeo = !!item.geo && (
    (item.geo.markers?.length || 0)
    + (item.geo.routes?.length || 0)
    + (item.geo.areas?.length || 0)
  ) > 0
  const chartable = !!item.chartHint
    || (hasNumericColumn(item.columns, item.rows) && hasCategoryColumn(item.columns, item.rows))
  return { chart: chartable, map: hasGeo, table: item.rows.length > 0 }
}

/** 判断行数据适合聚合图表还是明细 */
function inferMode(columns: string[], rows: Array<Record<string, any>>, hasGeo: boolean): 'aggregate' | 'detail' {
  if (hasGeo) return 'detail'
  if (rows.length <= 200 && hasNumericColumn(columns, rows) && hasCategoryColumn(columns, rows)) {
    return 'aggregate'
  }
  return 'detail'
}

/** 内部：把一组「列 + 行」切片整理成产物条目 */
function buildItem(
  artifactId: string,
  name: string,
  purpose: string,
  columnsRaw: any,
  rowsRaw: any[],
  totalRows: number,
  chartHint?: EvaluationArtifactItem['chartHint'],
): EvaluationArtifactItem | null {
  const columns = Array.isArray(columnsRaw) ? columnsRaw.map(String) : []
  const rows = cleanRows(columns, Array.isArray(rowsRaw) ? rowsRaw : [])
  if (!rows.length) return null
  const finalColumns = deriveColumns(columns, rows)
  const geo = detectGeo(finalColumns, rows)
  const mode = inferMode(finalColumns, rows, !!geo)
  return {
    artifactId,
    name: name || artifactId,
    purpose: purpose || '',
    mode,
    columns: finalColumns,
    rows,
    totalRows: Math.max(totalRows || 0, rows.length),
    truncated: (totalRows || 0) > rows.length || rows.length >= MAX_ROWS,
    chartHint,
    geo,
  }
}

/** 技能结果的图表建议 → 绑定到列命中的首个步骤 */
function resolveChartHint(result: any, item: EvaluationArtifactItem): EvaluationArtifactItem['chartHint'] {
  const config = result?.chartConfig
  if (!config || !config.xAxis || !Array.isArray(config.yAxis) || !config.yAxis.length) return undefined
  if (!item.columns.includes(String(config.xAxis))) return undefined
  const vizType = String(config.vizType || 'bar')
  return {
    vizType: (vizType === 'line' || vizType === 'pie' ? vizType : 'bar'),
    xAxis: String(config.xAxis),
    yAxis: config.yAxis.map(String),
    chartTitle: String(config.chartTitle || item.name),
  }
}

/**
 * 归一化评估结果：返回数据项与结论。
 *
 * 在原有结果形态之外，追加后端补充的「空间分布」产物
 * （result.geoArtifacts），使评估分析可以直接生成带地图的态势页面。
 */
export function normalizeEvaluationResult(
  result: any,
  ctx: ArtifactContext,
): { items: EvaluationArtifactItem[]; conclusion: string } {
  const normalized = normalizeBaseEvaluationResult(result, ctx)
  const seen = new Set(normalized.items.map((item) => item.artifactId))
  const geoItems = Array.isArray(result?.geoArtifacts) ? result.geoArtifacts : []
  geoItems.forEach((raw: any, index: number) => {
    const item = normalizeGeoArtifact(raw, index)
    if (!item) return
    let artifactId = item.artifactId
    let seq = 2
    while (seen.has(artifactId)) {
      artifactId = `${item.artifactId}_${seq}`
      seq += 1
    }
    item.artifactId = artifactId
    seen.add(artifactId)
    normalized.items.push(item)
  })
  return normalized
}

/** 原有结果形态归一化（skill / 空战 / 效能 / 指标 / 通用查询） */
function normalizeBaseEvaluationResult(
  result: any,
  ctx: ArtifactContext,
): { items: EvaluationArtifactItem[]; conclusion: string } {
  const items: EvaluationArtifactItem[] = []
  const conclusion = String(result?.final_answer || result?.summary || result?.answer || '')
  const type = String(result?.type || '')

  if (type === 'skill') {
    const queryResults = Array.isArray(result.queryResults) ? result.queryResults : []
    queryResults.forEach((step: any, index: number) => {
      if (String(step?.status || '') !== 'completed') return
      const item = buildItem(
        String(step?.stepId || `q${index + 1}`),
        String(step?.stepName || step?.datasetName || `步骤 ${index + 1}`),
        String(step?.instruction || ''),
        step?.columns,
        step?.rows,
        Number(step?.totalRows || 0),
      )
      if (item) items.push(item)
    })
    if (items.length) {
      const hintTarget = items.find((item) => item.columns.includes(String(result?.chartConfig?.xAxis || '')))
      if (hintTarget) hintTarget.chartHint = resolveChartHint(result, hintTarget)
    }
    return { items, conclusion }
  }

  if (type === 'air_superiority' || type === 'combat_effectiveness') {
    const results = Array.isArray(result.results) ? result.results : []
    results.forEach((entry: any, index: number) => {
      const label = [entry?.group, entry?.label].filter(Boolean).join(' · ') || `结果 ${index + 1}`
      const item = buildItem(
        `r${index + 1}`,
        label,
        String(entry?.insight || ''),
        entry?.columns,
        entry?.rows,
        Array.isArray(entry?.rows) ? entry.rows.length : 0,
      )
      if (item) items.push(item)
    })
    return { items, conclusion }
  }

  if (type === 'indicator_calculation') {
    const sample = result?.queryResult?.sampleData
    const item = buildItem(
      'q1',
      '指标计算结果',
      String(result?.question || ctx.question || ''),
      result?.queryResult?.columns,
      Array.isArray(sample) ? sample : [],
      Array.isArray(sample) ? sample.length : 0,
    )
    if (item) items.push(item)
    return { items, conclusion }
  }

  // general / data_query：rawResults 单项
  const rawResults = Array.isArray(result?.rawResults) ? result.rawResults : []
  const item = buildItem(
    'q1',
    '评估数据结果',
    String(ctx.question || ''),
    result?.columns,
    rawResults,
    Number(result?.totalRows || rawResults.length),
    result?.chartConfig
      ? {
        vizType: String(result.chartConfig.vizType || 'bar') as 'bar' | 'line' | 'pie',
        xAxis: String(result.chartConfig.xAxis || ''),
        yAxis: Array.isArray(result.chartConfig.yAxis) ? result.chartConfig.yAxis.map(String) : [],
        chartTitle: String(result.chartConfig.chartTitle || '数据可视化'),
      }
      : undefined,
  )
  if (item) items.push(item)
  return { items, conclusion }
}

/** 清洗后端下发的 geo 结构（坐标非法或数量不足时返回 undefined） */
function sanitizeGeo(raw: any): ArtifactGeo | undefined {
  if (!raw || typeof raw !== 'object') return undefined

  const markers: ArtifactMarker[] = []
  for (const item of Array.isArray(raw.markers) ? raw.markers : []) {
    const lng = toNumber(item?.lng)
    const lat = toNumber(item?.lat)
    if (lng === null || lat === null) continue
    markers.push({
      name: String(item?.name || `坐标点 ${markers.length + 1}`),
      lng,
      lat,
      props: item?.props && typeof item.props === 'object' ? item.props : undefined,
    })
  }

  const routes: ArtifactRoute[] = []
  for (const route of Array.isArray(raw.routes) ? raw.routes : []) {
    const points: Array<{ lng: number; lat: number }> = []
    for (const point of Array.isArray(route?.points) ? route.points : []) {
      const lng = toNumber(point?.lng)
      const lat = toNumber(point?.lat)
      if (lng === null || lat === null) continue
      points.push({ lng, lat })
    }
    if (points.length >= 2) {
      routes.push({ name: String(route?.name || `航迹 ${routes.length + 1}`), points })
    }
  }

  const areas: ArtifactArea[] = []
  for (const area of Array.isArray(raw.areas) ? raw.areas : []) {
    const lng = toNumber(area?.lng)
    const lat = toNumber(area?.lat)
    const radiusKm = toNumber(area?.radiusKm)
    if (lng === null || lat === null || radiusKm === null || radiusKm <= 0) continue
    areas.push({
      name: String(area?.name || '范围区域'),
      lng,
      lat,
      radiusKm,
      props: area?.props && typeof area.props === 'object' ? area.props : undefined,
    })
  }

  if (!markers.length && !routes.length && !areas.length) return undefined
  return {
    markers: markers.length ? markers : undefined,
    routes: routes.length ? routes : undefined,
    areas: areas.length ? areas : undefined,
  }
}

/** 后端补充的「空间分布」产物 → 前端产物条目 */
function normalizeGeoArtifact(raw: any, index: number): EvaluationArtifactItem | null {
  if (!raw || typeof raw !== 'object') return null
  const rawColumns = Array.isArray(raw.columns) ? raw.columns.map(String) : []
  const rows = cleanRows(rawColumns, Array.isArray(raw.rows) ? raw.rows : [])
  if (!rows.length) return null
  const columns = deriveColumns(rawColumns, rows)
  // 优先使用后端预计算的 geo，保证与态势页面 bridge 的识别口径一致
  const geo = sanitizeGeo(raw.geo) || detectGeo(columns, rows)
  if (!geo) return null
  const sanitizedId = String(raw.artifactId || `geo${index + 1}`).replace(/[^A-Za-z0-9_-]/g, '')
  return {
    artifactId: sanitizedId || `geo${index + 1}`,
    name: String(raw.name || '空间分布'),
    purpose: String(raw.purpose || ''),
    mode: 'detail',
    columns,
    rows,
    totalRows: Math.max(Number(raw.totalRows || 0), rows.length),
    truncated: !!raw.truncated || rows.length >= MAX_ROWS,
    geo,
  }
}

/** 是否存在可用于生成态势页面的数据产物 */
export function hasUsableArtifacts(result: any): boolean {
  if (!result) return false
  const { items } = normalizeEvaluationResult(result, { question: '', dataSourceId: '' })
  return items.length > 0
}

/**
 * 把「没有可用产物」的原因说清楚，便于排查是取数失败还是确实无数据。
 *
 * 用于弹窗里对不可选轮次的说明，以及点击入口时的中文提示。
 */
export function describeNoArtifacts(result: any): string {
  const type = String(result?.type || '')
  const reasonOf = (entry: any) => String(entry?.error || entry?.insight || '').trim()
  if (type === 'skill') {
    const steps = Array.isArray(result.queryResults) ? result.queryResults : []
    const failed = steps.filter((s: any) => String(s?.status || '') !== 'completed')
    const reason = failed.map(reasonOf).find(Boolean)
    return `本次评估 ${steps.length} 个步骤均无可用数据${reason ? '：' + reason.slice(0, 60) : ''}`
  }
  if (type === 'air_superiority' || type === 'combat_effectiveness') {
    const entries = Array.isArray(result.results) ? result.results : []
    const empty = entries.filter((e: any) => !(Array.isArray(e?.rows) && e.rows.length))
    const reason = empty.map(reasonOf).find(Boolean)
    return `本次评估 ${entries.length} 个查询均未返回数据${reason ? '：' + reason.slice(0, 60) : ''}`
  }
  const rows = Array.isArray(result?.rawResults) ? result.rawResults : []
  return rows.length
    ? '评估结果未包含可展示的数据列'
    : '本次评估没有返回可展示的数据行'
}

/** 默认勾选：全部可用数据项 */
export function defaultSelectedIds(items: EvaluationArtifactItem[]): string[] {
  return items.filter((item) => item.rows.length > 0).map((item) => item.artifactId)
}

/** 构建请求体：只发送勾选的数据项 */
export function buildArtifactPayload(
  result: any,
  ctx: ArtifactContext,
  selection: ArtifactSelection,
): EvaluationArtifactPayload {
  const { items, conclusion } = normalizeEvaluationResult(result, ctx)
  const selectedIds = new Set(selection.itemIds)
  const selectedItems = items.filter((item) => selectedIds.has(item.artifactId))
  // 已勾选产物没有坐标时不允许请求地图，避免生成空白地图
  const mapAvailable = selectedItems.some((item) => itemCapabilities(item).map)
  return {
    sourceSessionId: ctx.sourceSessionId || '',
    question: ctx.question || '',
    title: selection.title || '',
    dataSourceId: ctx.dataSourceId || '',
    skillId: ctx.skillId || '',
    skillName: ctx.skillName || '',
    conclusion: selection.includeConclusion ? conclusion : '',
    presentation: {
      ...selection.presentation,
      map: selection.presentation.map && mapAvailable,
    },
    items: selectedItems,
  }
}

/** 合并结论的最大字符数（后端字段上限 50000，留出余量） */
const MAX_CONCLUSION_CHARS = 20000
/** 多轮问题拼接后的最大字符数（后端字段上限 2000） */
const MAX_QUESTION_CHARS = 800

/** 文本截断，超出时以省略号结尾 */
function truncateText(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit)}…` : text
}

/**
 * 构建多轮评估产物请求体：把多轮勾选的产物统一合并为一次生成请求。
 *
 * 合并口径（与方案文档一致）：
 *  - 产物按轮次顺序拼接，artifactId 加 `r{轮次}_` 前缀，避免跨轮 id 冲突；
 *  - 仅带入勾选了结论的轮次，按轮序用空行拼接为一段总结；
 *  - 单轮问题直接使用，多轮问题用「；」拼接并截断；
 *  - 技能在选中轮次中完全一致时才填写，否则留空；
 *  - 数据源取首个选中轮次（仅用于溯源），不限制跨数据源合并。
 *
 * Args:
 *   selections: 各轮的勾选结果（顺序不限，函数内部按轮次排序）
 *   options: 全局呈现偏好与页面标题
 *
 * Returns:
 *   后端可直接消费的评估产物请求体
 */
export function buildMultiRoundPayload(
  selections: RoundSelection[],
  options: {
    title: string
    presentation: { kpi: boolean; chart: boolean; map: boolean; table: boolean }
  },
): EvaluationArtifactPayload {
  const ordered = [...selections].sort((a, b) => a.round.roundIndex - b.round.roundIndex)
  const items: EvaluationArtifactItem[] = []
  const conclusions: string[] = []
  const questions: string[] = []
  const skillIds = new Set<string>()
  const skillNames = new Set<string>()
  let dataSourceId = ''
  let sourceSessionId = ''

  for (const selection of ordered) {
    const { round } = selection
    const normalized = normalizeEvaluationResult(round.result, round.context)
    const selectedIds = new Set(selection.itemIds)
    for (const item of normalized.items) {
      if (!selectedIds.has(item.artifactId)) continue
      items.push({ ...item, artifactId: `r${round.roundIndex}_${item.artifactId}` })
    }
    if (selection.includeConclusion && normalized.conclusion.trim()) {
      conclusions.push(normalized.conclusion.trim())
    }
    if (round.question.trim()) questions.push(round.question.trim())
    if (!dataSourceId) dataSourceId = round.context.dataSourceId || ''
    if (!sourceSessionId) sourceSessionId = round.context.sourceSessionId || ''
    if (round.context.skillId) skillIds.add(round.context.skillId)
    if (round.context.skillName) skillNames.add(round.context.skillName)
  }

  const question = questions.length > 1
    ? truncateText(questions.join('；'), MAX_QUESTION_CHARS)
    : (questions[0] || '基于评估分析结果生成态势页面')
  // 已勾选产物都没有坐标时关闭地图，避免生成空白地图
  const mapAvailable = items.some((item) => itemCapabilities(item).map)

  return {
    sourceSessionId,
    question,
    title: options.title.trim(),
    dataSourceId,
    skillId: skillIds.size === 1 ? [...skillIds][0] : '',
    skillName: skillNames.size === 1 ? [...skillNames][0] : '',
    conclusion: truncateText(conclusions.join('\n\n'), MAX_CONCLUSION_CHARS),
    presentation: {
      ...options.presentation,
      map: options.presentation.map && mapAvailable,
    },
    items,
  }
}
