<template>
  <div class="metrics-card">
    <div v-if="title" class="metrics-title">{{ title }}</div>
    <div class="metrics-row" :class="{ compact: items.length > 3 }">
      <div v-for="(item, i) in items" :key="i" class="metric-item">
        <div class="metric-label">{{ item.label }}</div>
        <div class="metric-value" :title="item.full">{{ item.display }}</div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { DatasetSummary, LayoutMetric } from '@/stores/situation'

const props = defineProps<{
  /** 数据集（取 data 全量行做聚合，与图表/地图同源） */
  dataset?: DatasetSummary | null
  /** LLM 指定的指标项（label/column/agg，后端已校验列名存在） */
  metrics: LayoutMetric[]
  /** 卡片标题（可选） */
  title?: string
}>()

// 数值展示：大数带千分位；小数保留至多 2 位
function formatNumber(n: number): { display: string; full: string } {
  if (!Number.isFinite(n)) return { display: '-', full: '-' }
  const full = n.toLocaleString('zh-CN', { maximumFractionDigits: 4 })
  const display = Math.abs(n) >= 1000
    ? n.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
    : n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return { display, full }
}

// 从数据集全量行计算聚合值（数据只来自 dataset，LLM 不产出数值）
const items = computed(() => {
  const rows = props.dataset?.data?.length
    ? props.dataset.data
    : (Array.isArray(props.dataset?.rows) ? props.dataset!.rows! : [])
  return props.metrics
    .map((m) => {
      let value = 0
      if (m.agg === 'count') {
        value = rows.length
      } else {
        const nums = rows
          .map((r: any) => Number(r?.[m.column]))
          .filter((n: number) => Number.isFinite(n))
        if (!nums.length) return null
        if (m.agg === 'sum') value = nums.reduce((a: number, b: number) => a + b, 0)
        else if (m.agg === 'max') value = Math.max(...nums)
        else if (m.agg === 'min') value = Math.min(...nums)
        else value = nums.reduce((a: number, b: number) => a + b, 0) / nums.length
      }
      const { display, full } = formatNumber(value)
      return { label: m.label, display, full }
    })
    .filter(Boolean) as Array<{ label: string; display: string; full: string }>
})
</script>

<style scoped>
.metrics-card {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 12px 16px;
}
.metrics-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 8px;
}
.metrics-row {
  display: flex;
  gap: 12px;
}
.metrics-row.compact .metric-item {
  min-width: 0;
}
.metric-item {
  flex: 1 1 0;
  min-width: 72px;
  background: #f8fafc;
  border-radius: 6px;
  padding: 10px 12px;
}
.metric-label {
  font-size: 12px;
  color: #909399;
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.metric-value {
  font-size: 20px;
  font-weight: 700;
  color: #1f2d3d;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
