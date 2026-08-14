<template>
  <Layout>
    <div class="view-page" v-loading="loading">
      <!-- 轻量工具栏 -->
      <div class="view-toolbar">
        <div class="view-title-area">
          <el-button :icon="ArrowLeft" circle @click="goBack" title="返回" />
          <div class="title-text">
            <h2 class="view-title">{{ store.title || '态势图' }}</h2>
            <div class="view-meta">
              <el-tag size="small" effect="plain">{{ sourceLabel }}</el-tag>
              <span v-if="store.charts.length">{{ store.charts.length }} 张图表</span>
              <span v-if="store.mapLayers.length">{{ store.mapLayers.length }} 个图层</span>
            </div>
          </div>
        </div>
        <div class="view-actions">
          <el-button @click="onShare"><el-icon><Share /></el-icon> 分享</el-button>
          <el-button @click="onExport('image')"><el-icon><Download /></el-icon> 导出图片</el-button>
          <el-button @click="onExport('pdf')"><el-icon><Download /></el-icon> 导出 PDF</el-button>
        </div>
      </div>

      <!-- 纯展示内容：左图表 + 右地图（等高自适应）+ 底部态势分析 -->
      <div class="view-content custom-scroll" ref="captureRef">
        <div
          class="main-row"
          :class="{ 'only-map': !store.charts.length }"
          :style="{ minHeight: chartLayout.minHeight + 'px' }"
        >
          <div v-if="store.charts.length" class="chart-side">
            <h3 class="section-label">统计图表</h3>
            <SituationChartGrid :charts="store.charts" :cols="chartLayout.cols" :body-height="230" :row-min-height="300" />
          </div>

          <div v-if="store.mapLayers.length" class="map-side">
            <h3 class="section-label">地理分布</h3>
            <div class="view-map-section">
              <SituationMapSlot
                :dataset="store.activeDataset"
                :layers="store.mapLayers"
                :viewport="store.viewport"
                :selected-region="store.selectedRegion"
                :time-range="store.selectedTimeRange"
                :filters="store.filters"
                :explanation="store.mapExplanation"
                @region-select="onRegionSelect"
                @marker-click="onMarkerClick"
                @layer-toggle="onLayerToggle"
                @draw-end="onDrawEnd"
                @viewport-change="onViewportChange"
              />
            </div>
          </div>
        </div>

        <div v-if="store.narrative.intro" class="narrative-section">
          <h3 class="section-label">态势分析</h3>
          <SituationNarrative :narrative="store.narrative" />
        </div>

        <el-empty
          v-if="!store.charts.length && !store.mapLayers.length && !store.narrative.intro && !loading"
          description="暂无产物数据"
        />
      </div>
    </div>

    <!-- 分享对话框 -->
    <el-dialog v-model="shareVisible" title="分享链接" width="480px">
      <el-input v-model="shareUrl" readonly>
        <template #append><el-button @click="copyShare">复制</el-button></template>
      </el-input>
      <template #footer><el-button @click="shareVisible = false">关闭</el-button></template>
    </el-dialog>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Share, Download } from '@element-plus/icons-vue'
import Layout from '@/components/Layout.vue'
import SituationChartGrid from '@/components/situation/SituationChartGrid.vue'
import SituationMapSlot from '@/components/situation/SituationMapSlot.vue'
import SituationNarrative from '@/components/situation/SituationNarrative.vue'
import { useSituationStore, type Viewport } from '@/stores/situation'
import { useSituationExport } from '@/composables/useSituationExport'
import api from '@/services/api'

const route = useRoute()
const router = useRouter()
const store = useSituationStore()
const { exportPDF, exportImage } = useSituationExport()

const loading = ref(false)
const captureRef = ref<HTMLElement | null>(null)
const shareVisible = ref(false)
const shareUrl = ref('')

const sourceLabel = computed(() => {
  const map: Record<string, string> = { manual: '手动提问', qa: '智能问答', indicator: '指标分析', evaluation: '评估分析' }
  return map[store.source] || '手动提问'
})

/**
 * 根据图表数量智能规划布局（列数 + 区域最小高度）。
 *
 * 原则：让左侧图表区的行数决定高度，地图跟随等高（align-items:stretch）。
 * - 数量少时优先纵向或 2 列，保证地图有足够高度不致过扁；
 * - 3 个图表用 2 列 + 第 3 个跨列填满第 2 行（避免 1 列 3 行过高使地图过瘦）；
 * - 4 个用 2×2；5-6 个用 2 列 3 行；7+ 用 3 列。
 * - 单行高度按 300px 估算（图表卡片 body 230 + header/padding 60 + 说明块约 30），含 12px gap。
 *   说明块为 1-3 行（13px/1.6 行高 + 上下 padding），估算值保留余量；即使说明更长，
 *   行高也会随内容撑开，minHeight 仅作为下限。
 */
