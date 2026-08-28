import { createRouter, createWebHistory } from 'vue-router';
import AppShell from '@/components/AppShell.vue';
import OntologyDashboard from '@/views/OntologyDashboard.vue';
import OntologyDetail from '@/views/OntologyDetail.vue';

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', redirect: '/ontology' },
        { path: 'ontology', name: 'ontology-dashboard', component: OntologyDashboard },
        { path: 'ontology/:ontologyId', name: 'ontology-detail', component: OntologyDetail },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/ontology' },
  ],
});

export default router;
