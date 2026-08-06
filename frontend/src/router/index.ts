import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import Portal from '@/pages/Portal.vue'
import QAService from '@/pages/QAService.vue'
import IndicatorAnalysis from '@/pages/IndicatorAnalysis.vue'
import SolutionEvaluation from '@/pages/SolutionEvaluation.vue'
import KnowledgeBase from '@/pages/KnowledgeBase.vue'
import OntologyModel from '@/pages/OntologyModel.vue'
import OntologyDetail from '@/pages/OntologyDetail.vue'
import OntologyBuild from '@/pages/OntologyBuild.vue'
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
    path: '/ontology/:id',
    name: 'OntologyDetail',
    component: OntologyDetail,
    meta: { title: '本体详情' }
  },
  {
    path: '/ontology-build/:jobId',
    name: 'OntologyBuild',
    component: OntologyBuild,
    meta: { title: '文档构建' }
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
