<template>
  <Layout>
    <div class="solution-container">
      <!-- 左侧边栏 -->
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
              v-for="item in historyList"
              :key="item.id"
              :class="['history-item', { active: item.id === sessionId }]"
            >
              <div class="history-item-main" @click="loadHistory(item)">
                <el-icon><Document /></el-icon>
                <div class="history-item-content">
                  <span class="history-item-title">{{ item.title ? (item.title.length > 20 ? item.title.substring(0, 20) + '...' : item.title) : (item.query ? (item.query.length > 20 ? item.query.substring(0, 20) + '...' : item.query) : '') }}</span>
                  <span class="history-item-time">{{ item.time || formatTime(item.timestamp || item.last_active) }}</span>
                </div>
              </div>
              <el-button class="history-delete-btn" size="small" text type="danger" @click.stop="deleteHistory(item.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 主内容区 -->
      <div class="main-content">
        <!-- 顶部栏 -->
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

        <!-- 内容区 -->
        <div class="content-area">
          <!-- 左侧：用户交互区 -->
          <div class="chat-panel">
            <div class="chat-area custom-scroll" ref="chatArea">
              <!-- 初始推荐问题 -->
              <div v-if="messages.length === 0" class="empty-state">
                <div class="tags-section">
                  <div class="suggest-cards">
                      <div
                        v-for="(item, index) in allSuggestions"
                        :key="index"
                        class="suggest-card"
                        :style="{ '--card-color': item.color }"
                        @click="selectQuestion(item.text)"
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
              
              <!-- 消息列表 -->
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
                    <!-- 结果展示区（SQL + 数据表格）放在建议前面 -->
                    <div v-if="msg.result" class="result-section">
                      <div v-if="msg.result.type === 'air_superiority'" class="air-superiority-result">
                        <div class="result-header">
                          <h5>制空权分析结果<span v-if="msg.result.region"> - {{ msg.result.region }}</span></h5>
                        </div>
                        <div v-for="(qr, idx) in msg.result.results" :key="idx" class="query-result-item">
                          <p class="query-result-title">{{ qr.group }} - {{ qr.label }}</p>
                          <div v-if="qr.sql" class="result-block">
                            <p class="block-label">SQL语句</p>
                            <p style="white-space: pre-wrap;">{{ qr.sql }}</p>
                          </div>
                          <div v-if="qr.rows && qr.rows.length > 0" class="result-block">
                            <p class="block-label">数据结果</p>
                            <p style="white-space: pre-wrap;">{{ formatRowsAsText(qr.columns, qr.rows) }}</p>
                          </div>
                          <p v-if="!qr.sql && (!qr.rows || qr.rows.length === 0)" class="no-data">暂无数据</p>
                          <div v-if="qr.insight" class="result-block">
                            <p class="block-label">分析洞察</p>
                            <p>{{ qr.insight }}</p>
                          </div>
                        </div>
                        <div v-if="msg.result.need_conclusion && msg.result.final_answer" class="summary-section">
                          <h6>综合评估</h6>
                          <p>{{ msg.result.final_answer }}</p>
                        </div>
                      </div>

                      <div v-if="msg.result.type === 'combat_effectiveness'" class="combat-result">
                        <div class="result-header">
                          <h5>作战效能评估结果</h5>
                        </div>
                        <div v-for="(r, idx) in msg.result.results" :key="idx" class="query-result-item">
                          <p class="query-result-title">{{ r.group }} - {{ r.label }}</p>
                          <div v-if="r.sql" class="result-block">
                            <p class="block-label">SQL语句</p>
                            <p style="white-space: pre-wrap;">{{ r.sql }}</p>
                          </div>
                          <div v-if="r.rows && r.rows.length > 0" class="result-block">
                            <p class="block-label">数据结果</p>
                            <p style="white-space: pre-wrap;">{{ formatRowsAsText(r.columns, r.rows) }}</p>
                          </div>
                          <p v-if="!r.sql && (!r.rows || r.rows.length === 0)" class="no-data">暂无数据</p>
                          <div v-if="r.insight" class="result-block">
                            <p class="block-label">分析洞察</p>
                            <p>{{ r.insight }}</p>
                          </div>
                        </div>
                        <div v-if="msg.result.need_conclusion && msg.result.final_answer" class="summary-section">
                          <h6>综合评估</h6>
                          <p>{{ msg.result.final_answer }}</p>
                        </div>
                      </div>
                      
                      <div v-if="msg.result.type === 'indicator_calculation'" class="indicator-result">
                        <div class="result-header">
                          <h5>指标计算结果</h5>
                        </div>
                        <div class="sql-section">
                          <h6>生成的SQL</h6>
                          <pre class="sql-code">{{ msg.result.generatedSql }}</pre>
                        </div>
                        <div v-if="msg.result.queryResult" class="data-section">
                          <h6>查询结果</h6>
                          <el-table :data="msg.result.queryResult.sampleData" style="width: 100%" size="small">
                            <el-table-column
                              v-for="(_value, key) in msg.result.queryResult.sampleData[0]"
                              :key="key"
                              :prop="String(key)"
                              :label="msg.result.queryResult.columns ? msg.result.queryResult.columns[Object.keys(msg.result.queryResult.sampleData[0]).indexOf(String(key))] : String(key)"
                            />
                          </el-table>
                        </div>
                        <div v-if="msg.result.statistics" class="statistics-section">
                          <h6>统计汇总</h6>
                          <div class="stats-grid">
                            <div class="stat-item">
                              <span class="stat-label">总任务数</span>
                              <span class="stat-value">{{ msg.result.statistics.totalMissions }}</span>
                            </div>
                            <div class="stat-item">
                              <span class="stat-label">成功数</span>
                              <span class="stat-value">{{ msg.result.statistics.totalSuccess }}</span>
                            </div>
                            <div class="stat-item highlight">
                              <span class="stat-label">总成功率</span>
                              <span class="stat-value">{{ msg.result.statistics.overallRate }}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                      
                      <div v-if="msg.result.type === 'general' || msg.result.type === 'data_query'" class="general-result">
                        <!-- 执行的SQL -->
                        <div v-if="msg.result.generatedSql" class="sql-section">
                          <h6>生成的SQL</h6>
                          <pre class="sql-code">{{ msg.result.generatedSql }}</pre>
                        </div>
                        <!-- 图表可视化（仅当 chartConfig 有效时显示） -->
                        <div v-if="msg.result.chartConfig && msg.result.chartConfig.vizType !== 'table' && msg.result.rawResults && msg.result.rawResults.length > 0" class="chart-section">
                          <div class="chart-header">
                            <h6>{{ msg.result.chartConfig.chartTitle || '数据可视化' }}</h6>
                            <el-radio-group v-model="chartViewMode" size="small">
                              <el-radio-button value="chart">图表</el-radio-button>
                              <el-radio-button value="table">表格</el-radio-button>
                            </el-radio-group>
                          </div>
                          <div v-show="chartViewMode === 'chart'" class="chart-container">
                            <v-chart :option="buildChartOption(msg.result.chartConfig, msg.result.rawResults)" style="height: 360px" autoresize />
                          </div>
                          <div v-show="chartViewMode === 'table'" class="data-section">
                            <el-table :data="msg.result.rawResults" style="width: 100%" size="small" max-height="400" border stripe>
                              <el-table-column
                                v-for="col in Object.keys(msg.result.rawResults[0] || {})"
                                :key="col"
                                :prop="col"
                                :label="col"
                                min-width="100"
                                show-overflow-tooltip
                              />
                            </el-table>
                          </div>
                        </div>
                        <!-- 数据表格（无图表时） -->
                        <div v-else-if="msg.result.rawResults && msg.result.rawResults.length > 0" class="data-section">
                          <h6>查询结果（共 {{ msg.result.totalRows || msg.result.rawResults.length }} 行）</h6>
                          <el-table :data="msg.result.rawResults" style="width: 100%" size="small" max-height="400" border stripe>
                            <el-table-column
                              v-for="col in Object.keys(msg.result.rawResults[0] || {})"
                              :key="col"
                              :prop="col"
                              :label="col"
                              min-width="100"
                              show-overflow-tooltip
                            />
                          </el-table>
                        </div>
                        <!-- 数据为空提示 -->
                        <div v-if="msg.result.rawResults && msg.result.rawResults.length === 0" class="data-empty">
                          查询执行成功，但未返回数据
                        </div>
                        <!-- 结论（仅 need_conclusion=true 时显示） -->
                        <div v-if="msg.result.need_conclusion && msg.result.final_answer" class="summary-section">
                          <h6>评估结论</h6>
                          <p>{{ msg.result.final_answer }}</p>
                        </div>
                      </div>
                      
                      <div v-if="msg.result.knowledgeReference && msg.result.knowledgeReference.length > 0" class="references-section">
                        <h6>参考资料</h6>
                        <ul>
                          <li v-for="(ref, idx) in msg.result.knowledgeReference" :key="idx">{{ ref }}</li>
                        </ul>
                      </div>
                    </div>
                    <!-- 分析建议（2-3条） -->
                    <div class="message-text" v-html="renderMarkdown(msg.content)"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- 执行过程侧边栏 -->
          <div v-if="showExecutionPanel" class="execution-panel" :style="{ width: executionPanelWidth + 'px' }">
            <div class="resize-handle" @mousedown="startResize"></div>
            <div class="panel-header">
              <span>系统执行过程</span>
              <el-icon class="panel-close" @click="showExecutionPanel = false" title="收起"><Close /></el-icon>
            </div>
            <div class="execution-content custom-scroll">
              <div v-if="executionSteps.length === 0 && !analyzing" class="empty-execution">
                <el-icon :size="32" color="#d1d5db"><Cpu /></el-icon>
                <p>暂无执行步骤</p>
              </div>
              <div v-else class="steps-list">
                <div
                  v-for="step in executionSteps"
                  :key="step.step"
                  :class="['inline-step', getStepStatusClass(step.status)]"
                >
                  <div class="inline-step-header">
                    <span class="inline-step-icon">
                      <el-icon v-if="step.status === 'completed'"><CircleCheck /></el-icon>
                      <el-icon v-else-if="step.status === 'in_progress'"><Loading class="is-loading" /></el-icon>
                      <el-icon v-else-if="step.status === 'error'"><CircleClose /></el-icon>
                      <el-icon v-else><Clock /></el-icon>
                    </span>
                    <span class="inline-step-title">步骤 {{ step.step }}: {{ step.description }}</span>
                  </div>
                  <div class="inline-step-detail">{{ step.detail }}</div>
                  <div v-if="step.thinking" class="inline-step-thinking">{{ step.thinking }}</div>
                </div>
              </div>
            </div>
          </div>
          <!-- 收起状态下的展开按钮 -->
          <div v-else class="execution-panel-toggle" @click="showExecutionPanel = true" title="展开系统执行过程">
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
              placeholder="输入您的评估需求，如：分析XXX区域的红蓝双方制空权优势对比..."
              @keyup.enter.ctrl="sendMessage"
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
              <el-button type="primary" @click="sendMessage" :disabled="analyzing">
                <el-icon><Promotion /></el-icon>
                {{ analyzing ? '分析中...' : '发送' }}
              </el-button>
            </div>
          </div>
          
          <!-- 工具按钮 -->
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
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Collection,
  Box,
  Document,
  Setting,
  Promotion,
  CircleCheck,
  CircleClose,
  Clock,
  ChatDotRound,
  Loading,
  Cpu,
  Plus,
  Delete,
  ArrowRight,
  PieChart as ElPieChart,
  Microphone
} from '@element-plus/icons-vue'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, PieChart, LineChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent] as any)

