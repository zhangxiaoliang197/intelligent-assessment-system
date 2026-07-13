<template>
  <div class="portal-page">
    <div class="portal-bg">
      <div class="bg-glow bg-glow-1"></div>
      <div class="bg-glow bg-glow-2"></div>
      <div class="bg-grid"></div>
    </div>

    <div class="portal-wrapper">
      <header class="portal-header">
        <div class="header-left">
          <div class="logo-wrap">
            <div class="logo-icon">
              <img src="/logo.jfif" alt="天智" class="logo-img" />
            </div>
            <span class="logo-text">天智智能评估系统</span>
          </div>
        </div>
        <div class="header-right">
          <el-button :icon="Setting" circle @click="goToAdmin" />
          <el-avatar :size="36">{{ username?.charAt(0) || '用' }}</el-avatar>
        </div>
      </header>

      <main class="portal-main">
        <section class="hero-section">
          <div class="hero-icon">
            <img src="/logo.jfif" alt="天智" class="hero-logo-img" />
          </div>
          <h1 class="hero-title">
            有什么可以帮您评估？
          </h1>
          <p class="hero-subtitle">
            基于知识库与本体模型，为您提供智能问答、指标分析、评估分析等专业能力
          </p>
        </section>

        <section class="search-section">
          <div class="search-box">
            <el-input
              v-model="searchQuery"
              placeholder="请输入您的问题，回车或点击发送"
              size="large"
              class="search-input"
              @keyup.enter="handleSearch"
            >
              <template #prefix>
                <el-icon class="search-prefix-icon"><Search /></el-icon>
              </template>
              <template #suffix>
                <div class="search-suffix">
                  <el-button :icon="Upload" circle @click="handleFileUpload" />
                  <el-button type="primary" :icon="Promotion" @click="handleSearch">
                    发送
                  </el-button>
                </div>
              </template>
            </el-input>
          </div>

          <!-- 附件标签 -->
          <div v-if="attachments.length > 0" class="attachment-chips">
            <el-tag
              v-for="(att, idx) in attachments"
              :key="idx"
              :type="att.status === 'success' ? 'success' : att.status === 'uploading' ? 'warning' : 'danger'"
              closable
              size="small"
              @close="removeAttachment(idx)"
            >
              <el-icon v-if="att.status === 'uploading'"><Loading /></el-icon>
              {{ att.filename }}
            </el-tag>
          </div>

          <div class="tools-row">
            <div
              v-for="tool in tools"
              :key="tool.id"
              class="tool-pill"
              :style="{ '--tool-color': tool.color }"
              @click="navigateToTool(tool.path)"
            >
              <el-icon :size="16">
                <component :is="tool.icon" />
              </el-icon>
              <span>{{ tool.name }}</span>
            </div>
          </div>
        </section>

        <section class="suggest-section">
          <div class="section-header">
            <h3 class="section-title">推荐试试这些</h3>
          </div>
          <div class="suggest-grid">
            <div
              v-for="item in suggestList"
              :key="item.id"
              class="suggest-card"
              @click="selectSuggest(item)"
            >
              <div class="suggest-icon" :style="{ '--icon-color': item.color }">
                <el-icon :size="18">
                  <component :is="item.icon" />
                </el-icon>
              </div>
              <div class="suggest-content">
                <h4>{{ item.title }}</h4>
                <p>{{ item.desc }}</p>
              </div>
              <el-icon class="suggest-arrow"><ArrowRight /></el-icon>
            </div>
          </div>
        </section>
      </main>

      <footer class="portal-footer">
        <span>天智智能评估系统 · Tianzhi Intelligent Assessment</span>
      </footer>
    </div>

    <FloatingSidebar />

    <input
      ref="fileInputRef"
      type="file"
      accept=".pdf,.doc,.docx,.txt"
      style="display: none"
      @change="handleFileChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  Upload,
  Promotion,
  ChatDotRound,
  PieChart,
  Document,
  Setting,
  ArrowRight,
  Guide,
  DataAnalysis,
  Aim,
  Box,
  Loading
} from '@element-plus/icons-vue'
import FloatingSidebar from '@/components/FloatingSidebar.vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useAttachmentUpload } from '@/composables/useAttachmentUpload'

const router = useRouter()
const userStore = useUserStore()
const searchQuery = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const { attachments, uploading, upload: uploadFile, remove: removeAttachment, getAttachmentId } = useAttachmentUpload()

const username = userStore.username || '评估员'

const tools = [
  {
    id: 1,
    name: '智能问答',
    icon: ChatDotRound,
    color: '#3b82f6',
    path: '/qa'
  },
  {
    id: 2,
    name: '指标分析',
    icon: PieChart,
    color: '#10b981',
    path: '/indicator'
  },
  {
    id: 3,
    name: '评估分析',
    icon: Document,
    color: '#f59e0b',
    path: '/evaluation'
  }
]

const suggestList = [
  {
    id: 1,
    title: '装备作战效能评估',
    desc: '分析装备在复杂战场环境下的综合作战效能',
    icon: Aim,
    color: '#3b82f6'
  },
  {
    id: 2,
    title: '战斗力指标体系分析',
    desc: '构建并分析战斗力相关的关键指标体系',
    icon: DataAnalysis,
    color: '#10b981'
  },
  {
    id: 3,
    title: '作战方案可行性评估',
    desc: '对多套作战方案进行智能对比与评估',
    icon: Guide,
    color: '#f59e0b'
  },
  {
    id: 4,
    title: '知识库检索问答',
    desc: '基于知识库内容进行精准问答与知识溯源',
    icon: ChatDotRound,
    color: '#8b5cf6'
  },
  {
    id: 5,
    title: '本体模型关系图谱',
    desc: '可视化展示本体模型的数据关联与层次结构',
    icon: Box,
    color: '#ec4899'
  },
  {
    id: 6,
    title: '评估算法配置管理',
    desc: '配置与管理各类评估指标的计算算法',
    icon: PieChart,
    color: '#06b6d4'
  }
]

