/**
 * 从 AI 回复文本中解析结构化的路线和区域标注
 *
 * AI 输出格式约定:
 *   【路线标注:路线名称】
 *   东经116.32°，北纬39.89°
 *   ...  (每行一个坐标)
 *
 *   【区域标注:区域名称】
 *   东经115.70°，北纬40.50°
 *   ...  (每行一个边界顶点)
 */
import { extractCoordinates, type GeoPoint } from './geoParser'

export interface GeoRoute {
  name: string
  points: GeoPoint[]
  color?: string
}

export interface GeoArea {
  name: string
  points: GeoPoint[]
  color?: string
}

export interface GeoAnnotationResult {
  routes: GeoRoute[]
  areas: GeoArea[]
}

/** 匹配 【路线标注】:名称 或 【路线标注:名称】 — 冒号可在 】前后 */
function findAnchors(text: string): Array<{ type: 'route' | 'area'; name: string; start: number; end: number }> {
  const anchors: Array<{ type: 'route' | 'area'; name: string; start: number; end: number }> = []

  // 支持两种冒号位置: 【标签:名称】 和 【标签】:名称
  const headerRegex = /^【(路线标注|区域标注)(?:】:?|:)(.*?)】$/gm
  let m: RegExpExecArray | null
  while ((m = headerRegex.exec(text)) !== null) {
    const type = m[1] === '路线标注' ? 'route' : 'area'
    const name = (m[2] || '').trim()
    anchors.push({ type, name, start: m.index, end: m.index + m[0].length })
  }
  return anchors
}

/**
 * 凸包排序 (Graham Scan)
 * 将无序的多边形顶点按逆时针方向排列，避免自相交
 * 对于非凸多边形（如行政边界），退化为按质心角度排序
 */
function convexHullSort(points: GeoPoint[]): GeoPoint[] {
  if (points.length <= 2) return points

  // 计算质心
  let cx = 0, cy = 0
  for (const p of points) {
    cx += p.lng
    cy += p.lat
  }
  cx /= points.length
  cy /= points.length

  // 按相对于质心的极角排序
  const sorted = [...points].sort((a, b) => {
    const angleA = Math.atan2(a.lat - cy, a.lng - cx)
    const angleB = Math.atan2(b.lat - cy, b.lng - cx)
    return angleA - angleB
  })

  return sorted
}

/** 从文本中解析【路线标注】和【区域标注】 */
export function parseAnnotations(text: string): GeoAnnotationResult {
  const routes: GeoRoute[] = []
  const areas: GeoArea[] = []
  const anchors = findAnchors(text)

  if (anchors.length === 0) return { routes, areas }

  // 逐段提取坐标
  for (let i = 0; i < anchors.length; i++) {
    const anchor = anchors[i]
    const contentStart = anchor.end
    const contentEnd = i + 1 < anchors.length ? anchors[i + 1].start : text.length
    const segment = text.slice(contentStart, contentEnd)

    // 从该段中提取坐标
    const coords = extractCoordinates(segment)

    if (coords.length > 0) {
      if (anchor.type === 'route') {
        routes.push({ name: anchor.name, points: coords })
      } else {
        // 区域标注：对顶点进行凸包排序，避免自相交
        const sorted = convexHullSort(coords)
        areas.push({ name: anchor.name, points: sorted })
      }
    }
  }

  return { routes, areas }
}

/**
 * 从 geoPoints 中剔除与 route/area 顶点重叠的点
 * 避免同一个坐标同时显示为独立点和多边形顶点
 */
export function filterOverlapPoints(
  geoPoints: GeoPoint[],
  routes: GeoRoute[],
  areas: GeoArea[],
  tolerance = 0.01
): GeoPoint[] {
  if (routes.length === 0 && areas.length === 0) return geoPoints

  const allAnnotationPoints: GeoPoint[] = []
  routes.forEach(r => allAnnotationPoints.push(...r.points))
  areas.forEach(a => allAnnotationPoints.push(...a.points))

  return geoPoints.filter(p => {
    return !allAnnotationPoints.some(ap =>
      Math.abs(ap.lat - p.lat) < tolerance && Math.abs(ap.lng - p.lng) < tolerance
    )
  })
}
