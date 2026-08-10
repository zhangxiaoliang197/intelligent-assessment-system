<template>
  <div class="situation-page">
    <SituationToolbar
      :title="store.title"
      :source="store.source"
      :status="store.status"
      :can-refresh="store.status === 'ready'"
      :can-export="store.charts.length > 0"
      @refresh="onRefresh"
      @share="onShare"
      @export="onExport"
    />

    <SituationQueryBar
      v-model="query"
      :loading="store.isGenerating"
      :placeholder="queryPlaceholder"
      @generate="onGenerate"
    />

    <div class="situation-capture-root">
      <div class="situation-body">
        <div class="body-left">
          <SituationChartGrid
            ref="chartGridRef"
            :charts="store.charts"
            :loading="store.isGenerating"
          />
        </div>
        <div class="body-right">
          <SituationMapSlot
            :dataset="store.activeDataset"
            :layers="store.mapLayers"
            :viewport="store.viewport"
            :selected-region="store.selectedRegion"
            :time-range="store.selectedTimeRange"
            :filters="store.filters"
            @region-select="onRegionSelect"
            @marker-click="onMarkerClick"
            @layer-toggle="onLayerToggle"
            @draw-end="onDrawEnd"
            @viewport-change="onViewportChange"
          >
            <!--
              地图同事组件挂入点（docs/situation-map/06 §2）：
              同事采用方式 A（作用域插槽）或方式 B（直读 store）接入。
              当前未接入时显示占位，下方注释为同事接入示例（方式 A）：

              <template #map="ctx">
                <ColleagueMap
                  :dataset="ctx.dataset"
                  :layers="ctx.layers"
                  :viewport="ctx.viewport"
                  :selected-region="ctx.selectedRegion"
                  @region-select="ctx['on-region-select']"
                  @marker-click="ctx['on-marker-click']"
                  @layer-toggle="ctx['on-layer-toggle']"
                  @draw-end="ctx['on-draw-end']"
                  @viewport-change="ctx['on-viewport-change']"
                />
              </template>
            -->
          </SituationMapSlot>
        </div>
      </div>

      <SituationNarrative
        :narrative="store.narrative"
        :loading="store.isGenerating"
        @jump-chart="onJumpChart"
      />
    </div>

    <!-- 分享对话框 -->
    <el-dialog v-model="shareVisible" title="分享链接" width="480px">
      <el-input v-model="shareUrl" readonly>
        <template #append>
          <el-button @click="copyShare">复制</el-button>
        </template>
      </el-input>
      <template #footer>
        <el-button @click="shareVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import SituationToolbar from '@/components/situation/SituationToolbar.vue'
import SituationQueryBar from '@/components/situation/SituationQueryBar.vue'
import SituationChartGrid from '@/components/situation/SituationChartGrid.vue'
import SituationMapSlot from '@/components/situation/SituationMapSlot.vue'
import SituationNarrative from '@/components/situation/SituationNarrative.vue'
import { useSituationStore, type Viewport } from '@/stores/situation'
import { useSituationStream } from '@/composables/useSituationStream'
import { useSituationExport } from '@/composables/useSituationExport'
import api from '@/services/api'

const route = useRoute()
const store = useSituationStore()
const { start: startStream } = useSituationStream()
const { exportPDF, exportImage } = useSituationExport()

const query = ref('')
const queryPlaceholder = '请输入您的问题，例如：某区域近期装备损耗与战备状态'
const chartGridRef = ref<InstanceType<typeof SituationChartGrid> | null>(null)

const shareVisible = ref(false)
const shareUrl = ref('')

onMounted(async () => {
  // 1) 跨功能跳转：带 draftId
  const draftId = route.query.draftId as string
  if (draftId) {
    try {
      const resp: any = await api.get(`/situation/draft/${draftId}`)
      if (resp?.success !== false) {
        const draft = resp.data || resp
        store.initFromDraft(draft)
        query.value = store.query
        if (draft?.context?.autoGenerate) onGenerate(store.query)
      }
    } catch (e) {
      console.warn('草稿加载失败', e)
    }
  }
  // 2) 历史/分享回看：带 reportId
  const reportId = route.query.reportId as string
  if (reportId) {
    await loadExisting(reportId)
  }
})

async function loadExisting(rid: string) {
  try {
    const resp: any = await api.get(`/situation/reports/${rid}`)
    if (resp?.success !== false) {
      store.loadReport(resp.data || resp)
      query.value = store.query
    }
  } catch (e) {
    console.warn('产物加载失败', e)
  }
}

async function onGenerate(q?: string) {
  const text = (typeof q === 'string' ? q : query.value) || ''
  if (!text.trim()) {
    ElMessage.warning('请输入问题')
    return
  }
  query.value = text
  try {
    await store.generate(text)
    if (store.reportId) startStream(store.reportId)
  } catch (e: any) {
    ElMessage.error('生成失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

function onRefresh() {
  store.refresh()
}

async function onShare() {
  if (!store.reportId) {
    ElMessage.warning('尚未生成产物')
    return
  }
  try {
    const resp: any = await api.post(`/situation/reports/${store.reportId}/share`)
    if (resp?.success !== false) {
      const data = resp.data || resp
      shareUrl.value = `${window.location.origin}/#/situation/share/${data.token}`
      shareVisible.value = true
    }
  } catch (e: any) {
    ElMessage.error('生成分享链接失败：' + (e?.serverMessage || ''))
  }
}

function onExport(format: 'pdf' | 'image') {
  const name = `${store.title || '态势图'}.${format === 'pdf' ? 'pdf' : 'png'}`
  if (format === 'pdf') exportPDF('.situation-capture-root', name)
  else exportImage('.situation-capture-root', name)
}

function copyShare() {
  navigator.clipboard.writeText(shareUrl.value).then(() => ElMessage.success('已复制'))
}

// ── 地图联动回调（写共享状态 → 图表响应）──
function onRegionSelect(payload: { regionId: string; name: string }) {
  store.setSelectedRegion(payload.regionId)
}
function onMarkerClick(payload: { point: any; layerId?: string }) {
  // 点击标记 → 高亮对应图表数据点（v1 仅提示）
  console.log('marker-click', payload)
}
function onLayerToggle(payload: { layerId: string; visible: boolean }) {
  store.toggleLayer(payload.layerId, payload.visible)
}
function onDrawEnd(payload: { type: string; geojson: any; name?: string }) {
  console.log('draw-end', payload)
}
function onViewportChange(vp: Viewport) {
  store.setViewport(vp)
}

function onJumpChart(chartId: string) {
  chartGridRef.value?.scrollToChart(chartId)
}
</script>

<style scoped>
.situation-page {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f7fa;
  overflow: hidden;
}
.situation-capture-root {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
}
.situation-body {
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
  .situation-body {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto;
  }
}
</style>
