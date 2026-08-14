<template>
  <div class="geo-map-container" :class="{ 'is-compact': compact }">
    <div v-if="showHeader && !compact" class="geo-map-header">
      <span class="geo-map-title">坐标可视化</span>
      <div class="geo-map-header-right">
        <span class="geo-map-count">{{ points.length }} 个坐标点</span>
        <span v-if="routes && routes.length > 0" class="geo-map-count geo-map-route-count">
          {{ routes.length }} 条路线
        </span>
        <span v-if="areas && areas.length > 0" class="geo-map-count geo-map-area-count">
          {{ areas.length }} 个区域
        </span>
        <span v-if="circles && circles.length > 0" class="geo-map-count geo-map-circle-count">
          {{ circles.length }} 个圆形区域
        </span>
        <span v-if="drawnCount > 0" class="geo-map-count geo-map-drawn-count">
          {{ drawnCount }} 个手绘元素
        </span>
      </div>
    </div>
    <div ref="mapContainer" class="geo-map-content"></div>
    <div v-if="!compact && points.length > 0" class="geo-point-table">
      <div class="geo-table-header" @click="tableExpanded = !tableExpanded" style="cursor:pointer; user-select:none">
        <span class="geo-table-title">{{ tableExpanded ? '▼' : '▶' }} 提取坐标点 ({{ points.length }})</span>
      </div>
      <table v-if="tableExpanded">
        <thead>
          <tr>
            <th>名称</th>
            <th>经度</th>
            <th>纬度</th>
            <th v-for="col in extraColumns" :key="col">{{ cnLabel(col) }}</th>
            <th>原文</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in points" :key="i">
            <td>
              <span class="point-dot" :style="{ background: getColorByName(p.routeName || p.name) }"></span>
              {{ p.name }}
            </td>
            <td>{{ p.lng.toFixed(4) }}</td>
            <td>{{ p.lat.toFixed(4) }}</td>
            <td v-for="col in extraColumns" :key="col">{{ p.props?.[col] ?? '-' }}</td>
            <td class="raw-cell" :title="p.raw">{{ p.raw }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted, computed, nextTick } from 'vue'
import L from 'leaflet'
import 'leaflet-draw'
import 'leaflet-draw/dist/leaflet.draw.css'
import gcoord from 'gcoord'
import { type GeoPoint } from '@/utils/geoParser'
import { type GeoRoute, type GeoArea } from '@/utils/geoAnnotation'
import { type CircleArea } from '@/utils/mapAnnotationParser'
import { cnLabel } from '@/utils/mapAnnotationParser'
import api from '@/services/api'

const props = withDefaults(defineProps<{
  points: GeoPoint[]
  routes?: GeoRoute[]
  areas?: GeoArea[]
  circles?: CircleArea[]
  /** WGS84 视口。态势插槽恢复历史报告时以它为准。 */
  viewport?: { center: [number, number]; zoom: number }
  title?: string
  compact?: boolean  // 紧凑模式：隐藏标题栏和坐标表，适用于嵌入其他面板
  showHeader?: boolean   // 隐藏“坐标可视化”头部
  showTable?: boolean    // 隐藏坐标点表格
}>(), {
  showHeader: true,
  showTable: true,
})

const emit = defineEmits<{
  (e: 'marker-click', payload: { point: GeoPoint; layerId?: string }): void
  (e: 'region-select', payload: { regionId: string; name: string; geometry?: any }): void
  (e: 'draw-end', payload: { type: string; geojson: any; name?: string }): void
  (e: 'viewport-change', vp: { center: [number, number]; zoom: number }): void
}>()

const mapContainer = ref<HTMLElement | null>(null)
let map: L.Map | null = null
let markers: L.Marker[] = []
let circleMarkers: L.CircleMarker[] = []
let spiderLineLayer: L.FeatureGroup | null = null
let routeLayers: L.Polyline[] = []
let areaLayers: L.Polygon[] = []
let circleLayers: L.Circle[] = []
let tileLayers: { layer: L.TileLayer; config: MapLayerConfig }[] = []

// ── 用户手绘图层 ──
let drawnItems: L.FeatureGroup | null = null
let drawControl: L.Control.Draw | null = null
const drawnCount = ref(0)

const tableExpanded = ref(false)

/** 动态发现所有点共同的附加属性列（排除 lng/lat/name/raw） */
const extraColumns = computed(() => {
  const seen = new Set<string>()
  const result: string[] = []
  for (const p of props.points) {
    if (p.props) {
      for (const k of Object.keys(p.props)) {
        if (!seen.has(k)) {
          seen.add(k)
          result.push(k)
        }
      }
    }
  }
  return result
})

// ── 地图图层配置接口 ──
interface MapLayerConfig {
  id: string
  name: string
  urlTemplate: string
  opacity: number    // 基础透明度
  minZoom: number
  maxZoom: number
  tms?: boolean
}

