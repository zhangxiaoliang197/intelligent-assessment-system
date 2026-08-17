<template>
  <Layout>
    <div class="situation-container">
      <!-- 侧边栏 -->
      <div class="sidebar">
        <div class="sidebar-section">
          <div class="sidebar-section-header">
            <h3 class="sidebar-title">导航</h3>
            <el-button class="new-session-btn" type="primary" @click="onNewSession">
              <el-icon><Plus /></el-icon> 新会话
            </el-button>
          </div>
          <div class="nav-item" @click="go('/knowledge')">
            <el-icon><Collection /></el-icon><span>知识库</span>
          </div>
          <div class="nav-item" @click="go('/ontology')">
            <el-icon><Box /></el-icon><span>本体</span>
          </div>
          <div class="nav-item" @click="go('/situation/list')">
            <el-icon><List /></el-icon><span>历史管理</span>
          </div>
        </div>
        <div class="sidebar-section">
          <h3 class="sidebar-title">历史记录</h3>
          <div class="history-list custom-scroll">
            <div
              v-for="item in filteredHistory"
              :key="item.reportId"
              :class="['history-item', { active: item.reportId === store.reportId }]"
            >
              <div class="history-item-main" @click="onPickHistory(item)">
                <el-icon><MapLocation /></el-icon>
                <div class="history-item-content">
                  <span class="history-item-title">{{ item.title || item.query || '未命名态势' }}</span>
                  <span class="history-item-time">{{ formatTime(item.createTime || item.createdAt || '') }}</span>
                </div>
              </div>
              <el-button class="history-delete-btn" size="small" text type="danger" @click.stop="deleteHistory(item.reportId)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-empty v-if="!filteredHistory.length" description="暂无历史" :image-size="56" />
          </div>
          <div class="search-bar history-search">
            <el-input v-model="historySearch" placeholder="搜索历史记录..." :prefix-icon="Search" clearable />
          </div>
        </div>
      </div>

      <!-- 主内容 -->
      <div class="main-content">
        <!-- Skill 工具栏（Skill 引擎：选择 / 推荐 / 技能库 / SKILL.md / 参数配置） -->
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
        >
          <!-- 数据源选择（与技能同行，对齐指标分析 top-bar 布局） -->
          <template #append>
            <span class="label">数据源：</span>
            <el-select
              v-model="store.dataSourceId"
              class="data-source-select"
              placeholder="选择数据源"
              size="small"
              @change="onDataSourceChange"
            >
              <el-option
                v-for="ds in store.dataSources"
                :key="ds.id"
                :label="ds.status === 'available' ? ds.name : `${ds.name}（不可用）`"
                :value="ds.id"
                :disabled="ds.status !== 'available'"
              />
            </el-select>
            <el-button size="small" type="primary" @click="dataSourceDialogVisible = true">
              <el-icon><Setting /></el-icon> 配置
            </el-button>
          </template>
        </SituationSkillToolbar>

        <!-- 执行步骤流（对齐指标分析 skill-plan-bar：选中 Skill 后展示步骤链） -->
        <div v-if="activeFullSkill" class="skill-plan-bar">
          <div class="skill-plan-title">
            <el-icon><MagicStick /></el-icon>
            <strong>{{ activeFullSkill.name }}</strong>
            <el-tag size="small" effect="plain">{{ activeFullSkill.category }}</el-tag>
            <el-tag v-if="activeFullSkill.source === 'custom'" size="small" type="warning" effect="light">自定义</el-tag>
          </div>
          <div class="skill-plan-flow">
            <template v-for="(step, index) in activeFullSkill.steps" :key="index">
              <span class="skill-plan-step">{{ index + 1 }}. {{ step }}</span>
              <el-icon v-if="index < activeFullSkill.steps.length - 1" class="skill-plan-arrow"><ArrowRight /></el-icon>
            </template>
            <el-icon class="skill-plan-arrow"><ArrowRight /></el-icon>
            <span class="skill-plan-step output">生成态势</span>
          </div>
          <el-button
            class="skill-markdown-button"
            size="small"
            plain
            :icon="Document"
            @click="skillMarkdownVisible = true"
          >
            SKILL.md
          </el-button>
        </div>

        <div class="content-area">
          <!-- 对话面板 -->
          <div class="chat-panel">
            <div class="chat-area custom-scroll" ref="chatAreaRef">
              <!-- 空状态 -->
              <div v-if="isEmpty" class="empty-state">
                <p>态势图</p>
                <div class="tags-section">
                  <div class="suggest-cards">
                    <div
                      v-for="s in suggests"
                      :key="s.title"
                      class="suggest-card"
                      :style="{ '--card-color': s.color }"
                      @click="onSuggest(s.title)"
                    >
                      <div class="suggest-icon"><el-icon><component :is="s.icon" /></el-icon></div>
                      <div class="suggest-content">
                        <span class="suggest-title">{{ s.title }}</span>
                        <span class="suggest-desc">{{ s.desc }}</span>
                      </div>
                      <el-icon class="suggest-arrow"><ArrowRight /></el-icon>
                    </div>
                  </div>
                </div>
              </div>

              <!-- 消息列表 -->
              <div v-else class="message-list">
                <!-- 用户消息 -->
                <div v-if="store.query" class="message user">
                  <div class="message-avatar"><el-avatar :size="36">我</el-avatar></div>
                  <div class="message-content">
                    <div class="message-text">{{ store.query }}</div>
                  </div>
                </div>

                <!-- AI 消息 -->
                <div class="message assistant" ref="aiMsgRef">
                  <div class="message-avatar">
                    <el-avatar :size="36" class="ai-avatar">
                      <el-icon><MapLocation /></el-icon>
                    </el-avatar>
                  </div>
                  <div class="message-content">
                    <!-- 生成中占位 -->
                    <div v-if="store.isGenerating && !store.charts.length && !store.mapLayers.length" class="message-loading">
                      <el-icon class="rotating"><Loading /></el-icon> 正在编排数据、生成态势产物...
                    </div>

                    <div class="ai-response">
                      <!-- 图表区 -->
                      <div v-if="store.charts.length" class="tree-section">
                        <SituationChartGrid :charts="store.charts" :loading="store.isGenerating" :cols="1" :body-height="360" />
                      </div>

                      <!-- 地图（仅有图层时显示） -->
                      <div v-if="store.mapLayers.length" class="data-section ai-map-section">
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

                      <!-- 分析结论 -->
                      <div v-if="store.narrative.intro" class="references-section">
                        <SituationNarrative :narrative="store.narrative" />
                      </div>

                      <!-- 错误提示 -->
                      <div v-if="store.errorMsg">
                        <el-alert :title="store.errorMsg" type="error" :closable="false" show-icon />
                      </div>

                      <!-- 操作按钮 -->
                      <div v-if="store.status === 'ready' && store.reportId" class="confirm-actions">
                        <el-button type="primary" @click="openView"><el-icon><FullScreen /></el-icon> 打开态势图</el-button>
                        <el-button @click="onShare"><el-icon><Share /></el-icon> 分享</el-button>
                        <el-button @click="onExport('image')"><el-icon><Download /></el-icon> 导出图片</el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <!-- 输入区 -->
            <div class="input-area">
              <div class="input-wrapper">
                <el-input
                  v-model="inputText"
                  type="textarea"
                  :rows="3"
                  :placeholder="inputPlaceholder"
                  resize="none"
                  @keydown.enter.exact.prevent="onGenerate()"
                />
                <div class="input-actions">
                  <el-button v-if="store.isGenerating" type="danger" plain @click="onStop">
                    <el-icon><CircleClose /></el-icon> 取消
                  </el-button>
                  <el-button v-else type="primary" :loading="generatePending || store.requestPending" @click="onGenerate()">
                    <el-icon><Promotion /></el-icon> 生成态势
                  </el-button>
                </div>
              </div>

              <!-- 工具按钮 -->
              <div class="tools-bar">
                <div
                  v-for="tool in tools"
                  :key="tool.id"
                  :class="['tool-item', { current: tool.current }]"
                  @click="navigateToTool(tool.path)"
                >
                  <div class="tool-icon">
                    <el-icon :size="16" :color="tool.current ? 'white' : tool.color">
                      <component :is="tool.icon" />
                    </el-icon>
                  </div>
                  <span class="tool-name">{{ tool.name }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 执行面板 -->
          <div v-if="showExecPanel" class="execution-panel" :style="{ width: execPanelWidth + 'px' }">
            <div class="resize-handle" @mousedown="startResize"></div>
            <div class="panel-header">
              <div class="panel-title-wrap"><span>执行过程</span></div>
              <el-icon class="panel-close" @click="showExecPanel = false"><Close /></el-icon>
            </div>
            <div class="execution-progress">
              <div class="execution-progress-meta">
                <span>生成进度</span>
                <span>{{ store.stepProgress.done }} / {{ store.stepProgress.total }}</span>
              </div>
              <el-progress
                :percentage="store.stepProgress.percent"
                :status="store.status === 'failed' ? 'exception' : store.status === 'ready' ? 'success' : undefined"
              />
            </div>
            <div class="execution-content custom-scroll">
              <div class="panel-section">
                <div class="section-header"><h5>生成步骤</h5></div>
                <div class="steps-list">
                  <div
                    v-for="(step, idx) in store.executionSteps"
                    :key="idx"
                    :class="['inline-step', stepStatusClass(step.status)]"
                  >
                    <div class="inline-step-header">
                      <div class="inline-step-icon">
                        <el-icon v-if="step.status === 'completed'"><CircleCheck /></el-icon>
                        <el-icon v-else-if="step.status === 'error'"><CircleClose /></el-icon>
                        <el-icon v-else class="rotating"><Loading /></el-icon>
                      </div>
                      <div class="inline-step-title">{{ step.description }}</div>
                    </div>
                    <div v-if="step.detail" class="inline-step-detail">{{ step.detail }}</div>
                  </div>
                </div>
              </div>
              <el-empty v-if="!store.executionSteps.length" description="暂无执行步骤" :image-size="56" />
            </div>
          </div>
          <div v-else-if="store.executionSteps.length" class="execution-panel-toggle" @click="showExecPanel = true">
            <el-icon><ArrowRight /></el-icon>
            <span class="toggle-text">执行过程</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 分享对话框 -->
    <el-dialog v-model="shareVisible" title="分享链接" width="480px">
      <el-input v-model="shareUrl" readonly>
        <template #append><el-button @click="copyShare">复制</el-button></template>
      </el-input>
      <template #footer><el-button @click="shareVisible = false">关闭</el-button></template>
    </el-dialog>

    <!-- 数据源配置对话框（对齐指标分析） -->
    <el-dialog v-model="dataSourceDialogVisible" title="数据源配置" width="600px">
      <div class="data-source-list">
        <div
          v-for="ds in store.dataSources"
          :key="ds.id"
          :class="['ds-item', { active: ds.id === store.dataSourceId }]"
          @click="store.setDataSource(ds.id)"
        >
          <div class="ds-item-main">
            <div class="ds-item-content">
              <div class="ds-item-name">{{ ds.name }}</div>
            </div>
          </div>
          <div class="ds-item-meta">
            <el-tag v-if="ds.type" size="small">{{ ds.type }}</el-tag>
            <el-tag :type="ds.status === 'available' ? 'success' : 'info'" size="small">
              {{ ds.status === 'available' ? '可用' : '不可用' }}
            </el-tag>
            <el-icon v-if="ds.id === store.dataSourceId" class="ds-item-check"><CircleCheck /></el-icon>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="dataSourceDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmDataSource">确定</el-button>
      </template>
    </el-dialog>

    <!-- Skill 技能库抽屉 -->
    <SituationSkillDrawer
      v-model="skillDrawerVisible"
      :skills="skills"
      :categories="skillCategories"
      :selected-skill-id="store.activeSkill?.id"
      :query="inputText"
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
      :query="inputText"
      :data-source-id="store.dataSourceId"
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
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Plus, Collection, Box, List, Search, MapLocation, Promotion, Loading,
  FullScreen, Share, Download, CircleClose, CircleCheck, Close, ArrowRight,
  PieChart, TrendCharts, DataAnalysis, Setting, MagicStick, Document, Delete
} from '@element-plus/icons-vue'
import Layout from '@/components/Layout.vue'
import { useToolNav } from '@/composables/useToolNav'
import SituationChartGrid from '@/components/situation/SituationChartGrid.vue'
import SituationMapSlot from '@/components/situation/SituationMapSlot.vue'
import SituationNarrative from '@/components/situation/SituationNarrative.vue'
import SituationSkillToolbar from '@/components/situation/SituationSkillToolbar.vue'
import SituationSkillDrawer from '@/components/situation/SituationSkillDrawer.vue'
import SituationSkillParametersDialog from '@/components/situation/SituationSkillParametersDialog.vue'
import SituationSkillMarkdownDialog from '@/components/situation/SituationSkillMarkdownDialog.vue'
import { useSituationStore, type Viewport, type ReportMeta } from '@/stores/situation'
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

