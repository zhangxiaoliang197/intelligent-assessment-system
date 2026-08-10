/**
 * 统一地图标注解析器
 *
 * 支持两种输入格式：
 * 1. 【新格式】map_annotations JSON 代码块（LLM skill 输出，首选）
 * 2. 【旧格式】【区域标注】【路线标注】文本标注（兼容旧版 LLM 输出）
 *
 * 新格式示例：
 * ```map_annotations
 * { "markers": [...], "routes": [...], "areas": [...] }
 * ```
 */
import { extractCoordinates, type GeoPoint } from './geoParser'
import { parseAnnotations, filterOverlapPoints, type GeoRoute, type GeoArea } from './geoAnnotation'

// ── 新格式类型定义 ──

/** LLM 输出的标注点 */
interface AnnotationMarker {
  name: string
  lng: number
  lat: number
}

/** LLM 输出的路线 */
interface AnnotationRoute {
  name: string
  points: Array<{ lng: number; lat: number }>
}

/** LLM 输出的区域 */
interface AnnotationArea {
  name: string
  shape?: 'polygon' | 'circle'
  points?: Array<{ lng: number; lat: number }>
  center?: { lng: number; lat: number }
  radiusKm?: number
}

/** map_annotations JSON 顶层结构 */
interface MapAnnotationJson {
  markers?: AnnotationMarker[]
  routes?: AnnotationRoute[]
  areas?: AnnotationArea[]
}

/** 圆形区域（解析后） */
export interface CircleArea {
  name: string
  center: { lng: number; lat: number }
  radiusKm: number
}

export interface MapAnnotationResult {
  markers: GeoPoint[]
  routes: GeoRoute[]
  areas: GeoArea[]
  circles: CircleArea[]
  /** 标注来源：json = 新格式，text = 旧文本格式，none = 无标注 */
  source: 'json' | 'text' | 'none'
  /** 解析错误信息（如果有） */
  parseError?: string
}

// ── 工具函数 ──

/** 校验经纬度是否在合理范围 */
function isValidLngLat(lng: number, lat: number): boolean {
  return !isNaN(lng) && !isNaN(lat)
    && lng >= -180 && lng <= 180
    && lat >= -90 && lat <= 90
}

/** 校验点位名称是否合法 */
function isValidName(name: unknown): name is string {
  return typeof name === 'string' && name.trim().length > 0
}

// ── JSON 格式解析 ──

/**
 * 从 AI 回复文本中提取 map_annotations JSON 代码块
 * 支持有/无语言标识符两种写法：
 *   ```map_annotations\n{...}\n```
 *   ```json\n{...}\n```
 */
function extractMapAnnotationJson(text: string): MapAnnotationJson | null {
  // 优先匹配 ```map_annotations 代码块
  const blockRegex = /```(?:map_annotations|map-annotation)\s*\n([\s\S]*?)```/i
  const blockMatch = text.match(blockRegex)
  if (blockMatch) {
    try {
      return JSON.parse(blockMatch[1].trim()) as MapAnnotationJson
    } catch {
      // JSON 解析失败，继续尝试其他模式
    }
  }

  // 回退：匹配 ```json 代码块中包含 markers/routes/areas 的内容
  const jsonBlockRegex = /```json\s*\n([\s\S]*?)```/gi
  let jsonMatch: RegExpExecArray | null
  while ((jsonMatch = jsonBlockRegex.exec(text)) !== null) {
    try {
      const parsed = JSON.parse(jsonMatch[1].trim())
      if (parsed && (parsed.markers || parsed.routes || parsed.areas)) {
        return parsed as MapAnnotationJson
      }
    } catch {
      continue
    }
  }

  return null
}