// ── 默认硬编码配置（GeoWebCache 6层叠加，作为 API 失败时的兜底） ──
const DEFAULT_BASE_URL = '/geowebcache/gwc'

const colors = [
  '#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6',
  '#1abc9c', '#e67e22', '#2980b9', '#c0392b', '#27ae60',
  '#8e44ad', '#d35400',
]

/** Leaflet popup/divIcon 接收 HTML 字符串，所有业务数据必须先转义。 */
function escapeHtml(value: unknown): string {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

/** 仅允许可控 CSS 颜色进入 divIcon 的 style 属性。 */
function safeColor(value: unknown, fallback: string): string {
  const color = String(value ?? '').trim()
  return /^(?:#[0-9a-f]{3,8}|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}(?:\s*,\s*(?:0|1|0?\.\d+))?\s*\))$/i.test(color)
    ? color
    : fallback
}

function safeNumber(value: unknown, fallback: number, min: number, max: number): number {
  const number = Number(value)
  return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback
}

/** 名称 → 颜色（简单 hash，同名同色） */
function getColorByName(name: string): string {
  let hash = 0
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash)
  }
  return colors[Math.abs(hash) % colors.length]
}

// ── 根据 type + baseUrl 客户端构建图层 ──
function buildLayers(type: string, baseUrl: string): MapLayerConfig[] {
  const url = baseUrl.replace(/\/+$/, '')
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
  // 自定义: 地址作为单层瓦片源
  return [{ id: 'custom', name: '自定义图层', urlTemplate: baseUrl, opacity: 0.9, minZoom: 3, maxZoom: 18, tms: true }]
}

// ── 从 API 加载地图服务配置，失败则用默认配置 ──
async function loadMapConfig(): Promise<MapLayerConfig[]> {
  try {
    const res = await api.get('/admin/config/map/active')
    if (res.success && res.data && res.data.type) {
      const layers = buildLayers(res.data.type, res.data.baseUrl || DEFAULT_BASE_URL)
      console.log('[GeoMap] 加载动态地图配置:', res.data.name, layers.length, '层')
      return layers
    }
  } catch (e) {
    console.warn('[GeoMap] 地图配置API加载失败，使用默认配置:', e)
  }
  console.log('[GeoMap] 使用默认 GeoWebCache 配置')
  return buildLayers('geowebcache', DEFAULT_BASE_URL)
}

const fitViewport = computed(() => {
  const pts = props.points
  if (pts.length === 0) return { center: [35.0, 104.0] as L.LatLngTuple, zoom: 4 }
  if (pts.length === 1) return { center: [pts[0].lat, pts[0].lng] as L.LatLngTuple, zoom: 9 }
  const lngs = pts.map(p => p.lng)
  const lats = pts.map(p => p.lat)
  const minLng = Math.min(...lngs)
  const maxLng = Math.max(...lngs)
  const minLat = Math.min(...lats)
  const maxLat = Math.max(...lats)
  const centerLat = (minLat + maxLat) / 2
  const centerLng = (minLng + maxLng) / 2
  const lngSpan = maxLng - minLng || 1
  const latSpan = maxLat - minLat || 1
  const zoomLng = Math.log2(360 / lngSpan) - 1
  const zoomLat = Math.log2(180 / latSpan) - 1
  const zoom = Math.min(zoomLng, zoomLat, 18)
  return { center: [centerLat, centerLng] as L.LatLngTuple, zoom: Math.max(zoom, 4) }
})

function transformCoord(lng: number, lat: number): [number, number] {
  const result = gcoord.transform([lng, lat], gcoord.WGS84, gcoord.GCJ02)
  return [result[1], result[0]]
}

/** 手绘几何（GCJ02，画在 GCJ02 地图上）逆转为 WGS84。gcoord 会原地修改 GeoJSON，先深拷贝。 */
function toWgs84GeoJSON(gj: any): any {
  return gcoord.transform(JSON.parse(JSON.stringify(gj)), gcoord.GCJ02, gcoord.WGS84)
}

function buildTileLayers(layerConfigs: MapLayerConfig[]) {
  tileLayers = layerConfigs.map(cfg => ({
    config: cfg,
    layer: L.tileLayer(cfg.urlTemplate, {
      tms: cfg.tms ?? false,
      maxZoom: cfg.maxZoom,
      minZoom: cfg.minZoom,
      opacity: cfg.opacity,
      attribution: 'GeoWebCache',
    }),
  }))
}

function addTileLayers() {
  tileLayers.forEach(tl => {
    tl.layer.addTo(map!)
    tl.layer.setOpacity(tl.config.opacity)
  })
}

function clearTileLayers() {
  tileLayers.forEach(tl => {
    if (map) map.removeLayer(tl.layer)
  })
  tileLayers = []
}

