<template>
  <Layout>
    <div class="indicator-container">
      <div class="sidebar">
        <div class="sidebar-section">
          <div class="sidebar-section-header">
            <h3 class="sidebar-title">导航</h3>
            <el-button class="new-session-btn" type="primary" @click="newSession">
              <el-icon><Plus /></el-icon> 新会话
            </el-button>
          </div>
          <div class="nav-item" @click="goTo('/knowledge')">
            <el-icon><Collection /></el-icon>
            <span>知识库</span>
          </div>
          <div class="nav-item" @click="goTo('/ontology')">
            <el-icon><Box /></el-icon>
            <span>本体模型</span>
          </div>
        </div>
        <div class="sidebar-section">
          <h3 class="sidebar-title">历史记录</h3>
          <div class="history-list custom-scroll">
            <div
              v-for="item in filteredHistoryList"
              :key="item.id"
              :class="['history-item', { active: item.id === sessionId }]"
            >
              <div class="history-item-main" @click="loadHistory(item)">
                <el-icon><PieChart /></el-icon>
                <div class="history-item-content">
                  <span class="history-item-title">{{ item.title }}</span>
                  <span class="history-item-time">{{ item.time }}</span>
                </div>
              </div>
              <el-button class="history-delete-btn" size="small" text type="danger" @click.stop="deleteHistory(item.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
          <div class="search-bar history-search">
            <el-input
              v-model="searchQuery"
              placeholder="搜索历史记录..."
              :prefix-icon="Search"
              clearable
            />
          </div>
        </div>
      </div>

      <div class="main-content">
        <!-- 顶部数据源选择 -->
        <div class="top-bar">
          <div class="data-source-selector">
            <span class="label">数据源：</span>
            <el-select v-model="selectedDataSourceId" placeholder="选择数据源" size="small" style="width: 200px" @change="onDataSourceChange">
              <el-option
                v-for="ds in dataSources"
                :key="ds.id"
                :label="ds.name"
                :value="ds.id"
              />
            </el-select>
            <el-button size="small" type="primary" @click="showDataSourceDialog">
              <el-icon><Setting /></el-icon>
              配置
            </el-button>
          </div>
        </div>

        <div class="content-area">
          <!-- 左侧：对话区 -->
          <div class="chat-panel">
            <div class="chat-area custom-scroll" ref="chatArea">
              <div v-if="messages.length === 0" class="empty-state">
                <div class="tags-section">
                  <div class="suggest-cards">
                    <div
                      v-for="(item, index) in allIndicators"
                      :key="index"
                      class="suggest-card"
                      :style="{ '--card-color': item.color }"
                      @click="selectIndicator(item.text)"
                    >
                      <div class="suggest-icon">
                        <el-icon :size="20">
                          <component :is="item.icon" />
                        </el-icon>
                      </div>
                      <div class="suggest-content">
                        <div class="suggest-title">{{ item.text }}</div>
                        <div class="suggest-desc">{{ item.desc }}</div>
                      </div>
                      <el-icon class="suggest-arrow"><ArrowRight /></el-icon>
                    </div>
                  </div>
                </div>
              </div>
              <div v-else class="message-list">
                <div
                  v-for="(msg, index) in messages"
                  :key="index"
                  :class="['message', msg.role]"
                >
                  <div class="message-avatar">
                    <el-avatar :size="40">
                      {{ msg.role === 'user' ? '我' : 'AI' }}
                    </el-avatar>
                  </div>
                  <div class="message-content">
                    <!-- 用户消息 -->
                    <div v-if="msg.role === 'user'" class="message-text">
                      {{ msg.content }}
                    </div>

                    <!-- AI消息 -->
                    <div v-else class="ai-response">
                      <!-- 文本回答 -->
                      <div v-if="msg.content" class="message-text">{{ msg.content }}</div>
                      <div v-if="msg.querying && !msg.rawResults && (!msg.indicators || msg.indicators.length === 0)" class="message-loading">分析中...</div>

                      <!-- 指标树状结构 -->
                      <div v-if="msg.tree" class="tree-section">
                        <div class="section-collapse-header" @click="toggleMsgSection(msg, 'treeCollapsed')">
                          <h5>指标树状结构</h5>
                          <el-icon :class="{ rotated: !msg.treeCollapsed }"><ArrowDown /></el-icon>
                        </div>
                        <div v-show="!msg.treeCollapsed" :ref="el => setTreeChartRef(el, index)" class="tree-chart"></div>
                      </div>

                      <!-- 指标卡片列表 -->
                      <div v-if="msg.indicators && msg.indicators.length > 0" class="indicators-section">
                        <div class="section-collapse-header" @click="toggleMsgSection(msg, 'indicatorsCollapsed')">
                          <h5>指标计算方式（{{ msg.indicators.length }} 个）</h5>
                          <el-icon :class="{ rotated: !msg.indicatorsCollapsed }"><ArrowDown /></el-icon>
                        </div>
                        <div v-show="!msg.indicatorsCollapsed" class="indicator-list">
                          <div v-for="(ind, idx) in (msg.indicatorsExpanded ? msg.indicators : msg.indicators.slice(0, 5))" :key="idx" class="indicator-card">
                            <div class="indicator-header">
                              <span class="indicator-name">{{ ind.name }}</span>
                              <el-tag :type="ind.type === 'admin-db' ? 'success' : ind.type === 'knowledge' ? 'primary' : 'info'" size="small">
                                {{ ind.type === 'admin-db' ? '已配置' : ind.type === 'knowledge' ? '知识库' : 'AI生成' }}
                              </el-tag>
                            </div>
                            <div class="indicator-body">
                              <div v-if="ind.definition" class="indicator-definition">
                                <strong>定义：</strong>{{ ind.definition }}
                              </div>
                              <div v-if="ind.formula" class="indicator-formula">
                                <strong>公式：</strong>{{ ind.formula }}
                              </div>
                              <div v-if="ind.criteria" class="indicator-criteria">
                                <strong>标准：</strong>{{ ind.criteria }}
                              </div>
                              <div v-if="ind.weight" class="indicator-weight">
                                <strong>权重：</strong>{{ ind.weight }}
                              </div>
                            </div>
                          </div>
                          <div v-if="msg.indicators.length > 5 && !msg.indicatorsExpanded" class="expand-tip" @click="msg.indicatorsExpanded = true">
                            展开全部 {{ msg.indicators.length }} 个指标
                          </div>
                          <div v-if="msg.indicators.length > 5 && msg.indicatorsExpanded" class="expand-tip" @click="msg.indicatorsExpanded = false">
                            收起
                          </div>
                        </div>
                      </div>

                      <!-- 参考来源 -->
                      <div v-if="msg.references && msg.references.length > 0" class="references-section">
                        <h5>参考来源</h5>
                        <ul>
                          <li v-for="(ref, idx) in msg.references" :key="idx">{{ ref }}</li>
                        </ul>
                      </div>

                      <!-- 查询结果数据表 -->
                      <div v-if="msg.rawResults && msg.rawResults.length > 0" class="data-section">
                        <div class="section-collapse-header" @click="toggleMsgSection(msg, 'dataCollapsed')">
                          <h5>查询结果（共 {{ msg.rawResults.length }} 行）</h5>
                          <el-icon :class="{ rotated: !msg.dataCollapsed }"><ArrowDown /></el-icon>
                        </div>
                        <div v-show="!msg.dataCollapsed" class="data-table-wrapper">
                          <el-table
                            :data="msg.dataExpanded ? msg.rawResults : msg.rawResults.slice(0, 5)"
                            size="small"
                            border
                            stripe
                            max-height="350"
                          >
                            <el-table-column
                              v-for="(col, ci) in Object.keys(msg.rawResults[0])"
                              :key="ci"
                              :prop="col"
                              :label="col"
                              min-width="120"
                              show-overflow-tooltip
                            />
                          </el-table>
                          <div v-if="msg.rawResults.length > 5 && !msg.dataExpanded" class="expand-tip" @click="msg.dataExpanded = true">
                            展开全部 {{ msg.rawResults.length }} 行
                          </div>
                          <div v-if="msg.rawResults.length > 5 && msg.dataExpanded" class="expand-tip" @click="msg.dataExpanded = false">
                            收起至前 5 行
                          </div>
                        </div>
                      </div>

                      <!-- 追问快捷操作按钮 -->
                      <div v-if="msg.confirmActions" class="confirm-actions">
                        <el-button type="primary" size="large" @click="quickConfirm('查询')">
                          <el-icon><CircleCheck /></el-icon> 查询指标
                        </el-button>
                        <el-button size="large" @click="quickConfirm('不查询')">
                          暂不需要
                        </el-button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- 右侧：系统执行过程面板 -->
          <div v-if="showExecutionPanel" class="execution-panel" :style="{ width: executionPanelWidth + 'px' }">
            <div class="resize-handle" @mousedown="startResize"></div>
            <div class="panel-header">
              <div class="panel-title-wrap">
                <span>系统执行过程</span>
                <el-tag v-if="panelState.activeSkillName" size="small" effect="plain">{{ panelState.activeSkillName }}</el-tag>
              </div>
              <el-icon class="panel-close" @click="showExecutionPanel = false" title="收起"><Close /></el-icon>
            </div>
            <div v-if="executionSteps.length" class="execution-progress">
              <div class="execution-progress-meta">
                <span>{{ completedExecutionCount }}/{{ executionSteps.length }} 个节点已完成</span>
                <span>{{ executionProgress }}%</span>
              </div>
              <el-progress :percentage="executionProgress" :show-text="false" :stroke-width="5" />
            </div>
            <div class="execution-content custom-scroll">
              <div v-if="executionSteps.length === 0" class="panel-empty">
                <el-icon :size="32" color="#c0c4cc"><Cpu /></el-icon>
                <p>暂无执行步骤</p>
              </div>

              <!-- 执行步骤列表（平铺，仿评估分析风格） -->
              <div v-if="executionSteps.length > 0" class="steps-list">
                <div
                  v-for="(step, index) in executionSteps"
                  :key="step.phase + '_' + step.step + '_' + step.description"
                  :class="['inline-step', getStepStatusClass(step.status)]"
                >
                  <div class="inline-step-header">
                    <span class="inline-step-icon">
                      <el-icon v-if="step.status === 'completed'"><CircleCheck /></el-icon>
                      <el-icon v-else-if="step.status === 'in_progress'"><Loading /></el-icon>
                      <el-icon v-else-if="step.status === 'error'"><CircleClose /></el-icon>
                      <el-icon v-else><Clock /></el-icon>
                    </span>
                    <span class="inline-step-title">{{ step.phase === 'indicator_gen' ? `阶段1 · 步骤 ${index + 1}: ${step.description}` : step.phase === 'data_query' ? `阶段2 · 步骤 ${index + 1}: ${step.description}` : step.phase === 'dataset' ? `Skill ${step.sequence}/${step.total} · ${step.description}` : `步骤 ${index + 1}: ${step.description}` }}</span>
                  </div>
                  <div v-if="step.phase === 'dataset'" class="inline-step-meta">
                    <el-tag size="small" effect="plain">数据集 {{ step.sequence }}/{{ step.total }}</el-tag>
                    <span v-if="step.datasetName">{{ step.datasetName }}</span>
                    <span v-if="step.durationMs">{{ formatDuration(step.durationMs) }}</span>
                  </div>
                  <div v-if="step.detail" class="inline-step-detail">{{ step.detail }}</div>
                  <details v-if="step.thinking" class="inline-step-thinking">
                    <summary>查看执行详情</summary>
                    <pre>{{ step.thinking }}</pre>
                  </details>
                </div>
              </div>

              <!-- 指标体系（Phase 1 生成，默认折叠） -->
              <div v-if="panelState.indicators && panelState.indicators.length > 0" class="panel-section">
                <div class="section-header" @click="togglePanel('indicators')">
                  <h5>指标体系（{{ panelState.indicators.length }} 个）</h5>
                  <el-icon :class="{ rotated: !panelState.sections.indicators }"><ArrowDown /></el-icon>
                </div>
                <div v-show="!panelState.sections.indicators">
                  <div class="panel-data-wrapper">
                    <table class="data-table panel-indicator-table">
                      <thead>
                        <tr>
                          <th style="width:22%">名称</th>
                          <th style="width:12%">类型</th>
                          <th style="width:30%">定义</th>
                          <th style="width:36%">公式</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(ind, idx) in panelState.indicators" :key="idx">
                          <td>{{ ind.name }}</td>
                          <td><el-tag :type="ind.type === 'admin-db' ? 'success' : ind.type === 'knowledge' ? 'primary' : 'info'" size="small">{{ ind.type || 'llm' }}</el-tag></td>
                          <td>{{ ind.definition || '-' }}</td>
                          <td><code v-if="ind.formula" class="panel-formula">{{ ind.formula }}</code><span v-else>-</span></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>

              <!-- SQL 代码（默认折叠，已存在于步骤 thinking 中，作为冗余保留） -->
              <div v-if="panelState.generatedSql" class="panel-section">
                <div class="section-header" @click="togglePanel('sql')">
                  <h5>生成的 SQL</h5>
                  <el-icon :class="{ rotated: !panelState.sections.sql }"><ArrowDown /></el-icon>
                </div>
                <div v-show="!panelState.sections.sql">
                  <pre class="sql-block">{{ panelState.generatedSql }}</pre>
                </div>
              </div>

              <!-- 原始数据（默认折叠） -->
              <div v-if="panelState.rawResults && panelState.rawResults.length > 0" class="panel-section">
                <div class="section-header" @click="togglePanel('data')">
                  <h5>原始查询结果（{{ panelState.rawResults.length }} 行）</h5>
                  <el-icon :class="{ rotated: !panelState.sections.data }"><ArrowDown /></el-icon>
                </div>
                <div v-show="!panelState.sections.data">
                  <div class="panel-data-wrapper">
                    <table class="data-table">
                      <thead>
                        <tr>
                          <th v-for="(col, ci) in Object.keys(panelState.rawResults[0])" :key="ci">{{ col }}</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr v-for="(row, ri) in panelState.rawResults.slice(0, 20)" :key="ri">
                          <td v-for="(col, ci) in Object.keys(row)" :key="ci">{{ row[col] }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else-if="hasExecutionData" class="execution-panel-toggle" @click="showExecutionPanel = true" title="展开系统执行过程">
            <el-icon><ArrowRight /></el-icon>
            <span class="toggle-text">执行过程</span>
          </div>
        </div>

        <!-- 底部输入区 -->
        <div class="input-area">
          <div class="input-wrapper">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="3"
              placeholder="输入指标需求，如：帮我分析火力打击任务完成度指标..."
              @keyup.enter.ctrl="analyzeIndicator"
            />
            <div class="input-actions">
              <el-tooltip :content="isListening ? '停止录音' : '语音输入'" placement="top">
                <el-button
                  circle
                  :type="isListening ? 'danger' : 'default'"
                  :icon="Microphone"
                  @click="toggleSpeech"
                />
              </el-tooltip>
              <el-button v-if="analyzing" type="danger" plain @click="stopAnalysis">
                <el-icon><CircleClose /></el-icon>
                取消运行
              </el-button>
              <el-button v-else type="primary" @click="analyzeIndicator">
                <el-icon><Promotion /></el-icon>
                分析指标
              </el-button>
            </div>
          </div>

          <div class="tools-bar">
            <div
              v-for="tool in tools"
              :key="tool.id"
              :class="['tool-item', { 'current': tool.current }]"
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
    </div>

    <!-- 数据源配置对话框 -->
    <el-dialog v-model="dataSourceDialogVisible" title="数据源配置" width="600px">
      <div class="data-source-list">
        <div
          v-for="ds in dataSources"
          :key="ds.id"
          :class="['ds-item', { active: ds.id === selectedDataSourceId }]"
          @click="selectDataSource(ds)"
        >
          <div class="ds-name">{{ ds.name }}</div>
          <div class="ds-meta">
            <el-tag size="small">{{ ds.type }}</el-tag>
            <el-tag :type="ds.status === 'available' ? 'success' : 'info'" size="small">
              {{ ds.status === 'available' ? '可用' : '不可用' }}
            </el-tag>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="dataSourceDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmDataSource">确定</el-button>
      </template>
    </el-dialog>
  </Layout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick, watch } from 'vue'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { useRouter } from 'vue-router'
