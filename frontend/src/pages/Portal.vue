<template>
  <div class="portal-page">
    <div class="portal-bg" aria-hidden="true"></div>

    <div class="portal-wrapper">
      <header class="portal-header">
        <div class="header-left">
          <div class="logo-wrap" @click="goToPortal">
            <div class="logo-icon">
              <img src="/logo.jfif" alt="天智" class="logo-img" />
            </div>
            <span class="logo-text">天智智能评估系统</span>
          </div>
        </div>
        <div class="header-right">
          <!-- 顶部胶囊导航：与封面版式一致 -->
          <button
            v-for="nav in navItems"
            :key="nav.id"
            type="button"
            class="nav-pill"
            @click="navigateToTool(nav.path)"
          >
            <el-icon :size="15"><component :is="nav.icon" /></el-icon>
            <span>{{ nav.name }}</span>
          </button>
          <el-avatar :size="36">{{ username?.charAt(0) || '用' }}</el-avatar>
        </div>
      </header>

      <main class="portal-main">
        <section class="hero-section">
          <h1 class="hero-title">
            提出评估构想，分析全局走向
          </h1>
          <p class="hero-subtitle">
            我可以帮您进行指标体系构建、评估模型构建、指标溯源、评估结果归因、趋势预测、评估报告生成。
          </p>
        </section>

        <section class="search-section">
          <div class="search-box">
            <el-input
              v-model="searchQuery"
              size="large"
              class="search-input"
              :placeholder="inputPlaceholder"
              @keydown="sendMessageOnEnter($event, handleSearch)"
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

          <!-- 模块入口：横向小胶囊（图标+文字），与封面版式一致 -->
          <div class="tools-row">
            <button
              v-for="tool in tools"
              :key="tool.id"
              type="button"
              class="tool-btn"
              :style="{ '--tool-color': tool.color }"
              @click="navigateToTool(tool.path)"
            >
              <el-icon :size="17"><component :is="tool.icon" /></el-icon>
              <span class="tool-name">{{ tool.name }}</span>
            </button>
          </div>
        </section>

        <!-- 推荐卡片区：收进左栏，紧凑 3 列小卡，与封面版式一致 -->
        <section class="suggest-section">
          <h3 class="section-title">推荐试试这些</h3>
          <div class="suggest-grid">
            <div
              v-for="item in suggestList"
              :key="item.id"
              class="suggest-card"
              @click="selectSuggest(item)"
            >
              <div class="card-head">
                <span class="suggest-icon" :style="{ '--icon-color': item.color }">
                  <el-icon :size="15">
                    <component :is="item.icon" />
                  </el-icon>
                </span>
                <h4>{{ item.title }}</h4>
              </div>
              <p class="card-desc">{{ item.desc }}</p>
            </div>
          </div>
        </section>
      </main>
    </div>

    <footer class="portal-footer">
      <span>天智智能评估系统 · Tianzhi Intelligent Assessment</span>
    </footer>

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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Search,
  Upload,
  Promotion,
  ChatDotRound,
  PieChart,
  Document,
  Setting,
  Guide,
  DataAnalysis,
  Aim,
  Box,
  Loading,
  MagicStick,
  Collection,
  Share
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { useAttachmentUpload } from '@/composables/useAttachmentUpload'
import { sendMessageOnEnter } from '@/utils/messageInput'

const router = useRouter()
const userStore = useUserStore()
const searchQuery = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)
const { attachments, uploading: _uploading, upload: uploadFile, remove: removeAttachment, getAttachmentId } = useAttachmentUpload()

const username = userStore.username || '评估员'

// 移动端输入框宽度有限，缩短占位文案避免被截断
const isNarrow = ref(false)
const inputPlaceholder = computed(() =>
  isNarrow.value ? '请输入您的问题' : '请输入您的问题，回车或点击发送'
)
const syncViewport = () => {
  isNarrow.value = window.innerWidth <= 768
}

onMounted(() => {
  syncViewport()
  window.addEventListener('resize', syncViewport)
})

onUnmounted(() => {
  window.removeEventListener('resize', syncViewport)
})

// 顶部胶囊导航项
const navItems = [
  { id: 1, name: '知识库', icon: Collection, path: '/knowledge' },
  { id: 2, name: '动态本体', icon: Share, path: '/ontology' },
  { id: 3, name: '基础管理', icon: Setting, path: '/admin' }
]

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
    color: '#0ea5e9',
    path: '/indicator'
  },
  {
    id: 3,
    name: '评估分析',
    icon: Document,
    color: '#f59e0b',
    path: '/evaluation'
  },
  {
    id: 4,
    name: '态势页面',
    icon: MagicStick,
    color: '#10b981',
    path: '/situation-page'
  }
]