// ── leaflet-draw 中文本地化 ──
;(L as any).drawLocal = {
  draw: {
    toolbar: {
      actions: { title: '取消绘制', text: '取消' },
      finish: { title: '完成绘制', text: '完成' },
      undo: { title: '删除上一个点', text: '删除最后一点' },
      buttons: {
        polyline: '绘制折线 - 标注路线/连线',
        polygon: '绘制多边形 - 标注区域范围',
        circle: '绘制圆形 - 标注半径范围',
        marker: '放置标记点 - 补充标注点位',
        rectangle: '绘制矩形',
        circlemarker: '绘制圆形标记',
      },
    },
    handlers: {
      circle: {
        tooltip: { start: '点击并拖动绘制圆形' },
        radius: '半径',
      },
      circlemarker: { tooltip: { start: '点击地图放置圆形标记' } },
      marker: { tooltip: { start: '点击地图放置标记点' } },
      polygon: {
        tooltip: {
          start: '点击开始绘制多边形',
          cont: '点击继续绘制多边形',
          end: '点击起点闭合多边形',
        },
      },
      polyline: {
        error: '<strong>错误:</strong> 边不能交叉!',
        tooltip: {
          start: '点击开始绘制折线',
          cont: '点击继续绘制折线',
          end: '点击最后一点完成折线',
        },
      },
      rectangle: { tooltip: { start: '点击并拖动绘制矩形' } },
      simpleshape: { tooltip: { end: '释放鼠标完成绘制' } },
    },
  },
  edit: {
    toolbar: {
      actions: {
        save: { title: '保存更改', text: '保存' },
        cancel: { title: '取消编辑，放弃更改', text: '取消' },
        clearAll: { title: '清除全部', text: '清除全部' },
      },
      buttons: { edit: '编辑 - 修改已绘制要素', editDisabled: '没有可编辑的要素', remove: '删除 - 移除已绘制要素', removeDisabled: '没有可删除的要素' },
    },
    handlers: {
      edit: {
        tooltip: { text: '拖拽手柄或标记点来编辑要素', subtext: '点击"取消"放弃更改' },
      },
      remove: {
        tooltip: { text: '点击要删除的要素' },
      },
    },
  },
}

// ── 初始化绘制控件 ──
function initDrawControl() {
  if (!map) return

  // 用户手绘要素容器（独立图层组）
  drawnItems = new L.FeatureGroup()
  map.addLayer(drawnItems)

  // 绘制工具栏配置
  const drawOptions: L.Control.DrawConstructorOptions = {
    position: 'topright',
    draw: {
      polygon: {
        allowIntersection: false,
        showArea: true,
        shapeOptions: { color: '#e74c3c', weight: 2, fillOpacity: 0.2 },
      },
      rectangle: false,
      circle: {
        shapeOptions: { color: '#2ecc71', weight: 2, fillOpacity: 0.2 },
      },
      polyline: {
        shapeOptions: { color: '#f39c12', weight: 3 },
      },
      marker: {
        icon: L.divIcon({
          className: 'geo-draw-marker',
          html: '<div style="background:#e74c3c;width:12px;height:12px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,0.3)"></div>',
          iconSize: [16, 16],
          iconAnchor: [8, 8],
        }),
      },
      circlemarker: false,
    },
    edit: {
      featureGroup: drawnItems,
      edit: {},
      remove: true,
    },
  }

  drawControl = new L.Control.Draw(drawOptions)
  map.addControl(drawControl)

  // ── 默认名称映射 ──
  const defaultNames: Record<string, string> = {
    polygon: '区域',
    circle: '圆形范围',
    polyline: '路线',
    marker: '标注点',
  }

  /** 生成可编辑名称的 popup HTML */
  function buildPopupHtml(name: string): string {
    return `<div class="geo-name-popup">
      <span class="geo-name-display">
        <strong class="geo-name-label">${escapeHtml(name)}</strong>
        <button class="geo-name-edit-btn" title="修改名称">✎</button>
      </span>
      <span class="geo-name-edit-row" style="display:none">
        <input class="geo-name-input" value="${escapeHtml(name)}" />
        <button class="geo-name-save-btn">确认</button>
        <button class="geo-name-cancel-btn">取消</button>
      </span>
    </div>`
  }

  /** 为图层绑定可编辑名称的 popup */
  function bindEditablePopup(layer: any, initialName: string) {
    layer._customName = initialName
    layer.bindPopup(buildPopupHtml(initialName))

    layer.on('popupopen', function (this: any) {
      const popup = this.getPopup()
      const el = popup.getElement()
      if (!el) return

      const displayRow = el.querySelector('.geo-name-display') as HTMLElement
      const editRow = el.querySelector('.geo-name-edit-row') as HTMLElement
      const editBtn = el.querySelector('.geo-name-edit-btn') as HTMLElement
      const inputEl = el.querySelector('.geo-name-input') as HTMLInputElement
      const saveBtn = el.querySelector('.geo-name-save-btn') as HTMLElement
      const cancelBtn = el.querySelector('.geo-name-cancel-btn') as HTMLElement

      if (!displayRow || !editRow) return

      // 点击编辑按钮 → 切换到输入模式
      editBtn?.addEventListener('click', (ev: Event) => {
        ev.stopPropagation()
        displayRow.style.display = 'none'
        editRow.style.display = 'flex'
        inputEl.value = this._customName || ''
        inputEl.focus()
        inputEl.select()
      })

      // 保存
      const doSave = () => {
        const newName = inputEl.value.trim() || this._customName || initialName
        this._customName = newName
        // 更新 popup 内容（不关闭）
        popup.setContent(buildPopupHtml(newName))
        popup.update()
      }

      saveBtn?.addEventListener('click', doSave)
      inputEl?.addEventListener('keydown', (ev: KeyboardEvent) => {
        if (ev.key === 'Enter') doSave()
      })

      // 取消
      cancelBtn?.addEventListener('click', () => {
        displayRow.style.display = ''
        editRow.style.display = 'none'
      })
    })
  }

  // ── 绘制完成事件 ──
  map.on(L.Draw.Event.CREATED, (e: any) => {
    const layer = e.layer
    drawnItems!.addLayer(layer)
    updateDrawnCount()

    const initialName = defaultNames[e.layerType] || '手绘元素'
    bindEditablePopup(layer, initialName)

    const name = layer._customName || initialName
    emit('draw-end', {
      type: e.layerType === 'rectangle' ? 'polygon' : e.layerType,
      geojson: toWgs84GeoJSON(layer.toGeoJSON()),
      name,
    })
  })

  // ── 编辑完成事件 ──
  map.on(L.Draw.Event.EDITED, () => {
    updateDrawnCount()
  })

  // ── 删除完成事件 ──
  map.on(L.Draw.Event.DELETED, () => {
    updateDrawnCount()
  })
}

