/**
 * 地图瓦片配置（共享工具）。
 *
 * 从 GeoMap.vue 抽出：根据 admin-service 的地图服务配置构建 Leaflet 瓦片图层参数。
 * 消费方：GeoMap.vue（态势地图主组件）、ArtifactSandbox.vue（HTML Artifact 沙箱）。
 */
import api from '@/services/api'

export interface MapLayerConfig {
  id: string
  name: string
  urlTemplate: string
  opacity: number    // 基础透明度
  minZoom: number
  maxZoom: number
  tms?: boolean
  subdomains?: string[]
  attribution?: string
}

// 默认硬编码配置（GeoWebCache 6 层叠加，作为 API 失败时的兜底）
export const DEFAULT_BASE_URL = '/geowebcache/gwc'

/** 把本机 GeoServer 绝对地址转成同源代理相对路径，避免导出时 canvas 跨域污染 */
export function normalizeBaseUrl(baseUrl: string): string {
  if (!baseUrl) return baseUrl
  // http://localhost:9090/geowebcache/gwc → /geowebcache/gwc（走 vite/nginx 同源代理）
  return baseUrl.replace(/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//i, '/')
}

/** 根据 type + baseUrl 客户端构建图层 */
export function buildLayers(type: string, baseUrl: string): MapLayerConfig[] {
  const url = normalizeBaseUrl(baseUrl).replace(/\/+$/, '')
  if (type === 'geowebcache') {
    return [
      { id: 'china_provinces_3857', name: '省级行政边界', urlTemplate: `${url}/service/tms/1.0.0/china:china_provinces_3857@EPSG:900913@png/{z}/{x}/{y}.png`, opacity: 0.9, minZoom: 3, maxZoom: 18, tms: true },
      { id: 'china_cities_3857', name: '城市/区县边界', urlTemplate: `${url}/service/tms/1.0.0/china:china_cities_3857@EPSG:900913@png/{z}/{x}/{y}.png`, opacity: 0.3, minZoom: 3, maxZoom: 18, tms: true },
      { id: 'china_osm_waterareas_3857', name: '湖泊水库', urlTemplate: `${url}/service/tms/1.0.0/china:china_osm_waterareas_3857@EPSG:900913@png/{z}/{x}/{y}.png`, opacity: 0.4, minZoom: 3, maxZoom: 18, tms: true },
      { id: 'china_osm_waterways_3857', name: '河流水系', urlTemplate: `${url}/service/tms/1.0.0/china:china_osm_waterways_3857@EPSG:900913@png/{z}/{x}/{y}.png`, opacity: 0.3, minZoom: 3, maxZoom: 18, tms: true },
      { id: 'china_osm_roads_3857', name: '道路网络', urlTemplate: `${url}/service/tms/1.0.0/china:china_osm_roads_3857@EPSG:900913@png/{z}/{x}/{y}.png`, opacity: 0.2, minZoom: 3, maxZoom: 18, tms: true },
      { id: 'china_osm_railways_3857', name: '铁路地铁', urlTemplate: `${url}/service/tms/1.0.0/china:china_osm_railways_3857@EPSG:900913@png/{z}/{x}/{y}.png`, opacity: 0.1, minZoom: 3, maxZoom: 18, tms: true },
    ]
  }
  if (type === 'amap') {
    return [
      { id: 'amap_vector', name: '高德矢量底图', urlTemplate: 'https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}', opacity: 1, minZoom: 3, maxZoom: 18, tms: false, subdomains: ['1', '2', '3', '4'], attribution: '高德地图' },
      { id: 'amap_labels', name: '高德路网注记', urlTemplate: 'https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}', opacity: 1, minZoom: 3, maxZoom: 18, tms: false, subdomains: ['1', '2', '3', '4'], attribution: '高德地图' },
    ]
  }
  // 自定义: 地址作为单层瓦片源
  return [{ id: 'custom', name: '自定义图层', urlTemplate: normalizeBaseUrl(baseUrl), opacity: 0.9, minZoom: 3, maxZoom: 18, tms: true }]
}

/** 从 API 加载地图服务配置，失败则用默认配置 */
export async function loadActiveTileLayers(): Promise<MapLayerConfig[]> {
  try {
    const res: any = await api.get('/admin/config/map/active')
    if (res.success && res.data && res.data.type) {
      const layers = buildLayers(res.data.type, res.data.baseUrl || DEFAULT_BASE_URL)
      console.log('[mapTileConfig] 加载动态地图配置:', res.data.name, layers.length, '层')
      return layers
    }
  } catch (e) {
    console.warn('[mapTileConfig] 地图配置API加载失败，使用默认配置:', e)
  }
  console.log('[mapTileConfig] 使用默认 GeoWebCache 配置')
  return buildLayers('geowebcache', DEFAULT_BASE_URL)
}