const chartLayout = computed(() => {
  const n = store.charts.length
  // 单行高度估算：卡片 300 + gap 12（末行无 gap，公式 rows*300 + (rows-1)*12）
  const ROW_H = 300
  const GAP = 12
  const PAD = 32 // chart-side 上下 padding
  const h = (rows: number) => rows * ROW_H + (rows - 1) * GAP + PAD

  if (n === 0) return { cols: 1, minHeight: 520 }        // 无图表：给地图默认高度
  if (n === 1) return { cols: 1, minHeight: h(1) }       // 单个
  if (n === 2) return { cols: 1, minHeight: h(2) }       // 纵向 2 行
  if (n === 3) return { cols: 2, minHeight: h(2) }       // 2+1 跨列，2 行
  if (n === 4) return { cols: 2, minHeight: h(2) }       // 2×2，2 行
  if (n <= 6) return { cols: 2, minHeight: h(3) }        // 2 列 3 行
  if (n <= 9) return { cols: 3, minHeight: h(3) }        // 3×3，3 行
  // 10+：3 列，按行数动态
  const rows = Math.ceil(n / 3)
  return { cols: 3, minHeight: h(rows) }
})

onMounted(async () => {
  const rid = route.params.reportId as string
  if (!rid) return
  loading.value = true
  try {
    const resp: any = await api.get(`/situation/reports/${rid}`)
    if (resp?.success !== false) {
      store.loadReport(resp.data || resp)
    } else {
      ElMessage.error('产物不存在或已删除')
    }
  } catch (e: any) {
    ElMessage.error('加载失败：' + (e?.message || ''))
  } finally {
    loading.value = false
  }
})

function goBack() {
  // 优先返回上一页，否则回对话页
  if (window.history.length > 1) router.back()
  else router.push('/situation')
}

async function onShare() {
  if (!store.reportId) {
    ElMessage.warning('无可用产物')
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
  if (format === 'pdf') exportPDF('.view-content', name)
  else exportImage('.view-content', name)
}

function copyShare() {
  navigator.clipboard.writeText(shareUrl.value).then(() => ElMessage.success('已复制'))
}

// ── 地图联动回调（与对话页一致）──
function onRegionSelect(payload: { regionId: string; name: string }) {
  store.setSelectedRegion(payload.regionId)
}
function onMarkerClick(payload: { point: any; layerId?: string }) {
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
</script>

<style scoped>
.view-page {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #f5f7fa;
  overflow: hidden;
}

/* 工具栏 */
.view-toolbar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
}
.view-title-area {
  display: flex;
  align-items: center;
  gap: 12px;
}
.title-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.view-title {
  font-size: 16px;
  font-weight: 600;
  color: #1f2937;
  margin: 0;
}
.view-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #9ca3af;
}
.view-actions {
  display: flex;
  gap: 8px;
}

/* 展示内容 */
.view-content {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
/* 左图表 + 右地图等高，底部态势分析 */
.main-row {
  display: flex;
  align-items: stretch;
  gap: 16px;
  /* minHeight 由 chartLayout 计算属性内联设置，按图表数量自适应；
     禁止 flex 压缩：内容（含图表说明）高于 minHeight 时整页滚动，而不是把
     说明挤入下方区块被遮挡 */
  flex-shrink: 0;
}
.chart-side {
  flex: 1;
  min-width: 0;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
}
.chart-side :deep(.chart-grid) {
  flex: 1;
}
.map-side {
  flex: 0 0 44%;
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
}
/* 无图表时地图占满整行 */
.main-row.only-map .map-side {
  flex: 1;
}
.map-side .view-map-section {
  flex: 1;
  min-height: 0;
}
.section-label {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 12px;
  padding-left: 8px;
  border-left: 3px solid #8b5cf6;
}
.view-map-section {
  border: 1px solid #ebeef5;
  border-radius: 6px;
  overflow: hidden;
}
.narrative-section {
  background: #fff;
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 16px 18px;
}

.custom-scroll::-webkit-scrollbar {
  width: 8px;
}
.custom-scroll::-webkit-scrollbar-thumb {
  background: rgba(0, 0, 0, 0.15);
  border-radius: 4px;
}
.custom-scroll::-webkit-scrollbar-track {
  background: transparent;
}
</style>
