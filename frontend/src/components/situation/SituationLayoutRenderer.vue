<template>
  <div class="layout-renderer" :style="gridStyle">
    <div
      v-for="(block, bi) in blocks"
      :key="bi"
      class="layout-block"
      :style="blockStyle(block)"
    >
      <template v-for="(slot, si) in block.slots" :key="si">
        <!-- 图表块：复用单卡组件，数据仍来自 store（dataset+fieldMapping 重建） -->
        <div v-if="slot.kind === 'chart' && chartById(slot.ref)" class="slot-fill">
          <SituationChartCard
            :spec="chartById(slot.ref)!"
            :index="chartIndex(slot.ref)"
            :body-height="chartBodyHeight(block)"
            :show-explanation="!narrativeChartExists(slot.ref)"
          />
        </div>

        <!-- 地图块：复用地图槽组件，交互 props/events 全量透传 -->
        <div
          v-else-if="slot.kind === 'map' && mapLayers.length"
          class="slot-fill map-slot"
          :style="mapSlotStyle(block)"
        >
          <SituationMapSlot
            :dataset="activeDataset"
            :layers="mapLayers"
            :viewport="viewport"
            :selected-region="selectedRegion"
            :time-range="timeRange"
            :filters="filters"
            :show-explanation="false"
            @region-select="(p: any) => emit('region-select', p)"
            @marker-click="(p: any) => emit('marker-click', p)"
            @layer-toggle="(p: any) => emit('layer-toggle', p)"
            @draw-end="(p: any) => emit('draw-end', p)"
            @viewport-change="(p: any) => emit('viewport-change', p)"
          />
        </div>

        <!-- 态势介绍：markdown 渲染（与 SituationNarrative 同管线） -->
        <div v-else-if="slot.kind === 'narrative_intro' && narrative.intro" class="slot-text">
          <h4 class="text-title">态势介绍</h4>
          <div class="text-md" v-html="renderedIntro"></div>
        </div>

        <!-- 图表说明（跟图走）：取 narrative.explanations 中该图说明 -->
        <div v-else-if="slot.kind === 'narrative_chart' && explanationFor(slot.ref)" class="slot-explain">
          <div class="explain-title">
            <el-icon><InfoFilled /></el-icon>
            <span>{{ chartById(slot.ref)?.title || slot.ref }}</span>
          </div>
          <div class="explain-text" v-html="renderExplanation(explanationFor(slot.ref))"></div>
        </div>

        <!-- 地图说明 -->
        <div v-else-if="slot.kind === 'map_explanation' && mapExplanation" class="slot-explain">
          <div class="explain-title">
            <el-icon><InfoFilled /></el-icon>
            <span>地图说明</span>
          </div>
          <div class="explain-text" v-html="renderExplanation(mapExplanation)"></div>
        </div>

        <!-- KPI 指标块：数值由前端从 dataset 全量行计算，LLM 只指定列名与聚合 -->
        <SituationMetricsCard
          v-else-if="slot.kind === 'metrics' && datasetById(slot.ref) && slot.metrics?.length"
          :dataset="datasetById(slot.ref)!"
          :metrics="slot.metrics"
        />
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import SituationChartCard from './SituationChartCard.vue'
import SituationMapSlot from './SituationMapSlot.vue'
import SituationMetricsCard from './SituationMetricsCard.vue'
import type {
  ChartSpec, DatasetSummary, LayoutBlock, LayoutTree, MapLayer, Narrative, Viewport,
} from '@/stores/situation'

const props = defineProps<{
  layout: LayoutTree
  charts: ChartSpec[]
  mapLayers: MapLayer[]
  narrative: Narrative
  datasets: DatasetSummary[]
  activeDataset?: any
  viewport: Viewport
  selectedRegion: string | null
  timeRange: [number, number] | null
  filters: Record<string, any>
  mapExplanation?: string
}>()

const emit = defineEmits<{
  (e: 'region-select', payload: any): void
  (e: 'marker-click', payload: any): void
  (e: 'layer-toggle', payload: any): void
  (e: 'draw-end', payload: any): void
  (e: 'viewport-change', vp: Viewport): void
}>()

const blocks = computed<LayoutBlock[]>(() => props.layout.root?.children || [])

// 12 列栅格（span 由 LLM 决定，代表版面比例而非数据）
const gridStyle = computed(() => ({
  display: 'grid',
  gridTemplateColumns: 'repeat(12, minmax(0, 1fr))',
  gap: `${props.layout.root?.props?.gap || 12}px`,
  alignItems: 'stretch',
}))

function blockStyle(block: LayoutBlock) {
  const span = Math.min(12, Math.max(1, Number(block.span) || 12))
  return {
    gridColumn: `span ${span}`,
    minHeight: block.minHeight ? `${block.minHeight}px` : undefined,
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '12px',
  }
}

function mapSlotStyle(block: LayoutBlock) {
  return { flex: '1 1 auto', minHeight: block.minHeight ? `${block.minHeight}px` : '460px' }
}

// 图表主体高度：块有 minHeight 时留出说明空间，否则用块高的 70%
function chartBodyHeight(block: LayoutBlock): number {
  if (!block.minHeight) return 320
  return Math.max(200, Math.round(block.minHeight * 0.7))
}

// ── 引用查找（布局树只存 ref，数据从 store 产物取） ──
const chartMap = computed(() => new Map(props.charts.map((c) => [c.chartId, c])))
const datasetMap = computed(() => new Map(props.datasets.map((d) => [d.datasetId, d])))

function chartById(ref?: string): ChartSpec | undefined {
  return ref ? chartMap.value.get(ref) : undefined
}

function chartIndex(ref?: string): number {
  const idx = ref ? props.charts.findIndex((c) => c.chartId === ref) : -1
  return idx >= 0 ? idx : 0
}

function datasetById(ref?: string): DatasetSummary | undefined {
  return ref ? datasetMap.value.get(ref) : undefined
}

// 该图的说明是否被单独排块（是则隐藏卡内说明，避免重复）
function narrativeChartExists(ref?: string): boolean {
  if (!ref) return false
  return blocks.value.some((b) => b.slots.some((s) => s.kind === 'narrative_chart' && s.ref === ref))
}

function explanationFor(ref?: string): string {
  if (!ref) return ''
  return props.narrative.explanations?.find((e) => e.chartId === ref)?.text || ''
}

// ── markdown 渲染（与 SituationNarrative 同管线：marked + DOMPurify） ──
function renderMarkdown(text: string): string {
  if (!text) return ''
  return DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
}

const renderedIntro = computed(() => renderMarkdown(props.narrative.intro))
function renderExplanation(text: string): string {
  return renderMarkdown(text)
}
</script>

<style scoped>
.layout-renderer {
  width: 100%;
}
.layout-block {
  min-width: 0;
}
.slot-fill {
  flex: 1 1 auto;
  min-height: 0;
}
.slot-fill :deep(.chart-card) {
  height: 100%;
}
.map-slot :deep(.situation-map-slot) {
  height: 100%;
}
.slot-text {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 16px;
}
.text-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin: 0 0 8px;
}
.text-md {
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
}
.text-md :deep(p) {
  margin: 6px 0;
}
.slot-explain {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px 14px;
}
.explain-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #409eff;
  margin-bottom: 6px;
}
.explain-text {
  font-size: 13px;
  line-height: 1.7;
  color: #606266;
}
.explain-text :deep(p) {
  margin: 4px 0;
}
</style>