const router = useRouter()

// ── 语音识别 ──
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

// localStorage 持久化 key
const LS_SESSION_ID = 'solution_session_id'
const LS_HISTORY_LIST = 'solution_history_list'
const LS_SESSION_MSGS = 'solution_session_msgs'

// 工具配置
const tools = [
  {
    id: 1,
    name: '智能问答',
    icon: ChatDotRound,
    color: '#409eff',
    path: '/qa',
    current: false
  },
  {
    id: 2,
    name: '指标分析',
    icon: ElPieChart,
    color: '#67c23a',
    path: '/indicator',
    current: false
  },
  {
    id: 3,
    name: '评估分析',
    icon: Document,
    color: '#e6a23c',
    path: '/evaluation',
    current: true
  }
]

// 跳转工具
const navigateToTool = (path: string) => {
  router.push(path)
}

// 状态
const inputMessage = ref('')
const analyzing = ref(false)
const messages = ref<Array<any>>([])
const historyList = ref<Array<any>>(JSON.parse(localStorage.getItem(LS_HISTORY_LIST) || '[]'))
const sessionMessages = ref<Record<string, Array<any>>>(JSON.parse(localStorage.getItem(LS_SESSION_MSGS) || '{}'))
const sessionId = ref(localStorage.getItem(LS_SESSION_ID) || '')

