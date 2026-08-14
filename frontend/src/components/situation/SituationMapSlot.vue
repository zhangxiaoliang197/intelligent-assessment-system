<template>
  <div class="situation-map-slot">
    <GeoMap
      compact
      :points="mergedPoints"
      :routes="mergedRoutes"
      :areas="mergedAreas"
      :circles="mergedCircles"
      :viewport="viewport"
      @marker-click="(p: any) => emit('marker-click', p)"
      @region-select="(p: any) => emit('region-select', p)"
      @draw-end="(p: any) => emit('draw-end', p)"
      @viewport-change="(p: any) => emit('viewport-change', p)"
    />
    <div v-if="explanation" class="map-explain">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ explanation }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import GeoMap from '@/components/GeoMap.vue'
import type { GeoPoint } from '@/utils/geoParser'
import type { GeoRoute, GeoArea } from '@/utils/geoAnnotation'
import type { CircleArea } from '@/utils/mapAnnotationParser'
import type { MapLayer, Viewport } from '@/stores/situation'

const props = defineProps<{
  dataset: any
  layers: MapLayer[]
  viewport: Viewport
  selectedRegion: string | null
  timeRange: [number, number] | null
  filters: Record<string, any>
  explanation?: string
}>()

const emit = defineEmits<{
  (e: 'region-select', payload: { regionId: string; name: string; geometry?: any }): void
  (e: 'marker-click', payload: { point: any; layerId?: string }): void
  (e: 'layer-toggle', payload: { layerId: string; visible: boolean }): void
  (e: 'draw-end', payload: { type: string; geojson: any; name?: string }): void
  (e: 'viewport-change', vp: Viewport): void
}>()

function featureValue(feature: any, key: string): unknown {
  return feature?.[key] ?? feature?.props?.[key] ?? feature?.properties?.[key]
}

function featurePassesContext(feature: any): boolean {
  if (!feature) return false

  // 只在要素显式携带相应维度时做过滤，避免旧数据因没有上下文字段而被全部清空。
  if (props.selectedRegion) {
    const region = featureValue(feature, 'regionId')
      ?? featureValue(feature, 'region')
      ?? featureValue(feature, 'areaId')
    if (region != null && String(region) !== props.selectedRegion) return false
  }

  if (props.timeRange) {
    const rawTime = featureValue(feature, 'timestamp')
      ?? featureValue(feature, 'time')
      ?? featureValue(feature, 'recordTime')
      ?? featureValue(feature, 'record_time')
    if (rawTime != null) {
      const parsed = typeof rawTime === 'number' ? rawTime : Date.parse(String(rawTime))
      const milliseconds = parsed < 10_000_000_000 ? parsed * 1000 : parsed
      if (Number.isFinite(milliseconds)
        && (milliseconds < props.timeRange[0] || milliseconds > props.timeRange[1])) return false
    }
  }

  for (const [key, expected] of Object.entries(props.filters || {})) {
    if (expected == null || expected === '' || (Array.isArray(expected) && expected.length === 0)) continue
    const actual = featureValue(feature, key)
    if (actual == null) continue
    if (Array.isArray(expected)) {
      if (!expected.map(String).includes(String(actual))) return false
    } else if (String(actual) !== String(expected)) {
      return false
    }
  }
  return true
}

function layerType(layer: MapLayer): string {
  return String(layer.layerConfig?.type || 'points').toLowerCase()
}

function valueScale(value: unknown, minimum = 7, maximum = 26): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return minimum
  return Math.min(maximum, Math.max(minimum, minimum + Math.sqrt(Math.max(0, number)) * 1.7))
}

const mergedPoints = computed<GeoPoint[]>(() => {
  const all: GeoPoint[] = []
  for (const layer of props.layers) {
    if (layer.layerConfig?.visible === false) continue
    const type = layerType(layer)
    const sourcePoints = [
      ...(layer.points || []),
      ...((layer as any).clusters || []),
    ]
    if (!sourcePoints.length) continue
    for (const p of sourcePoints) {
      if (!featurePassesContext(p)) continue
      const center = p.center || p.coordinate || p
      const isIntensityLayer = type === 'clusters'
      all.push({
        name: p.name || '',
        lng: center.lng ?? center.longitude ?? 0,
        lat: center.lat ?? center.latitude ?? 0,
        raw: p.raw || `${center.lng ?? center.longitude}, ${center.lat ?? center.latitude}`,
        props: p.props || p.properties || {},
        routeName: p.routeName,
        color: p.color,
        radius: isIntensityLayer ? valueScale(p.value ?? p.count ?? p.weight) : layer.layerConfig?.radius,
        fillOpacity: isIntensityLayer ? layer.layerConfig?.fillOpacity ?? 0.55 : layer.layerConfig?.fillOpacity,
        _layerId: layer.layerId,
        _datasetRef: p.datasetRef || props.dataset?.datasetId || '',
        _featureId: p.featureId || '',
      } as any)
    }
  }
  return all
})