import { Search, Collection, Box, PieChart, ChatDotRound, Document, Plus, Delete, ArrowRight, ArrowDown, Microphone, CircleCheck, CircleClose, Loading, Clock, Close, Cpu, Promotion, Setting } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const router = useRouter()

// ── 数据源 ──
const dataSources = ref<Array<any>>([])
const selectedDataSourceId = ref<string | null>(null)
const selectedDataSourceName = ref<string>('')
const dataSourceDialogVisible = ref(false)

const selectDataSource = (ds: any) => {
  selectedDataSourceId.value = ds.id
  selectedDataSourceName.value = ds.name || ''
}
const onDataSourceChange = (val: string) => {
  const found = dataSources.value.find((ds: any) => ds.id === val)
  selectedDataSourceName.value = found?.name || ''
}
const confirmDataSource = () => {
  dataSourceDialogVisible.value = false
  ElMessage.success('数据源已更新')
}
const showDataSourceDialog = () => {
  dataSourceDialogVisible.value = true
}

const { isListening, isSupported: speechSupported, start: startSpeech, stop: stopSpeech } = useSpeechRecognition()

const toggleSpeech = () => {
  if (isListening.value) {
    const text = stopSpeech()
    if (text.trim()) inputMessage.value = (inputMessage.value + ' ' + text).trim()
  } else {
    if (!speechSupported.value) {
      ElMessage.warning('当前浏览器不支持语音识别，请使用 Chrome 或 Edge')
      return
    }
    startSpeech()
  }
}

