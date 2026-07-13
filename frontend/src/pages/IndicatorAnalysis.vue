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
                
                <!-- AI消息：包含文本、结构化数据、树状图、指标卡片 -->
                <div v-else class="ai-response">
                  <!-- 文本回答 / 分析中 -->
                  <div v-if="msg.content" class="message-text">{{ msg.content }}</div>
                  <div v-else-if="!msg.summary && !msg.tree && (!msg.indicators || msg.indicators.length === 0)" class="message-loading">分析中...</div>
                  
                  <!-- 分析总结 -->
                  <div v-if="msg.summary" class="summary-section">
                    <h5>分析总结</h5>
                    <p>{{ msg.summary }}</p>
                  </div>
                  
                  <!-- 指标树状结构 -->
                  <div v-if="msg.tree" class="tree-section">
                    <h5>指标树状结构</h5>
                    <div :ref="el => setTreeChartRef(el, index)" class="tree-chart"></div>
                  </div>
                  
                  <!-- 指标卡片列表 -->
                  <div v-if="msg.indicators && msg.indicators.length > 0" class="indicators-section">
                    <h5>指标计算方式</h5>
                    <div class="indicator-list">
                      <div v-for="(ind, idx) in msg.indicators" :key="idx" class="indicator-card">
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
                    </div>
                  </div>
                  
                  <!-- 参考来源 -->
                  <div v-if="msg.references && msg.references.length > 0" class="references-section">
                    <h5>参考来源</h5>
                    <ul>
                      <li v-for="(ref, idx) in msg.references" :key="idx">{{ ref }}</li>
                    </ul>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="input-area">
          <div class="input-wrapper">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="3"
              placeholder="输入指标需求，如：帮我分析火力打击任务完成度指标..."
              @keyup.enter="analyzeIndicator"
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
              <el-button type="primary" @click="analyzeIndicator" :loading="analyzing">
                {{ analyzing ? '分析中...' : '分析指标' }}
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
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed, nextTick, watch } from 'vue'
import { useSpeechRecognition } from '@/composables/useSpeechRecognition'
import { useRouter } from 'vue-router'
import { Search, Collection, Box, PieChart, ChatDotRound, Document, Plus, Delete, ArrowRight, Microphone } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'

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
    current: true
  },
  {
    id: 3,
    name: '评估分析',
    icon: Document,
    color: '#e6a23c',
    path: '/evaluation',
    current: false
  }
]

// 跳转工具
const navigateToTool = (path: string) => {
  router.push(path)
}

// localStorage 持久化 key
const LS_SESSION_ID = 'indicator_session_id'
const LS_HISTORY_LIST = 'indicator_history_list'
const LS_SESSION_MSGS = 'indicator_session_msgs'

const inputMessage = ref('')
const analyzing = ref(false)
const messages = ref<Array<any>>([])
const historyList = ref<Array<any>>(JSON.parse(localStorage.getItem(LS_HISTORY_LIST) || '[]'))
const sessionMessages = ref<Record<string, Array<any>>>(JSON.parse(localStorage.getItem(LS_SESSION_MSGS) || '{}'))
const sessionId = ref(localStorage.getItem(LS_SESSION_ID) || '')
const searchQuery = ref('')
const chatArea = ref<HTMLElement | null>(null)
const treeChartRefs = ref<HTMLElement[]>([])

// 持久化辅助函数
const persistState = () => {
  localStorage.setItem(LS_SESSION_ID, sessionId.value)
  localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
  localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
}

const recommendedIndicators = [
  {
    text: '作战效能',
    desc: '综合作战效能指标体系分析',
    icon: 'Aim',
    color: '#3b82f6'
  },
  {
    text: '打击能力',
    desc: '装备打击能力评估指标',
    icon: 'Guide',
    color: '#ef4444'
  },
  {
    text: '生存能力',
    desc: '战场生存能力评估维度',
    icon: 'Shield',
    color: '#8b5cf6'
  },
  {
    text: '保障能力',
    desc: '后勤保障能力评估体系',
    icon: 'Box',
    color: '#06b6d4'
  }
]

const hotIndicators = [
  {
    text: '任务完成度',
    desc: '作战任务完成情况分析',
    icon: 'CircleCheck',
    color: '#10b981'
  },
  {
    text: '响应时间',
    desc: '系统响应速度指标分析',
    icon: 'Timer',
    color: '#f59e0b'
  },
  {
    text: '准确率',
    desc: '命中精度与准确性评估',
    icon: 'Bullseye',
    color: '#ec4899'
  },
  {
    text: '覆盖率',
    desc: '探测与打击覆盖范围',
    icon: 'Histogram',
    color: '#14b8a6'
  }
]

const allIndicators = computed(() => [
  ...recommendedIndicators.map(q => ({ ...q, isHot: false })),
  ...hotIndicators.map(q => ({ ...q, isHot: true }))
])

const goTo = (path: string) => {
  router.push(path)
}

const loadHistory = (item: any) => {
  if (sessionMessages.value[item.id]) {
    messages.value = [...sessionMessages.value[item.id]]
    sessionId.value = item.id
    persistState()
    ElMessage.success('已加载历史记录')
    nextTick(() => {
      renderTreesForMessages()
    })
  } else {
    ElMessage.warning('暂无该历史记录内容')
  }
}

