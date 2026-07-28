/**
 * 公共地图检测逻辑
 * - 检测用户是否明确要求地图显示
 * - 综合处理坐标提取与地图显示意图
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
