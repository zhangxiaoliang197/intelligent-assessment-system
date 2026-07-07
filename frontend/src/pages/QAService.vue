<template>
  <Layout>
    <div class="qa-container">
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
        <div class="chat-area custom-scroll" ref="chatArea">
          <div v-if="messages.length === 0" class="empty-state">
            <div class="tags-section">
              <div class="suggest-cards">
                  <div
                    v-for="(item, index) in allQuestions"
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
                <div v-if="msg.role === 'assistant' && !msg.content" class="message-loading">分析中...</div>
                <div v-else class="message-text">
                  <div v-if="msg.knowledgeUsed && msg.role === 'assistant'" class="knowledge-badge">
                    <el-tag size="small" type="primary" effect="plain">含知识库参考</el-tag>
                  </div>
                  {{ msg.content }}
                </div>
                <div v-if="msg.references && msg.references.length > 0" class="references">
                  <h5>参考来源：</h5>
                  <ul>
                    <li v-for="(ref, idx) in msg.references" :key="idx">
                      {{ ref }}
                      <el-tag v-if="ref.includes('知识库')" size="small" type="primary" effect="plain">知识库</el-tag>
                      <el-tag v-else size="small" type="info" effect="plain">AI生成</el-tag>
                    </li>
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
import { ref, onMounted, computed, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Collection, Box, ChatLineRound, ChatDotRound, Promotion, PieChart, Document, Plus, Delete, ArrowRight, Aim, Guide, DataAnalysis, Shield, CircleCheck } from '@element-plus/icons-vue'
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
const chatArea = ref<HTMLElement | null>(null)
const historyList = ref<Array<any>>(JSON.parse(localStorage.getItem(LS_HISTORY_LIST) || '[]'))
const sessionMessages = ref<Record<string, Array<any>>>(JSON.parse(localStorage.getItem(LS_SESSION_MSGS) || '{}'))

// 持久化辅助函数
const persistState = () => {
  localStorage.setItem(LS_SESSION_ID, sessionId.value)
  localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
  localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
}

const recommendedQuestions = [
  {
    text: '作战效能指标有哪些？',
    desc: '了解作战效能评估的核心指标体系',
    icon: 'Aim',
    color: '#3b82f6'
  },
  {
    text: '如何评估打击能力？',
    desc: '分析装备打击能力的评估方法',
    icon: 'Guide',
    color: '#ef4444'
  },
  {
    text: '评估方案查询',
    desc: '快速检索已有的评估方案',
    icon: 'Document',
    color: '#10b981'
  },
  {
    text: '指标算法详解',
    desc: '深入了解各项指标的计算方法',
    icon: 'DataAnalysis',
    color: '#f59e0b'
  }
]

const hotQuestions = [
  {
    text: '生存能力指标',
    desc: '装备战场生存能力评估维度',
    icon: 'Shield',
    color: '#8b5cf6'
  },
  {
    text: '保障能力指标',
    desc: '后勤保障能力评估体系',
    icon: 'Box',
    color: '#06b6d4'
  },
  {
    text: '任务完成度评估',
    desc: '作战任务完成情况分析方法',
    icon: 'CircleCheck',
    color: '#ec4899'
  },
  {
    text: '综合效能分析',
    desc: '多维度综合作战效能评估',
    icon: 'PieChart',
    color: '#14b8a6'
  }
]

const allQuestions = computed(() => [
  ...recommendedQuestions.map(q => ({ ...q, isHot: false })),
  ...hotQuestions.map(q => ({ ...q, isHot: true }))
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

const scrollToBottom = () => {
  if (chatArea.value) {
    chatArea.value.scrollTop = chatArea.value.scrollHeight
  }
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
  nextTick(() => scrollToBottom())

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
            nextTick(() => scrollToBottom())
          } else if (data.type === 'done') {
            messages.value[msgIndex] = {
              ...messages.value[msgIndex],
              content: fullText,
              references: data.references || [],
              knowledgeUsed: data.knowledge_used || false
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
}

.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 8px;
}

.sidebar-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.5px;
  margin: 0;
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

.nav-item .el-icon {
  font-size: 18px;
}

.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
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
  background: var(--bg-card);
  border-left: 1px solid var(--border-light);
  border-right: 1px solid var(--border-light);
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 40px 0 20px;
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
  max-width: 80%;
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

.message.user .message-avatar {
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
}

.references {
  margin-top: 8px;
  padding: 12px 16px;
  background: var(--gray-50);
  border-radius: 12px;
  font-size: 13px;
  border: 1px solid var(--border-light);
}

.references h5 {
  margin: 0 0 8px 0;
  color: var(--text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.references ul {
  margin: 0;
  padding-left: 20px;
  color: var(--text-tertiary);
}

.input-area {
  flex-shrink: 0;
  padding: 16px 40px 24px;
  background: linear-gradient(to top, var(--bg-card) 60%, transparent);
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
  display: flex;
  align-items: center;
  justify-content: center;
  color: inherit;
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

.message-loading {
  padding: 12px 0;
  color: var(--text-muted);
  font-size: 14px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.message-loading::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary-500);
  animation: loading-pulse 1.2s ease-in-out infinite;
}

@keyframes loading-pulse {
  0%, 100% { opacity: 0.3; }
  50% { opacity: 1; }
}

.knowledge-badge {
  margin-bottom: 8px;
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
  justify-content: flex-end;
}

.input-actions .el-button {
  height: 38px;
  padding: 0 22px;
  border-radius: 10px;
  font-weight: 500;
  font-size: 14px;
}

@media (max-width: 768px) {
  .qa-container {
    padding: 0;
    gap: 0;
  }
  
  .sidebar {
    width: 200px;
    padding: 12px 8px;
  }
  
  .chat-area {
    padding: 20px 0 16px;
  }
  
  .message-list {
    padding: 0 20px;
  }
  
  .input-area {
    padding: 12px 20px 20px;
  }
  
  .message-content {
    max-width: 85%;
  }
  
  .tags-section {
    padding: 0 20px;
  }
  
  .tags {
    grid-template-columns: 1fr;
  }
}
</style>