const tools = [
  { id: 1, name: '智能问答', icon: ChatDotRound, color: '#409eff', path: '/qa', current: false },
  { id: 2, name: '指标分析', icon: PieChart, color: '#67c23a', path: '/indicator', current: true },
  { id: 3, name: '评估分析', icon: Document, color: '#e6a23c', path: '/evaluation', current: false }
]

const navigateToTool = (path: string) => { router.push(path) }

// ── localStorage 持久化 ──
const LS_SESSION_ID = 'indicator_session_id'
const LS_HISTORY_LIST = 'indicator_history_list'
const LS_SESSION_MSGS = 'indicator_session_msgs'
const LS_SESSION_EXEC = 'indicator_session_exec'

const inputMessage = ref('')
const analyzing = ref(false)
const messages = ref<Array<any>>([])
const historyList = ref<Array<any>>(JSON.parse(localStorage.getItem(LS_HISTORY_LIST) || '[]'))
const sessionMessages = ref<Record<string, Array<any>>>(JSON.parse(localStorage.getItem(LS_SESSION_MSGS) || '{}'))
const sessionId = ref(localStorage.getItem(LS_SESSION_ID) || '')
const searchQuery = ref('')
const chatArea = ref<HTMLElement | null>(null)
const treeChartRefs = ref<HTMLElement[]>([])
let activeAbortController: AbortController | null = null
let cancelRequested = false