console.log('[SolutionEvaluation] component loaded')

// 简单 markdown 渲染（处理 **加粗**、换行、列表）
function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br/>')
    .replace(/^(\d+)\.\s(.+)$/gm, '<div class="md-list-item"><span class="md-num">$1.</span> $2</div>')
    .replace(/<br\/>(\d+)\.\s/g, '<br/><span class="md-num">$1.</span> ')
  return html
}

const dataSources = ref<Array<any>>([])
const selectedDataSourceId = ref<string | null>(null)
const selectedDataSourceName = ref<string>('')
const dataSourceDialogVisible = ref(false)
const showExecutionPanel = ref(true)
const chartViewMode = ref('chart')
const executionPanelWidth = ref(460)
const isResizing = ref(false)
const executionSteps = ref<Array<any>>([])

// 拖拽调整面板宽度
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

// 持久化辅助函数
const persistState = () => {
  localStorage.setItem(LS_SESSION_ID, sessionId.value)
  localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
  localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
}

// 制空权分析示例
const airSuperiorityExamples = [
  {
    text: '分析A区域的红蓝双方制空权优势对比',
    desc: '区域空中优势对比分析',
    icon: 'Aim',
    color: '#3b82f6'
  },
  {
    text: '评估B区域的空中优势情况',
    desc: '区域制空能力评估',
    icon: 'Guide',
    color: '#ef4444'
  },
  {
    text: '对比红蓝双方的制空能力',
    desc: '双方制空能力综合对比',
    icon: 'TrendCharts',
    color: '#8b5cf6'
  }
]

