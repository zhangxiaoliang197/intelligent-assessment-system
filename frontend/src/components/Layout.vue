<template>
  <div class="layout-container">
    <div class="header">
      <div class="header-left">
        <el-button :icon="HomeFilled" circle @click="goToPortal" class="header-btn" />
        <el-avatar :size="36" :src="userStore.avatar" class="header-avatar">
          {{ userStore.username?.charAt(0) }}
        </el-avatar>
        <span class="username">{{ userStore.username }}</span>
      </div>
      <div class="header-center">
        <h1 class="system-title">{{ pageTitle }}</h1>
      </div>
      <div class="header-right">
        <el-button :icon="Setting" circle @click="goToAdmin" class="header-btn" />
      </div>
    </div>
    <div class="content">
      <slot></slot>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { HomeFilled, Setting } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    'Portal': '',
    'QAService': '智能问答',
    'IndicatorAnalysis': '指标分析',
    'EvaluationScheme': '方案评估',
    'KnowledgeBase': '知识库',
    'OntologyModel': '本体模型',
    'AdminSystem': '基础管理系统'
  }
  return titles[route.name as string] || ''
})

const goToPortal = () => {
  router.push('/')
}

const goToAdmin = () => {
  router.push('/admin')
}
</script>

<style scoped>
.layout-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.75rem 1.5rem;
  background: rgba(255, 255, 255, 0.15);
  backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(255, 255, 255, 0.2);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.header-btn {
  background: rgba(255, 255, 255, 0.2) !important;
  border: 1px solid rgba(255, 255, 255, 0.3) !important;
  color: white !important;
  transition: all 0.3s ease;
}

.header-btn:hover {
  background: rgba(255, 255, 255, 0.3) !important;
  border-color: rgba(255, 255, 255, 0.5) !important;
}

.header-avatar {
  background: rgba(255, 255, 255, 0.3);
  border: 2px solid rgba(255, 255, 255, 0.5);
  color: white;
  font-weight: 600;
}

.username {
  color: white;
  font-size: 0.95rem;
  font-weight: 500;
}

.header-center {
  flex: 1;
  display: flex;
  justify-content: center;
}

.system-title {
  color: white;
  font-size: 1.1rem;
  font-weight: 600;
  margin: 0;
  letter-spacing: 1px;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.content {
  flex: 1;
  overflow: hidden;
}
</style>
