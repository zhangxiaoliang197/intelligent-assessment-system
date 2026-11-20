/**
 * 地图瓦片配置（共享工具）。
 *
 * 根据 admin-service 的地图服务配置构建 Leaflet 瓦片图层参数，并给出备用图层。
 * 消费方：GeoMap.vue（问答/指标/评估页地图）、PageSandbox.vue（态势页面沙箱）。
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

// 默认硬编码配置（内网 GeoWebCache 的 seri1/seri2 两层，作为 API 失败或高德不可达时的兜底）
export const DEFAULT_BASE_URL = '/geowebcache/gwc'

// 高德瓦片同源代理前缀（vite 开发代理 / nginx 生产代理转发到高德瓦片域名）
export const DEFAULT_AMAP_BASE = '/amap-tiles'

/** 主用与备用瓦片图层 */
export interface MapLayersConfig {
  primary: MapLayerConfig[]
  fallback: MapLayerConfig[]
}

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
    // 内网 GeoWebCache：TMS 端点形如
    // /service/tms/1.0.0/{图层}@{网格集}@{格式}/{z}/{x}/{y}.png
    // 图层名与网格集必须与内网发布的一致。
    // TMS 端点固定按左下原点解释坐标，因此 tms 必须为 true（与网格集名里是否含 esri 无关）。
    const base = url || DEFAULT_BASE_URL
    return [
      {
        id: 'seri1', name: '底图系列一',
        urlTemplate: `${base}/service/tms/1.0.0/seri1@EPSG:3857_esri1@png/{z}/{x}/{y}.png`,
        opacity: 1, minZoom: 3, maxZoom: 18, tms: true, attribution: 'GeoWebCache',
      },
      {
        id: 'seri2', name: '底图系列二',
        urlTemplate: `${base}/service/tms/1.0.0/seri2@EPSG:3857_esri2@png/{z}/{x}/{y}.png`,
        opacity: 0.6, minZoom: 3, maxZoom: 18, tms: true, attribution: 'GeoWebCache',
      },
    ]
  }
  if (type === 'amap') {
    // 高德栅格瓦片经同源代理获取（baseUrl 留空时用默认代理前缀），
    // 矢量底图 webrd 本身自带注记，不再叠加 webst 注记层，避免文字重影。
    const base = url || DEFAULT_AMAP_BASE
    return [
      { id: 'amap_vector', name: '高德矢量底图', urlTemplate: `${base}/vec/{z}/{x}/{y}.png`, opacity: 1, minZoom: 3, maxZoom: 18, attribution: '高德地图' },
    ]
  }
  // 自定义: 地址作为单层瓦片源
  return [{ id: 'custom', name: '自定义图层', urlTemplate: normalizeBaseUrl(baseUrl), opacity: 0.9, minZoom: 3, maxZoom: 18, tms: true }]
}

/** GeoWebCache 兜底图层（非高德底图时无需回退） */
export function buildFallbackLayers(): MapLayerConfig[] {
  return buildLayers('geowebcache', DEFAULT_BASE_URL)
}

/** 从 API 加载地图服务配置，失败则用默认 GeoWebCache 配置 */
export async function loadMapLayersConfig(): Promise<MapLayersConfig> {
  try {
    const res: any = await api.get('/admin/config/map/active')
    if (res.success && res.data && res.data.type) {
      const type = res.data.type
      const layers = buildLayers(type, res.data.baseUrl || (type === 'amap' ? DEFAULT_AMAP_BASE : DEFAULT_BASE_URL))
      console.log('[mapTileConfig] 加载动态地图配置:', res.data.name, layers.length, '层')
      return { primary: layers, fallback: type === 'amap' ? buildFallbackLayers() : [] }
    }
  } catch (e) {
    console.warn('[mapTileConfig] 地图配置API加载失败，使用默认配置:', e)
  }
  console.log('[mapTileConfig] 使用默认 GeoWebCache 配置')
  return { primary: buildLayers('geowebcache', DEFAULT_BASE_URL), fallback: [] }
}
