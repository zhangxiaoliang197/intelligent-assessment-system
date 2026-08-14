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
        v-for="(c, index) in charts"
        :key="c.chartId"
        :ref="(el) => setCardRef(el, c.chartId)"
        :spec="c"
        :index="index"
        :body-height="bodyHeight"
        :show-explanation="showExplanation"
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
  /** 图表主体高度（px），透传给卡片；详情页缩小布局传较小值 */
  bodyHeight?: number
  /** 网格每行最小高度（px），单列时保证卡片不被压扁 */
  rowMinHeight?: number
  /** 是否显示图表说明（默认显示）；打开态势图等纯展示场景传 false 关闭 */
  showExplanation?: boolean
}>()

// 指定列数时用等宽 1fr（minmax(0,1fr) 防止内容溢出撑宽）
// 行高支持自定义：详情页缩小布局需传更小的 rowMinHeight，否则会被默认 360px 下限拉伸
const gridStyle = computed(() => {
  const style: Record<string, string> = {}
  if (props.cols) style.gridTemplateColumns = `repeat(${props.cols}, minmax(0, 1fr))`
  const rowMin = props.rowMinHeight ?? 360
  style.gridAutoRows = props.cols
    ? `minmax(${rowMin}px, 1fr)`
    : `minmax(${rowMin}px, auto)`
  return style
})

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
  /* 每行最小高度由 gridStyle 动态注入；此值作为无 JS 兜底 */
  grid-auto-rows: minmax(360px, auto);
}
/* 指定列数时，每行等高（1fr）让同行图表对齐（行高下限由 gridStyle 覆盖） */
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