// ── 右侧执行面板状态 ──
const showExecutionPanel = ref(false)
const executionPanelWidth = ref(460)
const executionSteps = ref<Array<any>>([])
const completedExecutionCount = computed(() =>
  executionSteps.value.filter(step => step.status === 'completed').length
)
const executionProgress = computed(() => {
  if (!executionSteps.value.length) return 0
  const explicitProgress = executionSteps.value
    .map(step => Number(step.progress) || 0)
    .filter(progress => progress > 0)
  if (explicitProgress.length) return Math.min(100, Math.max(...explicitProgress))
  return Math.round((completedExecutionCount.value / executionSteps.value.length) * 100)
})
const panelState = ref({
  generatedSql: '',
  rawResults: null as any[] | null,
  indicators: null as any[] | null,
  activeSkillName: '',
  sections: {
    steps: false,  // collapsed=false 表示展开
    indicators: true,  // collapsed=true 表示折叠
    sql: true,
    data: true
  }
})

const hasExecutionData = computed(() => {
  return executionSteps.value.length > 0 ||
    !!panelState.value.generatedSql ||
    (panelState.value.rawResults && panelState.value.rawResults.length > 0) ||
    (panelState.value.indicators && panelState.value.indicators.length > 0)
})

const togglePanel = (section: 'steps' | 'indicators' | 'sql' | 'data') => {
  panelState.value.sections[section] = !panelState.value.sections[section]
}

const toggleMsgSection = (msg: any, field: string) => {
  msg[field] = !msg[field]
}

const getStepStatusClass = (status: string) => {
  if (status === 'completed') return 'completed'
  if (status === 'in_progress') return 'in_progress'
  if (status === 'error') return 'error'
  return 'pending'
}

const formatDuration = (durationMs: number) => {
  if (!durationMs) return ''
  if (durationMs < 1000) return `${durationMs} ms`
  return `${(durationMs / 1000).toFixed(durationMs < 10000 ? 1 : 0)} 秒`
}

