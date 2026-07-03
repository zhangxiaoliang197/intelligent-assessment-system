<template>
  <Layout>
    <div class="qa-container">
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
              v-for="item in filteredHistoryList"
              :key="item.id"
              :class="['history-item', { active: item.id === sessionId }]"
            >
              <div class="history-item-main" @click="loadHistory(item)">
                <el-icon><ChatLineRound /></el-icon>
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
        <div class="chat-area custom-scroll">
          <div v-if="messages.length === 0" class="empty-state">
            <el-icon :size="80" color="#d1d5db"><ChatDotRound /></el-icon>
            <p>开始智能问答之旅</p>
            <div class="tags-section">
              <div class="tag-group">
                <h4>推荐问题</h4>
                <div class="tags">
                  <el-tag
                    v-for="tag in allQuestions"
                    :key="tag"
                    class="tag-item"
                    :type="tag.isHot ? 'warning' : ''"
                    @click="selectQuestion(tag.text)"
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
                <div class="message-text">{{ msg.content }}</div>
                <div v-if="msg.references && msg.references.length > 0" class="references">
                  <h5>参考文献：</h5>
                  <ul>
                    <li v-for="ref in msg.references" :key="ref">{{ ref }}</li>
                  </ul>
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
              placeholder="请输入您的问题..."
              @keyup.enter.ctrl="sendMessage"
            />
            <div class="input-actions">
              <el-button type="primary" :icon="Promotion" @click="sendMessage">
                发送
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
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Collection, Box, ChatLineRound, ChatDotRound, Promotion, PieChart, Document, Plus, Delete } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
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
    current: true
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
    current: false
  }
]

// 跳转工具
const navigateToTool = (path: string) => {
  router.push(path)
}

// localStorage 持久化 key
const LS_SESSION_ID = 'qa_session_id'
const LS_HISTORY_LIST = 'qa_history_list'
const LS_SESSION_MSGS = 'qa_session_msgs'

const searchQuery = ref('')
const inputMessage = ref('')
const sessionId = ref(localStorage.getItem(LS_SESSION_ID) || '')
const messages = ref<Array<any>>([])
const historyList = ref<Array<any>>(JSON.parse(localStorage.getItem(LS_HISTORY_LIST) || '[]'))
const sessionMessages = ref<Record<string, Array<any>>>(JSON.parse(localStorage.getItem(LS_SESSION_MSGS) || '{}'))

// 持久化辅助函数
const persistState = () => {
  localStorage.setItem(LS_SESSION_ID, sessionId.value)
  localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
  localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
}

const recommendedQuestions = [
  '作战效能指标有哪些？',
  '如何评估打击能力？',
  '评估方案查询',
  '指标算法详解'
]

const hotQuestions = [
  '生存能力指标',
  '保障能力指标',
  '任务完成度评估',
  '综合效能分析'
]

const allQuestions = computed(() => [
  ...recommendedQuestions.map(text => ({ text, isHot: false })),
  ...hotQuestions.map(text => ({ text, isHot: true }))
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

const selectQuestion = (question: string) => {
  inputMessage.value = question
  sendMessage()
}

const sendMessage = async () => {
  if (!inputMessage.value.trim()) {
    ElMessage.warning('请输入问题')
    return
  }

  const userQuestion = inputMessage.value
  inputMessage.value = ''

  messages.value.push({
    role: 'user',
    content: userQuestion
  })

  const msgIndex = messages.value.length
  messages.value.push({
    role: 'assistant',
    content: '',
    references: [] as string[]
  })

  try {
    const response = await fetch('/api/qa/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        query: userQuestion,
        session_id: sessionId.value || undefined,
        top_k: 5
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
          } else if (data.type === 'done') {
            messages.value[msgIndex] = {
              ...messages.value[msgIndex],
              content: fullText,
              references: data.references || []
            }
            if (data.session_id) {
              sessionId.value = data.session_id
              saveHistory(data.session_id, userQuestion)
            }
          } else if (data.type === 'error') {
            messages.value[msgIndex] = { ...messages.value[msgIndex], content: `请求失败: ${data.content}` }
          }
        } catch (e) {
          // 忽略解析错误
        }
      }
    }

    if (!fullText) {
      messages.value[msgIndex] = { ...messages.value[msgIndex], content: '抱歉，请求失败，请检查网络连接或大模型配置。' }
    }

    // 保存会话消息
    if (sessionId.value) {
      sessionMessages.value[sessionId.value] = [...messages.value]
    }
    persistState()
  } catch (e: any) {
    messages.value[msgIndex] = { ...messages.value[msgIndex], content: `抱歉，请求失败: ${e.message || '请检查网络连接或大模型配置。'}` }
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
  }
  ElMessage.info('智能问答系统加载完成')
})
</script>

<style scoped>
.qa-container {
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

.history-search {
  margin-top: 1rem;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 1.5rem;
  overflow: hidden;
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
  max-width: 70%;
}

.message-text {
  padding: 1rem;
  border-radius: 0.75rem;
  line-height: 1.8;
  font-size: 1.05rem;
  white-space: pre-wrap;
}

.message.user .message-text {
  background: #3b82f6;
  color: white;
}

.message.assistant .message-text {
  background: white;
  border: 1px solid #e2e8f0;
  color: #374151;
}

.references {
  margin-top: 1rem;
  padding: 1rem;
  background: #f9fafb;
  border-radius: 0.5rem;
  font-size: 0.95rem;
}

.references h5 {
  margin: 0 0 0.5rem 0;
  color: #64748b;
  font-size: 0.95rem;
}

.references ul {
  margin: 0;
  padding-left: 1.5rem;
  color: #6b7280;
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
