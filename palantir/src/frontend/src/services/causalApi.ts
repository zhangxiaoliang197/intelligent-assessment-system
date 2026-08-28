import axios from 'axios';
import type {
  CausalGraphResult,
  CausalAttributionRequest,
  CausalAttributionResult,
  CausalStatistics,
  DynamicOntologyRunResult,
  DynamicOntologyStatistics,
  ManualOntologyNodeRequest,
  ManualOntologyRelationRequest,
  MergeNodesRequest,
  MilitarySeedResponse,
  OntologyMutation,
  OntologyProposal,
  OntologyRuleDescriptor,
  ResolutionCandidate,
} from '@/types/causal';

const http = axios.create({ baseURL: '/api', timeout: 45000 });

export const causalApi = {
  getOverview: () => http.get<CausalGraphResult>('/causal/overview').then((r) => r.data),
  getStatistics: () => http.get<CausalStatistics>('/causal/statistics').then((r) => r.data),
  traceBack: (targetEntityId: string) =>
    http.get<CausalGraphResult>('/causal/trace-back', { params: { targetEntityId } }).then((r) => r.data),
  attribution: (payload: CausalAttributionRequest) =>
    http.post<CausalAttributionResult>('/causal/attribution', payload).then((r) => r.data),
  seedMilitaryDataset: () => http.post<MilitarySeedResponse>('/seed/military-dataset').then((r) => r.data),

  getDynamicGraph: () => http.get<CausalGraphResult>('/dynamic-ontology/graph').then((r) => r.data),
  getDynamicStatistics: () => http.get<DynamicOntologyStatistics>('/dynamic-ontology/statistics').then((r) => r.data),
  getRules: () => http.get<OntologyRuleDescriptor[]>('/dynamic-ontology/rules').then((r) => r.data),
  runRules: () => http.post<DynamicOntologyRunResult>('/dynamic-ontology/run').then((r) => r.data),
  getResolutionCandidates: () => http.get<ResolutionCandidate[]>('/dynamic-ontology/resolution-candidates').then((r) => r.data),
  mergeNodes: (payload: MergeNodesRequest) => http.post<OntologyMutation>('/dynamic-ontology/merge', payload).then((r) => r.data),
  getMutations: (limit = 50) => http.get<OntologyMutation[]>('/dynamic-ontology/mutations', { params: { limit } }).then((r) => r.data),
  createEntity: (payload: ManualOntologyNodeRequest) => http.post('/dynamic-ontology/entities', payload).then((r) => r.data),
  createRelationship: (payload: ManualOntologyRelationRequest) =>
    http.post<OntologyMutation>('/dynamic-ontology/relationships', payload).then((r) => r.data),
  getAgentStatus: () => http.get<{ configured: boolean }>('/dynamic-ontology/agent/status').then((r) => r.data),
  agentPropose: (focus: string) => http.post<OntologyProposal>('/dynamic-ontology/agent/propose', { focus }).then((r) => r.data),
  getProposals: (status?: string) => http.get<OntologyProposal[]>('/dynamic-ontology/proposals', { params: { status } }).then((r) => r.data),
  approveProposal: (proposalId: string) => http.post<OntologyMutation>(`/dynamic-ontology/proposals/${encodeURIComponent(proposalId)}/approve`).then((r) => r.data),
};
