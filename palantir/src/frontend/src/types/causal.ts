export interface CausalGraphNode {
  id: string;
  label: string;
  type: 'Entity' | 'ActionNode' | 'DerivedEvent' | 'OntologyRule' | 'OntologyProposal' | string;
  category?: 'ForceUnit' | 'Equipment' | 'Target' | 'Action' | string | null;
  role?: 'reconnaissance' | 'command' | 'firepower' | 'assessment' | 'enemyTarget' | 'effect' | 'derived' | 'rule' | 'proposal' | string | null;
  properties: Record<string, unknown>;
}

export interface CausalGraphEdge {
  id: string;
  source: string;
  target: string;
  type: 'OPERATES' | 'PERFORMS' | 'TARGETS' | 'DIRECTED_TO' | 'CAUSES' | 'DERIVED_FROM' | 'ABOUT' | 'HAS_DERIVED_EVENT' | string;
  properties: Record<string, unknown>;
}

export interface CausalGraphResult {
  nodes: CausalGraphNode[];
  edges: CausalGraphEdge[];
}

export interface CausalStatistics {
  entityCount: number;
  actionCount: number;
  stateCount: number;
  relationshipCount: number;
  entityTypeCount: number;
  operationalRoleCount: number;
  relationTypeCount: number;
  causalRelationCount: number;
}

export interface MilitarySeedResponse {
  datasetId: string;
  entities: number;
  actions: number;
  states: number;
  relationships: number;
  searchDocuments: number;
  message: string;
}

export interface OntologyRuleDescriptor {
  id: string;
  name: string;
  description: string;
  outputType: string;
  enabled: boolean;
  priority: number;
}

export interface OntologyMutation {
  id: string;
  mutationType: 'NODE_CREATED' | 'NODE_MERGED' | 'PROPOSAL_CREATED' | 'PROPOSAL_APPROVED' | 'RELATION_CREATED' | string;
  executedAt: string;
  ruleId?: string | null;
  reason?: string | null;
  confidence: number;
  sourceNodeIds: string[];
  targetNodeId?: string | null;
  metadata: Record<string, unknown>;
}

export interface DynamicOntologyStatistics {
  assertedNodeCount: number;
  derivedNodeCount: number;
  activeNodeCount: number;
  ruleCount: number;
  pendingResolutionCount: number;
  pendingProposalCount: number;
  mutationCount: number;
}

export interface DynamicOntologyRunResult {
  createdNodeCount: number;
  mutationCount: number;
  mutations: OntologyMutation[];
}

export interface ResolutionCandidate {
  leftId: string;
  leftName: string;
  rightId: string;
  rightName: string;
  confidence: number;
  basis: string;
  recommendation: string;
}

export interface ManualOntologyNodeRequest {
  name: string;
  ontologyType: 'ForceUnit' | 'Equipment' | 'Target';
  operationalRole: 'reconnaissance' | 'command' | 'firepower' | 'assessment' | 'enemyTarget';
  canonicalKey?: string;
  properties: Record<string, string>;
}

export interface ManualOntologyRelationRequest {
  sourceId: string;
  targetId: string;
  relationType: 'OPERATES' | 'RELATED_TO' | 'SAME_AS' | 'POSSIBLY_SAME_AS';
  properties?: Record<string, string>;
}

export interface MergeNodesRequest {
  sourceNodeId: string;
  targetNodeId: string;
  reason: string;
  confidence: number;
  physicalMerge: boolean;
}

export interface OntologyProposal {
  id: string;
  proposalType: 'NEW_CLASS' | 'NEW_RELATION' | 'NEW_RULE' | string;
  name: string;
  parentClass?: string | null;
  description: string;
  confidence: number;
  evidence: string[];
  status: 'PROPOSED' | 'APPROVED' | string;
  createdAt: string;
}

export interface CausalAttributionRequest {
  targetEntityId: string;
  maxDepth?: number;
  includeCounterfactual?: boolean;
}

export interface CausalAttributionSummary {
  actionCount: number;
  entityCount: number;
  phaseCount: number;
  pathCount: number;
  criticalNodeCount: number;
}

export interface CausalAttributionItem {
  id: string;
  name: string;
  type?: string | null;
  phase?: string | null;
  contributionPercent: number;
  counterfactualImpactPercent: number;
  pathCount: number;
  direct: boolean;
}

export interface CausalAttributionPath {
  nodeIds: string[];
  nodeNames: string[];
  weight: number;
}

export interface CausalCounterfactual {
  nodeId: string;
  nodeName: string;
  impactPercent: number;
  onEveryPath: boolean;
}

export interface CausalAttributionResult {
  target: CausalGraphNode;
  summary: CausalAttributionSummary;
  actions: CausalAttributionItem[];
  entities: CausalAttributionItem[];
  phases: CausalAttributionItem[];
  paths: CausalAttributionPath[];
  criticalNodes: CausalCounterfactual[];
}
