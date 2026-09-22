import { createRouter, createWebHistory, RouteRecordRaw } from 'vue-router'
import Portal from '@/pages/Portal.vue'
import QAService from '@/pages/QAService.vue'
import IndicatorAnalysis from '@/pages/IndicatorAnalysis.vue'
import SolutionEvaluation from '@/pages/SolutionEvaluation.vue'
import KnowledgeBase from '@/pages/KnowledgeBase.vue'
import OntologyModel from '@/pages/OntologyModel.vue'
import OntologyDetail from '@/pages/OntologyDetail.vue'
import OntologyBuild from '@/pages/OntologyBuild.vue'
import OntologyManualBuild from '@/pages/OntologyManualBuild.vue'
import OntologyMetaModelEdit from '@/pages/OntologyMetaModelEdit.vue'
import AdminSystem from '@/pages/AdminSystem.vue'
import InteractivePage from '@/pages/InteractivePage.vue'
import InteractiveView from '@/pages/InteractiveView.vue'
import SituationPageDialog from '@/pages/SituationPageDialog.vue'

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
    // 新建本体模型
    path: '/ontology/ontology-model/new',
    name: 'OntologyMetaModelCreate',
    component: OntologyMetaModelEdit,
    meta: { title: '新建本体模型' }
  },
  {
    // 编辑本体模型
    path: '/ontology/ontology-model/:id/edit',
    name: 'OntologyMetaModelEdit',
    component: OntologyMetaModelEdit,
    meta: { title: '编辑本体模型' }
  },
  {
    path: '/ontology/:id',
    name: 'OntologyDetail',
    component: OntologyDetail,
    meta: { title: '本体详情' }
  },
  {
    // 手动构建向导：?template={tplId} 触发本体模型预填骨架
    path: '/ontology/manual/:id',
    name: 'OntologyManualBuild',
    component: OntologyManualBuild,
    meta: { title: '手动构建本体' }
  },
  {
    path: '/ontology-build/:jobId',
    name: 'OntologyBuild',
    component: OntologyBuild,
    meta: { title: 'AI 构建' }
  },
  {
    path: '/admin',
    name: 'AdminSystem',
    component: AdminSystem
  },
  {
    // 态势页面主对话框（原"智能交互页面"门户入口）
    path: '/situation-page',
    name: 'SituationPageDialog',
    component: SituationPageDialog,
    meta: { title: '态势页面' }
  },
  {
    // 态势页工作台（从主对话框"打开态势页面"进入；支持 ?pageId= 直达）
    path: '/interactive',
    name: 'InteractivePage',
    component: InteractivePage,
    meta: { title: '态势页面' }
  },
  {
    path: '/interactive/view/:pageId',
    name: 'InteractiveView',
    component: InteractiveView,
    meta: { title: '态势页面查看' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