const suggestList = [
  {
    id: 1,
    title: '行动评估指标推荐',
    desc: '构建典型场景下不同阶段各类行动的指标体系',
    icon: Aim,
    color: '#3b82f6'
  },
  {
    id: 2,
    title: '任务完成度指标计算',
    desc: '问答交互构建计算模型，智能计算并可视化呈现',
    icon: DataAnalysis,
    color: '#10b981'
  },
  {
    id: 3,
    title: '指标结果归因分析',
    desc: '基于动态本体进行指标结果数据溯源与归因分析',
    icon: Guide,
    color: '#f59e0b'
  },
  {
    id: 4,
    title: '专题态势图生成',
    desc: '生成统计图表与态势图结合的特定场景专题分析',
    icon: ChatDotRound,
    color: '#8b5cf6'
  },
  {
    id: 5,
    title: '评估报告生成',
    desc: '报告模板拆解、数据查询填充、结果串联结论生成',
    icon: Box,
    color: '#ec4899'
  },
  {
    id: 6,
    title: '区域掌控能力分析',
    desc: '通过制权能力分析智能体进行理解编排、调度计算',
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

const goToPortal = () => {
  // 已在主页时点击 logo 回到顶部，否则跳转主页
  if (router.currentRoute.value.path === '/') {
    window.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
  router.push('/')
}
</script>

<style scoped>
.portal-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  color: #06182a;
  overflow-x: hidden;
}

/* ── 全屏背景 ── */
.portal-bg {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
  background: #2ea9f6 url('/portal-bg.jfif') center center / cover no-repeat;
}

.portal-bg::after {
  content: '';
  position: absolute;
  inset: 0;
  background:
    radial-gradient(ellipse 58% 72% at 24% 46%, rgba(255, 255, 255, 0.42) 0%, rgba(255, 255, 255, 0) 72%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.08) 0%, rgba(255, 255, 255, 0) 40%, rgba(255, 255, 255, 0.22) 100%);
}

.portal-wrapper {
  position: relative;
  z-index: 1;
  flex: 1 0 auto;
  display: flex;
  flex-direction: column;
  width: 100%;
  padding: 0 clamp(20px, 4.5vw, 88px);
}

/* ── 顶栏 ── */
.portal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 80px;
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
  cursor: pointer;
}

.logo-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: rgba(255, 255, 255, 0.85);
  border: 1px solid rgba(255, 255, 255, 0.95);
  box-shadow: 0 4px 14px rgba(6, 44, 74, 0.14);
}

.logo-img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.logo-text {
  font-size: 19px;
  font-weight: 700;
  color: #06182a;
  letter-spacing: 0.5px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* ── 顶部胶囊导航 ── */
.nav-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 15px;
  font-family: inherit;
  font-size: 13.5px;
  font-weight: 500;
  color: #0b3550;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(255, 255, 255, 0.9);
  border-radius: 999px;
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: 0 6px 16px rgba(6, 44, 74, 0.1);
  backdrop-filter: blur(10px);
}

.nav-pill:hover {
  background: #fff;
  color: #0b6cc4;
  border-color: rgba(46, 169, 246, 0.6);
  transform: translateY(-1px);
}

.header-right :deep(.el-avatar) {
  background: rgba(255, 255, 255, 0.9);
  color: #0b6cc4;
  border: 1px solid rgba(255, 255, 255, 0.95);
}

/* ── 主内容：全部收进左侧栏，右侧留给背景主视觉 ── */
.portal-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  width: min(900px, 48%);
  padding-top: clamp(28px, 7vh, 90px);
  padding-bottom: clamp(16px, 3vh, 34px);
}

.hero-section {
  text-align: left;
}

.hero-title {
  margin: 0;
  font-size: clamp(30px, 3.25vw, 62px);
  font-weight: 800;
  line-height: 1.22;
  letter-spacing: 1px;
  color: #06182a;
  text-wrap: balance;
}

.hero-subtitle {
  margin: 16px 0 0;
  max-width: 100%;
  font-size: 15.5px;
  line-height: 1.7;
  color: #10618c;
}

/* ── 搜索区 ── */
.search-section {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 18px;
  width: 100%;
  margin-top: clamp(24px, 4vh, 40px);
}

.search-box {
  width: 100%;
  max-width: 560px;
}

.search-section .search-input :deep(.el-input__wrapper) {
  padding: 8px 8px 8px 18px !important;
  border-radius: 16px !important;
  background: #fff !important;
  border: none;
  box-shadow:
    inset 0 0 0 1px rgba(13, 88, 140, 0.38),
    0 18px 40px rgba(6, 44, 74, 0.26) !important;
}

.search-section .search-input :deep(.el-input__wrapper:hover) {
  box-shadow:
    inset 0 0 0 1px rgba(46, 169, 246, 0.75),
    0 18px 40px rgba(6, 44, 74, 0.28) !important;
}

