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

    <SituationSkillToolbar
      :skills="skills"
      :categories="skillCategories"
      :active-skill="store.activeSkill"
      :recommendations="skillRecommendations"
      :skill-total="skillCatalogTotal"
      :loading="skillsLoading"
      :parameters="store.skillParameters"
      @select="onSelectSkill"
      @clear="onClearSkill"
      @open-library="onOpenSkillDrawer"
      @open-markdown="skillMarkdownVisible = true"
      @configure="skillParametersVisible = true"
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

    <SituationSkillDrawer
      v-model="skillDrawerVisible"
      :skills="skills"
      :categories="skillCategories"
      :selected-skill-id="store.activeSkill?.id"
      :query="query"
      :loading="skillsLoading"
      :favorite-ids="skillFavoriteIds"
      :usage-stats="skillUsageStats"
      @select="onSelectSkill"
      @clear="onClearSkill"
      @reload="loadSkillCatalog"
      @favorite="onToggleSkillFavorite"
      @show-usage="openSkillUsage"
    />

    <SituationSkillParametersDialog
      v-model="skillParametersVisible"
      :skill="activeFullSkill"
      :parameters="store.skillParameters"
      :query="query"
      @save="onSaveSkillParameters"
    />

    <SituationSkillMarkdownDialog
      v-model="skillMarkdownVisible"
      :skill="activeFullSkill"
      @saved="onSkillMarkdownSaved"
    />

    <el-dialog v-model="skillUsageVisible" title="Skill 使用记录" width="760px">
      <el-table v-loading="skillUsageLoading" :data="skillUsageItems" empty-text="暂无使用记录">
        <el-table-column label="Skill" min-width="150">
          <template #default="scope">{{ skillName(scope.row.skillId) }}</template>
        </el-table-column>
        <el-table-column prop="query" label="问题" min-width="230" show-overflow-tooltip />
        <el-table-column label="状态" width="90">
          <template #default="scope">
            <el-tag size="small" :type="scope.row.status === 'ready' ? 'success' : scope.row.status === 'failed' ? 'danger' : 'warning'">
              {{ scope.row.status === 'ready' ? '成功' : scope.row.status === 'failed' ? '失败' : '执行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="scope">{{ scope.row.durationMs ? `${(scope.row.durationMs / 1000).toFixed(1)}s` : '-' }}</template>
        </el-table-column>
        <el-table-column prop="startedAt" label="开始时间" width="180" />
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import SituationToolbar from '@/components/situation/SituationToolbar.vue'
import SituationSkillToolbar from '@/components/situation/SituationSkillToolbar.vue'
import SituationQueryBar from '@/components/situation/SituationQueryBar.vue'
import SituationChartGrid from '@/components/situation/SituationChartGrid.vue'
import SituationMapSlot from '@/components/situation/SituationMapSlot.vue'
import SituationNarrative from '@/components/situation/SituationNarrative.vue'
import SituationSkillDrawer from '@/components/situation/SituationSkillDrawer.vue'
import SituationSkillParametersDialog from '@/components/situation/SituationSkillParametersDialog.vue'
import SituationSkillMarkdownDialog from '@/components/situation/SituationSkillMarkdownDialog.vue'
import { useSituationStore, type Viewport } from '@/stores/situation'
import { useSituationExport } from '@/composables/useSituationExport'
import api from '@/services/api'
import {
  listSituationSkills,
  listSituationSkillFavorites,
  listSituationSkillUsage,
  preflightSituationSkill,
  recommendSituationSkills,
  setSituationSkillFavorite,
} from '@/services/situationSkills'
import type {
  SituationSkill,
  SituationSkillCategory,
  SituationSkillPreflight,
  SituationSkillUsageItem,
} from '@/types/situationSkill'

const route = useRoute()
const store = useSituationStore()
const { exportPDF, exportImage } = useSituationExport()

const query = ref('')
const queryPlaceholder = '请输入您的问题，例如：某区域近期装备损耗与战备状态'
const chartGridRef = ref<InstanceType<typeof SituationChartGrid> | null>(null)

const shareVisible = ref(false)
const shareUrl = ref('')
const skillDrawerVisible = ref(false)
const skillsLoading = ref(false)
const skills = ref<SituationSkill[]>([])
const skillCategories = ref<SituationSkillCategory[]>([])
const skillCatalogTotal = ref(0)
const skillRecommendations = ref<SituationSkill[]>([])
const skillFavoriteIds = ref<string[]>([])
const skillUsageStats = ref<Record<string, { uses: number; successes: number }>>({})
const skillUsageItems = ref<SituationSkillUsageItem[]>([])
const skillUsageVisible = ref(false)
const skillUsageLoading = ref(false)
const skillParametersVisible = ref(false)
const skillMarkdownVisible = ref(false)
let recommendTimer: ReturnType<typeof setTimeout> | undefined
let recommendRequest = 0

const activeFullSkill = computed(() => (
  skills.value.find((skill) => skill.id === store.activeSkill?.id) || null
))

onMounted(async () => {
  void loadSkillCatalog()
  void loadSkillPreferences()
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

onUnmounted(() => {
  if (recommendTimer) clearTimeout(recommendTimer)
})

watch(query, (value) => {
  if (recommendTimer) clearTimeout(recommendTimer)
  recommendTimer = setTimeout(() => void updateSkillRecommendations(value), 320)
})

watch(skills, (items) => {
  if (store.activeSkill?.id) {
    const fullSkill = items.find((skill) => skill.id === store.activeSkill?.id)
    if (fullSkill) store.setActiveSkill(fullSkill)
  }
  if (!query.value.trim()) {
    skillRecommendations.value = items.filter((skill) => skill.featured).slice(0, 3)
  }
})

watch(() => store.activeSkill?.id, (skillId) => {
  if (!skillId) return
  const fullSkill = skills.value.find((skill) => skill.id === skillId)
  if (fullSkill && store.activeSkill?.description !== fullSkill.description) {
    store.setActiveSkill(fullSkill)
  }
})

async function loadSkillCatalog() {
  if (skillsLoading.value) return
  skillsLoading.value = true
  try {
    const catalog = await listSituationSkills({ limit: 100 })
    skills.value = catalog.items
    skillCategories.value = catalog.categories
    skillCatalogTotal.value = catalog.catalogTotal || catalog.total
  } catch (error) {
    console.warn('态势 Skill 目录加载失败', error)
    ElMessage.error('态势 Skill 目录加载失败，请稍后重试')
  } finally {
    skillsLoading.value = false
  }
}

async function loadSkillPreferences() {
  try {
    const [favorites, usage] = await Promise.all([
      listSituationSkillFavorites(),
      listSituationSkillUsage(50),
    ])
    skillFavoriteIds.value = favorites
    skillUsageStats.value = usage.stats
    skillUsageItems.value = usage.items
  } catch (error) {
    console.warn('Skill 偏好与使用记录加载失败', error)
  }
}

function onOpenSkillDrawer() {
  skillDrawerVisible.value = true
  if (!skills.value.length) void loadSkillCatalog()
}

async function onSkillMarkdownSaved(skillId: string) {
  await loadSkillCatalog()
  const refreshed = skills.value.find((skill) => skill.id === skillId)
  if (refreshed && store.activeSkill?.id === skillId) store.setActiveSkill(refreshed)
}

async function updateSkillRecommendations(value: string) {
  const text = value.trim()
  if (!text) {
    skillRecommendations.value = skills.value.filter((skill) => skill.featured).slice(0, 3)
    return
  }
  const requestId = ++recommendRequest
  try {
    const items = await recommendSituationSkills(text, 3, {
      source: store.source,
      selectedRegion: store.selectedRegion || '',
      ...store.filters,
    })
    if (requestId === recommendRequest) skillRecommendations.value = items
  } catch (error) {
    if (requestId === recommendRequest) skillRecommendations.value = []
    console.warn('态势 Skill 推荐失败', error)
  }
}

function onSelectSkill(skill: SituationSkill, question?: string) {
  store.setActiveSkill(skill)
  if (question || !query.value.trim()) {
    query.value = question || skill.recommendedQuestions[0] || ''
  }
  ElMessage.success(`已启用「${skill.name}」`)
}

function onSaveSkillParameters(parameters: Record<string, unknown>, preflight?: SituationSkillPreflight) {
  store.setSkillParameters(preflight?.parameters || parameters)
  ElMessage.success('Skill 参数已保存')
}

async function onToggleSkillFavorite(skillId: string, favorite: boolean) {
  try {
    await setSituationSkillFavorite(skillId, favorite)
    skillFavoriteIds.value = favorite
      ? Array.from(new Set([skillId, ...skillFavoriteIds.value]))
      : skillFavoriteIds.value.filter((id) => id !== skillId)
    ElMessage.success(favorite ? '已收藏' : '已取消收藏')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '收藏操作失败')
  }
}

async function openSkillUsage() {
  skillUsageVisible.value = true
  skillUsageLoading.value = true
  try {
    const usage = await listSituationSkillUsage(50)
    skillUsageItems.value = usage.items
    skillUsageStats.value = usage.stats
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '使用记录加载失败')
  } finally {
    skillUsageLoading.value = false
  }
}

function skillName(skillId: string) {
  return skills.value.find((skill) => skill.id === skillId)?.name || skillId
}

function onClearSkill() {
  store.setActiveSkill(null)
}

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
    if (activeFullSkill.value) {
      const preflight = await preflightSituationSkill(
        activeFullSkill.value.id,
        text,
        store.skillParameters,
      )
      if (!preflight.ready) {
        ElMessage.error(preflight.errors.join('；') || 'Skill 执行前检查未通过')
        return
      }
      store.setSkillParameters(preflight.parameters)
      if (preflight.warnings.length) {
        ElMessage.warning(`执行前检查通过：${preflight.warnings[0]}`)
      }
    }
    await store.generate(text)
    void loadSkillPreferences()
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
