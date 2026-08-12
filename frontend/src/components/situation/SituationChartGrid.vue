<template>
  <div class="chart-grid">
    <div v-if="!charts.length && !loading" class="chart-empty">
      <el-empty description="尚未生成图表，请在上方提问生成态势图" />
    </div>
    <div
      v-else
      class="chart-grid-inner"
      :class="[cols ? 'cols-fixed' : '', cols ? `cols-${cols}` : '', `count-${charts.length}`]"
      :style="gridStyle"
    >
      <SituationChartCard
        v-for="c in charts"
        :key="c.chartId"
        :ref="(el) => setCardRef(el, c.chartId)"
        :spec="c"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import SituationChartCard from './SituationChartCard.vue'
import type { ChartSpec } from '@/stores/situation'

const props = defineProps<{
  charts: ChartSpec[]
  loading?: boolean
  /** 指定列数；不传则自适应 minmax(300px,1fr) */
  cols?: number
}>()

// 指定列数时用等宽 1fr（minmax(0,1fr) 防止内容溢出撑宽）
const gridStyle = computed(() =>
  props.cols ? { gridTemplateColumns: `repeat(${props.cols}, minmax(0, 1fr))` } : {}
)

// chartId → 组件实例（供说明点击滚动+高亮）
const cardRefs = ref<Record<string, InstanceType<typeof SituationChartCard>>>({})

function setCardRef(el: any, chartId: string) {
  if (el) cardRefs.value[chartId] = el
}

function scrollToChart(chartId: string) {
  const el = document.getElementById(`chart-${chartId}`)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  cardRefs.value[chartId]?.flashHighlight()
}

defineExpose({ scrollToChart })
</script>

<style scoped>
.chart-grid {
  width: 100%;
}
.chart-grid-inner {
  display: grid;
  /* 默认（未指定 cols）：自适应排列，minmax(300px,1fr) 让图表在 chart-side 内可多列 */
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
  /* 每行至少 360px，保证图表卡片有足够可视高度 */
  grid-auto-rows: minmax(360px, auto);
}
/* 指定列数时，每行等高（1fr）让同行图表对齐 */
.chart-grid-inner.cols-fixed {
  grid-auto-rows: minmax(360px, 1fr);
}

/* 3 个图表 + 2 列：第 3 个跨满第 2 行，避免 1 列 3 行过高导致地图过瘦 */
.chart-grid-inner.cols-2.count-3 > :last-child {
  grid-column: 1 / -1;
}

.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 240px;
}
</style>