const handleSearch = () => {
  if (!searchQuery.value.trim() && getAttachmentId().length === 0) {
    ElMessage.warning('请输入问题或上传文件')
    return
  }
  // 将 attachment_id 通过 sessionStorage 传递给目标页面
  const attId = getAttachmentId()
  if (attId) {
    sessionStorage.setItem('portal_attachment_id', attId)
    sessionStorage.setItem('portal_attachment_filename', attachments.value.find(a => a.status === 'success')?.filename || '')
  }
  router.push({
    path: '/qa',
    query: { q: searchQuery.value || undefined }
  })
}

const handleFileUpload = () => {
  fileInputRef.value?.click()
}

const handleFileChange = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (!files || files.length === 0) return
  const file = files[0]
  const result = await uploadFile(file)
  target.value = '' // 重置以允许重复选择
  if (result && result.status === 'success') {
    ElMessage.success(`${file.name} 解析完成（${result.text_length} 字符）`)
  } else {
    ElMessage.error(`${file.name} 上传失败`)
  }
}

const selectSuggest = (item: any) => {
  searchQuery.value = item.title
  setTimeout(() => {
    handleSearch()
  }, 100)
}

const navigateToTool = (path: string) => {
  router.push(path)
}

const goToAdmin = () => {
  router.push('/admin')
}
</script>

<style scoped>
.portal-page {
  position: relative;
  min-height: 100vh;
  background: var(--bg-page);
  overflow-x: hidden;
}

.portal-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: 0.4;
}

.bg-glow-1 {
  width: 500px;
  height: 500px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.25) 0%, transparent 70%);
  top: -150px;
  right: -100px;
}

.bg-glow-2 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.15) 0%, transparent 70%);
  bottom: 10%;
  left: -100px;
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.1) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.1) 1px, transparent 1px);
  background-size: 60px 60px;
  mask-image: radial-gradient(ellipse at center top, black 30%, transparent 70%);
  -webkit-mask-image: radial-gradient(ellipse at center top, black 30%, transparent 70%);
}

.portal-wrapper {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  max-width: 1100px;
  margin: 0 auto;
  padding: 0 180px 0 80px;
}

.portal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
}

.logo-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
}

.logo-icon {
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.logo-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.logo-text {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.5px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.portal-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: center;
  padding: 40px 0;
  gap: 48px;
}

.hero-section {
  text-align: center;
}

.hero-icon {
  width: 88px;
  height: 88px;
  margin: 0 auto 20px;
  border-radius: var(--radius-xl);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.25);
}

.hero-logo-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.hero-title {
  font-size: 36px;
  font-weight: 700;
  color: var(--text-primary);
  margin: 0 0 12px 0;
  letter-spacing: -0.5px;
  line-height: 1.3;
}

.hero-subtitle {
  font-size: var(--text-lg);
  color: var(--text-tertiary);
  margin: 0;
  max-width: 600px;
  margin-left: auto;
  margin-right: auto;
  line-height: 1.6;
}

.search-section {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 20px;
}

.search-box {
  width: 100%;
  max-width: 720px;
}

.search-input {
  font-size: var(--text-lg);
}

.search-prefix-icon {
  color: var(--text-muted);
  font-size: 18px;
}

.search-suffix {
  display: flex;
  align-items: center;
  gap: 8px;
}

.search-suffix .el-button {
  height: 36px;
}

.tools-row {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: center;
}

.tool-pill {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 18px;
  background: var(--bg-card);
  border: 1px solid var(--border-normal);
  border-radius: var(--radius-full);
  cursor: pointer;
  transition: all var(--transition-fast);
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.tool-pill:hover {
  border-color: var(--tool-color);
  color: var(--tool-color);
  background: color-mix(in srgb, var(--tool-color) 8%, white);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.06);
}

.tool-pill .el-icon {
  color: var(--tool-color);
}

.section-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 16px;
}

.section-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.section-desc {
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.suggest-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.suggest-card {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 16px;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  cursor: pointer;
  transition: all var(--transition-fast);
}

.suggest-card:hover {
  border-color: var(--border-normal);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.suggest-icon {
  flex-shrink: 0;
  width: 36px;
  height: 36px;
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--icon-color) 12%, white);
  color: var(--icon-color);
  display: flex;
  align-items: center;
  justify-content: center;
}

.suggest-content {
  flex: 1;
  min-width: 0;
}

.suggest-content h4 {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0 0 4px 0;
}

.suggest-content p {
  font-size: var(--text-sm);
  color: var(--text-tertiary);
  margin: 0;
  line-height: 1.5;
}

.suggest-arrow {
  flex-shrink: 0;
  color: var(--text-muted);
  opacity: 0;
  transition: all var(--transition-fast);
  align-self: center;
}

.suggest-card:hover .suggest-arrow {
  opacity: 1;
  transform: translateX(2px);
  color: var(--primary-500);
}

.portal-footer {
  flex-shrink: 0;
  text-align: center;
  padding: 24px 0;
  font-size: var(--text-sm);
  color: var(--text-muted);
}

.attachment-chips {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: center;
  margin-top: 2px;
}

@media (max-width: 768px) {
  .portal-wrapper {
    padding: 0 20px;
  }

  .hero-title {
    font-size: 28px;
  }

  .hero-subtitle {
    font-size: var(--text-base);
  }

  .suggest-grid {
    grid-template-columns: 1fr;
  }
}
</style>
