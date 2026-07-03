<template>
  <Layout>
    <div class="solution-container">
      <!-- 左侧边栏 -->
      <div class="sidebar">
        <div class="sidebar-section">
          <div class="sidebar-section-header">
            <h3 class="sidebar-title">导航</h3>
            <el-button size="small" type="primary" text @click="newSession">
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
            <el-select v-model="selectedDataSourceId" placeholder="选择数据源" size="small" style="width: 200px">
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
                <el-icon :size="80" color="#d1d5db"><DocumentChecked /></el-icon>
                <p>开始方案评估</p>
                <div class="tags-section">
                  <!-- 制空权分析示例 -->
                  <div class="tag-group">
                    <h4>制空权分析</h4>
                    <div class="tags">
                      <el-tag
                        v-for="q in airSuperiorityExamples"
                        :key="q"
                        class="tag-item"
                        @click="selectQuestion(q)"
                      >
                        {{ q }}
                      </el-tag>
                    </div>
                  </div>
                  
                  <!-- 指标计算示例 -->
                  <div class="tag-group">
                    <h4>指标计算</h4>
                    <div class="tags">
                      <el-tag
                        v-for="q in indicatorExamples"
                        :key="q"
                        class="tag-item"
                        @click="selectQuestion(q)"
                      >
                        {{ q }}
                      </el-tag>
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
                    <div class="message-text">{{ msg.content }}</div>
                    
                    <!-- 结果展示区 -->
                    <div v-if="msg.result" class="result-section">
                      <div v-if="msg.result.type === 'air_superiority'" class="air-superiority-result">
                        <div class="result-header">
                          <h5>制空权优势对比分析</h5>
                        </div>
                        <div class="score-display">
                          <div class="team red">
                            <div class="team-name">红方</div>
                            <div class="team-score">{{ msg.result.redScore }}</div>
                          </div>
                          <div class="vs">VS</div>
                          <div class="team blue">
                            <div class="team-name">蓝方</div>
                            <div class="team-score">{{ msg.result.blueScore }}</div>
                          </div>
                        </div>
                        <div class="advantage-banner">
                          <span class="winner">{{ msg.result.advantage }}</span>
                          <span class="text">优势 ({{ msg.result.advantageMargin }}分)</span>
                        </div>
                        <div v-if="msg.result.analysisDetails" class="analysis-details">
                          <div class="detail-section">
                            <h6>红方优势</h6>
                            <ul>
                              <li v-for="(item, idx) in msg.result.analysisDetails.strengthsRed" :key="idx">{{ item }}</li>
                            </ul>
                          </div>
                          <div class="detail-section">
                            <h6>蓝方优势</h6>
                            <ul>
                              <li v-for="(item, idx) in msg.result.analysisDetails.strengthsBlue" :key="idx">{{ item }}</li>
                            </ul>
                          </div>
                          <div class="recommendations">
                            <h6>作战建议</h6>
                            <p>{{ msg.result.analysisDetails.recommendations }}</p>
                          </div>
                        </div>
                        <div class="factors-section">
                          <h6>关键影响因素</h6>
                          <ul>
                            <li v-for="(factor, idx) in msg.result.factors" :key="idx">{{ factor }}</li>
                          </ul>
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
                              v-for="(value, key) in msg.result.queryResult.sampleData[0]"
                              :key="key"
                              :prop="key"
                              :label="msg.result.queryResult.columns ? msg.result.queryResult.columns[Object.keys(msg.result.queryResult.sampleData[0]).indexOf(key)] : key"
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
                      
                      <div v-if="msg.result.type === 'general'" class="general-result">
                        <div class="result-header">
                          <h5>分析结果</h5>
                        </div>
                        <div class="answer-text">
                          {{ msg.result.answer }}
                        </div>
                      </div>
                      
                      <div v-if="msg.result.knowledgeReference && msg.result.knowledgeReference.length > 0" class="references-section">
                        <h6>参考资料</h6>
                        <ul>
                          <li v-for="(ref, idx) in msg.result.knowledgeReference" :key="idx">{{ ref }}</li>
                        </ul>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          
          <!-- 右侧：执行过程区 -->
          <transition name="slide">
            <div v-if="showExecutionPanel" class="execution-panel">
              <div class="panel-header">
                <h4>系统执行过程</h4>
                <el-button link @click="showExecutionPanel = false" type="info">
                  <el-icon><DArrowRight /></el-icon>
                </el-button>
              </div>
              <div class="execution-content custom-scroll">
                <div v-if="executionSteps.length === 0 && !analyzing" class="empty-execution">
                  <el-icon :size="48" color="#d1d5db"><Cpu /></el-icon>
                  <p>开始评估后显示执行过程</p>
                </div>
                <div v-else-if="analyzing" class="analyzing-indicator">
                  <el-icon class="is-loading" :size="24"><Loading /></el-icon>
                  <span>正在分析...</span>
                </div>
                <div v-else class="steps-list">
                  <div
                    v-for="step in executionSteps"
                    :key="step.step + '-' + step.status"
                    :class="['step-item', getStepStatusClass(step.status)]"
                  >
                    <div class="step-icon">
                      <el-icon v-if="step.status === 'completed'"><CircleCheck /></el-icon>
                      <el-icon v-else-if="step.status === 'in_progress'"><Loading class="is-loading" /></el-icon>
                      <el-icon v-else-if="step.status === 'error'"><CircleClose /></el-icon>
                      <el-icon v-else><Clock /></el-icon>
                    </div>
                    <div class="step-content">
                      <div class="step-title">
                        步骤 {{ step.step }}: {{ step.description }}
                      </div>
                      <div class="step-detail">{{ step.detail }}</div>
                      <!-- 显示Thinking内容 -->
                      <div v-if="step.thinking" class="step-thinking">
                        <el-icon><ChatDotRound /></el-icon>
                        {{ step.thinking }}
                      </div>
                      <!-- 显示进度条 -->
                      <div v-if="step.progress !== undefined && step.status === 'in_progress'" class="step-progress">
                        <el-progress :percentage="step.progress" :stroke-width="6" />
                      </div>
                      <!-- 显示子步骤 -->
                      <div v-if="step.subStep" class="step-substep">
                        <el-tag size="small" type="info">{{ formatSubStep(step.subStep) }}</el-tag>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </transition>
        </div>

        <!-- 收起执行面板的按钮 -->
        <div v-if="!showExecutionPanel" class="toggle-button" @click="showExecutionPanel = true">
          <el-icon><DArrowLeft /></el-icon>
          <span>执行过程</span>
        </div>

        <!-- 底部输入区 -->
        <div class="input-area">
          <div class="input-wrapper">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="2"
              placeholder="输入您的评估需求，如：分析XXX区域的红蓝双方制空权优势对比..."
              @keyup.enter.ctrl="sendMessage"
            />
            <div class="input-actions">
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
import { ref, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Collection,
  Box,
  Document,
  DocumentChecked,
  Setting,
  DArrowLeft,
  DArrowRight,
  Promotion,
  CircleCheck,
  CircleClose,
  Clock,
  ChatDotRound,
  Loading,
  Cpu,
  PieChart,
  Plus,
  Delete
} from '@element-plus/icons-vue'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const router = useRouter()

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
    icon: PieChart,
    color: '#67c23a',
    path: '/indicator',
    current: false
  },
  {
    id: 3,
    name: '方案评估',
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
const dataSources = ref<Array<any>>([])
const selectedDataSourceId = ref<string | null>(null)
const dataSourceDialogVisible = ref(false)
const showExecutionPanel = ref(true)
const executionSteps = ref<Array<any>>([])

// 持久化辅助函数
const persistState = () => {
  localStorage.setItem(LS_SESSION_ID, sessionId.value)
  localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
  localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
}

// 制空权分析示例
const airSuperiorityExamples = [
  '分析A区域的红蓝双方制空权优势对比',
  '评估B区域的空中优势情况',
  '对比红蓝双方的制空能力'
]

// 指标计算示例
const indicatorExamples = [
  '计算本月任务完成率指标',
  '查询各区域作战效能指标',
  '统计武器系统作战成功率'
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

// 格式化子步骤
const formatSubStep = (subStep: string) => {
  const subStepMap: Record<string, string> = {
    'air_analysis': '制空权分析',
    'knowledge_retrieval': '知识检索',
    'report_generation': '报告生成',
    'sql_generation': 'SQL生成',
    'sql_execution': 'SQL执行',
    'indicator_analysis': '指标分析'
  }
  return subStepMap[subStep] || subStep
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
  
  // 清空执行步骤
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
    result: null
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
        dataSourceId: selectedDataSourceId.value || null,
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
        if (line.trim()) {
          try {
            const data = JSON.parse(line)
            
            if (data.type === 'step') {
              // 更新执行步骤
              const step = data.step
              
              // 检查是否已存在该步骤
              const existingIndex = executionSteps.value.findIndex(s => s.step === step.step)
              if (existingIndex >= 0) {
                // 更新已存在的步骤
                executionSteps.value[existingIndex] = step
              } else {
                // 添加新步骤
                executionSteps.value.push(step)
              }
              
              // 滚动到底部
              scrollExecutionPanel()
              
              // 更新AI消息内容
              if (step.detail) {
                aiMessage.content = step.detail
              }
            } else if (data.type === 'result') {
              // 收到最终结果
              let resultContent = '分析完成'
              
              if (data.result) {
                if (data.result.type === 'air_superiority') {
                  resultContent = `已完成制空权优势分析，${data.result.advantage}占优（领先${data.result.advantageMargin}分）。`
                } else if (data.result.type === 'indicator_calculation') {
                  resultContent = `指标计算完成，总成功率${data.result.statistics?.overallRate || '未知'}。`
                } else {
                  resultContent = data.result.answer || '分析完成'
                }
              }
              
              aiMessage.content = resultContent
              aiMessage.result = normalizeResult(data.result)
              
              // 保存会话
              if (data.session_id) {
                if (!sessionId.value) {
                  sessionId.value = data.session_id
                  saveHistory(data.session_id, query)
                }
                sessionMessages.value[sessionId.value || data.session_id] = [...messages.value]
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
    }
  } catch (error) {
    console.error('Evaluation error:', error)
    aiMessage.content = '分析失败，请稍后重试'
    ElMessage.error('分析失败：' + (error as Error).message)
  } finally {
    analyzing.value = false
  }
}

// 规范化结果数据（处理命名不一致）
const normalizeResult = (result: any) => {
  if (!result) return null
  
  return {
    type: result.type,
    redScore: result.redScore || result.red_score,
    blueScore: result.blueScore || result.blue_score,
    advantage: result.advantage,
    advantageMargin: result.advantageMargin || result.advantage_margin,
    factors: result.factors || [],
    analysisDetails: result.analysisDetails || result.analysis_details,
    generatedSql: result.generatedSql || result.generated_sql,
    queryResult: result.queryResult || result.query_result,
    statistics: result.statistics || result.stats,
    answer: result.answer,
    knowledgeReference: result.knowledgeReference || result.knowledge_reference || []
  }
}

// 滚动执行面板到底部
const scrollExecutionPanel = () => {
  nextTick(() => {
    const panel = document.querySelector('.execution-content') as HTMLElement
    if (panel) {
      panel.scrollTop = panel.scrollHeight
    }
  })
}

// 滚动聊天区域到底部
const scrollToBottom = () => {
  nextTick(() => {
    const chatArea = document.querySelector('.chat-area') as HTMLElement
    if (chatArea) {
      chatArea.scrollTop = chatArea.scrollHeight
    }
  })
}

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
    // 先检查服务是否可用
    const dsResp = await api.get('/evaluation/data-sources')
    
    if (dsResp.dataSources) {
      dataSources.value = dsResp.dataSources
      if (dataSources.value.length > 0) {
        selectedDataSourceId.value = dataSources.value[0].id
      }
    }
    
    // 获取历史记录
    try {
      const historyResp = await api.get('/evaluation/history')
      if (historyResp.history) {
        historyList.value = historyResp.history
      }
    } catch (e) {
      console.log('历史记录接口暂时不可用')
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
  background: white;
}

.sidebar {
  width: 260px;
  background: #f8fafc;
  border-right: 1px solid #e2e8f0;
  padding: 1.5rem;
  overflow-y: auto;
}

.sidebar-section {
  margin-bottom: 2rem;
}

.sidebar-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #64748b;
  text-transform: uppercase;
  margin-bottom: 1rem;
}

.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
}

.sidebar-section-header .sidebar-title {
  margin-bottom: 0;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
  color: #374151;
}

.nav-item:hover {
  background: #e2e8f0;
}

.history-list {
  max-height: 400px;
  overflow-y: auto;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
  color: #6b7280;
  font-size: 0.9rem;
}

.history-item:hover {
  background: #e2e8f0;
  color: #374151;
}

.history-item.active {
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.history-item-main {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0;
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
  gap: 0.25rem;
}

.history-item-title {
  font-size: 0.9rem;
  color: #374151;
}

.history-item-time {
  font-size: 0.75rem;
  color: #9ca3af;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.top-bar {
  display: flex;
  justify-content: flex-end;
  padding: 1rem 1.5rem;
  border-bottom: 1px solid #e2e8f0;
  background: #fafafa;
}

.data-source-selector {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.label {
  font-size: 0.9rem;
  color: #64748b;
}

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-right: 1px solid #e2e8f0;
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 1.5rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 2rem;
  color: #9ca3af;
  height: 100%;
}

.empty-state p {
  margin-top: 1rem;
  font-size: 1.1rem;
}

.tags-section {
  margin-top: 2rem;
  width: 100%;
  max-width: 800px;
}

.tag-group {
  margin-bottom: 2rem;
}

.tag-group h4 {
  font-size: 1.1rem;
  color: #475569;
  margin-bottom: 1rem;
  text-align: center;
  font-weight: 600;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  justify-content: center;
}

.tag-item {
  cursor: pointer;
  transition: all 0.2s;
  padding: 0.6rem 1rem !important;
  font-size: 0.95rem !important;
}

.tag-item:hover {
  transform: scale(1.05);
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

.execution-panel {
  width: 380px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border-bottom: 1px solid #e2e8f0;
  background: white;
}

.panel-header h4 {
  margin: 0;
  font-size: 1rem;
  color: #374151;
}

.execution-content {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
}

.empty-execution {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #9ca3af;
  text-align: center;
}

.empty-execution p {
  margin-top: 1rem;
}

.analyzing-indicator {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  padding: 2rem;
  color: #409eff;
  font-weight: 600;
}

.steps-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.step-item {
  display: flex;
  gap: 0.75rem;
  padding: 1rem;
  background: white;
  border-radius: 0.5rem;
  border: 2px solid #e2e8f0;
  transition: all 0.3s;
}

.step-item.completed {
  border-color: #10b981;
  background: linear-gradient(135deg, #f0fdf4, #dcfce7);
}

.step-item.in-progress {
  border-color: #f59e0b;
  background: linear-gradient(135deg, #fffbeb, #fef3c7);
  animation: pulse-border 2s infinite;
}

.step-item.error {
  border-color: #ef4444;
  background: linear-gradient(135deg, #fef2f2, #fee2e2);
}

.step-item.skipped {
  opacity: 0.6;
}

@keyframes pulse-border {
  0%, 100% { 
    border-color: #f59e0b;
    box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.4);
  }
  50% { 
    border-color: #fbbf24;
    box-shadow: 0 0 0 4px rgba(245, 158, 11, 0);
  }
}

.step-icon {
  font-size: 1.5rem;
  margin-top: 0.1rem;
}

.step-item.completed .step-icon {
  color: #10b981;
}

.step-item.in-progress .step-icon {
  color: #f59e0b;
}

.step-item.error .step-icon {
  color: #ef4444;
}

.step-title {
  font-weight: 600;
  color: #374151;
  margin-bottom: 0.5rem;
}

.step-detail {
  font-size: 0.9rem;
  color: #64748b;
  margin-bottom: 0.5rem;
}

.step-thinking {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: #f8fafc;
  border-radius: 0.25rem;
  font-size: 0.85rem;
  color: #64748b;
  font-style: italic;
}

.step-progress {
  margin-top: 0.5rem;
}

.step-substep {
  margin-top: 0.5rem;
}

.toggle-button {
  position: absolute;
  right: 0;
  top: 50%;
  transform: translateY(-50%);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.25rem;
  padding: 1rem 0.5rem;
  background: #409eff;
  color: white;
  border-radius: 0.5rem 0 0 0.5rem;
  cursor: pointer;
  font-size: 0.85rem;
  z-index: 10;
}

.slide-enter-active,
.slide-leave-active {
  transition: width 0.3s ease;
}

.slide-enter-from,
.slide-leave-to {
  width: 0;
  overflow: hidden;
}

.input-area {
  background: white;
  padding: 1rem;
  border-top: 1px solid #e2e8f0;
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
}

.input-actions {
  position: absolute;
  bottom: 1rem;
  right: 1rem;
  display: flex;
  justify-content: flex-end;
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
</style>