// 指标计算示例
const indicatorExamples = [
  {
    text: '计算本月任务完成率指标',
    desc: '任务完成率统计分析',
    icon: 'DataAnalysis',
    color: '#10b981'
  },
  {
    text: '查询各区域作战效能指标',
    desc: '区域效能指标分布查询',
    icon: 'Histogram',
    color: '#f59e0b'
  },
  {
    text: '统计武器系统作战成功率',
    desc: '武器系统效能统计',
    icon: 'Coin',
    color: '#ec4899'
  }
]

const allSuggestions = [
  ...airSuperiorityExamples,
  ...indicatorExamples
]

// 导航
const goTo = (path: string) => {
  router.push(path)
}

// 选择推荐问题
const selectQuestion = (question: string) => {
  inputMessage.value = question
  sendMessage()
}

// 选择数据源
const selectDataSource = (ds: any) => {
  selectedDataSourceId.value = ds.id
  selectedDataSourceName.value = ds.name || ''
}

// 下拉框切换数据源时同步名称
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

// 格式化时间
const formatTime = (time: string) => {
  const date = new Date(time)
  return date.toLocaleString()
}

// 获取步骤状态类名
const getStepStatusClass = (status: string) => {
  const statusMap: Record<string, string> = {
    'completed': 'completed',
    'in_progress': 'in-progress',
    'pending': 'pending',
    'error': 'error',
    'skipped': 'skipped'
  }
  return statusMap[status] || 'pending'
}

// 将 rows 统一转为二维数组格式（兼容对象/{col:val} 和数组/[val] 两种后端返回）
const normalizeRows = (columns: any[], rows: any[]): any[][] => {
  if (!rows || rows.length === 0) return []
  const first = rows[0]
  // 首行是数组 → 已经是二维数组格式
  if (Array.isArray(first)) return rows
  // 首行是对象 → 按 columns 顺序提取值转为数组
  return rows.map((r: any) => columns.map((col: string) => r[col]))
}

// 行列数据转可读文本
const formatRowsAsText = (columns: any[], rows: any[]) => {
  if (!columns || !rows || rows.length === 0) return ''
  const arr = normalizeRows(columns, rows)
  const lines = arr.map((row: any) => columns.map((col, i) => `${col}=${row[i]}`).join('，'))
  return lines.map((line, i) => `${i + 1}. ${line}`).join('\n')
}

