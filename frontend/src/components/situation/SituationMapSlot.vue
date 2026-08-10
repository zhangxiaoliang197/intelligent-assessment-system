<template>
  <div class="situation-map-slot">
    <div class="map-header">
      <span class="map-title">{{ title }}</span>
      <div class="map-tools">
        <slot name="map-tools" />
      </div>
    </div>
    <div class="map-body">
      <!--
        地图插槽（docs/situation-map/06 §2）：
        同事组件挂入点。框架通过作用域插槽注入 dataset/layers/viewport/联动状态 + 事件回调。
        未挂入同事组件时显示占位。
      -->
      <slot
        name="map"
        :dataset="dataset"
        :layers="layers"
        :viewport="viewport"
        :selected-region="selectedRegion"
        :time-range="timeRange"
        :filters="filters"
        :on-region-select="emitRegionSelect"
        :on-marker-click="emitMarkerClick"
        :on-layer-toggle="emitLayerToggle"
        :on-draw-end="emitDrawEnd"
        :on-viewport-change="emitViewportChange"
      >
        <div class="map-placeholder">
          <el-icon :size="36"><MapLocation /></el-icon>
          <p>地图组件待接入</p>
          <p class="map-placeholder-hint">
            同事按 docs/situation-map/06 契约把地图生成逻辑封装为 Vue 组件挂入 #map 插槽
          </p>
        </div>
      </slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { MapLocation } from '@element-plus/icons-vue'
import type { DatasetSummary, MapLayer, Viewport } from '@/stores/situation'

defineProps<{
  title?: string
  dataset: DatasetSummary | null
  layers: MapLayer[]
  viewport: Viewport
  selectedRegion: string | null
  timeRange: [number, number] | null
  filters: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'region-select', payload: { regionId: string; name: string; geometry?: any }): void
  (e: 'marker-click', payload: { point: any; layerId?: string }): void
  (e: 'layer-toggle', payload: { layerId: string; visible: boolean }): void
  (e: 'draw-end', payload: { type: string; geojson: any; name?: string }): void
  (e: 'viewport-change', vp: Viewport): void
}>()

const emitRegionSelect = (p: any) => emit('region-select', p)
const emitMarkerClick = (p: any) => emit('marker-click', p)
const emitLayerToggle = (p: any) => emit('layer-toggle', p)
const emitDrawEnd = (p: any) => emit('draw-end', p)
const emitViewportChange = (vp: Viewport) => emit('viewport-change', vp)
</script>

<style scoped>
.situation-map-slot {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
}
.map-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #ebeef5;
  background: #fafafa;
}
.map-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.map-body {
  flex: 1;
  position: relative;
  min-height: 320px;
}
.map-placeholder {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #909399;
  text-align: center;
  padding: 16px;
}
.map-placeholder-hint {
  font-size: 12px;
  color: #c0c4cc;
  max-width: 320px;
  line-height: 1.5;
}
</style>
