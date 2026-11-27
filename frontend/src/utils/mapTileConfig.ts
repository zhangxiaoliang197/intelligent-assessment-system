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

// 默认硬编码配置（内网 GeoWebCache 的 esri1/esri2 两层，作为 API 失败或高德不可达时的兜底）
// baseUrl 只到 GWC 上下文根（/geowebcache），TMS 路径由下方图层模板自行拼接；
// 多写一层 /gwc 会拼出 /geowebcache/gwc/service/tms/...，现场实测 404。
export const DEFAULT_BASE_URL = '/geowebcache'

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
  // http://localhost:9090/geowebcache → /geowebcache（走 vite/nginx 同源代理）
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
        id: 'esri1', name: '底图系列一',
        urlTemplate: `${base}/service/tms/1.0.0/esri1@EPSG:3857_esri1@png/{z}/{x}/{y}.png`,
        opacity: 1, minZoom: 3, maxZoom: 18, tms: true, attribution: 'GeoWebCache',
      },
      {
        id: 'esri2', name: '底图系列二',
        urlTemplate: `${base}/service/tms/1.0.0/esri2@EPSG:3857_esri2@png/{z}/{x}/{y}.png`,
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

// ── 瓦片连通性探测（配置页「测试」按钮使用） ──

/**
 * 探测坐标：尽量选中国区域内、通常有数据的行列。
 * geowebcache 走 TMS，y 轴自下而上，这里的 y 已按 2^z-1-y 翻转。
 */
const PROBE_TILES: Record<string, Array<{ z: number; x: number; y: number }>> = {
  geowebcache: [
    { z: 5, x: 26, y: 19 },
    { z: 3, x: 6, y: 4 }
  ],
  amap: [
    { z: 3, x: 6, y: 3 },
    { z: 4, x: 13, y: 6 }
  ],
  custom: [
    { z: 3, x: 6, y: 3 },
    { z: 4, x: 13, y: 6 }
  ]
}

/** 探测结果：失败时 message 已翻译成可操作的中文原因 */
export interface TileProbeResult {
  ok: boolean
  message: string
  url: string
  status?: number
  contentType?: string
  bytes?: number
  latencyMs?: number
}

/** 把 {z}/{x}/{y}/{-y} 占位符替换成具体行列 */
function fillTileTemplate(template: string, z: number, x: number, y: number): string {
  return template
    .replace(/\{-y\}/g, String(y))
    .replace(/\{z\}/g, String(z))
    .replace(/\{x\}/g, String(x))
    .replace(/\{y\}/g, String(y))
}

/**
 * 生成前端同源探测地址（走 nginx/vite 实际代理链路）。
 *
 * @param type    地图服务类型
 * @param baseUrl 同源前缀或空（空时用默认前缀）
 * @returns 候选瓦片地址，依次尝试
 */
export function buildProbeTileUrls(type: string, baseUrl: string): string[] {
  const layers = buildLayers(type, baseUrl)
  const template = layers[0]?.urlTemplate || ''
  const tiles = PROBE_TILES[type] || PROBE_TILES.custom
  const hasPlaceholder = /\{(z|x|y|-y)\}/.test(template)
  return tiles.map(t => hasPlaceholder
    ? fillTileTemplate(template, t.z, t.x, t.y)
    : `${template.replace(/\/+$/, '')}/${t.z}/${t.x}/${t.y}.png`)
}

/**
 * 把探测失败原因翻译成具体的中文说明，便于现场直接定位问题类型。
 *
 * @param status      HTTP 状态码，网络不可达时为空
 * @param contentType 响应内容类型
 * @param error       捕获到的异常
 * @param bodySnippet 上游响应正文摘要（用于说明具体原因）
 */
export function describeTileProbeFailure(
  status?: number,
  contentType?: string,
  error?: unknown,
  bodySnippet?: string
): string {
  const detail = bodySnippet ? `（上游返回：${bodySnippet.slice(0, 120)}）` : ''
  if (status === undefined) {
    const message = error instanceof Error ? error.message : String(error ?? '')
    return `无法连接地图服务：网络不可达，或同源代理未转发该路径（${message || '请求被浏览器拦截'}）`
  }
  if (status === 400) {
    return `请求被上游拒绝（HTTP 400）：瓦片地址、图层名或网格集不正确${detail}`
  }
  if (status === 401 || status === 403) {
    return `上游拒绝访问（HTTP ${status}）：瓦片服务需要鉴权，或未放行当前来源 IP${detail}`
  }
  if (status === 404) {
    return '上游可达但瓦片不存在（HTTP 404）：图层名或网格集不匹配，或该层级/行列无数据'
  }
  if (status >= 500) {
    return `地图服务异常（HTTP ${status}）：瓦片服务未启动，或反向代理目标地址配置错误`
  }
  if (status >= 300 && status < 400) {
    return `地址发生重定向（HTTP ${status}）：请直接填写最终可访问的瓦片服务地址`
  }
  if (contentType && !contentType.startsWith('image/')) {
    return `返回内容不是图片（${contentType}）：代理指到了错误页或登录页${detail}`
  }
  if (status >= 200 && status < 300) {
    return '瓦片响应为空或格式不符（0 字节/非图片）：瓦片服务异常，或该层级/行列没有数据'
  }
  return `瓦片检测失败（HTTP ${status}）：响应不符合瓦片格式${detail}`
}

/**
 * 按真实链路探测同源代理下的瓦片是否可用。
 *
 * @param type    地图服务类型
 * @param baseUrl 同源前缀（如 /geowebcache、/amap-tiles）
 * @returns 探测结果
 */
export async function probeSameOriginTiles(type: string, baseUrl: string): Promise<TileProbeResult> {
  const urls = buildProbeTileUrls(type, baseUrl)
  let last: TileProbeResult = { ok: false, url: '', message: '没有可用的瓦片探测地址，请先填写服务地址' }

  for (const url of urls) {
    const started = performance.now()
    try {
      const res = await fetch(url, { cache: 'no-store' })
      const contentType = res.headers.get('content-type') || ''
      if (res.ok && contentType.startsWith('image/')) {
        const blob = await res.blob()
        const latencyMs = Math.round(performance.now() - started)
        if (blob.size > 0) {
          return {
            ok: true,
            url,
            status: res.status,
            contentType,
            bytes: blob.size,
            latencyMs,
            message: `瓦片检测通过：HTTP ${res.status}，${contentType}，${blob.size} 字节，${latencyMs}ms`
          }
        }
        last = {
          ok: false, url, status: res.status, contentType, bytes: 0, latencyMs,
          message: '瓦片响应为空（0 字节）：瓦片服务异常，或该层级/行列没有数据'
        }
        continue
      }
      // 非图片响应读取正文摘要，便于指出“图层名/网格集不正确”等具体原因
      const text = await res.text()
      const latencyMs = Math.round(performance.now() - started)
      last = {
        ok: false,
        url,
        status: res.status,
        contentType,
        bytes: text.length,
        latencyMs,
        message: describeTileProbeFailure(res.status, contentType, undefined, text.trim())
      }
      // 404 可能只是该层级无数据，继续尝试下一个坐标
    } catch (e) {
      last = { ok: false, url, message: describeTileProbeFailure(undefined, undefined, e) }
    }
  }
  return last
}