// 根据 chartConfig + 全量 rawResults 构建 ECharts option
const buildChartOption = (chartConfig: any, rawResults: any[]): any => {
  if (!chartConfig || !rawResults || rawResults.length === 0) return undefined
  const vizType = chartConfig.vizType || 'bar'
  const xAxisField = chartConfig.xAxis || Object.keys(rawResults[0])[0]
  const yAxisFields = chartConfig.yAxis && chartConfig.yAxis.length > 0
    ? chartConfig.yAxis
    : Object.keys(rawResults[0]).slice(1)

  if (vizType === 'table') return undefined

  const categories = rawResults.map((r: any) => String(r[xAxisField] ?? ''))

  if (vizType === 'pie') {
    const firstY = yAxisFields[0]
    return {
      title: { text: chartConfig.chartTitle || '', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', left: 'left', top: 30 },
      series: [{
        type: 'pie',
        radius: ['40%', '65%'],
        center: ['55%', '55%'],
        data: rawResults.map((r: any) => ({
          name: String(r[xAxisField] ?? ''),
          value: Number(r[firstY]) || 0
        })),
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 }
      }]
    }
  }

  // bar / line
  const series = yAxisFields.map((field: string) => ({
    name: field,
    type: vizType,
    data: rawResults.map((r: any) => Number(r[field]) || 0),
    barMaxWidth: 40,
    smooth: vizType === 'line'
  }))

  return {
    title: { text: chartConfig.chartTitle || '', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: yAxisFields, top: 30 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: 60, containLabel: true },
    xAxis: { type: 'category', data: categories, axisLabel: { rotate: categories.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value' },
    series
  }
}

// 发送消息 - 使用 fetch API 实现流式读取
const sendMessage = async () => {
  if (!inputMessage.value.trim()) {
    ElMessage.warning('请输入评估需求')
    return
  }
  
  const query = inputMessage.value.trim()
  inputMessage.value = ''
  analyzing.value = true
  executionSteps.value = []
  
  // 添加用户消息
  messages.value.push({
    role: 'user',
    content: query
  })
  
  // 添加AI等待消息
  const aiMessage = {
    role: 'assistant',
    content: '正在分析您的需求，请稍候...',
    result: null,
    executionSteps: [] as any[]
  }
  messages.value.push(aiMessage)
  
  try {
    // 使用 fetch API 进行流式请求
    const response = await fetch('/api/evaluation/analyze/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        query: query,
        session_id: sessionId.value || undefined,
        dataSourceId: selectedDataSourceId.value || '',
        skillId: null
      })
    })
    
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }
    
    // 获取 reader
    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('无法获取响应流')
    }
    
    const decoder = new TextDecoder()
    let buffer = ''
    
    // 持续读取流
    while (true) {
      const { done, value } = await reader.read()
      
      if (done) {
        break
      }
      
      // 解码数据
      buffer += decoder.decode(value, { stream: true })
      
      // 按行分割处理
      const lines = buffer.split('\n')
      buffer = lines.pop() || '' // 保留未完成的行
      
      for (const line of lines) {
        // 跳过 SSE 心跳注释行
        if (!line.trim() || line.startsWith(':')) continue
        try {
          const data = JSON.parse(line)
            
            if (data.type === 'step') {
              const step = data.step
              const existingIndex = executionSteps.value.findIndex(s => s.step === step.step)
              if (existingIndex >= 0) {
                executionSteps.value.splice(existingIndex, 1, step)
              } else {
                executionSteps.value.push(step)
              }
              aiMessage.content = '正在分析...'
            } else if (data.type === 'result') {
              // 收到最终结果
              const result = data.result || {}
              const answerText = result.final_answer || result.summary || result.answer || '分析完成'
              // need_conclusion=false 时清空正文结论，避免重复显示
              aiMessage.content = result.need_conclusion === false ? '' : answerText
              aiMessage.result = result
              
              // 保存会话
              if (data.session_id) {
                if (!sessionId.value) {
                  sessionId.value = data.session_id
                  saveHistory(data.session_id, query)
                }
                sessionMessages.value[sessionId.value || data.session_id] = [
                  { role: 'user', content: query },
                  { role: 'assistant', content: answerText }
                ]
                persistState()
              }
              
              // 滚动到结果
              scrollToBottom()
            }
          } catch (error) {
            console.error('Parse error:', error)
          }
        }
      }
  } catch (error) {
    console.error('Evaluation error:', error)
    aiMessage.content = '分析失败，请稍后重试'
    ElMessage.error('分析失败：' + (error as Error).message)
  } finally {
    analyzing.value = false
  }
}

// 滚动聊天区域到底部
const scrollToBottom = () => {
  nextTick(() => {
    const chatArea = document.querySelector('.chat-area') as HTMLElement
    if (chatArea) {
      chatArea.scrollTop = chatArea.scrollHeight
    }
    // 同时滚动执行过程面板
    const execContent = document.querySelector('.execution-content') as HTMLElement
    if (execContent) {
      execContent.scrollTop = execContent.scrollHeight
    }
  })
}

// 监听消息和步骤变化，自动滚动
watch(() => messages.value.length, () => scrollToBottom())
watch(() => executionSteps.value.length, () => scrollToBottom())

