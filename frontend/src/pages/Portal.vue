<template>
  <Layout>
    <div class="portal-container">
      <div class="portal-content">
        <div class="logo-section">
          <div class="logo">
            <img src="/logo.jpg" alt="天基" class="logo-img" />
          </div>
          <h1 class="system-name">智能评估系统</h1>
          <p class="system-subtitle">Intelligent Assessment System</p>
        </div>

        <div class="search-section">
          <div class="search-box">
            <el-input
              v-model="searchQuery"
              placeholder="请输入您的问题..."
              size="large"
              class="search-input"
              @keyup.enter="handleSearch"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
              <template #suffix>
                <div class="search-actions">
                  <el-button :icon="Upload" text @click="handleFileUpload" />
                  <el-button :icon="Microphone" text @click="handleVoiceInput" />
                  <el-button :icon="VideoPlay" text @click="handleVoiceOutput" />
                </div>
              </template>
            </el-input>
          </div>

          <div class="tools-row">
            <div
              v-for="tool in tools"
              :key="tool.id"
              class="tool-item"
              @click="navigateToTool(tool.path)"
            >
              <div class="tool-icon">
                <el-icon :size="20" :color="tool.color">
                  <component :is="tool.icon" />
                </el-icon>
              </div>
              <span class="tool-name">{{ tool.name }}</span>
            </div>
          </div>
        </div>

        <div class="systems-section">
          <h3 class="section-title">辅助系统</h3>
          <div class="systems-grid">
            <div
              v-for="system in systems"
              :key="system.id"
              class="system-card"
              @click="navigateToSystem(system.path)"
            >
              <div class="system-icon">
                <el-icon :size="24" :color="system.color">
                  <component :is="system.icon" />
                </el-icon>
              </div>
              <div class="system-info">
                <h4>{{ system.name }}</h4>
                <p>{{ system.description }}</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      style="display: none"
      @change="handleFileChange"
    />
  </Layout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Search, Upload, Microphone, VideoPlay, ChatDotRound, PieChart, Document, Collection, Box, Cpu } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'

const router = useRouter()
const searchQuery = ref('')
const fileInputRef = ref<HTMLInputElement | null>(null)

const tools = [
  {
    id: 1,
    name: '智能问答',
    icon: ChatDotRound,
    color: '#409eff',
    path: '/qa'
  },
  {
    id: 2,
    name: '指标分析',
    icon: PieChart,
    color: '#67c23a',
    path: '/indicator'
  },
  {
    id: 3,
    name: '方案评估',
    icon: Document,
    color: '#e6a23c',
    path: '/evaluation'
  }
]

const systems = [
  {
    id: 1,
    name: '知识库',
    description: '知识管理与检索',
    icon: Collection,
    color: '#909399',
    path: '/knowledge'
  },
  {
    id: 2,
    name: '本体模型',
    description: '本体构建与图谱展示',
    icon: Box,
    color: '#f56c6c',
    path: '/ontology'
  },
  {
    id: 3,
    name: '基础管理',
    description: '系统配置与管理',
    icon: Cpu,
    color: '#5a5ad6',
    path: '/admin'
  }
]

const handleSearch = () => {
  if (!searchQuery.value.trim()) {
    ElMessage.warning('请输入问题')
    return
  }
  ElMessage.info('搜索功能开发中')
}

const handleFileUpload = () => {
  fileInputRef.value?.click()
}

const handleFileChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  const files = target.files
  if (files && files.length > 0) {
    ElMessage.success(`已选择文件: ${files[0].name}`)
  }
}

const handleVoiceInput = () => {
  ElMessage.info('语音输入功能开发中')
}

const handleVoiceOutput = () => {
  ElMessage.info('语音输出功能开发中')
}

const navigateToTool = (path: string) => {
  router.push(path)
}

const navigateToSystem = (path: string) => {
  router.push(path)
}
</script>

<style scoped>
.portal-container {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.portal-content {
  max-width: 700px;
  width: 100%;
  z-index: 10;
  padding: 3rem 2rem;
}

.logo-section {
  text-align: center;
  margin-bottom: 3rem;
}

.logo {
  width: 90px;
  height: 90px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.95);
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1.5rem;
  overflow: hidden;
}

.logo-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.system-name {
  color: white;
  font-size: 2.2rem;
  font-weight: 600;
  margin: 0 0 0.5rem 0;
  letter-spacing: 2px;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.system-subtitle {
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.95rem;
  margin: 0;
  letter-spacing: 1px;
}

.search-section {
  margin-bottom: 3rem;
}

.search-box {
  background: white;
  border-radius: 12px;
  padding: 0.5rem;
  margin-bottom: 1.5rem;
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.15);
}

.search-input :deep(.el-input__wrapper) {
  background: transparent;
  box-shadow: none;
  padding: 1rem 1.5rem;
}

.search-input :deep(.el-input__inner) {
  color: #303133;
  font-size: 1rem;
}

.search-input :deep(.el-input__inner::placeholder) {
  color: #909399;
}

.search-actions {
  display: flex;
  gap: 0.5rem;
}

.tools-row {
  display: flex;
  gap: 1rem;
  justify-content: center;
  flex-wrap: wrap;
}

.tool-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1.2rem;
  background: rgba(255, 255, 255, 0.95);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.tool-item:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.15);
}

.tool-icon {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  background: rgba(64, 158, 255, 0.1);
  display: flex;
  align-items: center;
  justify-content: center;
}

.tool-name {
  color: #303133;
  font-size: 0.9rem;
  font-weight: 500;
}

.systems-section {
  text-align: center;
}

.section-title {
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.9rem;
  font-weight: 600;
  margin: 0 0 1.5rem 0;
  text-transform: uppercase;
  letter-spacing: 2px;
}

.systems-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1.5rem;
}

.system-card {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  cursor: pointer;
  transition: all 0.3s ease;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.system-card:hover {
  transform: translateY(-5px);
  box-shadow: 0 12px 32px rgba(0, 0, 0, 0.15);
}

.system-icon {
  width: 50px;
  height: 50px;
  border-radius: 12px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 1rem;
}

.system-info h4 {
  color: #303133;
  font-size: 0.95rem;
  font-weight: 600;
  margin: 0 0 0.5rem 0;
}

.system-info p {
  color: #909399;
  font-size: 0.8rem;
  margin: 0;
}
</style>
