export interface Facility {
  facilityId: string;
  name: string;
  type: string;
  status: string;
  criticality: string;
  latitude: number;
  longitude: number;
  sensorCount: number;
  assetCount: number;
}

export interface Event {
  eventId: string;
  eventType: string;
  description: string;
  severity: number;
  timestamp: string;
  facilityId?: string;
  facilityName?: string;
  personId?: string;
  personName?: string;
  metadata: Record<string, unknown>;
}

export interface Person {
  personId: string;
  name: string;
  role: string;
  clearance: string;
  personType: string;
  organizationId?: string;
  organizationName?: string;
}

export interface RiskCase {
  caseId: string;
  title: string;
  status: string;
  confidence: number;
  riskScore: number;
  description: string;
  createdAt: string;
  facilityName?: string;
  linkedEventsCount: number;
  linkedPersonNames: string[];
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphNode {
  id: string;
  label: string;
  type: string;
  properties: Record<string, unknown>;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  properties: Record<string, unknown>;
}

export interface DashboardStats {
  totalFacilities: number;
  totalEvents: number;
  openCases: number;
  criticalAlerts: number;
  totalPersons: number;
  eventsByType: { type: string; count: number }[];
  eventsBySeverity: { severity: number; count: number }[];
}

export interface SearchResult {
  totalCount: number;
  hits: SearchHit[];
}

export interface SearchHit {
  id: string;
  type: string;
  description: string;
  score: number;
  sourceType?: 'event' | 'document';
  docType?: string;
  facilityName?: string;
  personName?: string;
  sourceFile?: string;
  classification?: string;
  timestamp?: string;
}

export interface TimelineEvent {
  eventId: string;
  eventType: string;
  description: string;
  severity: number;
  timestamp: string;
  facilityName?: string;
  personName?: string;
}

// ── Link Analysis ──

export interface LinkAnalysisResult {
  paths: DiscoveredPath[];
  graph: GraphData;
  totalPathsFound: number;
  summary: string;
}

export interface DiscoveredPath {
  fromId: string;
  fromLabel: string;
  toId: string;
  toLabel: string;
  length: number;
  nodeSequence: string[];        // e.g. ["Person:García", "Facility:ETAP Majadahonda"]
  relationshipSequence: string[];  // e.g. ["WORKS_AT", "HAS_SENSOR"]
  relevance: number;              // 0..1 — higher = more hidden
}

// ── Multi-Agent Command Center ──

export interface AgentProfile {
  id: string;
  name: string;
  role: string;
  description: string;
  icon: string;     // emoji
  color: string;    // tailwind color name
}

export interface CommandCenterStep {
  type: 'agent' | 'thought' | 'cypher' | 'observation' | 'alert' | 'answer';
  content: string;
}

export interface AlertAction {
  type: 'notify_person' | 'alert_facility' | 'escalate_case' | 'broadcast';
  target: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  timestamp: string;
}

// ── Risk Propagation ──

export interface RiskPropagationRequest {
  sourceNodeId: string;
  maxDepth?: number;
  decayFactor?: number;
}

export interface RiskPropagationResult {
  sourceNodeId: string;
  sourceLabel: string;
  sourceType: string;
  sourceRisk: number;
  waves: PropagationWave[];
  summary: PropagationSummary;
  affectedGraph: GraphData;
}

export interface PropagationWave {
  depth: number;
  riskLevel: number;
  riskCategory: 'critical' | 'high' | 'medium' | 'low' | 'minimal';
  nodes: PropagatedNode[];
}

export interface PropagatedNode {
  id: string;
  label: string;
  type: string;
  inheritedRisk: number;
  relationshipFromParent: string;
  parentId: string;
  properties: Record<string, unknown>;
}

export interface PropagationSummary {
  totalAffectedNodes: number;
  criticalNodes: number;
  highRiskNodes: number;
  facilitiesAffected: number;
  personsAffected: number;
  maxPropagatedRisk: number;
  criticalPaths: string[];
}
