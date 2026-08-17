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
import SituationMap from '@/pages/SituationMap.vue'
import SituationView from '@/pages/SituationView.vue'
import SituationList from '@/pages/SituationList.vue'
import SituationShare from '@/pages/SituationShare.vue'

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
    meta: { title: '文档构建' }
  },
  {
    path: '/admin',
    name: 'AdminSystem',
    component: AdminSystem
  },
  {
    path: '/situation',
    name: 'SituationMap',
    component: SituationMap,
    meta: { title: '态势图' }
  },
  {
    path: '/situation/view/:reportId',
    name: 'SituationView',
    component: SituationView,
    meta: { title: '态势图查看' }
  },
  {
    path: '/situation/list',
    name: 'SituationList',
    component: SituationList,
    meta: { title: '态势图历史' }
  },
  {
    path: '/situation/share/:token',
    name: 'SituationShare',
    component: SituationShare,
    meta: { title: '态势图分享' }
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

export default router