// ── 面板拖拽缩放 ──
const isResizing = ref(false)
const startResize = (e: MouseEvent) => {
  isResizing.value = true
  const startX = e.clientX
  const startWidth = executionPanelWidth.value
  const onMouseMove = (ev: MouseEvent) => {
    if (!isResizing.value) return
    const delta = startX - ev.clientX
    executionPanelWidth.value = Math.min(700, Math.max(300, startWidth + delta))
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

const persistState = () => {
  localStorage.setItem(LS_SESSION_ID, sessionId.value)
  localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
  localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
  // 持久化右侧执行面板状态
  if (sessionId.value && hasExecutionData.value) {
    const execMap = JSON.parse(localStorage.getItem(LS_SESSION_EXEC) || '{}')
    execMap[sessionId.value] = {
      steps: executionSteps.value,
      generatedSql: panelState.value.generatedSql,
      rawResults: panelState.value.rawResults,
      indicators: panelState.value.indicators,
      sections: panelState.value.sections
    }
    localStorage.setItem(LS_SESSION_EXEC, JSON.stringify(execMap))
  }
}

const recommendedIndicators = [
  { text: '作战效能', desc: '综合作战效能指标体系分析', icon: 'Aim', color: '#3b82f6' },
  { text: '打击能力', desc: '装备打击能力评估指标', icon: 'Guide', color: '#ef4444' },
  { text: '生存能力', desc: '战场生存能力评估维度', icon: 'Shield', color: '#8b5cf6' },
  { text: '保障能力', desc: '后勤保障能力评估体系', icon: 'Box', color: '#06b6d4' }
]

const hotIndicators = [
  { text: '任务完成度', desc: '作战任务完成情况分析', icon: 'CircleCheck', color: '#10b981' },
  { text: '响应时间', desc: '系统响应速度指标分析', icon: 'Timer', color: '#f59e0b' },
  { text: '准确率', desc: '命中精度与准确性评估', icon: 'Bullseye', color: '#ec4899' },
  { text: '覆盖率', desc: '探测与打击覆盖范围', icon: 'Histogram', color: '#14b8a6' }
]

const allIndicators = computed(() => [
  ...recommendedIndicators.map(q => ({ ...q, isHot: false })),
  ...hotIndicators.map(q => ({ ...q, isHot: true }))
])

const goTo = (path: string) => { router.push(path) }

const restoreExecutionState = (sid: string) => {
  const execMap = JSON.parse(localStorage.getItem(LS_SESSION_EXEC) || '{}')
  const state = execMap[sid]
  if (state) {
    executionSteps.value = state.steps || []
    panelState.value.generatedSql = state.generatedSql || ''
    panelState.value.rawResults = state.rawResults || null
    panelState.value.indicators = state.indicators || null
    if (state.sections) {
      panelState.value.sections = state.sections
    }
    if (hasExecutionData.value) showExecutionPanel.value = true
  }
}

const loadHistory = (item: any) => {
  if (sessionMessages.value[item.id]) {
    messages.value = [...sessionMessages.value[item.id]]
    sessionId.value = item.id
    restoreExecutionState(item.id)
    persistState()
    ElMessage.success('已加载历史记录')
    nextTick(() => { renderTreesForMessages() })
  } else {
    ElMessage.warning('暂无该历史记录内容')
  }
}

const newSession = () => {
  sessionId.value = ''
  messages.value = []
  executionSteps.value = []
  panelState.value = { generatedSql: '', rawResults: null, indicators: null, activeSkillName: '', sections: { steps: false, indicators: true, sql: true, data: true } }
  showExecutionPanel.value = false
  activeAbortController = null
  cancelRequested = false
  persistState()
  ElMessage.success('已创建新会话')
}

const deleteHistory = (id: string) => {
  delete sessionMessages.value[id]
  historyList.value = historyList.value.filter(item => item.id !== id)
  if (sessionId.value === id) {
    sessionId.value = ''
    messages.value = []
    executionSteps.value = []
    panelState.value = { generatedSql: '', rawResults: null, indicators: null, activeSkillName: '', sections: { steps: false, indicators: true, sql: true, data: true } }
    showExecutionPanel.value = false
    activeAbortController = null
    cancelRequested = false
  }
  persistState()
  ElMessage.success('已删除会话')
}

const selectIndicator = async (indicator: string) => {
  inputMessage.value = `分析${indicator}指标`
  await analyzeIndicator()
}

// 快捷确认查询/不查询
const quickConfirm = async (action: string) => {
  inputMessage.value = action
  await analyzeIndicator()
}

// 取消运行
const stopAnalysis = () => {
  if (!analyzing.value) return
  cancelRequested = true
  activeAbortController?.abort()
}

const analyzeIndicator = async () => {
  if (!inputMessage.value.trim()) {
    ElMessage.warning('请输入指标需求')
    return
  }

  const userQuestion = inputMessage.value
  inputMessage.value = ''
  analyzing.value = true
  cancelRequested = false
  activeAbortController = null

  messages.value.push({ role: 'user', content: userQuestion })

  let currentMsgIndex = messages.value.length
  messages.value.push({
    role: 'assistant',
    content: '',
    tree: null,
    indicators: [],
    references: [],
    steps: [],
    rawResults: null,
    generatedSql: '',
    treeCollapsed: false,
    indicatorsCollapsed: false,
    dataCollapsed: false,
    indicatorsExpanded: false,
    dataExpanded: false,
    confirmActions: false
  })
  nextTick(() => scrollToBottom())

  // 自动展开右侧面板
  showExecutionPanel.value = true

  activeAbortController = new AbortController()

  // 安全兜底：200 秒后强制恢复按钮状态，防止因异常导致 analyzing 卡死
  const analyzingGuard = setTimeout(() => {
    if (analyzing.value) {
      analyzing.value = false
      cancelRequested = false
      activeAbortController = null
    }
  }, 200000)

  try {
    const reqBody: any = { query: userQuestion, session_id: sessionId.value || undefined }
    if (selectedDataSourceId.value) {
      reqBody.database_id = selectedDataSourceId.value
      reqBody.database_name = selectedDataSourceName.value
    }
    const response = await fetch('/api/indicator/analyze/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: activeAbortController?.signal,
      body: JSON.stringify(reqBody)
    })

    if (!response.ok) throw new Error(`HTTP ${response.status}`)

    const reader = response.body?.getReader()
    if (!reader) throw new Error('无法获取流式响应')

    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (!line.trim()) continue
        try {
          const data = JSON.parse(line)
          if (data.type === 'text') {
            fullText += data.content
            messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], content: fullText }
            nextTick(() => scrollToBottom())
          } else if (data.type === 'step') {
            const step = data.step || data
            // 更新左侧消息的步骤（upsert by phase+step+description）
            const existingSteps = messages.value[currentMsgIndex].steps || []
            const dupIdx = existingSteps.findIndex(
              (s: any) => s.phase === step.phase && s.step === step.step && s.description === step.description
            )
            if (dupIdx >= 0) {
              existingSteps.splice(dupIdx, 1, step)
            } else {
              existingSteps.push(step)
            }
            messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], steps: [...existingSteps] }
            // 同步更新右侧面板的步骤（upsert by phase+step+description）
            const panelDupIdx = executionSteps.value.findIndex(
              (s: any) => s.phase === step.phase && s.step === step.step && s.description === step.description
            )
            if (panelDupIdx >= 0) {
              executionSteps.value.splice(panelDupIdx, 1, { ...step })
            } else {
              executionSteps.value.push({ ...step })
            }
            // 展开右侧面板
            if (!showExecutionPanel.value) showExecutionPanel.value = true
            nextTick(() => scrollToBottom())
          } else if (data.type === 'result') {
            messages.value[currentMsgIndex] = {
              ...messages.value[currentMsgIndex],
              content: fullText || data.final_answer || '',
              tree: data.tree || null,
              indicators: data.indicators || [],
              rawResults: data.rawResults || null,
              generatedSql: data.generatedSql || '',
              querying: false
            }
            // 更新右侧面板
            if (data.generatedSql) panelState.value.generatedSql = data.generatedSql
            if (data.rawResults) panelState.value.rawResults = data.rawResults
            if (data.indicators) panelState.value.indicators = data.indicators

            if (data.session_id) {
              if (!sessionId.value) {
                sessionId.value = data.session_id
                saveHistory(data.session_id, userQuestion)
              }
            }
          } else if (data.type === 'error') {
            fullText += '\n\n' + (data.message || data.content || '未知错误')
            messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], content: fullText }
            nextTick(() => scrollToBottom())
          } else if (data.type === 'new_message') {
            const content = data.content || ''
            const currentMsg = messages.value[currentMsgIndex]
            const isEmptyMsg = currentMsg && 
              !currentMsg.content && 
              !currentMsg.tree && 
              (!currentMsg.indicators || currentMsg.indicators.length === 0) && 
              !currentMsg.rawResults && 
              !currentMsg.generatedSql && 
              (!currentMsg.steps || currentMsg.steps.length === 0)
            
            if (isEmptyMsg) {
              messages.value[currentMsgIndex] = {
                ...currentMsg,
                content: content,
                confirmActions: content.includes('是否需要查询'),
                querying: true
              }
            } else {
              messages.value.push({
                role: 'assistant',
                content: content,
                summary: '',
                tree: null,
                indicators: [],
                references: [],
                steps: [],
                rawResults: null,
                generatedSql: '',
                treeCollapsed: false,
                indicatorsCollapsed: false,
                dataCollapsed: false,
                indicatorsExpanded: false,
                dataExpanded: false,
                confirmActions: content.includes('是否需要查询'),
                querying: true
              })
              currentMsgIndex = messages.value.length - 1
            }
            nextTick(() => scrollToBottom())
          }
        } catch (e) { /* ignore */ }
      }
    }

    if (!fullText && !messages.value[currentMsgIndex].summary && !messages.value[currentMsgIndex].rawResults) {
      messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], content: '分析失败，请检查网络连接或大模型配置。', querying: false }
    } else if (messages.value[currentMsgIndex].querying) {
      messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], querying: false }
    }

    if (!sessionId.value) {
      const newSessionId = 'session_' + Date.now()
      sessionId.value = newSessionId
      saveHistory(newSessionId, userQuestion)
    }
    sessionMessages.value[sessionId.value] = [...messages.value]
    persistState()

    nextTick(() => {
      setTimeout(() => { renderTreesForMessages(); scrollToBottom() }, 300)
    })
  } catch (e: any) {
    if (cancelRequested || (e as Error).name === 'AbortError') {
      messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], content: '本次分析已取消。', querying: false }
    } else {
      messages.value[currentMsgIndex] = { ...messages.value[currentMsgIndex], content: '分析失败，请检查网络连接或大模型配置。', querying: false }
    }
  } finally {
    clearTimeout(analyzingGuard)
    analyzing.value = false
    activeAbortController = null
    cancelRequested = false
  }
}