// 加载历史记录
const loadHistory = (item: any) => {
  if (sessionMessages.value[item.id]) {
    messages.value = [...sessionMessages.value[item.id]]
    sessionId.value = item.id
    executionSteps.value = []
    persistState()
    ElMessage.success('已加载历史记录')
  } else {
    ElMessage.warning('暂无该历史记录内容')
  }
}

const newSession = () => {
  sessionId.value = ''
  messages.value = []
  executionSteps.value = []
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
  }
  persistState()
  ElMessage.success('已删除会话')
}

const saveHistory = (id: string, question: string) => {
  const exists = historyList.value.find(item => item.id === id)
  if (!exists) {
    historyList.value.unshift({
      id: id,
      title: question.length > 20 ? question.substring(0, 20) + '...' : question,
      time: new Date().toLocaleString()
    })
  } else {
    exists.title = question.length > 20 ? question.substring(0, 20) + '...' : question
    exists.time = new Date().toLocaleString()
    const index = historyList.value.indexOf(exists)
    if (index > 0) {
      historyList.value.splice(index, 1)
      historyList.value.unshift(exists)
    }
  }
  persistState()
}

// 初始化数据
const initData = async () => {
  try {
    const dsResp = await api.get('/evaluation/data-sources')
    
    if (dsResp.dataSources) {
      dataSources.value = dsResp.dataSources
      if (dataSources.value.length > 0) {
        selectedDataSourceId.value = dataSources.value[0].id
        selectedDataSourceName.value = dataSources.value[0].name || ''
      }
    }
  } catch (error) {
    console.error('Init data error:', error)
    ElMessage.warning('部分数据加载失败，请检查服务是否启动')
  }
}

onMounted(() => {
  // 恢复上次会话的消息
  if (sessionId.value && sessionMessages.value[sessionId.value]) {
    messages.value = [...sessionMessages.value[sessionId.value]]
  }
  initData()
})
</script>

<style scoped>
.solution-container {
  display: flex;
  height: 100%;
  background: transparent;
}

.sidebar {
  width: 260px;
  flex-shrink: 0;
  padding: 16px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 0;
}

.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0;
  padding: 0 8px;
}

.sidebar-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.5px;
  margin-bottom: 0;
}

.new-session-btn {
  height: 32px !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  padding: 0 12px !important;
  border-radius: 8px !important;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
}

.nav-item:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-primary);
}

.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: none;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
}

.history-item:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-primary);
}

.history-item.active {
  background: rgba(59, 130, 246, 0.08);
  color: var(--primary-600);
  border: none;
}

.history-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.history-item .el-icon {
  font-size: 16px;
  flex-shrink: 0;
  color: var(--text-muted);
}

.history-item.active .el-icon {
  color: var(--primary-500);
}

.history-delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  flex-shrink: 0;
}

.history-item:hover .history-delete-btn {
  opacity: 1;
}

.history-item-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.history-item-title {
  font-size: 13px;
  font-weight: 500;
  color: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-item-time {
  font-size: 11px;
  color: var(--text-muted);
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  gap: 0;
  background: var(--bg-card);
  border-left: none;
  border-right: none;
  border-radius: 0;
  box-shadow: none;
}

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

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  gap: 0;
}

.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-right: none;
  padding: 0;
  gap: 0;
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
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

.empty-state > .el-icon {
  color: var(--gray-200) !important;
}

.empty-state p {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.tags-section {
  margin-top: 0;
  width: 100%;
  max-width: 720px;
  padding: 0 20px;
}

.tag-group {
  margin-bottom: 0;
}

.tag-group h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-tertiary);
  margin-bottom: 16px;
  text-align: center;
  letter-spacing: 0.5px;
}

.suggest-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.suggest-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--gray-50);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.suggest-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--card-color);
  opacity: 0;
  transition: opacity 0.2s;
}

.suggest-card:hover {
  background: white;
  border-color: color-mix(in srgb, var(--card-color) 30%, white);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

.suggest-card:hover::before {
  opacity: 1;
}

.suggest-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--card-color) 12%, white);
  color: var(--card-color);
  transition: all 0.2s;
}

.suggest-card:hover .suggest-icon {
  background: var(--card-color);
  color: white;
  transform: scale(1.05);
}

.suggest-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.suggest-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  transition: color 0.2s;
}

.suggest-card:hover .suggest-title {
  color: var(--card-color);
}