/** 更新手绘元素计数 */
function updateDrawnCount() {
  if (drawnItems) {
    drawnCount.value = drawnItems.getLayers().length
  }
}

async function initMap() {
  if (!mapContainer.value) return

  const layerConfigs = await loadMapConfig()

  const initialViewport = resolveViewport()
  map = L.map(mapContainer.value, {
    center: initialViewport.center,
    zoom: initialViewport.zoom,
    zoomControl: true,
    attributionControl: false,
    minZoom: 3,
    maxZoom: 18,
  })

  buildTileLayers(layerConfigs)
  addTileLayers()

  // ── 初始化绘制控件（在瓦片层之上，AI标注层之下） ──
  initDrawControl()

  map.on('zoomend', updateLayerOpacity)
  map.on('moveend', onViewportChange)
  updateLayerOpacity()

  addMarkers()
  addRoutes()
  addAreas()
  addCircles()
}

/** 地图平移/缩放结束后向外发送 viewport（仅 emit，不回写，避免与 props 形成循环）。 */
function onViewportChange() {
  if (!map) return
  const c = map.getCenter()
  const wgs84 = gcoord.transform([c.lng, c.lat], gcoord.GCJ02, gcoord.WGS84)
  emit('viewport-change', {
    center: [Number(wgs84[1].toFixed(6)), Number(wgs84[0].toFixed(6))],
    zoom: map.getZoom(),
  })
}

function resolveViewport(): { center: L.LatLngTuple; zoom: number } {
  if (props.viewport?.center?.length === 2) {
    const [lat, lng] = transformCoord(props.viewport.center[1], props.viewport.center[0])
    return {
      center: [lat, lng],
      zoom: safeNumber(props.viewport.zoom, 4, 3, 18),
    }
  }
  return fitViewport.value
}

function applyViewport() {
  if (!map || !props.viewport) return
  const target = resolveViewport()
  const current = map.getCenter()
  const zoom = map.getZoom()
  if (Math.abs(current.lat - target.center[0]) < 0.00001
    && Math.abs(current.lng - target.center[1]) < 0.00001
    && zoom === target.zoom) return
  map.setView(target.center, target.zoom, { animate: false })
}

/**
 * 根据当前缩放级别动态调整各图层透明度
 * 使用图层 ID 识别不同图层，应用与原硬编码逻辑一致的规则
 */
function updateLayerOpacity() {
  if (!map) return
  const z = map.getZoom()

  tileLayers.forEach(({ layer, config }) => {
    let opacity = config.opacity

    // 按图层 ID 应用与原来一致的缩放透明度规则
    if (z >= 13) {
      if (config.id.includes('provinces')) opacity = 0.1
      else if (config.id.includes('cities')) opacity = 0.4
      else if (config.id.includes('waterareas')) opacity = 0.9
      else if (config.id.includes('waterways')) opacity = 0.8
      else if (config.id.includes('roads')) opacity = 0.9
      else if (config.id.includes('railways')) opacity = 0.7
    } else if (z >= 10) {
      if (config.id.includes('provinces')) opacity = 0.15
      else if (config.id.includes('cities')) opacity = 0.5
      else if (config.id.includes('waterareas')) opacity = 0.8
      else if (config.id.includes('waterways')) opacity = 0.7
      else if (config.id.includes('roads')) opacity = 0.8
      else if (config.id.includes('railways')) opacity = 0.6
    } else if (z >= 7) {
      if (config.id.includes('provinces')) opacity = 0.3
      else if (config.id.includes('cities')) opacity = 0.5
      else if (config.id.includes('waterareas')) opacity = 0.6
      else if (config.id.includes('waterways')) opacity = 0.5
      else if (config.id.includes('roads')) opacity = 0.5
      else if (config.id.includes('railways')) opacity = 0.4
    }
    // z < 7 使用各自的默认 opacity

    layer.setOpacity(opacity)
  })
}

