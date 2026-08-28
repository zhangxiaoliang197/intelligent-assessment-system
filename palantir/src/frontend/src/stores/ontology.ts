import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { causalApi } from '@/services/causalApi';
import type {
  CausalGraphNode,
  CausalGraphResult,
  CausalStatistics,
  DynamicOntologyStatistics,
  OntologyMutation,
  OntologyProposal,
  OntologyRuleDescriptor,
  ResolutionCandidate,
} from '@/types/causal';

const emptyCausalStats: CausalStatistics = {
  entityCount: 0,
  actionCount: 0,
  stateCount: 0,
  relationshipCount: 0,
  entityTypeCount: 0,
  operationalRoleCount: 0,
  relationTypeCount: 0,
  causalRelationCount: 0,
};
const emptyDynamicStats: DynamicOntologyStatistics = {
  assertedNodeCount: 0,
  derivedNodeCount: 0,
  activeNodeCount: 0,
  ruleCount: 0,
  pendingResolutionCount: 0,
  pendingProposalCount: 0,
  mutationCount: 0,
};

export const useOntologyStore = defineStore('ontology', () => {
  const overview = ref<CausalGraphResult>({ nodes: [], edges: [] });
  const dynamicGraph = ref<CausalGraphResult>({ nodes: [], edges: [] });
  const causalTrace = ref<CausalGraphResult>({ nodes: [], edges: [] });
  const statistics = ref<CausalStatistics>({ ...emptyCausalStats });
  const dynamicStatistics = ref<DynamicOntologyStatistics>({ ...emptyDynamicStats });
  const rules = ref<OntologyRuleDescriptor[]>([]);
  const mutations = ref<OntologyMutation[]>([]);
  const resolutionCandidates = ref<ResolutionCandidate[]>([]);
  const proposals = ref<OntologyProposal[]>([]);
  const selectedNode = ref<CausalGraphNode | null>(null);
  const loading = ref(false);

  const entities = computed(() => overview.value.nodes.filter((n) => n.type === 'Entity'));

  async function loadBase() {
    loading.value = true;
    try {
      const [graph, stats] = await Promise.all([causalApi.getOverview(), causalApi.getStatistics()]);
      overview.value = graph;
      statistics.value = stats;
    } finally {
      loading.value = false;
    }
  }

  async function loadDynamic() {
    loading.value = true;
    try {
      const [graph, stats, ruleRows, mutationRows, candidates, proposalRows] = await Promise.all([
        causalApi.getDynamicGraph(),
        causalApi.getDynamicStatistics(),
        causalApi.getRules(),
        causalApi.getMutations(40),
        causalApi.getResolutionCandidates(),
        causalApi.getProposals(),
      ]);
      dynamicGraph.value = graph;
      dynamicStatistics.value = stats;
      rules.value = ruleRows;
      mutations.value = mutationRows;
      resolutionCandidates.value = candidates;
      proposals.value = proposalRows;
    } finally {
      loading.value = false;
    }
  }

  async function reloadAll() {
    await Promise.all([loadBase(), loadDynamic()]);
  }

  async function traceBack(entityId: string) {
    causalTrace.value = await causalApi.traceBack(entityId);
    return causalTrace.value;
  }

  function selectNode(node: CausalGraphNode | null) {
    selectedNode.value = node;
  }

  function ingestMutation(mutation: OntologyMutation) {
    mutations.value = [mutation, ...mutations.value.filter((x) => x.id !== mutation.id)].slice(0, 40);
  }

  return {
    overview,
    dynamicGraph,
    causalTrace,
    statistics,
    dynamicStatistics,
    rules,
    mutations,
    resolutionCandidates,
    proposals,
    selectedNode,
    loading,
    entities,
    loadBase,
    loadDynamic,
    reloadAll,
    traceBack,
    selectNode,
    ingestMutation,
  };
});
