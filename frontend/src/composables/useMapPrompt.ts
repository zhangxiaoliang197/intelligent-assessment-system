/**
 * 公共地图检测逻辑
 * - 检测用户是否明确要求地图显示
 * - 综合处理坐标提取与地图显示意图
 * - 从查询结果数据（rawResults）中提取坐标列
 */
import { extractCoordinates, type GeoPoint } from '@/utils/geoParser'

/** 地图意图关键词 */
const MAP_KEYWORDS = ['地图', '标注', '坐标可视化', '显示地图', '地图显示', '在地图上']

/** 检测用户文本中是否包含地图显示意图 */
export function detectMapIntent(text: string): boolean {
  return MAP_KEYWORDS.some(kw => text.includes(kw))
}

export interface MapDataResult {
  geoPoints: GeoPoint[]
  showMap: boolean
  showMapPrompt: boolean
}

// ── 坐标列名模式 ──
/** 经度列名关键词 */
const LNG_PATTERNS = /^(?:经度|lng|longitude|lon|lng_|lon_|x_coord|coord_x|坐标x)$/i
/** 纬度列名关键词 */
const LAT_PATTERNS = /^(?:纬度|lat|latitude|lat_|y_coord|coord_y|坐标y)$/i
/** 地点/名称列名关键词 */
const NAME_PATTERNS = /^(?:名称|地点|位置|区域|地区|城市|地名|name|location|place|region|city|site)$/i

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

      geoPoints.push({
        name,
        lng: lngVal,
        lat: latVal,
        raw: `${columns[lngIdx]}=${lngVal}, ${columns[latIdx]}=${latVal}`,
      })
    }
  }

  return geoPoints
}

/**
 * 综合处理：提取坐标 + 判断地图显示策略
 *
 * @param fullText   AI 回复全文
 * @param userQuery  用户原始输入
 * @returns {geoPoints, showMap, showMapPrompt}
 *   - showMapPrompt=true：需弹出提示询问用户
 *   - showMap=true：直接显示地图（用户明确要求）
 */
export function processMapData(fullText: string, userQuery: string): MapDataResult {
  const geoPoints = extractCoordinates(fullText)

  if (geoPoints.length === 0) {
    return { geoPoints: [], showMap: false, showMapPrompt: false }
  }

  if (detectMapIntent(userQuery)) {
    // 用户明确要求 → 直接显示地图
    return { geoPoints, showMap: true, showMapPrompt: false }
  }

  // 有坐标但未明确要求 → 弹出提示
  return { geoPoints, showMap: false, showMapPrompt: true }
}