const newSession = () => {
  sessionId.value = ''
  messages.value = []
  persistState()
  ElMessage.success('已创建新会话')
}

const deleteHistory = (id: string) => {
  delete sessionMessages.value[id]
  historyList.value = historyList.value.filter(item => item.id !== id)
  if (sessionId.value === id) {
    sessionId.value = ''
    messages.value = []
  }
  persistState()
  ElMessage.success('已删除会话')
}

const selectIndicator = async (indicator: string) => {
  inputMessage.value = `分析${indicator}指标`
  await analyzeIndicator()
}

const analyzeIndicator = async () => {
  if (!inputMessage.value.trim()) {
    ElMessage.warning('请输入指标需求')
    return
  }

  const userQuestion = inputMessage.value
  inputMessage.value = ''
  analyzing.value = true

  messages.value.push({
    role: 'user',
    content: userQuestion
  })

  const msgIndex = messages.value.length
  messages.value.push({
    role: 'assistant',
    content: '',
    summary: '',
    tree: null,
    indicators: [],
    references: []
  })
  nextTick(() => scrollToBottom())

  try {
    const response = await fetch('/api/indicator/analyze/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: userQuestion,
        session_id: sessionId.value || undefined
      })
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
            messages.value[msgIndex] = { ...messages.value[msgIndex], content: fullText }
            nextTick(() => scrollToBottom())
          } else if (data.type === 'result') {
            messages.value[msgIndex] = {
              ...messages.value[msgIndex],
              content: fullText || data.summary || '',
              tree: data.tree || null,
              indicators: data.indicators || [],
              summary: data.summary || ''
            }

            if (data.session_id) {
              if (!sessionId.value) {
                sessionId.value = data.session_id
                saveHistory(data.session_id, userQuestion)
              }
            }
          }
        } catch (e) {
          // 忽略解析错误
        }
      }
    }

    if (!fullText && !messages.value[msgIndex].summary) {
      messages.value[msgIndex] = { ...messages.value[msgIndex], content: '分析失败，请检查网络连接或大模型配置。' }
    }

    // 保存会话
    if (!sessionId.value) {
      const newSessionId = 'session_' + Date.now()
      sessionId.value = newSessionId
      saveHistory(newSessionId, userQuestion)
    }
    sessionMessages.value[sessionId.value] = [...messages.value]
    persistState()

    // 延迟渲染树状图
    nextTick(() => {
      setTimeout(() => {
        renderTreesForMessages()
        scrollToBottom()
      }, 300)
    })

  } catch (e: any) {
    messages.value[msgIndex] = { ...messages.value[msgIndex], content: `分析失败，请检查网络连接或大模型配置。` }
  } finally {
    analyzing.value = false
  }
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

const setTreeChartRef = (el: any, index: number) => {
  if (el) {
    treeChartRefs.value[index] = el
  }
}

const renderTreesForMessages = () => {
  messages.value.forEach((msg, index) => {
    if (msg.tree && treeChartRefs.value[index]) {
      nextTick(() => {
        const container = treeChartRefs.value[index]
        if (container) {
          initTreeChart(container, msg.tree)
        }
      })
    }
  })
}

const initTreeChart = (container: HTMLElement, data: any) => {
  if (!container || !data) return
  
  const chart = echarts.getInstanceByDom(container)
  if (chart) {
    chart.dispose()
  }
  
  const newChart = echarts.init(container)

  const processTreeData = (node: any): any => {
    const processed: any = {
      name: node.name || '未知指标',
      children: []
    }
    
    if (node.children && Array.isArray(node.children)) {
      processed.children = node.children.map((child: any) => processTreeData(child))
    }
    
    processed.itemStyle = {
      color: node.source === 'knowledge' ? '#409eff' : '#909399'
    }
    
    return processed
  }

  const option = {
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove',
      formatter: (params: any) => {
        return `${params.name}<br/>来源: ${params.data.source || '未知'}`
      }
    },
    series: [
      {
        type: 'tree',
        data: [processTreeData(data)],
        symbolSize: 14,
        label: {
          position: 'left',
          verticalAlign: 'middle',
          align: 'right',
          fontSize: 12,
          formatter: '{b}'
        },
        leaves: {
          label: {
            position: 'right',
            verticalAlign: 'middle',
            align: 'left'
          }
        },
        expandAndCollapse: true,
        initialTreeDepth: 3,
        animationDuration: 550,
        animationDurationUpdate: 750,
        lineStyle: {
          width: 2,
          curveness: 0.5
        },
        emphasis: {
          focus: 'ancestor'
        }
      }
    ]
  }

  newChart.setOption(option)

  window.addEventListener('resize', () => {
    newChart.resize()
  })
}

const scrollToBottom = () => {
  nextTick(() => {
    if (chatArea.value) {
      chatArea.value.scrollTop = chatArea.value.scrollHeight
    }
  })
}

// 监听消息变化，自动滚动
watch(() => messages.value.length, () => scrollToBottom())