function addMarkers() {
  if (!map) return
  clearMarkers()

  // ── 按坐标分组，相同坐标的点做螺旋偏移避免重叠 ──
  const coordKey = (lat: number, lng: number) => `${lat.toFixed(6)},${lng.toFixed(6)}`
  const groups = new Map<string, { lat: number; lng: number; points: typeof props.points }>()

  props.points.forEach((p) => {
    const [lat, lng] = transformCoord(p.lng, p.lat)
    const key = coordKey(lat, lng)
    if (!groups.has(key)) {
      groups.set(key, { lat, lng, points: [] })
    }
    groups.get(key)!.points.push(p)
  })

  if (spiderLineLayer) { map!.removeLayer(spiderLineLayer) }
  const currentSpiderLineLayer = L.featureGroup().addTo(map!)
  spiderLineLayer = currentSpiderLineLayer

  groups.forEach(({ lat, lng, points: group }) => {
    const n = group.length
    const baseRadius = 0.005 // ~550m 基础偏移半径，确保在地图上肉眼可见

    group.forEach((p, i) => {
      let offsetLat = lat
      let offsetLng = lng

      if (n > 1) {
        // 螺旋偏移：角度均匀分布，半径逐圈递增
        const angle = (2 * Math.PI * i) / n + Math.PI / 6
        const r = baseRadius * (1 + i * 0.4)
        offsetLat = lat + r * Math.cos(angle)
        offsetLng = lng + r * Math.sin(angle)

        // 画一根细线连接偏移位置到真实位置
        L.polyline([[offsetLat, offsetLng], [lat, lng]], {
          color: '#999',
          weight: 1.5,
          opacity: 0.5,
          dashArray: '4 3',
        }).addTo(currentSpiderLineLayer)
      }

      // 同路线使用同一颜色（基于 routeName），不同路线颜色不同
      const color = safeColor((p as any).color, getColorByName(p.routeName || p.name))

      const circle = L.circleMarker([offsetLat, offsetLng], {
        radius: safeNumber((p as any).radius, n > 1 ? 6 : 8, 3, 36),
        fillColor: color,
        color: '#fff',
        weight: 2,
        opacity: 1,
        fillOpacity: safeNumber((p as any).fillOpacity, 0.9, 0.05, 1),
      }).addTo(map!)

      // 构建弹窗内容：基础信息 + 动态属性（中文化）
      let tooltip = `<strong>${escapeHtml(p.name)}</strong>`
      tooltip += `<br/>经度: ${p.lng.toFixed(4)}`
      tooltip += `<br/>纬度: ${p.lat.toFixed(4)}`
      if (n > 1) tooltip += `<br/><em>该位置共 ${n} 个点</em>`
      if (p.props) {
        for (const [key, val] of Object.entries(p.props)) {
          if (val !== null && val !== undefined && val !== '') {
            tooltip += `<br/>${escapeHtml(cnLabel(key))}: ${escapeHtml(val)}`
          }
        }
      }
      tooltip += `<br/><small style="color:#999">${escapeHtml(p.raw)}</small>`

      circle.bindPopup(tooltip)
      circle.on('mouseover', () => { circle.openPopup() })
      circle.on('click', () => { emit('marker-click', { point: p, layerId: (p as any)._layerId }) })
      circleMarkers.push(circle)

      const marker = L.marker([offsetLat, offsetLng], {
        icon: L.divIcon({
          className: 'geo-marker-label',
          html: `<span style="color:${color}">${escapeHtml(p.name)}</span>`,
          iconSize: [80, 20],
          iconAnchor: [-10, -25],
        }),
      }).addTo(map!)
      markers.push(marker)
    })
  })

  if (props.points.length > 0 && !props.viewport) {
    const bounds = props.points.map(p => {
      const [lat, lng] = transformCoord(p.lng, p.lat)
      return [lat, lng] as L.LatLngTuple
    }) as L.LatLngBoundsExpression
    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 })
  }
}

function clearMarkers() {
  markers.forEach(m => { if (map) map.removeLayer(m) })
  markers = []
  circleMarkers.forEach(m => { if (map) map.removeLayer(m) })
  circleMarkers = []
  if (spiderLineLayer && map) {
    map.removeLayer(spiderLineLayer)
    spiderLineLayer = null
  }
}