/** 将新格式 JSON 标注转换为统一结果 */
function convertJsonToResult(json: MapAnnotationJson, validationMode: 'strict' | 'lenient' = 'strict'): MapAnnotationResult {
  const errors: string[] = []
  const markers: GeoPoint[] = []
  const routes: GeoRoute[] = []
  const areas: GeoArea[] = []

  // ── 解析 markers ──
  if (Array.isArray(json.markers)) {
    for (const m of json.markers) {
      if (!isValidName(m.name)) {
        errors.push('marker 缺少 name 字段')
        continue
      }
      if (!isValidLngLat(m.lng, m.lat)) {
        errors.push(`marker "${m.name}" 经纬度无效: (${m.lng}, ${m.lat})`)
        continue
      }
      const name = m.name.trim()
      markers.push({
        name,
        lng: parseFloat(m.lng.toFixed(6)),
        lat: parseFloat(m.lat.toFixed(6)),
        raw: `${name}: ${m.lng}, ${m.lat}`,
      })
    }
  }

  // ── 解析 routes ──
  if (Array.isArray(json.routes)) {
    for (const r of json.routes) {
      if (!isValidName(r.name)) {
        errors.push('route 缺少 name 字段')
        continue
      }
      if (!Array.isArray(r.points) || r.points.length < 2) {
        errors.push(`route "${r.name}" 至少需要2个节点，实际 ${r.points?.length ?? 0} 个`)
        if (validationMode === 'strict') continue
      }
      const points: GeoPoint[] = []
      for (const p of r.points) {
        if (!isValidLngLat(p.lng, p.lat)) {
          errors.push(`route "${r.name}" 包含无效经纬度: (${p.lng}, ${p.lat})`)
          continue
        }
        points.push({
          name: '',
          lng: parseFloat(p.lng.toFixed(6)),
          lat: parseFloat(p.lat.toFixed(6)),
          raw: `${p.lng}, ${p.lat}`,
        })
      }
      if (points.length >= 2) {
        routes.push({ name: r.name.trim(), points })
      }
    }
  }

  // ── 解析 areas（区分 polygon 和 circle）──
  const circles: CircleArea[] = []
  if (Array.isArray(json.areas)) {
    for (const a of json.areas) {
      if (!isValidName(a.name)) {
        errors.push('area 缺少 name 字段')
        continue
      }

      // 判断形状类型
      const shape = a.shape || 'polygon'

      if (shape === 'circle') {
        // ── 圆形区域 ──
        if (!a.center || !isValidLngLat(a.center.lng, a.center.lat)) {
          errors.push(`circle "${a.name}" 缺少 center 或坐标无效`)
          continue
        }
        const radiusKm = typeof a.radiusKm === 'number' ? a.radiusKm : NaN
        if (isNaN(radiusKm) || radiusKm <= 0 || radiusKm > 5000) {
          errors.push(`circle "${a.name}" radiusKm 无效: ${a.radiusKm}（需为 0~5000 的正数）`)
          if (validationMode === 'strict') continue
        }
        circles.push({
          name: a.name.trim(),
          center: {
            lng: parseFloat(a.center.lng.toFixed(6)),
            lat: parseFloat(a.center.lat.toFixed(6)),
          },
          radiusKm: parseFloat(radiusKm.toFixed(2)),
        })
      } else {
        // ── 多边形区域（默认）──
        if (!Array.isArray(a.points) || a.points.length < 3) {
          errors.push(`polygon "${a.name}" 至少需要3个顶点，实际 ${a.points?.length ?? 0} 个`)
          if (validationMode === 'strict') continue
        }
        const points: GeoPoint[] = []
        for (const p of a.points || []) {
          if (!isValidLngLat(p.lng, p.lat)) {
            errors.push(`polygon "${a.name}" 包含无效经纬度: (${p.lng}, ${p.lat})`)
            continue
          }
          points.push({
            name: '',
            lng: parseFloat(p.lng.toFixed(6)),
            lat: parseFloat(p.lat.toFixed(6)),
            raw: `${p.lng}, ${p.lat}`,
          })
        }
        if (points.length >= 3) {
          areas.push({ name: a.name.trim(), points })
        }
      }
    }
  }

  return {
    markers,
    routes,
    areas,
    circles,
    source: 'json',
    parseError: errors.length > 0 ? errors.join('；') : undefined,
  }
}

/** 从旧文本格式中解析标注，转换为统一结果 */
function convertTextToResult(text: string): MapAnnotationResult {
  const geoPoints = extractCoordinates(text)
  const { routes, areas } = parseAnnotations(text)
  const markers = filterOverlapPoints(geoPoints, routes, areas)

  const hasData = markers.length > 0 || routes.length > 0 || areas.length > 0

  return {
    markers,
    routes,
    areas,
    circles: [],
    source: hasData ? 'text' : 'none',
  }
}

/**
 * 统一入口：从 AI 回复文本中解析地图标注数据
 *
 * 优先级：
 *   1. 新格式 JSON（map_annotations 代码块）
 *   2. 旧格式文本（【区域标注】【路线标注】）
 *
 * @param text AI 回复全文
 * @returns 统一的地图标注结果
 */
export function extractMapAnnotations(text: string): MapAnnotationResult {
  // 先尝试新格式 JSON
  const json = extractMapAnnotationJson(text)
  if (json) {
    const result = convertJsonToResult(json)
    // 如果新格式解析出了数据（即使有部分错误），也优先使用
    if (result.markers.length > 0 || result.routes.length > 0 || result.areas.length > 0 || result.circles.length > 0) {
      return result
    }
    // JSON 块存在但全无效 → 告知错误
    if (result.parseError) {
      return result
    }
  }

  // 回退到旧格式文本解析
  return convertTextToResult(text)
}

/**
 * 从文本中移除 map_annotations 代码块，用于渲染前过滤。
 * LLM 输出的 JSON 标注块是给系统解析的，不应在聊天中展示。
 *
 * @param text 原始 AI 回复文本
 * @returns 过滤后的纯展示文本
 */
export function stripMapAnnotationBlock(text: string): string {
  // 匹配 ```map_annotations ... ``` 代码块（含前后空白行）
  return text.replace(/```map_annotations[\s\S]*?```/g, '').trim()
}