const filteredHistoryList = computed(() => {
  if (!searchQuery.value.trim()) return historyList.value
  return historyList.value.filter(item => 
    item.title.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

onMounted(() => {
  // 恢复上次会话的消息
  if (sessionId.value && sessionMessages.value[sessionId.value]) {
    messages.value = [...sessionMessages.value[sessionId.value]]
    nextTick(() => {
      setTimeout(() => renderTreesForMessages(), 300)
    })
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

.history-search {
  margin-top: 4px;
}

.history-search :deep(.el-input__wrapper) {
  border-radius: 8px;
  box-shadow: 0 0 0 1px var(--border-normal) inset;
  background: var(--bg-card);
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  padding: 0;
  gap: 0;
  overflow: hidden;
  background: var(--bg-card);
  border-left: 1px solid var(--border-light);
  border-right: 1px solid var(--border-light);
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 0;
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

.empty-state > .el-icon {
  color: var(--gray-200) !important;
}

.empty-state p {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  color: var(--text-primary);
}

.tags-section {
  margin-top: 0;
  width: 100%;
  max-width: 800px;
  padding: 0 40px;
}

.tag-group {
  margin-bottom: 24px;
}

.tag-group h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 12px;
  text-align: center;
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
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  transition: color 0.2s;
}

.suggest-card:hover .suggest-title {
  color: var(--card-color);
}

.suggest-desc {
  font-size: 12px;
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
  gap: 28px;
  max-width: 900px;
  margin: 0 auto;
  padding: 0 40px;
}

.message {
  display: flex;
  gap: 16px;
}

.message.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 85%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.message.user .message-content {
  align-items: flex-end;
}

.message-avatar {
  flex-shrink: 0;
  padding-top: 2px;
}

.message-text {
  padding: 14px 18px;
  border-radius: 16px;
  line-height: 1.75;
  font-size: 15px;
  white-space: pre-wrap;
  word-wrap: break-word;
}

.message.user .message-text {
  background: linear-gradient(135deg, #4f8cff 0%, #3b82f6 100%);
  color: white;
  border-bottom-right-radius: 4px;
}

.message.assistant .message-text {
  background: transparent;
  color: var(--text-primary);
  padding: 0;
  border-radius: 0;
  border: none;
}

/* AI响应区域样式 */
.ai-response {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.summary-section {
  padding: 1rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  border-radius: 0.75rem;
  color: white;
}

.summary-section h5 {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
  font-weight: 600;
}

.summary-section p {
  margin: 0;
  line-height: 1.6;
  font-size: 1rem;
}

.tree-section,
.indicators-section,
.references-section {
  padding: 1.5rem;
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 0.75rem;
}

.tree-section h5,
.indicators-section h5,
.references-section h5 {
  margin: 0 0 1rem 0;
  color: #374151;
  font-size: 1rem;
  font-weight: 600;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #409eff;
}

.tree-chart {
  width: 100%;
  height: 400px;
}

.indicator-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1rem;
}

.indicator-card {
  background: linear-gradient(135deg, #f5f7fa 0%, #e4e8eb 100%);
  border-radius: 0.75rem;
  border-left: 4px solid #409eff;
  overflow: hidden;
  transition: transform 0.2s, box-shadow 0.2s;
}

.indicator-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.indicator-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  background: white;
  border-bottom: 1px solid #e2e8f0;
}

.indicator-name {
  font-weight: 600;
  color: #374151;
  font-size: 1rem;
}

.indicator-body {
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.indicator-definition,
.indicator-formula,
.indicator-criteria,
.indicator-weight {
  font-size: 0.95rem;
  color: #606266;
  line-height: 1.6;
}

.indicator-formula {
  background: white;
  padding: 0.5rem;
  border-radius: 0.25rem;
  font-family: 'Courier New', monospace;
  color: #409eff;
}

.references-section ul {
  list-style: disc;
  padding-left: 1.5rem;
  margin: 0;
  color: #606266;
}

.references-section li {
  padding: 0.25rem 0;
  font-size: 0.95rem;
}

.input-area {
  flex-shrink: 0;
  padding: 16px 40px 24px;
  background: linear-gradient(to top, var(--bg-card) 60%, transparent);
  border: none;
  border-radius: 0;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.tools-bar {
  display: flex;
  gap: 8px;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.tools-bar .tool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  background: var(--gray-50);
  border-radius: 20px;
  cursor: pointer;
  transition: all 0.2s;
  border: 1px solid var(--border-light);
}

.tools-bar .tool-item:hover {
  background: white;
  border-color: var(--primary-300);
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.1);
}

.tools-bar .tool-item.current {
  background: var(--primary-500);
  border-color: var(--primary-500);
  cursor: default;
}

.tools-bar .tool-icon {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
}

.tools-bar .tool-item.current .tool-icon {
  background: transparent;
}

.tools-bar .tool-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-secondary);
}

.tools-bar .tool-item.current .tool-name {
  color: white;
}

.tools-bar .tool-item:hover .tool-name {
  color: var(--primary-600);
}

.tools-bar .tool-item.current:hover .tool-name {
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
  font-size: 14px;
}
</style>
