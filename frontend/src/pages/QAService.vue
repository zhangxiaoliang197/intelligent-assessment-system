<template>
  <Layout>
    <div class="qa-container">
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
              v-for="item in historyList"
              :key="item.id"
              class="history-item"
              @click="loadHistory(item)"
            >
              <el-icon><ChatLineRound /></el-icon>
              <span>{{ item.title }}</span>
            </div>
          </div>
        </div>
      </div>
      <div class="main-content">
        <div class="search-bar">
          <el-input
            v-model="searchQuery"
            placeholder="搜索问答记录..."
            :prefix-icon="Search"
            clearable
          />
        </div>
        <div class="tags-section">
          <div class="tag-group">
            <h4>推荐问题</h4>
            <div class="tags">
              <el-tag
                v-for="tag in recommendedQuestions"
                :key="tag"
                class="tag-item"
                @click="selectQuestion(tag)"
              >
                {{ tag }}
              </el-tag>
            </div>
          </div>
          <div class="tag-group">
            <h4>热门问题</h4>
            <div class="tags">
              <el-tag
                v-for="tag in hotQuestions"
                :key="tag"
                type="warning"
                class="tag-item"
                @click="selectQuestion(tag)"
              >
                {{ tag }}
              </el-tag>
            </div>
          </div>
        </div>
        <div class="chat-area custom-scroll">
          <div v-if="messages.length === 0" class="empty-state">
            <el-icon :size="80" color="#d1d5db"><ChatDotRound /></el-icon>
            <p>开始智能问答之旅</p>
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
      </div>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Collection, Box, ChatLineRound, ChatDotRound, Promotion } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const router = useRouter()
const searchQuery = ref('')
const inputMessage = ref('')
const sessionId = ref('')
const messages = ref<Array<any>>([])
const historyList = ref([
  { id: 1, title: '作战效能指标体系' },
  { id: 2, title: '打击能力评估方法' },
  { id: 3, title: '历史方案查询' }
])

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

const goTo = (path: string) => {
  router.push(path)
}

const loadHistory = (item: any) => {
  ElMessage.info('加载历史记录')
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

  messages.value.push({
    role: 'user',
    content: inputMessage.value
  })

  const userQuestion = inputMessage.value
  inputMessage.value = ''

  const loadingMsg = {
    role: 'assistant',
    content: '正在思考...'
  }
  messages.value.push(loadingMsg)

  try {
    const data = await api.post('/qa/chat', {
      query: userQuestion,
      session_id: sessionId.value,
      top_k: 5
    })
    messages.value.pop()
    messages.value.push({
      role: 'assistant',
      content: data.answer,
      references: data.references || []
    })
    if (data.session_id) {
      sessionId.value = data.session_id
    }
  } catch (e) {
    messages.value.pop()
    messages.value.push({
      role: 'assistant',
      content: '抱歉，请求失败，请检查网络连接或大模型配置。'
    })
  }
}

onMounted(() => {
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

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding: 1.5rem;
  overflow: hidden;
}

.search-bar {
  margin-bottom: 1.5rem;
}

.tags-section {
  margin-bottom: 1.5rem;
}

.tag-group {
  margin-bottom: 1rem;
}

.tag-group h4 {
  font-size: 0.9rem;
  color: #64748b;
  margin-bottom: 0.75rem;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.tag-item {
  cursor: pointer;
  transition: all 0.2s;
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
  justify-content: center;
  height: 100%;
  color: #9ca3af;
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

.input-actions {
  margin-top: 1rem;
  display: flex;
  justify-content: flex-end;
}
</style>