// ── AI 路线/区域标注渲染 ──
let arrowMarkers: L.Marker[] = []

/** 计算两点间方位角（度），用于箭头旋转 */
function bearing(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const dLng = (lng2 - lng1) * Math.PI / 180
  const y = Math.sin(dLng) * Math.cos(lat2 * Math.PI / 180)
  const x = Math.cos(lat1 * Math.PI / 180) * Math.sin(lat2 * Math.PI / 180)
    - Math.sin(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.cos(dLng)
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

function addRoutes() {
  if (!map || !props.routes) return
  clearRoutes()
  props.routes.forEach((route) => {
    const latlngs = route.points.map(p => {
      const [lat, lng] = transformCoord(p.lng, p.lat)
      return [lat, lng] as L.LatLngTuple
    })
    if (latlngs.length < 2) return
    const routeStyle = route as any
    const color = safeColor(routeStyle.color, getColorByName(route.name))
    const polyline = L.polyline(latlngs, {
      color,
      weight: safeNumber(routeStyle.weight, 4, 1, 16),
      opacity: safeNumber(routeStyle.opacity, 0.85, 0.05, 1),
      dashArray: routeStyle.dashArray === false ? undefined : '10 5',
    }).addTo(map!)
    polyline.bindPopup(`<strong>路线: ${escapeHtml(route.name)}</strong><br/>${route.points.length} 个节点`)
    routeLayers.push(polyline)

    // ── 方向箭头：在连续点对的中点上放置旋转箭头 ──
    for (let i = 0; i < latlngs.length - 1; i++) {
      const [latA, lngA] = latlngs[i]
      const [latB, lngB] = latlngs[i + 1]
      const midLat = (latA + latB) / 2
      const midLng = (lngA + lngB) / 2
      const angle = bearing(latA, lngA, latB, lngB)
      const arrow = L.marker([midLat, midLng], {
        icon: L.divIcon({
          className: 'geo-route-arrow',
          html: `<div style="
            width:0;height:0;
            border-left:6px solid transparent;
            border-right:6px solid transparent;
            border-bottom:12px solid ${color};
            transform:rotate(${angle}deg);
          "></div>`,
          iconSize: [12, 12],
          iconAnchor: [6, 6],
        }),
        interactive: false,
      }).addTo(map!)
      arrowMarkers.push(arrow)
    }
  })
}

function clearRoutes() {
  routeLayers.forEach(l => { if (map) map.removeLayer(l) })
  routeLayers = []
  arrowMarkers.forEach(m => { if (map) map.removeLayer(m) })
  arrowMarkers = []
}

function addAreas() {
  if (!map || !props.areas) return
  clearAreas()
  props.areas.forEach((area) => {
    const latlngs = area.points.map(p => {
      const [lat, lng] = transformCoord(p.lng, p.lat)
      return [lat, lng] as L.LatLngTuple
    })
    if (latlngs.length < 3) return
    const areaStyle = area as any
    const color = safeColor(areaStyle.color, getColorByName(area.name))
    const polygon = L.polygon(latlngs, {
      color,
      weight: safeNumber(areaStyle.weight, 2, 1, 16),
      opacity: safeNumber(areaStyle.opacity, 1, 0.05, 1),
      fillOpacity: safeNumber(areaStyle.fillOpacity, areaStyle._selected ? 0.28 : 0.12, 0.02, 0.9),
      fillColor: color,
    }).addTo(map!)
    polygon.bindPopup(`<strong>区域: ${escapeHtml(area.name)}</strong><br/>${area.points.length} 个顶点`)
    polygon.on('click', () => {
      const a = area as any
      emit('region-select', {
        regionId: a._regionId || area.name,
        name: area.name,
        geometry: toWgs84GeoJSON(polygon.toGeoJSON()),
      })
    })
    areaLayers.push(polygon)
  })
}

function clearAreas() {
  areaLayers.forEach(l => { if (map) map.removeLayer(l) })
  areaLayers = []
}

function addCircles() {
  if (!map || !props.circles) return
  clearCircles()
  props.circles.forEach((c) => {
    const [lat, lng] = transformCoord(c.center.lng, c.center.lat)
    const radiusMeters = c.radiusKm * 1000
    const circleStyle = c as any
    const color = safeColor(circleStyle.color, getColorByName(c.name))
    const circle = L.circle([lat, lng], {
      radius: radiusMeters,
      color,
      weight: safeNumber(circleStyle.weight, 2, 1, 16),
      opacity: safeNumber(circleStyle.opacity, 1, 0.05, 1),
      fillOpacity: safeNumber(circleStyle.fillOpacity, 0.12, 0.02, 0.9),
      fillColor: color,
    }).addTo(map!)
    // ── 圆形弹窗：基础信息 + 附加业务属性（中文化）──
    let popupHtml = `<strong>${escapeHtml(c.name)}</strong>`
    popupHtml += `<br/>覆盖半径: ${c.radiusKm}km`
    popupHtml += `<br/>圆心: ${c.center.lng.toFixed(4)}°, ${c.center.lat.toFixed(4)}°`
    if (c.props) {
      for (const [key, val] of Object.entries(c.props)) {
        if (val !== null && val !== undefined && val !== '') {
          popupHtml += `<br/>${escapeHtml(cnLabel(key))}: ${escapeHtml(val)}`
        }
      }
    }
    circle.bindPopup(popupHtml)
    circleLayers.push(circle)
  })
}

function clearCircles() {
  circleLayers.forEach(l => { if (map) map.removeLayer(l) })
  circleLayers = []
}

watch(() => props.points, () => {
  if (!map) return
  // compact/嵌入模式下容器尺寸常在挂载后才稳定，标注到达时先强制 leaflet 重测容器，
  // 否则 addMarkers 内的 fitBounds 会用旧像素尺寸算 zoom，导致部分点落在视口外。
  nextTick(() => {
    map!.invalidateSize()
    addMarkers()
  })
}, { deep: true })

watch(() => props.routes, () => {
  if (map) addRoutes()
}, { deep: true })

watch(() => props.areas, () => {
  if (map) addAreas()
}, { deep: true })

watch(() => props.circles, () => {
  if (map) addCircles()
}, { deep: true })

watch(() => props.viewport, () => {
  applyViewport()
}, { deep: true })

onMounted(() => {
  initMap().then(() => {
    // 等布局就绪后重测一次，避免 flex/grid 嵌套下初始容器高度为 0 导致视野/瓦片错位
    nextTick(() => map?.invalidateSize())
  })
})

onUnmounted(() => {
  if (map) {
    map.off('zoomend', updateLayerOpacity)
    map.off('moveend', onViewportChange)
    // 清理绘制控件事件
    map.off(L.Draw.Event.CREATED)
    map.off(L.Draw.Event.EDITED)
    map.off(L.Draw.Event.DELETED)
    if (drawControl) {
      map.removeControl(drawControl)
    }
    clearTileLayers()
    map.remove()
    map = null
  }
})
</script>

<style scoped>
.geo-map-container {
  width: 620px;
  max-width: 100%;
  margin-top: 16px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}
.geo-map-container.is-compact {
  width: 100%;
  height: 100%;
  margin-top: 0;
  border: none;
  border-radius: 0;
  display: flex;
  flex-direction: column;
}

.geo-map-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light);
  background: var(--gray-50);
}