.search-section .search-input :deep(.el-input.is-focus .el-input__wrapper) {
  box-shadow:
    inset 0 0 0 1px #2ea9f6,
    0 0 0 3px rgba(46, 169, 246, 0.22),
    0 18px 40px rgba(6, 44, 74, 0.3) !important;
}

.search-input :deep(.el-input__inner) {
  color: #0b3550;
  font-size: 16px;
}

.search-input :deep(.el-input__inner::placeholder) {
  color: #54748a;
}

.search-prefix-icon {
  color: #7aa8c4;
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

.search-suffix :deep(.el-button.is-circle) {
  background: #f0f8ff;
  border-color: rgba(46, 169, 246, 0.28);
  color: #0f7ce3;
}

.search-suffix :deep(.el-button.is-circle:hover) {
  background: #e2f4ff;
  border-color: #2ea9f6;
  color: #0b6cc4;
}

/* ── 模块入口：横向小胶囊 ── */
.tools-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.tool-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 9px 16px;
  font-family: inherit;
  color: var(--tool-color);
  background: rgba(255, 255, 255, 0.78);
  border: 1px solid rgba(255, 255, 255, 0.92);
  border-radius: 999px;
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: 0 8px 20px rgba(6, 44, 74, 0.12);
  backdrop-filter: blur(10px);
}

.tool-btn:hover {
  background: #fff;
  border-color: color-mix(in srgb, var(--tool-color) 45%, white);
  transform: translateY(-2px);
  box-shadow: 0 12px 26px rgba(6, 44, 74, 0.18);
}

.tool-name {
  font-size: 13.5px;
  font-weight: 500;
  color: #0b3550;
  white-space: nowrap;
}

/* ── 推荐卡片区：紧凑小卡直接排在左栏 ── */
.suggest-section {
  /* 布局整体下移，与搜索区拉开距离 */
  margin-top: clamp(34px, 5.5vh, 56px);
}

.section-title {
  margin: 0 0 14px;
  font-size: 17px;
  font-weight: 700;
  color: #06182a;
}

.suggest-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  /* 卡片整体比主栏更窄，进一步缩短卡片长度 */
  width: 85%;
}

.suggest-card {
  padding: 13px 14px 12px;
  background: rgba(255, 255, 255, 0.94);
  border: 1px solid rgba(255, 255, 255, 0.95);
  border-radius: 8px;
  cursor: pointer;
  transition: all var(--transition-fast);
  box-shadow: 0 10px 24px rgba(6, 44, 74, 0.12);
  backdrop-filter: blur(8px);
}

.suggest-card:hover {
  border-color: rgba(46, 169, 246, 0.55);
  box-shadow: 0 14px 30px rgba(15, 124, 227, 0.16);
  transform: translateY(-2px);
}

.card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.card-head h4 {
  margin: 0;
  font-size: 14.5px;
  font-weight: 600;
  color: #0b2436;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggest-icon {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--icon-color) 14%, white);
  color: var(--icon-color);
}

.card-desc {
  margin: 7px 0 0;
  font-size: 12.5px;
  line-height: 1.55;
  color: #4f7089;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

/* ── 页脚 ── */
.portal-footer {
  position: relative;
  z-index: 1;
  flex-shrink: 0;
  text-align: center;
  padding: 0 40px 22px;
}

.portal-footer span {
  color: #2c5a75;
  font-size: 12.5px;
  letter-spacing: 0.3px;
}

.attachment-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

/* ── 响应式 ── */
@media (max-width: 1300px) {
  .portal-main {
    width: min(720px, 52%);
    /* 压缩纵向节奏，保证 800 高度视口下页脚仍在一屏内 */
    padding-top: clamp(20px, 4vh, 40px);
    padding-bottom: 20px;
  }

  .suggest-section {
    margin-top: 24px;
  }

  .suggest-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 1100px) {
  .portal-main {
    width: min(620px, calc(100% - 280px));
  }
}

@media (max-width: 900px) {
  .portal-wrapper {
    padding: 0 28px;
  }

  .portal-main {
    width: 100%;
    max-width: 640px;
    padding-top: 40px;
  }
}

@media (max-width: 768px) {
  .portal-wrapper {
    padding: 0 20px;
  }

  .portal-header {
    height: 64px;
  }

  .nav-pill {
    display: none;
  }

  .hero-title {
    font-size: 28px;
    letter-spacing: 0.5px;
  }

  .hero-subtitle {
    margin-top: 12px;
    font-size: 14px;
  }

  .search-section {
    margin-top: 24px;
    gap: 14px;
  }

  .search-box {
    max-width: 100%;
  }

  .suggest-grid {
    grid-template-columns: 1fr;
    gap: 10px;
  }

  .portal-footer {
    padding: 0 20px 18px;
  }
}
</style>
