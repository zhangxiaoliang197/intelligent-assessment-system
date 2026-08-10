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
        <div class="share-body">
          <div class="body-left">
            <SituationChartGrid :charts="store.charts" />
          </div>
          <div class="body-right">
            <SituationMapSlot
              :dataset="store.activeDataset"
              :layers="store.mapLayers"
              :viewport="store.viewport"
              :selected-region="store.selectedRegion"
              :time-range="store.selectedTimeRange"
              :filters="store.filters"
            />
          </div>
        </div>
        <SituationNarrative :narrative="store.narrative" />
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
import { useSituationStore } from '@/stores/situation'
import { useSituationExport } from '@/composables/useSituationExport'
import api from '@/services/api'

const route = useRoute()
const store = useSituationStore()
const { exportPDF, exportImage } = useSituationExport()
const loading = ref(true)

onMounted(async () => {
  const token = route.params.token as string
  try {
    const resp: any = await api.get(`/situation/share/${token}`)
    if (resp?.success !== false) {
      store.loadReport(resp.data || resp)
    }
  } catch (e) {
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
  overflow: hidden;
  min-height: 0;
}
.body-left, .body-right {
  min-height: 0;
  overflow: hidden;
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