const saveHistory = (id: string, question: string) => {
  const exists = historyList.value.find(item => item.id === id)
  if (!exists) {
    historyList.value.unshift({ id, title: question.length > 20 ? question.substring(0, 20) + '...' : question, time: new Date().toLocaleString() })
  } else {
    exists.title = question.length > 20 ? question.substring(0, 20) + '...' : question
    exists.time = new Date().toLocaleString()
    const index = historyList.value.indexOf(exists)
    if (index > 0) { historyList.value.splice(index, 1); historyList.value.unshift(exists) }
  }
  persistState()
}

const setTreeChartRef = (el: any, index: number) => { if (el) treeChartRefs.value[index] = el }

const renderTreesForMessages = () => {
  messages.value.forEach((msg, index) => {
    if (msg.tree && treeChartRefs.value[index]) {
      nextTick(() => {
        const container = treeChartRefs.value[index]
        if (container) initTreeChart(container, msg.tree)
      })
    }
  })
}

const initTreeChart = (container: HTMLElement, data: any) => {
  if (!container || !data) return
  const chart = echarts.getInstanceByDom(container)
  if (chart) chart.dispose()
  const newChart = echarts.init(container)

  const processTreeData = (node: any): any => {
    const processed: any = { name: node.name || '未知指标', children: [] }
    if (node.children && Array.isArray(node.children)) {
      processed.children = node.children.map((child: any) => processTreeData(child))
    }
    processed.itemStyle = { color: node.source === 'knowledge' ? '#409eff' : '#909399' }
    return processed
  }

  newChart.setOption({
    tooltip: { trigger: 'item', triggerOn: 'mousemove', formatter: (params: any) => `${params.name}<br/>来源: ${params.data.source || '未知'}` },
    series: [{
      type: 'tree', data: [processTreeData(data)], symbolSize: 14,
      label: { position: 'left', verticalAlign: 'middle', align: 'right', fontSize: 12, formatter: '{b}' },
      leaves: { label: { position: 'right', verticalAlign: 'middle', align: 'left' } },
      expandAndCollapse: true, initialTreeDepth: 3, animationDuration: 550, animationDurationUpdate: 750,
      lineStyle: { width: 2, curveness: 0.5 },
      emphasis: { focus: 'ancestor' }
    }]
  })

  window.addEventListener('resize', () => newChart.resize())
}