const router = useRouter()
const route = useRoute()
const store = useSituationStore()
const { exportPDF, exportImage } = useSituationExport()

// ── 页面状态 ──
const inputText = ref('')
const historySearch = ref('')
const chatAreaRef = ref<HTMLElement | null>(null)
const aiMsgRef = ref<HTMLElement | null>(null)
const showExecPanel = ref(false)
const execPanelWidth = ref(460)
const isResizing = ref(false)
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
const dataSourceDialogVisible = ref(false)
const generatePending = ref(false)
let recommendTimer: ReturnType<typeof setTimeout> | undefined
let recommendRequest = 0

// ── 执行面板拖拽缩放（与指标分析保持一致）──
function startResize(e: MouseEvent) {
  isResizing.value = true
  const startX = e.clientX
  const startWidth = execPanelWidth.value
  const onMouseMove = (ev: MouseEvent) => {
    if (!isResizing.value) return
    const delta = startX - ev.clientX
    execPanelWidth.value = Math.min(700, Math.max(300, startWidth + delta))
  }
  const onMouseUp = () => {
    isResizing.value = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// ── 数据源切换 ──
function onDataSourceChange(val: string) {
  store.setDataSource(val)
}

// 确认数据源选择（关闭对话框并提示）
function confirmDataSource() {
  dataSourceDialogVisible.value = false
  if (store.dataSourceId) ElMessage.success('数据源已更新')
}

const activeFullSkill = computed(() => (
  skills.value.find((skill) => skill.id === store.activeSkill?.id) || null
))

const inputPlaceholder = '输入军事态势分析需求，如：分析战斗机巡航覆盖范围、舰艇编队部署、雷达探测范围等态势...'

// 工具胶囊（与 Portal tools-row 一致，态势图 current）
// 四功能切换栏（共享配置，current 由当前路由自动推导）
const { tools, navigateToTool } = useToolNav()

// 推荐提问（军事题材）
const suggests = [
  { title: '战斗机巡航覆盖范围态势', desc: '巡航区域与作战覆盖分析', icon: MapLocation, color: '#8b5cf6' },
  { title: '舰艇编队部署态势', desc: '编队分布与活动规律', icon: TrendCharts, color: '#10b981' },
  { title: '雷达探测范围态势', desc: '探测覆盖与盲区分析', icon: PieChart, color: '#f59e0b' },
  { title: '综合战场态势', desc: '兵力+装备+态势融合', icon: DataAnalysis, color: '#3b82f6' }
]

const isEmpty = computed(() =>
  !store.query && !store.isGenerating && store.status === 'idle'
)

const filteredHistory = computed(() => {
  const kw = historySearch.value.trim().toLowerCase()
  if (!kw) return store.history
  return store.history.filter((h) =>
    (h.title || h.query || '').toLowerCase().includes(kw)
  )
})

// ── 生命周期 ──
onMounted(async () => {
  store.fetchHistory()
  void store.fetchDataSources()
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
        if (draft?.context?.autoGenerate && store.query) onGenerate(store.query)
      }
    } catch (e) {
      console.warn('草稿加载失败', e)
    }
  }
  const reportId = route.query.reportId as string
  if (reportId) await loadReportById(reportId)
})

