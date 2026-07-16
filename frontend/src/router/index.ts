import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'

// 页面按路由懒加载，避免用户进入评估页前下载管理、知识库和图表模块的全部代码。
const Portal = () => import('@/pages/Portal.vue')
const QAService = () => import('@/pages/QAService.vue')
const IndicatorAnalysis = () => import('@/pages/IndicatorAnalysis.vue')
const SolutionEvaluation = () => import('@/pages/SolutionEvaluation.vue')
const KnowledgeBase = () => import('@/pages/KnowledgeBase.vue')
const OntologyModel = () => import('@/pages/OntologyModel.vue')
const AdminSystem = () => import('@/pages/AdminSystem.vue')

const routes: Array<RouteRecordRaw> = [
  {
    path: '/',
    name: 'Portal',
    component: Portal
  },
  {
    path: '/qa',
    name: 'QAService',
    component: QAService
  },
  {
    path: '/indicator',
    name: 'IndicatorAnalysis',
    component: IndicatorAnalysis
  },
  {
    path: '/evaluation',
    name: 'SolutionEvaluation',
    component: SolutionEvaluation
  },
  {
    path: '/knowledge',
    name: 'KnowledgeBase',
    component: KnowledgeBase
  },
  {
    path: '/ontology',
    name: 'OntologyModel',
    component: OntologyModel
  },
  {
    path: '/admin',
    name: 'AdminSystem',
    component: AdminSystem
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
