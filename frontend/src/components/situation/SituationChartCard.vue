<template>
  <div class="chart-card" :class="{ highlighted: highlighted }">
    <div class="chart-card-header">
      <span class="chart-title">{{ spec.title }}</span>
      <el-tag size="small" type="info">{{ typeLabel }}</el-tag>
    </div>
    <div class="chart-card-body" :id="`chart-${spec.chartId}`">
      <component
        v-if="chartDef"
        :is="chartDef.component"
        :option="builtOption"
        autoresize
      />
      <el-empty v-else description="不支持的图表类型" :image-size="60" />
    </div>
    <div v-if="spec.explanation" class="chart-card-explain">
      <el-icon><InfoFilled /></el-icon>
      <span>{{ spec.explanation }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'
import { getChart } from '@/components/charts/registry'
import type { ChartSpec } from '@/stores/situation'

const props = defineProps<{
  spec: ChartSpec
  /** 图表在列表中的序号，用于配色轮转，避免所有图表同色 */
  index?: number
}>()

const highlighted = ref(false)

const chartDef = computed(() => getChart(props.spec.type))

const typeLabel = computed(() => chartDef.value?.name || props.spec.type)

const builtOption = computed(() => {
  if (!chartDef.value?.buildOption) return props.spec.option
  return chartDef.value.buildOption({ option: props.spec.option, title: props.spec.title, index: props.index })
})

// 暴露给父组件：滚动到此图并高亮
function flashHighlight() {
  highlighted.value = true
  setTimeout(() => { highlighted.value = false }, 1600)
}

defineExpose({ flashHighlight, chartId: props.spec.chartId })
</script>

<style scoped>
.chart-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: box-shadow 0.3s, border-color 0.3s;
}
.chart-card.highlighted {
  border-color: #409eff;
  box-shadow: 0 0 0 2px rgba(64, 158, 255, 0.25);
}
.chart-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.chart-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.chart-card-body {
  height: 320px;
  width: 100%;
}
.chart-card-explain {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  color: #606266;
  line-height: 1.5;
  background: #f5f7fa;
  padding: 6px 8px;
  border-radius: 4px;
}
</style>