.suggest-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggest-arrow {
  flex-shrink: 0;
  font-size: 14px;
  color: var(--text-muted);
  opacity: 0;
  transform: translateX(-4px);
  transition: all 0.2s;
}

.suggest-card:hover .suggest-arrow {
  opacity: 1;
  transform: translateX(0);
  color: var(--card-color);
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.message {
  display: flex;
  gap: 1rem;
}

.message.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 90%;
}

.message-text {
  padding: 1rem;
  border-radius: 0.75rem;
  line-height: 1.8;
  font-size: 1.05rem;
}

.message.user .message-text {
  background: #409eff;
  color: white;
}

.message.assistant .message-text {
  background: white;
  border: 1px solid #e2e8f0;
  color: #374151;
}

.assistant .message-text strong {
  color: #374151;
  font-weight: 600;
}

.md-list-item {
  margin-bottom: 0.35rem;
  padding-left: 0.5rem;
}

.md-num {
  font-weight: 600;
  color: #409eff;
}

.result-section {
  margin-top: 1rem;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 0.5rem;
}

.result-header {
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #409eff;
}

.result-header h5 {
  margin: 0;
  color: #374151;
}

.query-result-item {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: white;
  border-radius: 0.5rem;
  border: 1px solid #e5e7eb;
}

.query-result-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.5rem;
}

.query-result-insight {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.6;
  margin-bottom: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #f0f9ff;
  border-radius: 6px;
  border-left: 3px solid #409eff;
}

.summary-section {
  margin-top: 0.5rem;
  padding: 1rem;
  background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
  border-radius: 0.5rem;
  border: 1px solid #bae6fd;
}

.summary-section h6 {
  margin: 0 0 0.5rem;
  color: #0369a1;
  font-size: 14px;
}

.summary-section p {
  margin: 0;
  color: #075985;
  line-height: 1.8;
  font-size: 14px;
}

.no-data {
  text-align: center;
  padding: 1.5rem;
  color: #9ca3af;
  font-size: 13px;
}

.air-superiority-result .score-display {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 2rem;
  margin: 1.5rem 0;
}

.air-superiority-result .team {
  text-align: center;
}