const mergedRoutes = computed<GeoRoute[]>(() => {
  const all: GeoRoute[] = []
  for (const layer of props.layers) {
    if (layer.layerConfig?.visible === false) continue
    const sourceRoutes = [
      ...(layer.routes || []),
      ...((layer as any).flows || []),
      ...((layer as any).flow || []),
    ]
    if (!sourceRoutes.length) continue
    for (const r of sourceRoutes) {
      if (!featurePassesContext(r)) continue
      const routePoints = r.points || (r.from && r.to ? [r.from, r.to] : [])
      const pts: GeoPoint[] = routePoints.map((p: any) => ({
        name: '',
        lng: p.lng ?? 0,
        lat: p.lat ?? 0,
        raw: `${p.lng}, ${p.lat}`,
      } as any))
      all.push({
        name: r.name || '', points: pts, color: r.color,
        weight: layer.layerConfig?.weight,
        opacity: layer.layerConfig?.opacity,
        dashArray: layerType(layer) === 'flow' ? false : layer.layerConfig?.dashArray,
        _layerId: layer.layerId,
        _datasetRef: r.datasetRef || props.dataset?.datasetId || '',
      } as any)
    }
  }
  return all
})

const mergedAreas = computed<GeoArea[]>(() => {
  const all: GeoArea[] = []
  for (const layer of props.layers) {
    if (layer.layerConfig?.visible === false) continue
    const sourceAreas = [
      ...(layer.areas || []),
      ...((layer as any).coverage?.areas || []),
    ]
    if (!sourceAreas.length) continue
    for (const a of sourceAreas) {
      if (!featurePassesContext(a)) continue
      const pts: GeoPoint[] = (a.points || []).map((p: any) => ({
        name: '',
        lng: p.lng ?? 0,
        lat: p.lat ?? 0,
        raw: `${p.lng}, ${p.lat}`,
      } as any))
      all.push({
        name: a.name || '', points: pts, color: a.color,
        weight: layer.layerConfig?.weight,
        opacity: layer.layerConfig?.opacity,
        fillOpacity: layer.layerConfig?.fillOpacity,
        _layerId: layer.layerId,
        _regionId: a.featureId || a.regionId || a.name || '',
        _selected: Boolean(props.selectedRegion && props.selectedRegion === (a.featureId || a.regionId || a.name)),
        _datasetRef: a.datasetRef || props.dataset?.datasetId || '',
      } as any)
    }
  }
  return all
})

const mergedCircles = computed<CircleArea[]>(() => {
  const all: CircleArea[] = []
  for (const layer of props.layers) {
    if (layer.layerConfig?.visible === false) continue
    const sourceCircles = [
      ...(layer.circles || []),
      ...((layer as any).coverage?.circles || []),
      ...((layer as any).coverages || []),
    ]
    if (!sourceCircles.length) continue
    for (const c of sourceCircles) {
      if (!featurePassesContext(c)) continue
      all.push({
        name: c.name || '',
        center: { lng: c.center?.lng ?? 0, lat: c.center?.lat ?? 0 },
        radiusKm: c.radiusKm || 50,
        props: c.props || c.properties || {},
        color: c.color,
        weight: layer.layerConfig?.weight,
        opacity: layer.layerConfig?.opacity,
        fillOpacity: layer.layerConfig?.fillOpacity,
        _layerId: layer.layerId,
        _datasetRef: c.datasetRef || props.dataset?.datasetId || '',
      } as any)
    }
  }
  return all
})
</script>

<style scoped>
.situation-map-slot {
  position: relative;
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.map-explain {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
  background: #f5f7fa;
  padding: 6px 8px;
  border-radius: 4px;
  flex-shrink: 0;
}
</style>