.geo-map-header-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.geo-map-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.geo-map-count {
  font-size: 12px;
  background: var(--primary-50, #eff6ff);
  color: var(--primary-600, #3b82f6);
  padding: 2px 10px;
  border-radius: 12px;
}

.geo-map-drawn-count {
  background: #fef3c7;
  color: #d97706;
}

.geo-map-route-count {
  background: #fee2e2;
  color: #dc2626;
}

.geo-map-area-count {
  background: #dbeafe;
  color: #2563eb;
}

.geo-map-content {
  height: 420px;
}
.geo-map-container.is-compact .geo-map-content {
  flex: 1;
  height: auto;
}

.geo-point-table {
  border-top: 1px solid var(--border-light);
}

.geo-table-header {
  padding: 10px 16px;
  background: var(--gray-50);
}

.geo-table-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-secondary);
}

.geo-point-table table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.geo-point-table thead th {
  padding: 8px 16px;
  text-align: left;
  font-weight: 500;
  color: var(--text-muted);
  font-size: 12px;
  border-bottom: 1px solid var(--border-light);
  background: #fafbfc;
}

.geo-point-table tbody td {
  padding: 8px 16px;
  border-bottom: 1px solid #f0f0f0;
  color: var(--text-primary);
}

.geo-point-table tbody tr:hover { background: #f8f9fb; }
.geo-point-table tbody tr:last-child td { border-bottom: none; }

.point-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}

.raw-cell {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-muted);
  font-size: 12px;
}

/* ── leaflet-draw 控件样式覆盖（与项目风格统一） ── */
:deep(.leaflet-draw-toolbar) {
  margin-top: 0 !important;
  border-radius: 8px !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1) !important;
}

:deep(.leaflet-draw-toolbar a) {
  background: #fff !important;
  border-bottom: 1px solid #eee !important;
  width: 32px !important;
  height: 32px !important;
  line-height: 32px !important;
}

:deep(.leaflet-draw-toolbar a:hover) {
  background: #f5f5f5 !important;
}

/* ── 所有绘制/编辑按钮统一用内联 SVG（解决 leaflet-draw 精灵图不加载的问题） ── */
:deep(.leaflet-draw-toolbar a) {
  background-repeat: no-repeat !important;
  background-size: 16px 16px !important;
  background-position: center !important;
}

:deep(.leaflet-draw-toolbar .leaflet-draw-draw-polygon) {
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="%23555" stroke-width="2"><polygon points="12,2 22,8.5 22,15.5 12,22 2,15.5 2,8.5"/></svg>') !important;
}

