import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import Layout from '@/components/Layout.vue'
import Portal from '@/pages/Portal.vue'
import QAService from '@/pages/QAService.vue'
import IndicatorAnalysis from '@/pages/IndicatorAnalysis.vue'
import SolutionEvaluation from '@/pages/SolutionEvaluation.vue'
import KnowledgeBase from '@/pages/KnowledgeBase.vue'
import OntologyModel from '@/pages/OntologyModel.vue'
import AdminSystem from '@/pages/AdminSystem.vue'

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
