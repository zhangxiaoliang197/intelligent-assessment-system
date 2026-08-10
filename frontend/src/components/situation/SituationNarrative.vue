<template>
  <div class="situation-narrative">
    <div v-if="!narrative.intro && !loading" class="narrative-empty">
      态势介绍与图表说明将在图表生成后呈现
    </div>
    <template v-else>
      <div v-if="narrative.intro" class="narrative-intro">
        <h4 class="narrative-section-title">态势介绍</h4>
        <div class="narrative-md" v-html="renderedIntro"></div>
      </div>
      <div v-if="narrative.explanations?.length" class="narrative-explanations">
        <h4 class="narrative-section-title">图表说明</h4>
        <ul class="explanation-list">
          <li
            v-for="exp in narrative.explanations"
            :key="exp.chartId"
            class="explanation-item"
            @click="$emit('jump-chart', exp.chartId)"
          >
            <el-icon class="explanation-icon"><Link /></el-icon>
            <div class="explanation-text">
              <span class="explanation-chart-id">{{ exp.chartId }}</span>
              <span>{{ exp.text }}</span>
            </div>
          </li>
        </ul>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Link } from '@element-plus/icons-vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Narrative } from '@/stores/situation'

const props = defineProps<{
  narrative: Narrative
  loading?: boolean
}>()

defineEmits<{
  (e: 'jump-chart', chartId: string): void
}>()

const renderedIntro = computed(() => {
  if (!props.narrative.intro) return ''
  const html = marked.parse(props.narrative.intro, { async: false }) as string
  return DOMPurify.sanitize(html)
})
</script>

<style scoped>
.situation-narrative {
  padding: 12px 16px;
  background: #fff;
  border-top: 1px solid #ebeef5;
  min-height: 80px;
}
.narrative-empty {
  color: #909399;
  font-size: 13px;
  padding: 16px 0;
  text-align: center;
}
.narrative-section-title {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  margin: 8px 0;
}
.narrative-md {
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
}
.narrative-md :deep(p) {
  margin: 6px 0;
}
.explanation-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.explanation-item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  cursor: pointer;
  transition: background 0.2s;
}
.explanation-item:hover {
  background: #f5f7fa;
}
.explanation-icon {
  color: #409eff;
  margin-top: 2px;
}
.explanation-text {
  font-size: 13px;
  color: #606266;
  line-height: 1.5;
}
.explanation-chart-id {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  background: #ecf5ff;
  color: #409eff;
  border-radius: 3px;
  font-size: 12px;
  font-family: monospace;
}
</style>