:deep(.leaflet-draw-toolbar .leaflet-draw-draw-circle) {
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="%23555" stroke-width="2"><circle cx="12" cy="12" r="9"/></svg>') !important;
}

:deep(.leaflet-draw-toolbar .leaflet-draw-draw-polyline) {
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="%23555" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="2,20 7,8 13,14 18,4 22,10"/></svg>') !important;
}

:deep(.leaflet-draw-toolbar .leaflet-draw-draw-marker) {
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="%23555" stroke="%23fff" stroke-width="1"><path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5a2.5 2.5 0 010-5 2.5 2.5 0 010 5z"/></svg>') !important;
}

:deep(.leaflet-draw-toolbar .leaflet-draw-edit-edit) {
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="%23555" stroke-width="2"><path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>') !important;
}

:deep(.leaflet-draw-toolbar .leaflet-draw-edit-remove) {
  background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="%23555" stroke-width="2"><polyline points="3,6 5,6 21,6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>') !important;
}

:deep(.leaflet-draw-actions) {
  border-radius: 6px !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1) !important;
}

:deep(.leaflet-draw-actions a) {
  background: #fff !important;
  font-size: 12px !important;
  padding: 4px 8px !important;
}

:deep(.leaflet-draw-actions a:hover) {
  background: #f5f5f5 !important;
}

:deep(.leaflet-control-zoom) {
  border: none;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}
:deep(.leaflet-control-zoom a) {
  background: #fff;
  border-bottom: 1px solid #eee;
  color: #333;
  width: 32px;
  height: 32px;
  line-height: 32px;
  font-size: 18px;
}
:deep(.leaflet-control-zoom a:hover) { background: #f5f5f5; }
:deep(.leaflet-control-zoom a:first-child) { border-radius: 8px 8px 0 0; }
:deep(.leaflet-control-zoom a:last-child) { border-radius: 0 0 8px 8px; border-bottom: none; }

:deep(.leaflet-popup-content) {
  padding: 12px;
  font-size: 13px;
  min-width: 180px;
}
:deep(.leaflet-popup-content strong) { font-size: 14px; color: #333; }
:deep(.leaflet-popup-tip) { background: #fff; border: 1px solid #e0e0e0; }
:deep(.leaflet-popup-wrapper) {
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
}

:deep(.geo-marker-label) {
  font-size: 12px;
  font-weight: 500;
  text-shadow: 0 1px 2px rgba(255, 255, 255, 0.9);
  white-space: nowrap;
}

/* ── 绘制/编辑时顶点手柄改为小圆点 ── */
:deep(.leaflet-div-icon.leaflet-editing-icon) {
  border-radius: 50% !important;
  border: 2px solid #fff !important;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.3) !important;
  background: #3b82f6 !important;
  margin-left: -5px !important;
  margin-top: -5px !important;
  width: 10px !important;
  height: 10px !important;
}

:deep(.leaflet-div-icon.leaflet-editing-icon.leaflet-touch-icon) {
  margin-left: -8px !important;
  margin-top: -8px !important;
  width: 16px !important;
  height: 16px !important;
}

/* 中间添加点标记（更小更淡） */
:deep(.leaflet-div-icon.leaflet-editing-icon.leaflet-middle-icon),
:deep(.leaflet-marker-icon.leaflet-div-icon.leaflet-editing-icon[style*="opacity"]) {
  background: #93c5fd !important;
  width: 7px !important;
  height: 7px !important;
  margin-left: -3.5px !important;
  margin-top: -3.5px !important;
}
</style>

<style>
/* ── 可编辑名称 popup 样式（非 scoped，因 Leaflet popup 渲染在组件 DOM 外） ── */
.geo-name-popup {
  min-width: 140px;
}

.geo-name-display {
  display: flex;
  align-items: center;
  gap: 8px;
}

.geo-name-label {
  font-size: 14px;
  color: #333;
  cursor: default;
}

.geo-name-edit-btn {
  background: none;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  padding: 1px 6px;
  color: #888;
  line-height: 1.4;
  flex-shrink: 0;
}

.geo-name-edit-btn:hover {
  color: #3b82f6;
  border-color: #3b82f6;
}

.geo-name-edit-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.geo-name-input {
  width: 100px;
  padding: 3px 6px;
  border: 1px solid #3b82f6;
  border-radius: 4px;
  font-size: 13px;
  outline: none;
  font-family: inherit;
}

.geo-name-save-btn,
.geo-name-cancel-btn {
  padding: 2px 8px;
  border-radius: 4px;
  border: none;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.5;
  flex-shrink: 0;
}

.geo-name-save-btn {
  background: #3b82f6;
  color: #fff;
}

.geo-name-save-btn:hover {
  background: #2563eb;
}

.geo-name-cancel-btn {
  background: #f0f0f0;
  color: #666;
}

.geo-name-cancel-btn:hover {
  background: #e0e0e0;
}
</style>
