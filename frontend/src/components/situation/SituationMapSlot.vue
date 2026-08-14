<template>
  <div class="situation-map-slot">
    <GeoMap
      compact
      :points="mergedPoints"
      :routes="mergedRoutes"
      :areas="mergedAreas"
      :circles="mergedCircles"
      :heat-points="heatPoints"
      @marker-click="(p: any) => emit('marker-click', { point: p })"
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

/** 合并所有图层 → GeoMap props */

/** 热力图图层点（type=heatmap）→ GeoMap heatPoints（带热度权重） */
const heatPoints = computed(() => {
  const all: { lng: number; lat: number; weight?: number }[] = []
  for (const layer of props.layers) {
    if (layer.layerConfig?.type !== 'heatmap') continue
    if (!layer.points) continue
    for (const p of layer.points) {
      all.push({
        lng: p.lng ?? 0,
        lat: p.lat ?? 0,
        weight: typeof p.weight === 'number' ? p.weight : 1,
      })
    }
  }
  return all
})

const mergedPoints = computed<GeoPoint[]>(() => {
  const all: GeoPoint[] = []
  for (const layer of props.layers) {
    if (!layer.points) continue
    // 热力图图层不渲染为普通标点，交由 heatPoints 渲染
    if (layer.layerConfig?.type === 'heatmap') continue
    const color = layer.layerConfig?.color || '#e74c3c'
    for (const p of layer.points) {
      all.push({
        name: p.name || '',
        lng: p.lng ?? 0,
        lat: p.lat ?? 0,
        raw: p.raw || `${p.lng}, ${p.lat}`,
        color,
      } as any)
    }
  }
  return all
})

const mergedRoutes = computed<GeoRoute[]>(() => {
  const all: GeoRoute[] = []
  for (const layer of props.layers) {
    if (!layer.routes || layer.routes.length === 0) continue
    const color = layer.layerConfig?.color || '#e74c3c'
    for (const r of layer.routes) {
      const pts: GeoPoint[] = (r.points || []).map((p: any) => ({
        name: '',
        lng: p.lng ?? 0,
        lat: p.lat ?? 0,
        raw: `${p.lng}, ${p.lat}`,
        color,
      } as any))
      all.push({ name: r.name || '', points: pts, color })
    }
  }
  return all
})

const mergedAreas = computed<GeoArea[]>(() => {
  const all: GeoArea[] = []
  for (const layer of props.layers) {
    if (!layer.areas || layer.areas.length === 0) continue
    const color = layer.layerConfig?.color || '#3498db'
    for (const a of layer.areas) {
      const pts: GeoPoint[] = (a.points || []).map((p: any) => ({
        name: '',
        lng: p.lng ?? 0,
        lat: p.lat ?? 0,
        raw: `${p.lng}, ${p.lat}`,
        color,
      } as any))
      all.push({ name: a.name || '', points: pts, color })
    }
  }
  return all
})

const mergedCircles = computed<CircleArea[]>(() => {
  const all: CircleArea[] = []
  for (const layer of props.layers) {
    if (!layer.circles || layer.circles.length === 0) continue
    for (const c of layer.circles) {
      all.push({
        name: c.name || '',
        center: { lng: c.center?.lng ?? 0, lat: c.center?.lat ?? 0 },
        radiusKm: c.radiusKm || 50,
      })
    }
  }
  return all
})
</script>

<style scoped>
.situation-map-slot {
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
