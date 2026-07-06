<template>
  <div class="layout-container">
    <div class="layout-bg">
      <div class="bg-glow bg-glow-1"></div>
      <div class="bg-glow bg-glow-2"></div>
      <div class="bg-grid"></div>
    </div>
    <header class="layout-header">
      <div class="header-inner">
        <div class="header-left">
          <div class="logo-wrap" @click="goToPortal">
            <div class="logo-icon">
              <el-icon :size="18"><Cpu /></el-icon>
            </div>
            <span class="logo-text">智能评估系统</span>
          </div>
          <div class="header-divider"></div>
          <h1 class="page-title">{{ pageTitle }}</h1>
        </div>
        <div class="header-right">
          <el-button :icon="Setting" circle @click="goToAdmin" class="icon-btn" />
          <div class="user-info">
            <el-avatar :size="32" class="user-avatar">
              {{ userStore.username?.charAt(0) || '用' }}
            </el-avatar>
            <span class="username">{{ userStore.username || '评估员' }}</span>
          </div>
        </div>
      </div>
    </header>
    <main class="layout-content">
      <slot></slot>
    </main>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { Setting, Cpu } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const userStore = useUserStore()

const pageTitle = computed(() => {
  const titles: Record<string, string> = {
    'Portal': '',
    'QAService': '智能问答',
    'IndicatorAnalysis': '指标分析',
    'SolutionEvaluation': '方案评估',
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
  position: relative;
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: var(--bg-page);
  overflow: hidden;
}

.layout-bg {
  position: absolute;
  inset: 0;
  pointer-events: none;
  overflow: hidden;
}

.bg-glow {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
  opacity: 0.35;
}

.bg-glow-1 {
  width: 400px;
  height: 400px;
  background: radial-gradient(circle, rgba(59, 130, 246, 0.2) 0%, transparent 70%);
  top: -100px;
  right: -80px;
}

.bg-glow-2 {
  width: 350px;
  height: 350px;
  background: radial-gradient(circle, rgba(16, 185, 129, 0.15) 0%, transparent 70%);
  bottom: -50px;
  left: -80px;
}

.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(148, 163, 184, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(148, 163, 184, 0.06) 1px, transparent 1px);
  background-size: 40px 40px;
  mask-image: radial-gradient(ellipse at center top, black 20%, transparent 60%);
  -webkit-mask-image: radial-gradient(ellipse at center top, black 20%, transparent 60%);
}

.layout-header {
  flex-shrink: 0;
  height: 60px;
  background: rgba(255, 255, 255, 0.8);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border-bottom: 1px solid var(--border-light);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-inner {
  height: 100%;
  max-width: 100%;
  margin: 0 auto;
  padding: 0 32px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 16px;
  flex: 1;
}

.icon-btn {
  --el-button-hover-bg-color: var(--bg-hover);
  --el-button-bg-color: transparent;
  --el-button-border-color: var(--border-light);
  --el-button-hover-border-color: var(--border-normal);
  --el-button-text-color: var(--text-secondary);
  --el-button-hover-text-color: var(--text-primary);
}

.logo-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  transition: opacity var(--transition-fast);
}

.logo-wrap:hover {
  opacity: 0.8;
}

.logo-icon {
  width: 32px;
  height: 32px;
  border-radius: var(--radius-md);
  background: linear-gradient(135deg, var(--primary-500), var(--primary-600));
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
}

.logo-text {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.3px;
}

.header-divider {
  width: 1px;
  height: 22px;
  background: var(--border-light);
  margin: 0 8px;
}

.page-title {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  letter-spacing: 0.3px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-shrink: 0;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 12px 4px 4px;
  border-radius: var(--radius-full);
  background: var(--gray-50);
  transition: background var(--transition-fast);
  cursor: pointer;
}

.user-info:hover {
  background: var(--bg-hover);
}

.user-avatar {
  width: 32px !important;
  height: 32px !important;
  font-size: var(--text-sm) !important;
  background: linear-gradient(135deg, var(--primary-400), var(--primary-600)) !important;
}

.username {
  font-size: var(--text-sm);
  font-weight: 500;
  color: var(--text-secondary);
}

.layout-content {
  flex: 1;
  overflow: hidden;
  position: relative;
  z-index: 1;
}
</style>