const scrollToBottom = () => {
  nextTick(() => { if (chatArea.value) chatArea.value.scrollTop = chatArea.value.scrollHeight })
}

watch(() => messages.value.length, () => scrollToBottom())

const filteredHistoryList = computed(() => {
  if (!searchQuery.value.trim()) return historyList.value
  return historyList.value.filter(item => item.title.toLowerCase().includes(searchQuery.value.toLowerCase()))
})

onMounted(async () => {
  // 加载数据源
  try {
    const dsResp = await api.get('/evaluation/data-sources')
    if (dsResp.dataSources) {
      dataSources.value = dsResp.dataSources
      if (dataSources.value.length > 0 && !selectedDataSourceId.value) {
        selectedDataSourceId.value = dataSources.value[0].id
        selectedDataSourceName.value = dataSources.value[0].name || ''
      }
    }
  } catch (e) {
    console.error('Failed to load data sources:', e)
  }

  if (sessionId.value && sessionMessages.value[sessionId.value]) {
    messages.value = [...sessionMessages.value[sessionId.value]]
    restoreExecutionState(sessionId.value)
    nextTick(() => { setTimeout(() => renderTreesForMessages(), 300) })
  }
  ElMessage.info('指标分析系统加载完成')
})
</script>

<style scoped>
.indicator-container {
  display: flex;
  height: 100%;
  background: transparent;
}

/* ── 侧边栏 ── */
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
.history-item.active { background: rgba(59, 130, 246, 0.08); color: var(--primary-600); border: none; }

.history-item-main { display: flex; align-items: center; gap: 10px; flex: 1; min-width: 0; }
.history-item .el-icon { font-size: 16px; flex-shrink: 0; color: var(--text-muted); }
.history-item.active .el-icon { color: var(--primary-500); }

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

/* ── 顶部栏 / 数据源 ── */
.top-bar {
  display: flex;
  justify-content: flex-end;
  padding: 14px 24px;
  border-bottom: none;
  background: transparent;
  flex-shrink: 0;
}

.data-source-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

/* ── 数据源配置对话框 ── */
.data-source-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ds-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
}

.ds-item:hover {
  border-color: #409eff;
}

.ds-item.active {
  border-color: #409eff;
  background: #ecf5ff;
}

.ds-name {
  font-size: 0.95rem;
  font-weight: 500;
}