// 生成时自动滚动到底部
watch(() => store.charts.length + store.mapLayers.length + store.executionSteps.length, async () => {
  await nextTick()
  if (chatAreaRef.value) chatAreaRef.value.scrollTop = chatAreaRef.value.scrollHeight
})

onUnmounted(() => {
  if (recommendTimer) clearTimeout(recommendTimer)
  store.closeStream()
})

// 输入变化时防抖刷新 Skill 智能推荐
watch(inputText, (value) => {
  if (recommendTimer) clearTimeout(recommendTimer)
  recommendTimer = setTimeout(() => void updateSkillRecommendations(value), 320)
})

watch(skills, (items) => {
  if (store.activeSkill?.id) {
    const fullSkill = items.find((skill) => skill.id === store.activeSkill?.id)
    if (fullSkill) store.setActiveSkill(fullSkill)
  }
  if (!inputText.value.trim()) {
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

// ── Skill 目录 / 偏好 ──
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
  if (question || !inputText.value.trim()) {
    inputText.value = question || skill.recommendedQuestions[0] || ''
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

// ── 交互 ──
async function onGenerate(q?: string) {
  if (generatePending.value || store.isGenerating || store.requestPending) return
  const text = (typeof q === 'string' ? q : inputText.value) || ''
  if (!text.trim()) {
    ElMessage.warning('请输入问题')
    return
  }
  // 发送后立即清空输入框，避免问题残留；pending 状态驱动按钮 loading
  inputText.value = ''
  generatePending.value = true
  try {
    // 已启用 Skill 时先执行前检查（preflight）
    if (activeFullSkill.value) {
      const preflight = await preflightSituationSkill(
        activeFullSkill.value.id,
        text,
        store.skillParameters,
        store.dataSourceId,
      )
      if (!preflight.ready) {
        inputText.value = text
        ElMessage.error(preflight.errors.join('；') || 'Skill 执行前检查未通过')
        return
      }
      store.setSkillParameters(preflight.parameters)
      if (preflight.warnings.length) {
        ElMessage.warning(`执行前检查通过：${preflight.warnings[0]}`)
      }
    }
    // 用户提问后展示系统执行过程面板（与指标分析保持一致）
    showExecPanel.value = true
    const started = await store.generate(text)
    if (started) {
      void store.fetchHistory()
      void loadSkillPreferences()
    }
  } catch (e: any) {
    inputText.value = text
    ElMessage.error('生成失败：' + (e?.serverMessage || e?.message || '未知错误'))
  } finally {
    generatePending.value = false
  }
}

async function onStop() {
  await store.cancelGeneration()
  ElMessage.info('已取消本次生成')
}

function onNewSession() {
  store.reset()
  inputText.value = ''
  showExecPanel.value = false
}

async function onPickHistory(item: ReportMeta) {
  await loadReportById(item.reportId)
}

async function loadReportById(rid: string) {
  try {
    const resp: any = await api.get(`/situation/reports/${rid}`)
    if (resp?.success !== false) {
      store.loadReport(resp.data || resp)
    }
  } catch (e) {
    console.warn('产物加载失败', e)
  }
}

function onSuggest(s: string) {
  onGenerate(s)
}

function openView() {
  if (store.reportId) router.push(`/situation/view/${store.reportId}`)
}

function go(path: string) {
  router.push(path)
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
  if (format === 'pdf') exportPDF('.ai-response', name)
  else exportImage('.ai-response', name)
}

function copyShare() {
  navigator.clipboard.writeText(shareUrl.value).then(() => ElMessage.success('已复制'))
}

// ── 地图联动回调 ──
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

// ── 辅助 ──
function stepStatusClass(s: string) {
  if (s === 'completed') return 'completed'
  if (s === 'error') return 'error'
  return 'in-progress'
}
function formatTime(t?: string): string {
  if (!t) return ''
  const d = new Date(t)
  if (isNaN(d.getTime())) return t
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

async function deleteHistory(targetId: string) {
  try {
    await store.deleteHistory(targetId)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.serverMessage || e?.message || ''))
  }
}
</script>

<style scoped>
.situation-container {
  display: flex;
  height: 100%;
  background: transparent;
}

/* ── 侧边栏（对齐指标分析）── */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  padding: 16px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.sidebar-section { display: flex; flex-direction: column; gap: 8px; margin-bottom: 0; }
.sidebar-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 0; padding: 0 8px; }
.sidebar-title { font-size: 12px; font-weight: 600; color: var(--text-muted); letter-spacing: 0.5px; margin-bottom: 0; }
.new-session-btn { height: 32px !important; font-size: 13px !important; font-weight: 500 !important; padding: 0 12px !important; border-radius: 8px !important; }
.nav-item { display: flex; align-items: center; gap: 10px; padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: all 0.2s; color: var(--text-secondary); font-size: 14px; font-weight: 500; }
.nav-item:hover { background: rgba(0, 0, 0, 0.04); color: var(--text-primary); }
.history-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; max-height: none; }
.history-item { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-radius: 8px; cursor: pointer; transition: all 0.2s; color: var(--text-secondary); }
.history-item:hover { background: rgba(0, 0, 0, 0.04); color: var(--text-primary); }
.history-item.active { background: rgba(139, 92, 246, 0.08); color: #6d28d9; border: none; }
.history-item-main { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.history-item .el-icon { font-size: 16px; flex-shrink: 0; color: var(--text-muted); }
.history-item.active .el-icon { color: #8b5cf6; }
.history-delete-btn { opacity: 0; transition: opacity 0.2s; flex-shrink: 0; }
.history-item:hover .history-delete-btn { opacity: 1; }
.history-item-content { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.history-item-title { font-size: 13px; font-weight: 500; color: inherit; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.history-item-time { font-size: 11px; color: var(--text-muted); }
.history-search { margin-top: 4px; }
.history-search :deep(.el-input__wrapper) { border-radius: 8px; box-shadow: 0 0 0 1px var(--border-normal) inset; background: var(--bg-card); }

/* ── 主内容区 ── */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--bg-card);
  border-left: 1px solid var(--border-light);
}

/* ── 执行步骤流（对齐指标分析 skill-plan-bar）── */
.skill-plan-bar {
  display: flex;
  align-items: center;
  gap: 18px;
  padding: 10px 24px;
  background: linear-gradient(90deg, rgba(139, 92, 246, 0.06), rgba(109, 40, 217, 0.04));
  border-top: 1px solid rgba(139, 92, 246, 0.08);
  border-bottom: 1px solid rgba(139, 92, 246, 0.12);
  flex-shrink: 0;
  overflow: hidden;
}
.skill-plan-title {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #6d28d9;
  white-space: nowrap;
  font-size: 13px;
}
.skill-plan-title .el-icon { color: #8b5cf6; }
.skill-plan-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  overflow-x: auto;
  padding-bottom: 2px;
}
.skill-markdown-button {
  margin-left: auto;
  flex-shrink: 0;
}
.skill-plan-step {
  padding: 4px 8px;
  border-radius: 999px;
  background: white;
  border: 1px solid rgba(139, 92, 246, 0.18);
  color: var(--text-secondary);
  font-size: 12px;
  white-space: nowrap;
}
.skill-plan-step.output {
  color: #6d28d9;
  border-color: rgba(109, 40, 217, 0.25);
}
.skill-plan-arrow {
  color: var(--text-muted);
  font-size: 12px;
  flex-shrink: 0;
}

/* 数据源标签（插槽内容，对齐指标分析 label 样式） */
.label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
  white-space: nowrap;
}

/* ── 数据源配置对话框（对齐指标分析）── */
.data-source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
}
.ds-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.ds-item:hover {
  border-color: #a78bfa;
  background: #faf5ff;
}
.ds-item.active {
  border-color: #8b5cf6;
  background: #faf5ff;
}
.ds-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ds-item-content {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ds-item-name {
  font-size: 14px;
  font-weight: 500;
  color: var(--text-primary);
}
.ds-item-meta {
  display: flex;
  align-items: center;
  gap: 6px;
}
.ds-item-check {
  color: #8b5cf6;
}

/* ── 内容区（左侧对话 + 右侧面板）── */
.content-area {
  flex: 1;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  min-height: 0;
}

/* ── 对话面板 ── */
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 40px 0 20px;
  background: transparent;
  border: none;
  border-radius: 0;
  box-shadow: none;
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 80px;
  height: 100%;
  color: var(--text-muted);
  gap: 0;
}
.empty-state p { margin: 0; font-size: 18px; font-weight: 600; color: var(--text-primary); }
.tags-section { margin-top: 24px; width: 100%; max-width: 800px; padding: 0 40px; }
.suggest-cards { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.suggest-card {
  display: flex; align-items: center; gap: 12px; padding: 14px 16px;
  background: var(--gray-50); border: 1px solid var(--border-light); border-radius: 12px;
  cursor: pointer; transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1); position: relative; overflow: hidden;
}
.suggest-card::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px; background: var(--card-color); opacity: 0; transition: opacity 0.2s; }
.suggest-card:hover { background: white; border-color: color-mix(in srgb, var(--card-color) 30%, white); transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06); }
.suggest-card:hover::before { opacity: 1; }
.suggest-icon { flex-shrink: 0; width: 40px; height: 40px; border-radius: 10px; display: flex; align-items: center; justify-content: center; background: color-mix(in srgb, var(--card-color) 12%, white); color: var(--card-color); transition: all 0.2s; }
.suggest-card:hover .suggest-icon { background: var(--card-color); color: white; transform: scale(1.05); }
.suggest-content { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
.suggest-title { font-size: 14px; font-weight: 600; color: var(--text-primary); line-height: 1.4; transition: color 0.2s; }
.suggest-card:hover .suggest-title { color: var(--card-color); }
.suggest-desc { font-size: 12px; color: var(--text-muted); line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.suggest-arrow { flex-shrink: 0; font-size: 14px; color: var(--text-muted); opacity: 0; transform: translateX(-4px); transition: all 0.2s; }
.suggest-card:hover .suggest-arrow { opacity: 1; transform: translateX(0); color: var(--card-color); }

/* ── 消息列表 ── */
.message-list { display: flex; flex-direction: column; gap: 28px; max-width: 900px; margin: 0 auto; padding: 0 40px; }
.message { display: flex; gap: 16px; }
.message.user { flex-direction: row-reverse; }
.message-content { max-width: 85%; display: flex; flex-direction: column; gap: 8px; }
.message.user .message-content { align-items: flex-end; }
.message-avatar { flex-shrink: 0; padding-top: 2px; }
.message-avatar .ai-avatar { background: linear-gradient(135deg, #8b5cf6, #6d28d9); color: #fff; }
.message-text { padding: 14px 18px; border-radius: 16px; line-height: 1.75; font-size: 15px; white-space: pre-wrap; word-wrap: break-word; }
.message.user .message-text { background: linear-gradient(135deg, #4f8cff 0%, #3b82f6 100%); color: white; border-bottom-right-radius: 4px; }
.message.assistant .message-text { background: transparent; color: var(--text-primary); padding: 0; border-radius: 0; border: none; }
.message-loading { color: var(--text-muted); font-size: 14px; padding: 8px 0; display: flex; align-items: center; gap: 8px; }

/* ── AI 响应 ── */
.ai-response { display: flex; flex-direction: column; gap: 1rem; width: 100%; }
.tree-section, .references-section { padding: 1rem 1.5rem; background: white; border: 1px solid #e2e8f0; border-radius: 0.75rem; }
.data-section { padding: 1rem 1.5rem; background: white; border: 1px solid #e2e8f0; border-radius: 0.75rem; }
.ai-map-section { padding: 0; overflow: hidden; height: 460px; }
.ai-map-section :deep(.map-container) { height: 100%; }

/* ── 操作按钮 ── */
.confirm-actions {
  display: flex;
  gap: 12px;
  margin-top: 4px;
  padding-top: 12px;
  border-top: 1px dashed #e2e8f0;
}
.confirm-actions .el-button {
  flex: 1;
  height: 44px;
  font-size: 15px;
  font-weight: 500;
  border-radius: 10px;
  transition: all 0.2s;
}
.confirm-actions .el-button .el-icon { margin-right: 4px; }

/* ── 执行面板（右侧）── */
.execution-panel {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
  background: #fafbfc;
  position: relative;
  overflow: hidden;
}

.resize-handle {
  position: absolute;
  top: 0;
  left: -4px;
  width: 8px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
  background: transparent;
  transition: background 0.15s;
}
.resize-handle:hover, .resize-handle:active { background: rgba(64, 158, 255, 0.35); }

.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #e2e8f0; background: white;
  font-size: 14px; font-weight: 600; color: #374151; flex-shrink: 0;
}
.panel-title-wrap { display: flex; align-items: center; gap: 8px; min-width: 0; }
.panel-close { cursor: pointer; color: #9ca3af; font-size: 16px; }
.panel-close:hover { color: #374151; }
.execution-progress {
  padding: 10px 14px;
  background: #fff;
  border-bottom: 1px solid #eef2f7;
}
.execution-progress-meta {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  color: #64748b;
  font-size: 11px;
}
.execution-content { flex: 1; overflow-y: auto; padding: 8px; }
.panel-section {
  background: white; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;
}
.section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; cursor: default; user-select: none;
  background: #f8fafc;
}
.section-header h5 { margin: 0; font-size: 13px; font-weight: 600; color: #475569; }

/* 面板中的步骤 */
.steps-list { display: flex; flex-direction: column; gap: 2px; padding: 8px 12px; }
.inline-step { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; font-size: 13px; display: flex; flex-direction: column; gap: 4px; word-break: break-word; overflow-wrap: break-word; }
.inline-step:last-child { border-bottom: none; }
.inline-step-header { display: flex; align-items: flex-start; gap: 8px; }
.inline-step-icon { display: flex; align-items: center; flex-shrink: 0; margin-top: 1px; }
.inline-step-title { font-weight: 500; color: #1f2937; flex: 1; min-width: 0; }
.inline-step-detail { color: #6b7280; font-size: 12px; padding-left: 24px; }
.inline-step.in-progress .inline-step-icon { color: #8b5cf6; animation: rotating 2s linear infinite; }
.inline-step.completed .inline-step-icon { color: #67c23a; }
.inline-step.error .inline-step-icon { color: #f56c6c; }
@keyframes rotating { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* ── 折叠切换按钮 ── */
.execution-panel-toggle {
  flex-shrink: 0;
  width: 32px;
  background: #fafafa;
  border-left: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: background 0.2s, color 0.2s;
  color: #9ca3af;
}
.execution-panel-toggle .el-icon { writing-mode: horizontal-tb; font-size: 16px; }
.execution-panel-toggle .toggle-text { writing-mode: vertical-rl; font-size: 13px; letter-spacing: 2px; user-select: none; }
.execution-panel-toggle:hover { background: #f5f3ff; color: #8b5cf6; }

/* ── 输入区域 ── */
.input-area {
  flex-shrink: 0;
  padding: 16px 40px 24px;
  background: linear-gradient(to top, var(--bg-card) 60%, transparent);
  border: none; border-radius: 0; box-shadow: none;
  display: flex; flex-direction: column; gap: 0;
}
.tools-bar { display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin-bottom: 14px; }
.tools-bar .tool-item { display: flex; align-items: center; gap: 6px; padding: 6px 14px; background: var(--gray-50); border-radius: 20px; cursor: pointer; transition: all 0.2s; border: 1px solid var(--border-light); }
.tools-bar .tool-item:hover { background: white; border-color: #c4b5fd; box-shadow: 0 2px 8px rgba(139, 92, 246, 0.1); }
.tools-bar .tool-item.current { background: #8b5cf6; border-color: #8b5cf6; cursor: default; }
.tools-bar .tool-icon { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: inherit; }
.tools-bar .tool-item.current .tool-icon { background: transparent; }
.tools-bar .tool-name { font-size: 13px; font-weight: 500; color: var(--text-secondary); }
.tools-bar .tool-item.current .tool-name { color: white; }
.tools-bar .tool-item:hover .tool-name { color: #6d28d9; }
.tools-bar .tool-item.current:hover .tool-name { color: white; }

.input-wrapper { position: relative; max-width: 1000px; margin: 0 auto; width: 100%; }
.input-wrapper :deep(.el-textarea__inner) { border-radius: 16px !important; border-color: var(--border-normal) !important; padding: 16px 100px 16px 20px !important; font-size: 15px !important; line-height: 1.6 !important; transition: all 0.2s !important; background: var(--gray-50) !important; resize: none; }
.input-wrapper :deep(.el-textarea__inner:hover) { border-color: #a78bfa !important; background: white !important; }
.input-wrapper :deep(.el-textarea__inner:focus) { border-color: #8b5cf6 !important; background: white !important; box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.1) !important; }
.input-actions { position: absolute; bottom: 14px; right: 16px; display: flex; gap: 8px; justify-content: flex-end; align-items: center; }
.input-actions .el-button { height: 38px; padding: 0 22px; border-radius: 10px; font-weight: 500; font-size: 14px; }

/* ── 通用 ── */
.rotating { animation: rotating 1.2s linear infinite; }
.custom-scroll::-webkit-scrollbar { width: 6px; }
.custom-scroll::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.15); border-radius: 3px; }
.custom-scroll::-webkit-scrollbar-track { background: transparent; }
</style>
