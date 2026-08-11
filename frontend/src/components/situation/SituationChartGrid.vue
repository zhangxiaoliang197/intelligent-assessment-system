<template>
  <div class="chart-grid">
    <div v-if="!charts.length && !loading" class="chart-empty">
      <el-empty description="尚未生成图表，请在上方提问生成态势图" />
    </div>
    <div v-else class="chart-grid-inner">
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
import { ref } from 'vue'
import SituationChartCard from './SituationChartCard.vue'
import type { ChartSpec } from '@/stores/situation'

defineProps<{
  charts: ChartSpec[]
  loading?: boolean
}>()

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
  /* 左侧分栏宽度有限，minmax(300px,1fr) 让图表在 chart-side 内可多列排列，
     数量多时自动换行撑高，高度由内容决定（区域内不滚动）。 */
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 12px;
}
.chart-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 240px;
}
</style>