.air-superiority-result .team.red .team-score {
  background: linear-gradient(135deg, #fef2f2, #fee2e2);
  color: #dc2626;
  border: 2px solid #fecaca;
}

.air-superiority-result .team.blue .team-score {
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
  color: #2563eb;
  border: 2px solid #bfdbfe;
}

.air-superiority-result .team-name {
  font-size: 1.2rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.air-superiority-result .team-score {
  font-size: 3rem;
  font-weight: 700;
  width: 120px;
  height: 120px;
  line-height: 120px;
  border-radius: 50%;
}

.air-superiority-result .vs {
  font-size: 1.5rem;
  color: #64748b;
  font-weight: 600;
}

.air-superiority-result .advantage-banner {
  text-align: center;
  padding: 1rem;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  border-radius: 0.5rem;
  font-size: 1.2rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.air-superiority-result .advantage-banner .winner {
  margin-right: 0.5rem;
}

.air-superiority-result .analysis-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}

.air-superiority-result .detail-section,
.air-superiority-result .recommendations {
  background: white;
  padding: 1rem;
  border-radius: 0.5rem;
}

.air-superiority-result .detail-section h6,
.air-superiority-result .recommendations h6 {
  margin: 0 0 0.5rem;
  color: #374151;
}

.air-superiority-result .detail-section ul {
  list-style: disc;
  padding-left: 1.5rem;
  margin: 0;
  color: #64748b;
}

.air-superiority-result .recommendations {
  grid-column: 1 / -1;
}

.air-superiority-result .recommendations p {
  margin: 0;
  color: #64748b;
}

.air-superiority-result .factors-section h6,
.indicator-result .sql-section h6,
.indicator-result .data-section h6,
.indicator-result .statistics-section h6,
.references-section h6 {
  margin: 1rem 0 0.5rem;
  color: #374151;
}

.indicator-result .sql-code {
  background: #1f2937;
  color: #e5e7eb;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  font-family: 'Courier New', monospace;
  font-size: 0.9rem;
  line-height: 1.6;
}

.indicator-result .statistics-section {
  background: white;
  padding: 1rem;
  border-radius: 0.5rem;
}

.indicator-result .stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.indicator-result .stat-item {
  text-align: center;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 0.5rem;
}

.indicator-result .stat-item.highlight {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.indicator-result .stat-label {
  display: block;
  font-size: 0.85rem;
  margin-bottom: 0.5rem;
}

.indicator-result .stat-value {
  display: block;
  font-size: 1.5rem;
  font-weight: 700;
}

.references-section ul {
  list-style: disc;
  padding-left: 1.5rem;
  color: #64748b;
}

.execution-panel-toggle {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 32px;
  flex-shrink: 0;
  background: #fafafa;
  border-left: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
  cursor: pointer;
  color: #9ca3af;
  transition: background 0.2s, color 0.2s;
  writing-mode: vertical-rl;
}
.execution-panel-toggle .el-icon {
  writing-mode: horizontal-tb;
  font-size: 16px;
}
.execution-panel-toggle .toggle-text {
  font-size: 13px;
  letter-spacing: 2px;
  user-select: none;
}
.execution-panel-toggle:hover {
  background: #f0f7ff;
  color: #409eff;
}

.execution-panel {
  min-width: 300px;
  max-width: 700px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
  flex-shrink: 0;
  position: relative;
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
  transition: background 0.2s;
}
.resize-handle:hover,
.resize-handle:active {
  background: rgba(64, 158, 255, 0.35);
}
.panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 14px;
  color: #1f2937;
  background: #fff;
}
.panel-close {
  cursor: pointer;
  color: #9ca3af;
}
.panel-close:hover {
  color: #374151;
}
.execution-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.empty-execution {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #9ca3af;
  gap: 8px;
  font-size: 13px;
}

/* 内联执行步骤样式 */
.execution-inline {
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  background: #f9fafb;
}
.inline-step {
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  word-break: break-word;
  overflow-wrap: break-word;
}
.inline-step:last-child {
  border-bottom: none;
}
.inline-step-header {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.inline-step-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.inline-step-title {
  font-weight: 500;
  color: #1f2937;
  flex: 1;
  min-width: 0;
}
.inline-step-detail {
  color: #6b7280;
  font-size: 12px;
  padding-left: 24px;
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
.inline-step.in-progress .inline-step-icon {
  color: #409eff;
}
.inline-step.completed .inline-step-icon {
  color: #67c23a;
}
.inline-step.error .inline-step-icon {
  color: #f56c6c;
}

.input-area {
  flex-shrink: 0;
  padding: 16px 40px 24px;
  background: linear-gradient(to top, var(--bg-card) 60%, transparent);
  border: none;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.tools-bar {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.tools-bar .tool-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: #f5f7fa;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.tools-bar .tool-item:hover {
  background: #eff6ff;
  border-color: #409eff;
}

.tools-bar .tool-item.current {
  background: #409eff;
  border-color: #409eff;
  cursor: default;
}

.tools-bar .tool-icon {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
}

.tools-bar .tool-item.current .tool-icon {
  background: rgba(255, 255, 255, 0.2);
}

.tools-bar .tool-name {
  color: #606266;
  font-size: 0.85rem;
  font-weight: 500;
}

.tools-bar .tool-item.current .tool-name {
  color: white;
}

.input-wrapper {
  position: relative;
  max-width: 1000px;
  margin: 0 auto;
  width: 100%;
}

.input-wrapper :deep(.el-textarea__inner) {
  border-radius: 16px !important;
  border-color: var(--border-normal) !important;
  padding: 16px 100px 16px 20px !important;
  font-size: 15px !important;
  line-height: 1.6 !important;
  transition: all 0.2s !important;
  background: var(--gray-50) !important;
  resize: none;
}

.input-wrapper :deep(.el-textarea__inner:hover) {
  border-color: var(--primary-400) !important;
  background: white !important;
}

.input-wrapper :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-500) !important;
  background: white !important;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1) !important;
}

.input-actions {
  position: absolute;
  bottom: 14px;
  right: 16px;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  align-items: center;
}

.attachment-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  padding: 4px 16px 0;
  max-width: 1000px;
  margin: 0 auto;
}

.input-actions .el-button {
  height: 38px;
  padding: 0 22px;
  border-radius: 10px;
  font-weight: 500;
}

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
  background: #eff6ff;
}

.ds-name {
  font-weight: 600;
  color: #374151;
}

.ds-meta {
  display: flex;
  gap: 0.5rem;
}

.is-loading {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 图表可视化区域 */
.chart-section {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid #e5e7eb;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.chart-header h6 {
  margin: 0;
  font-size: 14px;
  color: #374151;
}
.chart-container {
  width: 100%;
  min-height: 360px;
}
</style>
