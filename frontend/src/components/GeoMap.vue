<template>
  <div class="geo-map-container">
    <div class="geo-map-header">
      <span class="geo-map-title">坐标可视化</span>
      <span class="geo-map-count">{{ points.length }} 个坐标点</span>
    </div>
    <div ref="mapContainer" class="geo-map-content"></div>
    <div v-if="points.length > 0" class="geo-point-table">
      <div class="geo-table-header">
        <span class="geo-table-title">提取坐标点</span>
      </div>
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>经度</th>
            <th>纬度</th>
            <th>原文</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in points" :key="i">
            <td>
              <span class="point-dot" :style="{ background: colors[i % colors.length] }"></span>
              {{ p.name }}
            </td>
            <td>{{ p.lng.toFixed(4) }}</td>
            <td>{{ p.lat.toFixed(4) }}</td>
            <td class="raw-cell" :title="p.raw">{{ p.raw }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, onUnmounted, computed } from 'vue'
import L from 'leaflet'
import gcoord from 'gcoord'
import type { GeoPoint } from '@/utils/geoParser'

const props = defineProps<{
  points: GeoPoint[]
  title?: string
}>()

const mapContainer = ref<HTMLElement | null>(null)
let map: L.Map | null = null
let markers: L.Marker[] = []
let circleMarkers: L.CircleMarker[] = []

const colors = ['#e74c3c', '#3498db', '#2ecc71', '#f39c12', '#9b59b6', '#1abc9c', '#e67e22', '#2980b9']

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
  const result = gcoord.transform(
    [lng, lat],
    gcoord.WGS84,
    gcoord.GCJ02
  )
  return [result[1], result[0]]
}

function initMap() {
  if (!mapContainer.value) return

  map = L.map(mapContainer.value, {
    center: fitViewport.value.center,
    zoom: fitViewport.value.zoom,
    zoomControl: true,
    attributionControl: false,
  })

  const wmtsUrl = '/geowebcache/gwc/service/wmts?' +
    'layer=ne:world' +
    '&style=' +
    '&tilematrixset=EPSG:900913' +
    '&Service=WMTS' +
    '&Request=GetTile' +
    '&Version=1.0.0' +
    '&Format=image/png' +
    '&TileMatrix=EPSG:900913:{z}' +
    '&TileCol={x}' +
    '&TileRow={y}'

  L.tileLayer(wmtsUrl, {
    maxZoom: 18,
    minZoom: 1,
    attribution: 'GeoWebCache',
    crossOrigin: '',
  }).addTo(map)

  addMarkers()
}

function addMarkers() {
  if (!map) return

  clearMarkers()

  props.points.forEach((p, i) => {
    const [lat, lng] = transformCoord(p.lng, p.lat)
    const color = colors[i % colors.length]

    const circle = L.circleMarker([lat, lng], {
      radius: 8,
      fillColor: color,
      color: '#fff',
      weight: 2,
      opacity: 1,
      fillOpacity: 0.9,
    }).addTo(map!)

    circle.bindPopup(`<strong>${p.name}</strong><br/>经度: ${p.lng.toFixed(4)}<br/>纬度: ${p.lat.toFixed(4)}<br/>原文: ${p.raw}`)

    circle.on('mouseover', () => {
      circle.openPopup()
    })

    circleMarkers.push(circle)

    const marker = L.marker([lat, lng], {
      icon: L.divIcon({
        className: 'geo-marker-label',
        html: `<span style="color:${color}">${p.name}</span>`,
        iconSize: [80, 20],
        iconAnchor: [-10, -25],
      }),
    }).addTo(map!)

    markers.push(marker)
  })

  if (props.points.length > 0) {
    const bounds = props.points.map(p => {
      const [lat, lng] = transformCoord(p.lng, p.lat)
      return [lat, lng] as L.LatLngTuple
    }) as L.LatLngBoundsExpression
    map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 })
  }
}

function clearMarkers() {
  markers.forEach(m => {
    if (map) map.removeLayer(m)
  })
  markers = []
  circleMarkers.forEach(m => {
    if (map) map.removeLayer(m)
  })
  circleMarkers = []
}

watch(() => props.points, () => {
  if (map) {
    addMarkers()
  }
}, { deep: true })

onMounted(() => {
  initMap()
})

onUnmounted(() => {
  if (map) {
    map.remove()
    map = null
  }
})
</script>

<style scoped>
.geo-map-container {
  margin-top: 16px;
  border: 1px solid var(--border-light);
  border-radius: 12px;
  overflow: hidden;
  background: #fff;
}

.geo-map-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border-light);
  background: var(--gray-50);
}

.geo-map-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.geo-map-count {
  font-size: 12px;
  color: var(--text-muted);
  background: var(--primary-50, #eff6ff);
  color: var(--primary-600, #3b82f6);
  padding: 2px 10px;
  border-radius: 12px;
}

.geo-map-content {
  height: 420px;
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

.geo-point-table tbody tr:hover {
  background: #f8f9fb;
}

.geo-point-table tbody tr:last-child td {
  border-bottom: none;
}

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

:deep(.leaflet-control-zoom a:hover) {
  background: #f5f5f5;
}

:deep(.leaflet-control-zoom a:first-child) {
  border-radius: 8px 8px 0 0;
}

:deep(.leaflet-control-zoom a:last-child) {
  border-radius: 0 0 8px 8px;
  border-bottom: none;
}

:deep(.leaflet-popup-content) {
  padding: 12px;
  font-size: 13px;
  min-width: 180px;
}

:deep(.leaflet-popup-content strong) {
  font-size: 14px;
  color: #333;
}

:deep(.leaflet-popup-tip) {
  background: #fff;
  border: 1px solid #e0e0e0;
}

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
</style>
