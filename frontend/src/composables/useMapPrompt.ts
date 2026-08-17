/**
 * 公共地图检测逻辑
 * - 检测用户是否明确要求地图显示
 * - 综合处理坐标提取与地图显示意图
 * - 从查询结果数据（rawResults）中提取坐标列
 * - 优先使用新格式 map_annotations JSON，回退到旧文本标注格式
 */
import type { GeoPoint } from '@/utils/geoParser'
import type { GeoRoute, GeoArea } from '@/utils/geoAnnotation'
import { extractMapAnnotations, type CircleArea } from '@/utils/mapAnnotationParser'

/** 地图意图关键词 */
const MAP_KEYWORDS = ['地图', '标注', '坐标可视化', '显示地图', '地图显示', '在地图上', '绘制', '画出', '展示地图', '画地图']

/** 检测用户文本中是否包含地图显示意图 */
export function detectMapIntent(text: string): boolean {
  return MAP_KEYWORDS.some(kw => text.includes(kw))
}

export interface MapDataResult {
  geoPoints: GeoPoint[]
  routes: GeoRoute[]
  areas: GeoArea[]
  circles: CircleArea[]
  showMap: boolean
  showMapPrompt: boolean
  /** true 表示使用了 map_annotations JSON（后端显式标注），应跳过 rawResults 的点提取 */
  hasAnnotations: boolean
}

// ── 坐标列名模式 ──
/** 经度列名关键词（支持 hometown_longitude, lng, longitude, 经度 等） */
const LNG_PATTERNS = /^(?:.*_)?(?:经度|lng|longitude|lon)(?:_|$)/i
/** 纬度列名关键词 */
const LAT_PATTERNS = /^(?:.*_)?(?:纬度|lat|latitude)(?:_|$)/i
/** 地点/名称列名关键词（支持 name、名称 以及 *name、*名称 格式） */
const NAME_PATTERNS = /^(?:.*_)?(?:名称|地点|位置|区域|地区|城市|地名|name|location|place|region|city|site)$/i

/**
 * 从查询结果数据中提取坐标列
 *
 * 扫描 SQL 查询返回的 rawResults（或 combat/air 的 results），
 * 识别经度/纬度列名配对，提取数值型坐标构建 GeoPoint 数组。
 *
 * 支持的 result 结构：
 *   - data_query 类型: { columns: [...], rawResults: [{...}, ...] }
 *   - combat_effectiveness/air_superiority 类型: { results: [{ columns: [...], rows: [[...], ...] }, ...] }
 *
 * @param result  评估分析 API 返回的完整 result 对象
 * @returns GeoPoint 数组
 */
