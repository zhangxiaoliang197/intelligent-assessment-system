<template>
  <div class="situation-narrative">
    <div v-if="!narrative.intro && !loading" class="narrative-empty">
      态势介绍将在图表生成后呈现
    </div>
    <div v-else-if="narrative.intro" class="narrative-intro">
      <h4 class="narrative-section-title">态势介绍</h4>
      <div class="narrative-md" v-html="renderedIntro"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import type { Narrative } from '@/stores/situation'

const props = defineProps<{
  narrative: Narrative
  loading?: boolean
}>()

const renderedIntro = computed(() => {
  if (!props.narrative.intro) return ''
  const html = marked.parse(props.narrative.intro, { async: false }) as string
  return DOMPurify.sanitize(html)
})
</script>

<style scoped>
.situation-narrative {
  /* 压缩态势介绍留白，把空间让给上方图表与地图 */
  padding: 8px 16px;
  background: #fff;
  border-top: 1px solid #ebeef5;
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
</style>
