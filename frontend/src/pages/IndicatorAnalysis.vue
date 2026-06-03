<template>
  <Layout>
    <div class="indicator-container">
      <div class="sidebar">
        <div class="sidebar-section">
          <h3 class="sidebar-title">导航</h3>
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
              class="history-item"
              @click="loadHistory(item)"
            >
              <el-icon><PieChart /></el-icon>
              <div class="history-item-content">
                <span class="history-item-title">{{ item.title }}</span>
                <span class="history-item-time">{{ item.time }}</span>
              </div>
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
            <el-icon :size="80" color="#d1d5db"><PieChart /></el-icon>
            <p>开始指标分析</p>
            <div class="tags-section">
              <div class="tag-group">
                <h4>推荐指标</h4>
                <div class="tags">
                  <el-tag
                    v-for="tag in allIndicators"
                    :key="tag.text"
                    class="tag-item"
                    :type="tag.isHot ? 'warning' : ''"
                    @click="selectIndicator(tag.text)"
                  >
                    {{ tag.text }}
                  </el-tag>
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
                  <!-- 文本回答 -->
                  <div v-if="msg.content" class="message-text">{{ msg.content }}</div>
                  
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
                          <el-tag :type="ind.type === 'knowledge' ? 'primary' : 'info'" size="small">
                            {{ ind.type === 'knowledge' ? '知识库' : 'AI生成' }}
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
              :rows="2"
              placeholder="输入指标需求，如：帮我分析火力打击任务完成度指标..."
              @keyup.enter="analyzeIndicator"
            />
            <div class="input-actions">
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
import { ref, onMounted, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Collection, Box, PieChart, ChatDotRound, Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const router = useRouter()

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
    name: '方案评估',
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

const inputMessage = ref('')
const analyzing = ref(false)
const messages = ref<Array<any>>([])
const historyList = ref<Array<any>>([])
const sessionMessages = ref<Record<string, Array<any>>>({})
const sessionId = ref('')
const searchQuery = ref('')
const chatArea = ref<HTMLElement | null>(null)
const treeChartRefs = ref<HTMLElement[]>([])

const recommendedIndicators = [
  '作战效能',
  '打击能力',
  '生存能力',
  '保障能力'
]

const hotIndicators = [
  '任务完成度',
  '响应时间',
  '准确率',
  '覆盖率'
]

const allIndicators = computed(() => [
  ...recommendedIndicators.map(text => ({ text, isHot: false })),
  ...hotIndicators.map(text => ({ text, isHot: true }))
])

const goTo = (path: string) => {
  router.push(path)
}

const loadHistory = (item: any) => {
  if (sessionMessages.value[item.id]) {
    messages.value = [...sessionMessages.value[item.id]]
    sessionId.value = item.id
    ElMessage.success('已加载历史记录')
    nextTick(() => {
      renderTreesForMessages()
    })
  } else {
    ElMessage.warning('暂无该历史记录内容')
  }
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

  const loadingMsg = {
    role: 'assistant',
    content: '正在分析指标，请稍候...'
  }
  messages.value.push(loadingMsg)

  try {
    // 调用后端API获取指标分析结果
    const res = await api.post('/indicator/analyze', {
      query: userQuestion
    })
    
    messages.value.pop()
    
    // 构建响应消息，包含结构化数据
    const responseMsg = {
      role: 'assistant',
      content: res.answer || '',
      summary: res.summary || '',
      tree: res.tree || null,
      indicators: res.indicators || [],
      references: res.references || []
    }
    messages.value.push(responseMsg)

    const newSessionId = 'session_' + Date.now()
    sessionId.value = newSessionId
    saveHistory(newSessionId, userQuestion)
    sessionMessages.value[newSessionId] = [...messages.value]

    // 延迟渲染树状图，确保DOM已更新
    nextTick(() => {
      setTimeout(() => {
        renderTreesForMessages()
        scrollToBottom()
      }, 300)
    })

  } catch (e) {
    messages.value.pop()
    messages.value.push({
      role: 'assistant',
      content: '分析失败，请检查网络连接或大模型配置。',
      summary: '',
      tree: null,
      indicators: [],
      references: []
    })
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
  if (chatArea.value) {
    chatArea.value.scrollTop = chatArea.value.scrollHeight
  }
}

const filteredHistoryList = computed(() => {
  if (!searchQuery.value.trim()) return historyList.value
  return historyList.value.filter(item => 
    item.title.toLowerCase().includes(searchQuery.value.toLowerCase())
  )
})

onMounted(() => {
  ElMessage.info('指标分析系统加载完成')
})
</script>

<style scoped>
.indicator-container {
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
  padding: 0.75rem;
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

.history-search {
  margin-top: 1rem;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 1.5rem;
  overflow-y: auto;
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  margin-bottom: 1rem;
  padding: 1rem;
  background: #f9fafb;
  border-radius: 0.75rem;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 3rem;
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
  max-width: 900px;
}

.tag-group {
  margin-bottom: 1.5rem;
}

.tag-group h4 {
  font-size: 1.1rem;
  color: #475569;
  margin-bottom: 1rem;
  text-align: center;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 1rem;
  justify-content: center;
}

.tag-item {
  cursor: pointer;
  transition: all 0.2s;
  padding: 0.75rem 1.25rem !important;
  font-size: 1.05rem !important;
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
  white-space: pre-wrap;
  word-wrap: break-word;
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
  background: white;
  padding: 1rem;
  border-radius: 0.75rem;
  box-shadow: 0 -4px 6px rgba(0, 0, 0, 0.05);
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
</style>