.ds-meta {
  display: flex;
  gap: 0.5rem;
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

.tags-section { margin-top: 0; width: 100%; max-width: 800px; padding: 0 40px; }

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

.message-text { padding: 14px 18px; border-radius: 16px; line-height: 1.75; font-size: 15px; white-space: pre-wrap; word-wrap: break-word; }
.message.user .message-text { background: linear-gradient(135deg, #4f8cff 0%, #3b82f6 100%); color: white; border-bottom-right-radius: 4px; }
.message.assistant .message-text { background: transparent; color: var(--text-primary); padding: 0; border-radius: 0; border: none; }

.message-loading { color: var(--text-muted); font-size: 14px; padding: 8px 0; }

/* ── AI 响应 ── */
.ai-response { display: flex; flex-direction: column; gap: 1rem; }

.tree-section, .indicators-section, .references-section { padding: 1rem 1.5rem; background: white; border: 1px solid #e2e8f0; border-radius: 0.75rem; }
.data-section { padding: 1rem 1.5rem; background: white; border: 1px solid #e2e8f0; border-radius: 0.75rem; }

/* ── 可折叠区域标题 ── */
.section-collapse-header {
  display: flex; align-items: center; justify-content: space-between;
  cursor: pointer; user-select: none;
}
.section-collapse-header h5 { margin: 0; color: #374151; font-size: 1rem; font-weight: 600; padding-bottom: 0; border-bottom: none; }
.section-collapse-header .el-icon { transition: transform 0.25s; color: #909399; font-size: 16px; flex-shrink: 0; }
.section-collapse-header .el-icon.rotated { transform: rotate(180deg); }

.tree-chart { width: 100%; height: 350px; margin-top: 0.75rem; }

.indicator-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 0.75rem; margin-top: 0.75rem; }

.indicator-card { background: linear-gradient(135deg, #f5f7fa 0%, #e4e8eb 100%); border-radius: 0.75rem; border-left: 4px solid #409eff; overflow: hidden; transition: transform 0.2s, box-shadow 0.2s; }
.indicator-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }

.indicator-header { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; background: white; border-bottom: 1px solid #e2e8f0; }
.indicator-name { font-weight: 600; color: #374151; font-size: 0.95rem; }

.indicator-body { padding: 0.75rem 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
.indicator-definition, .indicator-formula, .indicator-criteria, .indicator-weight { font-size: 0.9rem; color: #606266; line-height: 1.6; }
.indicator-formula { background: white; padding: 0.5rem; border-radius: 0.25rem; font-family: 'Courier New', monospace; color: #409eff; }

.expand-tip { text-align: center; padding: 8px; color: #409eff; cursor: pointer; font-size: 0.85rem; border-top: 1px dashed #e2e8f0; margin-top: 4px; }
.expand-tip:hover { background: #f0f7ff; border-radius: 0 0 0.75rem 0.75rem; }

.references-section ul { list-style: disc; padding-left: 1.5rem; margin: 0; color: #606266; }
.references-section li { padding: 0.25rem 0; font-size: 0.95rem; }

/* ── 数据表格 ── */
.data-table-wrapper { overflow-x: auto; max-height: 350px; overflow-y: auto; }
.data-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
.data-table th { background: #f1f5f9; padding: 0.5rem 0.75rem; text-align: left; font-weight: 600; color: #475569; border-bottom: 2px solid #cbd5e1; position: sticky; top: 0; z-index: 1; }
.data-table td { padding: 0.4rem 0.75rem; border-bottom: 1px solid #e2e8f0; color: #334155; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.data-table tr:hover td { background: #f8fafc; }

.data-section .section-collapse-header { margin-bottom: 0; }

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
.panel-title-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.panel-title-wrap .el-tag {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
}
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

.panel-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; color: #9ca3af; gap: 8px; font-size: 13px; }
.panel-empty p { margin: 0; }

/* 面板区域 */
.panel-section {
  background: white; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;
}

.section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; cursor: pointer; user-select: none;
  background: #f8fafc; transition: background 0.15s;
}
.section-header:hover { background: #f1f5f9; }
.section-header h5 { margin: 0; font-size: 13px; font-weight: 600; color: #475569; }
.section-header .el-icon { transition: transform 0.25s; color: #909399; font-size: 14px; }
.section-header .el-icon.rotated { transform: rotate(180deg); }

/* 面板中的步骤 */
.steps-list { display: flex; flex-direction: column; gap: 2px; padding: 8px 12px; }

.inline-step { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; font-size: 13px; display: flex; flex-direction: column; gap: 4px; word-break: break-word; overflow-wrap: break-word; }
.inline-step:last-child { border-bottom: none; }

.inline-step-header { display: flex; align-items: flex-start; gap: 8px; }
.inline-step-icon { display: flex; align-items: center; flex-shrink: 0; margin-top: 1px; }
.inline-step-title { font-weight: 500; color: #1f2937; flex: 1; min-width: 0; }
.inline-step-detail { color: #6b7280; font-size: 12px; padding-left: 24px; }
.inline-step-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 24px;
  color: #64748b;
  font-size: 11px;
}
.inline-step-thinking {
  margin-top: 4px;
  padding: 8px 10px;
  background: #f3f4f6;
  border-radius: 4px;
  font-size: 12px;
  color: #6b7280;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}
.inline-step-thinking summary {
  cursor: pointer;
  color: #475569;
  font-weight: 500;
}
.inline-step-thinking pre {
  margin: 8px 0 0;
  font: inherit;
  white-space: pre-wrap;
}
.inline-step.in-progress .inline-step-icon { color: #409eff; animation: rotating 2s linear infinite; }
.inline-step.completed .inline-step-icon { color: #67c23a; }
.inline-step.error .inline-step-icon { color: #f56c6c; }
.inline-step.skipped .inline-step-icon { color: #e6a23c; }
.inline-step.pending .inline-step-icon { color: #c0c4cc; }

@keyframes rotating { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

/* 面板中的 SQL 代码块 */
.sql-block {
  margin: 8px 12px 12px;
  padding: 10px;
  background: #0f172a;
  border-radius: 6px;
  color: #e2e8f0;
  font-family: 'Courier New', monospace;
  font-size: 0.75rem;
  line-height: 1.6;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 200px;
  overflow-y: auto;
}

/* 面板中的数据 */
.panel-data-wrapper {
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
  padding: 0 12px 12px;
}
.panel-data-wrapper .data-table { font-size: 0.78rem; }
.panel-data-wrapper .data-table th { padding: 0.35rem 0.5rem; }
.panel-data-wrapper .data-table td { padding: 0.3rem 0.5rem; max-width: 120px; }

/* 面板中指标表格 */
.panel-indicator-table td { max-width: none !important; overflow: visible !important; white-space: normal !important; word-break: break-word; font-size: 0.78rem; vertical-align: top; }
.panel-formula { font-family: 'Courier New', monospace; font-size: 0.75rem; color: #409eff; background: #f0f7ff; padding: 1px 4px; border-radius: 3px; }

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
.execution-panel-toggle .el-icon {
  writing-mode: horizontal-tb;
  font-size: 16px;
}
.execution-panel-toggle .toggle-text {
  writing-mode: vertical-rl;
  font-size: 13px;
  letter-spacing: 2px;
  user-select: none;
}
.execution-panel-toggle:hover { background: #f0f7ff; color: #409eff; }

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
.tools-bar .tool-item:hover { background: white; border-color: var(--primary-300); box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1); }
.tools-bar .tool-item.current { background: var(--primary-500); border-color: var(--primary-500); cursor: default; }
.tools-bar .tool-icon { width: 18px; height: 18px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: inherit; }
.tools-bar .tool-item.current .tool-icon { background: transparent; }
.tools-bar .tool-name { font-size: 13px; font-weight: 500; color: var(--text-secondary); }
.tools-bar .tool-item.current .tool-name { color: white; }
.tools-bar .tool-item:hover .tool-name { color: var(--primary-600); }
.tools-bar .tool-item.current:hover .tool-name { color: white; }

.input-wrapper { position: relative; max-width: 1000px; margin: 0 auto; width: 100%; }
.input-wrapper :deep(.el-textarea__inner) { border-radius: 16px !important; border-color: var(--border-normal) !important; padding: 16px 100px 16px 20px !important; font-size: 15px !important; line-height: 1.6 !important; transition: all 0.2s !important; background: var(--gray-50) !important; resize: none; }
.input-wrapper :deep(.el-textarea__inner:hover) { border-color: var(--primary-400) !important; background: white !important; }
.input-wrapper :deep(.el-textarea__inner:focus) { border-color: var(--primary-500) !important; background: white !important; box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1) !important; }

.input-actions { position: absolute; bottom: 14px; right: 16px; display: flex; gap: 8px; justify-content: flex-end; align-items: center; }
.input-actions .el-button { height: 38px; padding: 0 22px; border-radius: 10px; font-weight: 500; font-size: 14px; }

/* ── 追问快捷操作按钮 ── */
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
.confirm-actions .el-button .el-icon {
  margin-right: 4px;
}
</style>