export function extractGeoFromResults(result: any): GeoPoint[] {
  if (!result) return []

  // 兼容直接传入行数组（[{lng, lat, ...}, ...]）——从首行推导列名
  if (Array.isArray(result)) {
    if (result.length && result[0] && typeof result[0] === 'object' && !Array.isArray(result[0])) {
      result = { columns: Object.keys(result[0]), rawResults: result }
    } else {
      return []
    }
  }

  // ── 收集所有列名+数据行的组合 ──
  const dataSlices: Array<{ columns: string[]; rows: any[] }> = []

  // 提取 data_query / general 类型的 rawResults
  if (result.columns && Array.isArray(result.columns) && Array.isArray(result.rawResults)) {
    dataSlices.push({ columns: result.columns, rows: result.rawResults })
  }

  // 提取 combat_effectiveness / air_superiority / indicator_calculation 的 results
  if (Array.isArray(result.results)) {
    for (const r of result.results) {
      if (r.columns && Array.isArray(r.columns) && Array.isArray(r.rows)) {
        dataSlices.push({ columns: r.columns, rows: r.rows })
      }
    }
  }

  // 提取 skill 类型的 queryResults
  if (Array.isArray(result.queryResults)) {
    for (const r of result.queryResults) {
      if (r.columns && Array.isArray(r.columns) && Array.isArray(r.rows)) {
        dataSlices.push({ columns: r.columns, rows: r.rows })
      }
    }
  }

  // ── 逐份数据查找坐标列配对 ──
  const geoPoints: GeoPoint[] = []

  for (const slice of dataSlices) {
    const { columns, rows } = slice
    if (!columns.length || !rows.length) continue

    // 识别经度/纬度/名称列的索引
    let lngIdx = -1
    let latIdx = -1
    let nameIdx = -1

    for (let i = 0; i < columns.length; i++) {
      const col = String(columns[i]).trim()
      if (lngIdx < 0 && LNG_PATTERNS.test(col)) lngIdx = i
      if (latIdx < 0 && LAT_PATTERNS.test(col)) latIdx = i
      if (nameIdx < 0 && NAME_PATTERNS.test(col)) nameIdx = i
    }

    // 没有找到经纬度配对 → 跳过
    if (lngIdx < 0 || latIdx < 0) continue

    // 提取每行的坐标
    for (let r = 0; r < rows.length; r++) {
      const row = rows[r]
      // 兼容对象数组和二维数组两种格式
      const lngVal = Array.isArray(row) ? parseFloat(row[lngIdx]) : parseFloat(row[columns[lngIdx]])
      const latVal = Array.isArray(row) ? parseFloat(row[latIdx]) : parseFloat(row[columns[latIdx]])

      if (isNaN(lngVal) || isNaN(latVal)) continue
      // 合理范围检查：经度 [-180, 180]，纬度 [-90, 90]
      if (lngVal < -180 || lngVal > 180 || latVal < -90 || latVal > 90) continue

      let name = ''
      if (nameIdx >= 0) {
        name = Array.isArray(row) ? String(row[nameIdx] ?? '') : String(row[columns[nameIdx]] ?? '')
        name = name.trim()
      }
      if (!name) {
        name = `坐标点 ${geoPoints.length + 1}`
      }

      // ── 提取非坐标、非名称的业务属性作为 props ──
      const props: Record<string, any> = {}
      for (let i = 0; i < columns.length; i++) {
        if (i === lngIdx || i === latIdx || i === nameIdx) continue
        const val = Array.isArray(row) ? row[i] : row[columns[i]]
        if (val !== null && val !== undefined && val !== '') {
          props[columns[i]] = typeof val === 'number' ? parseFloat(val.toFixed(2)) : val
        }
      }

      geoPoints.push({
        name,
        lng: lngVal,
        lat: latVal,
        raw: `${columns[lngIdx]}=${lngVal}, ${columns[latIdx]}=${latVal}`,
        ...(Object.keys(props).length > 0 ? { props } : {}),
      })
    }
  }

  return geoPoints
}

/**
 * 综合处理：提取坐标 + 判断地图显示策略
 *
 * 优先使用新的 map_annotations JSON 格式（LLM skill 输出），
 * 自动回退到旧的【区域标注】【路线标注】文本格式。
 *
 * @param fullText   AI 回复全文
 * @param userQuery  用户原始输入
 * @returns {geoPoints, showMap, showMapPrompt}
 *   - showMapPrompt=true：需弹出提示询问用户
 *   - showMap=true：直接显示地图（用户明确要求）
 */
export function processMapData(fullText: string, userQuery: string): MapDataResult {
  // ── 统一解析：优先新格式 JSON，回退旧文本格式 ──
  const result = extractMapAnnotations(fullText)

  const geoPoints = result.markers
  const routes = result.routes
  const areas = result.areas
  const circles = result.circles

  const hasData = geoPoints.length > 0 || routes.length > 0 || areas.length > 0 || circles.length > 0

  if (!hasData) {
    return { geoPoints: [], routes: [], areas: [], circles: [], showMap: false, showMapPrompt: false, hasAnnotations: false }
  }

  // 新 JSON 格式由 LLM 主动输出 → 直接显示，不弹提示
  if (result.source === 'json') {
    return { geoPoints, routes, areas, circles, showMap: true, showMapPrompt: false, hasAnnotations: true }
  }

  // 旧文本格式：根据用户是否明确要求决定
  if (detectMapIntent(userQuery)) {
    return { geoPoints, routes, areas, circles, showMap: true, showMapPrompt: false, hasAnnotations: false }
  }

  // 有坐标但未明确要求 → 弹出提示
  return { geoPoints, routes, areas, circles, showMap: false, showMapPrompt: true, hasAnnotations: false }
}
