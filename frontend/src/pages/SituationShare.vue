<template>
  <div class="situation-share-page">
    <div v-if="loading" class="share-loading">
      <el-icon class="is-loading" :size="32"><Loading /></el-icon>
      <p>加载中...</p>
    </div>
    <template v-else-if="store.title">
      <SituationToolbar
        :title="store.title"
        :source="store.source"
        :status="store.status"
        :can-export="store.charts.length > 0"
        @export="onExport"
      />
      <div class="situation-capture-root">
        <!-- HTML Artifact 沙箱渲染（优先；LLM 整页排版 + situation-kit 挂载真实图表/地图） -->
        <ArtifactSandbox
          v-if="store.artifact"
          :html="store.artifact.html"
          :charts="store.charts"
          :map-layers="store.mapLayers"
          :datasets="store.datasets"
          :narrative="store.narrative"
        />
        <!-- LLM 布局树渲染（回退路径：无 artifact 时） -->
        <div v-else-if="store.layout" class="share-layout">
          <SituationLayoutRenderer
            :layout="store.layout"
            :charts="store.charts"
            :map-layers="store.mapLayers"
            :narrative="store.narrative"
            :datasets="store.datasets"
            :active-dataset="store.activeDataset"
            :viewport="store.viewport"
            :selected-region="store.selectedRegion"
            :time-range="store.selectedTimeRange"
            :filters="store.filters"
            :map-explanation="store.mapExplanation"
          />
        </div>
        <!-- 固定布局（回退路径：旧产物/布局生成失败） -->
        <template v-else>
          <div class="share-body">
            <div class="body-left">
              <SituationChartGrid :charts="store.charts" :body-height="230" :row-min-height="300" />
            </div>
            <div class="body-right">
              <SituationMapSlot
                :dataset="store.activeDataset"
                :layers="store.mapLayers"
                :viewport="store.viewport"
                :selected-region="store.selectedRegion"
                :time-range="store.selectedTimeRange"
                :filters="store.filters"
                :explanation="store.mapExplanation"
              />
            </div>
          </div>
          <SituationNarrative :narrative="store.narrative" />
        </template>
      </div>
    </template>
    <el-empty v-else description="分享链接无效或已失效" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Loading } from '@element-plus/icons-vue'
import SituationToolbar from '@/components/situation/SituationToolbar.vue'
import SituationChartGrid from '@/components/situation/SituationChartGrid.vue'
import SituationMapSlot from '@/components/situation/SituationMapSlot.vue'
import SituationNarrative from '@/components/situation/SituationNarrative.vue'
import SituationLayoutRenderer from '@/components/situation/SituationLayoutRenderer.vue'
import ArtifactSandbox from '@/components/situation/ArtifactSandbox.vue'
import { useSituationStore } from '@/stores/situation'
import { useSituationExport } from '@/composables/useSituationExport'
import api from '@/services/api'

const route = useRoute()
const store = useSituationStore()
const { exportPDF, exportImage } = useSituationExport()
const loading = ref(true)

onMounted(async () => {
  store.reset()
  const token = route.params.token as string
  try {
    const resp: any = await api.get(`/situation/share/${token}`)
    if (resp?.success !== false) {
      store.loadReport(resp.data || resp)
    }
  } catch (e) {
    store.reset()
    console.warn('分享加载失败', e)
  } finally {
    loading.value = false
  }
})

function onExport(format: 'pdf' | 'image') {
  const name = `${store.title || '态势图'}.${format === 'pdf' ? 'pdf' : 'png'}`
  if (format === 'pdf') exportPDF('.situation-capture-root', name)
  else exportImage('.situation-capture-root', name)
}
</script>

<style scoped>
.situation-share-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f7fa;
  overflow: hidden;
}
.share-loading {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  height: 100%;
  color: #909399;
}
.situation-capture-root {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
.share-body {
  flex: 1;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 12px;
  /* 图表较多（如 4 个 2×2）时左侧内容高度可能超过视口，允许滚动查看完整说明 */
  overflow-y: auto;
  min-height: 0;
}
/* 布局树模式：整体可滚动，内容纵向自然铺排 */
.share-layout {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  padding: 12px;
}
.body-left, .body-right {
  min-height: auto;
  display: flex;
  flex-direction: column;
}
@media (max-width: 1024px) {
  .share-body {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto;
  }
}
</style>
