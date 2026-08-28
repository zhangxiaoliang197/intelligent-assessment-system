<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import cytoscape, { type Core } from 'cytoscape';
import * as signalR from '@microsoft/signalr';
import {
  BarChart3, Bot, Box, BrainCircuit, ChevronDown, ChevronLeft, ChevronRight, CircleDot,
  GitMerge, GitPullRequestArrow, History, Maximize2, Network, Plus, RefreshCw,
  Search, Sparkles, WandSparkles, X, Zap,
} from 'lucide-vue-next';
import { useOntologyStore } from '@/stores/ontology';
import { causalApi } from '@/services/causalApi';
import type {
  CausalGraphNode,
  CausalGraphResult,
  CausalAttributionResult,
  ManualOntologyNodeRequest,
  ManualOntologyRelationRequest,
  OntologyMutation,
  ResolutionCandidate,
} from '@/types/causal';

const store = useOntologyStore();
const graphContainer = ref<HTMLDivElement | null>(null);
const cy = ref<Core | null>(null);
const graphMode = ref<'ontology' | 'instance' | 'dynamic' | 'causal'>('instance');
const layoutMode = ref<'force' | 'hierarchy'>('force');
const query = ref('');
const typeFilter = ref('all');
const errorMessage = ref('');
const infoMessage = ref('');
const ruleRunning = ref(false);
const attributionBusy = ref(false);
const attributionResult = ref<CausalAttributionResult | null>(null);
const attributionTargetId = ref('');
const mergeBusy = ref(false);
const agentBusy = ref(false);
const agentConfigured = ref(false);

const leftCollapsed = ref(false);
const rightCollapsed = ref(false);
const entityBoxOpen = ref(true);
const relationBoxOpen = ref(true);
const propertyBoxOpen = ref(true);
const lifecycleBoxOpen = ref(true);
const ruleBoxOpen = ref(true);

const showCreate = ref(false);
const showCreateRelation = ref(false);
const showResolution = ref(false);
const showAgent = ref(false);
const agentFocus = ref('请分析当前机动目标打击图谱，判断现有本体是否缺少能够概括重复结构的新概念、关系或规则。');
const createForm = ref<ManualOntologyNodeRequest>({
  name: '', ontologyType: 'Equipment', operationalRole: 'reconnaissance', canonicalKey: '', properties: {},
});
const propertyRows = ref<Array<{ key: string; value: string }>>([{ key: '', value: '' }]);
const relationForm = ref<ManualOntologyRelationRequest>({ sourceId: '', targetId: '', relationType: 'RELATED_TO', properties: {} });
let hub: signalR.HubConnection | null = null;

const ONTOLOGY_GRAPH: CausalGraphResult = {
  nodes: [
    { id: 'CLASS-ENTITY', label: 'Entity\n作战实体', type: 'OntologyClass', category: 'Entity', role: 'schema', properties: { 定义: '具有身份、固有属性并参与行动的对象' } },
    { id: 'CLASS-FORCE', label: 'ForceUnit\n部队', type: 'OntologyClass', category: 'ForceUnit', role: 'schema', properties: { 父类: 'Entity' } },
    { id: 'CLASS-EQUIPMENT', label: 'Equipment\n装备', type: 'OntologyClass', category: 'Equipment', role: 'schema', properties: { 父类: 'Entity' } },
    { id: 'CLASS-TARGET', label: 'Target\n目标', type: 'OntologyClass', category: 'Target', role: 'schema', properties: { 父类: 'Entity' } },
    { id: 'CLASS-ACTION', label: 'ActionNode\n底层行动事实', type: 'OntologyClass', category: 'Action', role: 'schemaAction', properties: { origin: 'ASSERTED', 定义: '源数据明确记录的行动事实' } },
    { id: 'CLASS-DERIVED', label: 'DerivedEvent\n规则派生高阶事件', type: 'OntologyClass', category: 'DerivedEvent', role: 'derived', properties: { origin: 'RULE', 定义: '规则条件成立后动态长出的高阶分析节点' } },
    { id: 'CLASS-RULE', label: 'OntologyRule\n派生规则', type: 'OntologyClass', category: 'OntologyRule', role: 'rule', properties: { 定义: '决定何时从底层事实派生高阶节点' } },
    { id: 'CLASS-PROPOSAL', label: 'OntologyProposal\nAgent扩充建议', type: 'OntologyClass', category: 'OntologyProposal', role: 'proposal', properties: { 定义: 'AI发现本体表达不足后提出、待人工审批的结构扩充建议' } },
    { id: 'CLASS-MUTATION', label: 'OntologyMutation\n生命周期变更', type: 'OntologyClass', category: 'OntologyMutation', role: 'mutation', properties: { 定义: '记录节点长出、融合、关系新增、建议批准等不可丢失审计事实' } },
  ],
  edges: [
    { id: 'isa1', source: 'CLASS-FORCE', target: 'CLASS-ENTITY', type: 'IS_A', properties: {} },
    { id: 'isa2', source: 'CLASS-EQUIPMENT', target: 'CLASS-ENTITY', type: 'IS_A', properties: {} },
    { id: 'isa3', source: 'CLASS-TARGET', target: 'CLASS-ENTITY', type: 'IS_A', properties: {} },
    { id: 'operates', source: 'CLASS-FORCE', target: 'CLASS-EQUIPMENT', type: 'OPERATES', properties: {} },
    { id: 'performs', source: 'CLASS-ENTITY', target: 'CLASS-ACTION', type: 'PERFORMS', properties: {} },
    { id: 'targets', source: 'CLASS-ACTION', target: 'CLASS-TARGET', type: 'TARGETS', properties: {} },
    { id: 'derived', source: 'CLASS-DERIVED', target: 'CLASS-ACTION', type: 'DERIVED_FROM', properties: {} },
    { id: 'about', source: 'CLASS-DERIVED', target: 'CLASS-TARGET', type: 'ABOUT', properties: {} },
    { id: 'ruleProduces', source: 'CLASS-RULE', target: 'CLASS-DERIVED', type: 'PRODUCES', properties: {} },
    { id: 'agent', source: 'CLASS-PROPOSAL', target: 'CLASS-ENTITY', type: 'MAY_EXTEND', properties: {} },
    { id: 'mutation', source: 'CLASS-MUTATION', target: 'CLASS-DERIVED', type: 'RECORDS_CHANGE', properties: {} },
  ],
};

const REL_LABELS: Record<string, string> = {
  IS_A: '继承', OPERATES: '操作装备', PERFORMS: '执行', TARGETS: '作用目标', DIRECTED_TO: '指令投送', CAUSES: '因果',
  DERIVED_FROM: '由事实派生', ABOUT: '关于', HAS_DERIVED_EVENT: '产生高阶事件', PRODUCES: '产出', MAY_EXTEND: '扩充',
  RECORDS_CHANGE: '记录变化', PROPOSES_CLASS: '建议新类', PROPOSES_RELATION: '建议新关系', PROPOSES_RULE: '建议新规则',
};

const activeGraph = computed<CausalGraphResult>(() => {
  if (graphMode.value === 'ontology') return ONTOLOGY_GRAPH;
  if (graphMode.value === 'instance') return store.overview;
  if (graphMode.value === 'causal') return store.causalTrace;
  return store.dynamicGraph;
});
const attributionTargets = computed(() => store.overview.nodes.filter((node) => node.type === 'Entity' && node.category === 'Target'));

const entityRows = computed(() => {
  const src = graphMode.value === 'dynamic' ? store.dynamicGraph.nodes : store.overview.nodes;
  return src.filter((n) => n.type === 'Entity').filter((n) => {
    const keyword = query.value.trim().toLowerCase();
    const matchText = !keyword || n.label.toLowerCase().includes(keyword);
    const matchType = typeFilter.value === 'all' || n.category === typeFilter.value;
    return matchText && matchType;
  });
});

const relationEntityOptions = computed(() => store.dynamicGraph.nodes
  .filter((n) => n.type === 'Entity')
  .map((n) => ({ id: n.id, label: n.label, category: n.category ?? 'Entity' }))
  .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN')));

const relationRows = computed(() => activeGraph.value.edges.slice(0, 120).map((edge) => {
  const map = new Map(activeGraph.value.nodes.map((n) => [n.id, n.label]));
  return { ...edge, sourceLabel: map.get(edge.source) ?? edge.source, targetLabel: map.get(edge.target) ?? edge.target };
}));

const selectedProperties = computed(() => {
  const node = store.selectedNode;
  if (!node) return [];
  const props = { ...node.properties } as Record<string, unknown>;
  let staticProps: Record<string, unknown> = {};
  if (typeof props.staticProps === 'string') {
    try { staticProps = JSON.parse(props.staticProps) as Record<string, unknown>; } catch { staticProps = { 固定属性: props.staticProps }; }
  }
  delete props.staticProps;
  const labels: Record<string, string> = {
    ontologyType: '本体类型', operationalRole: '作战角色', origin: '来源', lifecycleStatus: '生命周期', ruleId: '派生规则',
    eventType: '高阶事件类型', confidence: '置信度', createdAt: '创建时间', description: '说明', status: '状态', proposalType: '建议类型',
    directResult: '直接结果', timestamp: '源记录时间', actionType: '行动类型', actionObject: '行动对象',
  };
  return Object.entries({ ...staticProps, ...props })
    .filter(([k]) => !['id', 'dataset', 'name', 'derivationExplanation', 'sourceExplanation', 'evidenceNodeIds', 'evidence'].includes(k))
    .map(([key, value]) => ({ key, label: labels[key] ?? key, value: Array.isArray(value) ? value.join('、') : String(value ?? '—') }));
});

const selectedOrigin = computed(() => String(store.selectedNode?.properties?.origin ?? (store.selectedNode?.type === 'DerivedEvent' ? 'RULE' : 'ASSERTED')));
const derivedEvents = computed(() => store.dynamicGraph.nodes.filter((n) => n.type === 'DerivedEvent'));
const pendingProposals = computed(() => store.proposals.filter((p) => p.status === 'PROPOSED'));
const proposalTypeLabels: Record<string, string> = {
  NEW_CLASS: '新增本体类别',
  NEW_RELATION: '新增关系类型',
  NEW_RULE: '新增推理规则',
};
const proposalTypeLabel = (type: string) => proposalTypeLabels[type] ?? type;
const selectedDerivationSources = computed(() => {
  const node = store.selectedNode;
  if (!node) return [] as CausalGraphNode[];
  const sourceIds = activeGraph.value.edges
    .filter((edge) => edge.source === node.id && edge.type === 'DERIVED_FROM')
    .map((edge) => edge.target);
  return sourceIds
    .map((id) => activeGraph.value.nodes.find((item) => item.id === id))
    .filter((item): item is CausalGraphNode => Boolean(item));
});

const selectedSourceExplanation = computed(() => {
  const node = store.selectedNode;
  if (!node) return '';
  const props = node.properties ?? {};
  const origin = String(props.origin ?? (node.type === 'DerivedEvent' ? 'RULE' : 'ASSERTED'));

  if (typeof props.derivationExplanation === 'string' && props.derivationExplanation.trim()) {
    return props.derivationExplanation;
  }
  if (typeof props.sourceExplanation === 'string' && props.sourceExplanation.trim()) {
    return props.sourceExplanation;
  }

  if (node.type === 'DerivedEvent') {
    const source = selectedDerivationSources.value[0];
    const directResult = source && typeof source.properties?.directResult === 'string' ? source.properties.directResult : '';
    const aboutId = activeGraph.value.edges.find((edge) => edge.source === node.id && edge.type === 'ABOUT')?.target;
    const about = aboutId ? activeGraph.value.nodes.find((item) => item.id === aboutId) : undefined;
    const ruleId = typeof props.ruleId === 'string' ? props.ruleId : '';
    const rule = store.rules.find((item) => item.id === ruleId);
    return `根据底层事实${source ? `“${source.label}”` : ''}${directResult ? `，其直接结果为“${directResult}”` : ''}${about ? `，并关联目标“${about.label}”` : ''}，满足${rule ? `规则“${rule.name}”（${rule.description}）` : `派生规则 ${ruleId || ''}`}，因此推理生成“${node.label}”。`;
  }

  if (origin === 'AGENT') {
    const evidence = Array.isArray(props.evidence) ? props.evidence.map(String).filter(Boolean) : [];
    const description = typeof props.description === 'string' ? props.description : '';
    return `该结构由 Ontology_Resolution_Agent 基于当前图谱结构提出，并经人工批准后进入本体。${description ? `建议依据：${description}。` : ''}${evidence.length ? `证据：${evidence.join('；')}。` : ''}`;
  }

  if (origin === 'MANUAL') {
    return '该节点由分析员人工新建，属于 MANUAL 原始事实，不是规则推理结果。';
  }

  if (node.type === 'ActionNode') {
    const result = typeof props.directResult === 'string' ? props.directResult : '';
    const ts = typeof props.timestamp === 'string' ? props.timestamp : '';
    return `该行动来自 Word 结构化原始事实${ts ? `（${ts}）` : ''}${result ? `，原文直接结果为“${result}”` : ''}。`;
  }

  if (node.type === 'Entity') {
    return '该实体来自 Word 中明确描述的核心部队、装备或目标实体，作为 ASSERTED 原始事实写入 Neo4j。';
  }

  return '该节点来自当前本体图谱中的已记录事实或已批准结构。';
});

function nodePalette(node: CausalGraphNode) {
  if (node.type === 'DerivedEvent') return { fill: '#F3E8FF', border: '#8B5CF6', text: '#5B21B6' };
  if (node.type === 'OntologyRule') return { fill: '#E8F1FF', border: '#4F7FF0', text: '#214FAD' };
  if (node.type === 'OntologyProposal') return { fill: '#FFF6DC', border: '#D9A62E', text: '#8A6414' };
  if (node.type === 'ActionNode') return { fill: '#F5F7FA', border: '#A9B4C2', text: '#4D5D70' };
  if (node.type === 'OntologyClass') return { fill: '#FFFFFF', border: '#7896C8', text: '#233B62' };
  const role = node.role;
  if (role === 'firepower') return { fill: '#FFF0EF', border: '#E1847D', text: '#A74A44' };
  if (role === 'assessment') return { fill: '#ECF8F2', border: '#68B58D', text: '#337B59' };
  if (role === 'enemyTarget') return { fill: '#FFF5E4', border: '#D99D43', text: '#8D611D' };
  if (role === 'command') return { fill: '#EEF1FF', border: '#7B87D9', text: '#4F59AA' };
  return { fill: '#EDF4FF', border: '#6F98DD', text: '#315FAD' };
}

function buildGraph(highlightId?: string) {
  if (!graphContainer.value) return;
  cy.value?.destroy();
  const elements = [
    ...activeGraph.value.nodes.map((node) => {
      const p = nodePalette(node);
      return { data: { ...node, fill: p.fill, border: p.border, textColor: p.text, edgeLabel: '' } };
    }),
    ...activeGraph.value.edges.map((edge) => ({ data: { ...edge, label: REL_LABELS[edge.type] ?? edge.type } })),
  ];

  cy.value = cytoscape({
    container: graphContainer.value,
    elements,
    style: [
      { selector: 'node', style: {
        label: 'data(label)', 'background-color': 'data(fill)', 'border-color': 'data(border)', color: 'data(textColor)',
        'border-width': 1.6, 'font-size': 9, 'font-weight': 500, 'text-wrap': 'wrap', 'text-max-width': '110px',
        'text-valign': 'bottom', 'text-margin-y': 7, 'overlay-opacity': 0,
      } },
      { selector: 'node[type="Entity"][category="ForceUnit"]', style: { shape: 'round-rectangle', width: 62, height: 42 } },
      { selector: 'node[type="Entity"][category="Equipment"]', style: { shape: 'ellipse', width: 48, height: 48 } },
      { selector: 'node[type="Entity"][category="Target"]', style: { shape: 'hexagon', width: 58, height: 52, 'border-width': 2.2 } },
      { selector: 'node[type="ActionNode"]', style: { shape: 'round-rectangle', width: 86, height: 34, 'font-size': 8.5, 'text-valign': 'center', 'text-margin-y': 0 } },
      { selector: 'node[type="DerivedEvent"]', style: { shape: 'diamond', width: 62, height: 62, 'border-width': 2.2, 'text-valign': 'bottom' } },
      { selector: 'node[type="OntologyRule"]', style: { shape: 'diamond', width: 54, height: 54, 'font-size': 8, 'text-valign': 'bottom' } },
      { selector: 'node[type="OntologyProposal"]', style: { shape: 'tag', width: 60, height: 46, 'font-size': 8, 'text-valign': 'bottom' } },
      { selector: 'node[type="OntologyClass"]', style: { shape: 'round-rectangle', width: 96, height: 48, 'text-valign': 'center', 'text-margin-y': 0, 'font-size': 8.5 } },
      { selector: 'node:selected', style: { 'border-width': 3.2, 'border-color': '#2563EB', 'overlay-color': '#2563EB', 'overlay-opacity': 0.05 } },
      { selector: 'edge', style: {
        width: 1.1, 'line-color': '#C9D1DC', 'target-arrow-color': '#A4B0BF', 'target-arrow-shape': 'triangle', 'arrow-scale': 0.72,
        'curve-style': 'bezier', label: graphMode.value === 'ontology' || graphMode.value === 'causal' ? 'data(label)' : '',
        'font-size': 7, color: '#758195', 'text-background-color': '#FFFFFF', 'text-background-opacity': 0.92,
        'text-background-padding': '2px', 'text-rotation': 'autorotate', 'overlay-opacity': 0,
      } },
      { selector: 'edge[type="CAUSES"]', style: { width: 1.8, 'line-color': '#8BA8DE', 'target-arrow-color': '#6E91D0' } },
      { selector: 'edge[type="DERIVED_FROM"]', style: { width: 1.8, 'line-color': '#B790E6', 'target-arrow-color': '#8B5CF6', 'line-style': 'dashed' } },
      { selector: 'edge[type="ABOUT"]', style: { width: 1.5, 'line-color': '#D8A752', 'target-arrow-color': '#C48F2F' } },
      { selector: 'edge[type="IS_A"]', style: { 'line-style': 'dotted', 'line-color': '#AAB6C5' } },
    ],
    layout: graphMode.value === 'ontology' || graphMode.value === 'causal' || layoutMode.value === 'hierarchy'
      ? { name: 'breadthfirst', directed: true, padding: 40, spacingFactor: 1.2 }
      : { name: 'cose', animate: true, fit: true, padding: 46, idealEdgeLength: 92, nodeRepulsion: 8800, gravity: 0.35 },
    wheelSensitivity: 0.22,
  });

  cy.value.on('tap', 'node', (event) => {
    const id = event.target.id();
    const node = activeGraph.value.nodes.find((n) => n.id === id) ?? null;
    store.selectNode(node);
  });
  cy.value.on('tap', (event) => { if (event.target === cy.value) store.selectNode(null); });
  if (highlightId) animateNewNode(highlightId);
}

function zoomGraph(factor: number) {
  const instance = cy.value;
  const container = graphContainer.value;
  if (!instance || !container) return;

  const level = Math.min(3, Math.max(0.15, instance.zoom() * factor));
  instance.zoom({
    level,
    renderedPosition: {
      x: container.clientWidth / 2,
      y: container.clientHeight / 2,
    },
  });
}

function fitGraph() {
  cy.value?.fit(undefined, 50);
}

function animateNewNode(id: string) {
  const node = cy.value?.getElementById(id);
  if (!node || node.empty()) return;
  node.style('opacity', 0.15);
  node.animate({ style: { opacity: 1 }, duration: 700 });
  node.select();
  cy.value?.animate({ fit: { eles: node, padding: 180 }, duration: 600 });
}

async function switchMode(mode: typeof graphMode.value) {
  graphMode.value = mode;
  errorMessage.value = '';
  if (mode === 'causal' && store.causalTrace.nodes.length === 0) {
    const target = store.overview.nodes.find((n) => n.type === 'Entity' && n.category === 'Target');
    if (target) await store.traceBack(target.id);
  }
  await nextTick(); buildGraph();
}

async function runRules() {
  ruleRunning.value = true; errorMessage.value = ''; infoMessage.value = '';
  try {
    const result = await causalApi.runRules();
    await store.loadDynamic();
    graphMode.value = 'dynamic';
    await nextTick(); buildGraph(result.mutations[0]?.targetNodeId ?? undefined);
    infoMessage.value = result.createdNodeCount > 0 ? `规则引擎动态派生 ${result.createdNodeCount} 个高阶节点。` : '规则已执行，当前没有新的可派生节点。';
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '规则执行失败'; }
  finally { ruleRunning.value = false; }
}

async function runAttribution() {
  const targetId = attributionTargetId.value || attributionTargets.value[0]?.id;
  if (!targetId) {
    errorMessage.value = '当前没有可分析的目标实体';
    return;
  }

  attributionBusy.value = true;
  errorMessage.value = '';
  infoMessage.value = '';
  try {
    attributionTargetId.value = targetId;
    attributionResult.value = await causalApi.attribution({
      targetEntityId: targetId,
      maxDepth: 12,
      includeCounterfactual: true,
    });
    infoMessage.value = `已完成“${attributionResult.value.target.label}”的因果归因统计。`;
  } catch (e) {
    errorMessage.value = e instanceof Error ? e.message : '归因分析失败';
  } finally {
    attributionBusy.value = false;
  }
}

async function scanResolution() {
  await store.loadDynamic(); showResolution.value = true;
}

async function resolveCandidate(candidate: ResolutionCandidate, physicalMerge: boolean) {
  mergeBusy.value = true; errorMessage.value = '';
  try {
    const mutation = await causalApi.mergeNodes({
      sourceNodeId: candidate.rightId,
      targetNodeId: candidate.leftId,
      reason: `${candidate.basis}；由分析员确认`,
      confidence: candidate.confidence,
      physicalMerge,
    });
    store.ingestMutation(mutation);
    if (physicalMerge) {
      const disappearing = cy.value?.getElementById(candidate.rightId);
      if (disappearing && !disappearing.empty()) {
        disappearing.animate({ style: { opacity: 0 }, duration: 480 });
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
    }
    await store.reloadAll();
    await nextTick(); buildGraph(mutation.targetNodeId ?? undefined);
    showResolution.value = false;
    infoMessage.value = physicalMerge ? '实体已融合，原重复节点已消融，关系已由 APOC 继承。' : '已建立 POSSIBLY_SAME_AS，暂未物理融合。';
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '实体消歧失败'; }
  finally { mergeBusy.value = false; }
}

async function createEntity() {
  const properties = Object.fromEntries(propertyRows.value.filter((x) => x.key.trim()).map((x) => [x.key.trim(), x.value.trim()]));
  if (!createForm.value.name.trim()) { errorMessage.value = '请输入实体名称'; return; }
  try {
    await causalApi.createEntity({ ...createForm.value, properties });
    showCreate.value = false;
    createForm.value = { name: '', ontologyType: 'Equipment', operationalRole: 'reconnaissance', canonicalKey: '', properties: {} };
    propertyRows.value = [{ key: '', value: '' }];
    await store.reloadAll(); graphMode.value = 'dynamic'; await nextTick(); buildGraph();
    infoMessage.value = '新实体已作为 ASSERTED/MANUAL 事实加入动态图谱。';
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '创建失败'; }
}

async function createRelation() {
  if (!relationForm.value.sourceId || !relationForm.value.targetId) { errorMessage.value = '请选择关系两端实体'; return; }
  if (relationForm.value.sourceId === relationForm.value.targetId) { errorMessage.value = '关系两端不能是同一个实体'; return; }
  try {
    const mutation = await causalApi.createRelationship(relationForm.value);
    store.ingestMutation(mutation);
    showCreateRelation.value = false;
    relationForm.value = { sourceId: '', targetId: '', relationType: 'RELATED_TO', properties: {} };
    await store.loadDynamic(); graphMode.value = 'dynamic'; await nextTick(); buildGraph();
    infoMessage.value = '新关系已写入 Neo4j，并记录为 OntologyMutation。';
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '关系创建失败'; }
}

async function askAgent() {
  agentBusy.value = true; errorMessage.value = '';
  try {
    await causalApi.agentPropose(agentFocus.value);
    await store.loadDynamic();
    showAgent.value = false;
    graphMode.value = 'dynamic'; await nextTick(); buildGraph();
    infoMessage.value = 'Ontology_Resolution_Agent 已提交一条待人工审批的本体扩充建议。';
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : 'Agent 调用失败'; }
  finally { agentBusy.value = false; }
}

async function approveProposal(id: string) {
  try {
    const mutation = await causalApi.approveProposal(id);
    store.ingestMutation(mutation);
    await store.loadDynamic(); await nextTick(); buildGraph();
    infoMessage.value = '本体扩充建议已批准并进入 ACTIVE。';
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '批准失败'; }
}

async function connectHub() {
  hub = new signalR.HubConnectionBuilder().withUrl('/hub/alerts').withAutomaticReconnect().build();
  hub.on('OntologyMutation', async (mutation: OntologyMutation) => {
    store.ingestMutation(mutation);
    if (mutation.mutationType === 'NODE_MERGED') {
      mutation.sourceNodeIds.filter((id) => id !== mutation.targetNodeId).forEach((id) => {
        const node = cy.value?.getElementById(id);
        if (node && !node.empty()) node.animate({ style: { opacity: 0 }, duration: 520 });
      });
      await new Promise((resolve) => setTimeout(resolve, 540));
    }
    await store.loadDynamic();
    if (graphMode.value === 'dynamic') { await nextTick(); buildGraph(mutation.targetNodeId ?? undefined); }
  });
  try { await hub.start(); await hub.invoke('SubscribeToOntology'); } catch { /* polling/manual reload remains available */ }
}

watch([activeGraph, layoutMode], async () => { await nextTick(); buildGraph(); }, { deep: true });
onMounted(async () => {
  try {
    await store.reloadAll();
    agentConfigured.value = (await causalApi.getAgentStatus()).configured;
    await nextTick(); buildGraph();
    await connectHub();
  } catch (e) { errorMessage.value = e instanceof Error ? e.message : '加载失败'; }
});
onBeforeUnmount(async () => { cy.value?.destroy(); if (hub) await hub.stop(); });
</script>

<template>
  <div class="space-y-4">
    <section class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <div class="text-xs text-slate-400">Ontology / Dynamic Lifecycle</div>
        <h2 class="mt-1 text-xl font-bold text-slate-950">机动目标打击动态本体</h2>
        <p class="mt-1 text-xs text-slate-500">动态 = 规则派生“长出” · 实体消歧融合“消失” · Agent 发现结构并人工批准扩充</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button class="soft-btn" @click="showCreate = true"><Plus class="h-4 w-4" />新建实体</button>
        <button class="soft-btn" @click="scanResolution"><GitMerge class="h-4 w-4" />消歧扫描</button>
        <button class="soft-btn" :disabled="!agentConfigured" @click="showAgent = true"><BrainCircuit class="h-4 w-4" />Agent 扩充</button>
        <button class="primary-btn" :disabled="ruleRunning" @click="runRules"><Zap class="h-4 w-4" />{{ ruleRunning ? '推理中…' : '运行规则引擎' }}</button>
      </div>
    </section>

    <div v-if="errorMessage" class="rounded-xl border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">{{ errorMessage }}</div>
    <div v-if="infoMessage" class="rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-2 text-xs text-emerald-700">{{ infoMessage }}</div>

    <section class="attribution-launch">
      <div>
        <div class="text-sm font-semibold text-slate-900">因果归因统计</div>
        <p class="mt-1 text-xs text-slate-500">手动选择目标，统计行动、实体和阶段对目标结果的贡献。</p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <select v-model="attributionTargetId" class="soft-btn attribution-target" :disabled="!attributionTargets.length">
          <option value="">选择归因目标</option>
          <option v-for="target in attributionTargets" :key="target.id" :value="target.id">{{ target.label }}</option>
        </select>
        <button class="primary-btn" :disabled="attributionBusy || !attributionTargets.length" @click="runAttribution">
          <BarChart3 class="h-4 w-4" />{{ attributionBusy ? '统计中…' : '开始归因分析' }}
        </button>
      </div>
    </section>

    <section v-if="attributionResult" class="attribution-panel">
      <div class="attribution-header">
        <div>
          <div class="text-xs font-semibold uppercase tracking-[0.14em] text-blue-600">Causal Attribution</div>
          <h3 class="mt-1 text-base font-semibold text-slate-900">目标归因：{{ attributionResult.target.label }}</h3>
          <p class="mt-1 text-xs text-slate-500">贡献度按因果路径权重统计；反事实影响度表示移除该节点后受影响的路径比例。</p>
        </div>
        <button class="tiny-btn" title="关闭归因结果" @click="attributionResult = null"><X class="h-3.5 w-3.5" /></button>
      </div>
      <div class="attribution-summary">
        <div><span>因果路径</span><strong>{{ attributionResult.summary.pathCount }}</strong></div>
        <div><span>行动节点</span><strong>{{ attributionResult.summary.actionCount }}</strong></div>
        <div><span>贡献实体</span><strong>{{ attributionResult.summary.entityCount }}</strong></div>
        <div><span>关键节点</span><strong>{{ attributionResult.summary.criticalNodeCount }}</strong></div>
      </div>
      <div class="attribution-columns">
        <div>
          <h4>行动贡献排名</h4>
          <div v-for="item in attributionResult.actions.slice(0, 8)" :key="item.id" class="attribution-row">
            <div class="flex min-w-0 items-center justify-between gap-3"><span class="truncate">{{ item.name }}</span><b>{{ item.contributionPercent.toFixed(1) }}%</b></div>
            <div class="attribution-bar"><i :style="{ width: `${Math.min(100, item.contributionPercent)}%` }" /></div>
            <small>{{ item.direct ? '直接作用' : '间接作用' }} · 反事实影响 {{ item.counterfactualImpactPercent.toFixed(1) }}%</small>
          </div>
        </div>
        <div>
          <h4>实体贡献排名</h4>
          <div v-for="item in attributionResult.entities.slice(0, 8)" :key="item.id" class="attribution-row">
            <div class="flex min-w-0 items-center justify-between gap-3"><span class="truncate">{{ item.name }}</span><b>{{ item.contributionPercent.toFixed(1) }}%</b></div>
            <div class="attribution-bar entity"><i :style="{ width: `${Math.min(100, item.contributionPercent)}%` }" /></div>
            <small>参与 {{ item.pathCount }} 条路径 · 影响 {{ item.counterfactualImpactPercent.toFixed(1) }}%</small>
          </div>
        </div>
        <div>
          <h4>阶段贡献统计</h4>
          <div v-for="item in attributionResult.phases" :key="item.id" class="attribution-row">
            <div class="flex min-w-0 items-center justify-between gap-3"><span>{{ item.name }}</span><b>{{ item.contributionPercent.toFixed(1) }}%</b></div>
            <div class="attribution-bar phase"><i :style="{ width: `${Math.min(100, item.contributionPercent)}%` }" /></div>
            <small>包含 {{ item.pathCount }} 个行动路径节点</small>
          </div>
        </div>
      </div>
      <div v-if="attributionResult.criticalNodes.length" class="critical-list">
        <h4>反事实关键节点</h4>
        <span v-for="node in attributionResult.criticalNodes" :key="node.nodeId">{{ node.nodeName }} · {{ node.impactPercent.toFixed(1) }}%</span>
      </div>
    </section>

    <section class="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-7">
      <div class="metric"><span>原始事实</span><strong>{{ store.dynamicStatistics.assertedNodeCount }}</strong></div>
      <div class="metric violet"><span>规则派生</span><strong>{{ store.dynamicStatistics.derivedNodeCount }}</strong></div>
      <div class="metric"><span>当前有效节点</span><strong>{{ store.dynamicStatistics.activeNodeCount }}</strong></div>
      <div class="metric"><span>启用规则</span><strong>{{ store.dynamicStatistics.ruleCount }}</strong></div>
      <div class="metric amber"><span>待消歧</span><strong>{{ store.dynamicStatistics.pendingResolutionCount }}</strong></div>
      <div class="metric amber"><span>待审批建议</span><strong>{{ store.dynamicStatistics.pendingProposalCount }}</strong></div>
      <div class="metric"><span>生命周期变更</span><strong>{{ store.dynamicStatistics.mutationCount }}</strong></div>
    </section>

    <section class="toolbar-card">
      <div class="mode-tabs">
        <button :class="{ active: graphMode === 'ontology' }" @click="switchMode('ontology')">本体结构</button>
        <button :class="{ active: graphMode === 'instance' }" @click="switchMode('instance')">实例事实</button>
        <button :class="{ active: graphMode === 'dynamic' }" @click="switchMode('dynamic')"><Sparkles class="h-3.5 w-3.5" />动态本体</button>
        <button :class="{ active: graphMode === 'causal' }" @click="switchMode('causal')">事件溯源</button>
      </div>
      <div class="flex items-center gap-2">
        <button class="icon-btn" @click="layoutMode = layoutMode === 'force' ? 'hierarchy' : 'force'" title="切换布局"><Network class="h-4 w-4" /></button>
        <button class="icon-btn" @click="cy?.fit(undefined, 50)" title="适应画布"><Maximize2 class="h-4 w-4" /></button>
        <button class="icon-btn" @click="store.reloadAll()" title="刷新"><RefreshCw class="h-4 w-4" /></button>
      </div>
    </section>

    <section class="workspace" :class="{ 'left-off': leftCollapsed, 'right-off': rightCollapsed }">
      <aside v-if="!leftCollapsed" class="side-column">
        <div class="panel-card">
          <div class="panel-head">
            <div class="font-semibold">实体实例 <span class="count">{{ entityRows.length }}</span></div>
            <button class="tiny-btn" @click="entityBoxOpen = !entityBoxOpen"><ChevronDown class="h-4 w-4 transition" :class="{ 'rotate-180': !entityBoxOpen }" /></button>
          </div>
          <div v-if="entityBoxOpen" class="panel-body">
            <div class="flex gap-2">
              <label class="search-box"><Search class="h-3.5 w-3.5" /><input v-model="query" placeholder="搜索实体" /></label>
              <select v-model="typeFilter" class="mini-select"><option value="all">全部</option><option>ForceUnit</option><option>Equipment</option><option>Target</option></select>
            </div>
            <button v-for="node in entityRows" :key="node.id" class="list-row" @click="store.selectNode(node); cy?.getElementById(node.id).select()">
              <span class="node-dot" :style="{ background: nodePalette(node).border }" />
              <span class="min-w-0 flex-1"><b>{{ node.label }}</b><small>{{ node.category }}</small></span>
              <ChevronRight class="h-3.5 w-3.5 text-slate-300" />
            </button>
          </div>
        </div>

        <div class="panel-card">
          <div class="panel-head">
            <div class="font-semibold">关系 <span class="count">{{ relationRows.length }}</span></div>
            <div class="flex items-center gap-1">
              <button class="tiny-btn" title="新建关系" @click="showCreateRelation = true"><Plus class="h-3.5 w-3.5" /></button>
              <button class="tiny-btn" @click="relationBoxOpen = !relationBoxOpen"><ChevronDown class="h-4 w-4 transition" :class="{ 'rotate-180': !relationBoxOpen }" /></button>
            </div>
          </div>
          <div v-if="relationBoxOpen" class="panel-body max-h-[340px] overflow-auto">
            <div v-for="edge in relationRows" :key="edge.id" class="relation-row">
              <span>{{ edge.sourceLabel }}</span><em>{{ REL_LABELS[edge.type] ?? edge.type }}</em><span>{{ edge.targetLabel }}</span>
            </div>
          </div>
        </div>
      </aside>

      <button v-if="leftCollapsed" class="rail-toggle left" @click="leftCollapsed = false"><ChevronRight class="h-4 w-4" /></button>
      <button v-else class="rail-toggle left" @click="leftCollapsed = true"><ChevronLeft class="h-4 w-4" /></button>

      <div class="graph-stage">
        <div class="graph-legend">
          <span><i class="asserted" />ASSERTED 原始事实</span>
          <span><i class="derived" />DERIVED 规则派生</span>
          <span><i class="rule" />Rule</span>
          <span><i class="proposal" />Agent Proposal</span>
        </div>
        <div class="graph-controls" aria-label="图谱缩放">
          <button type="button" title="放大图谱" @click="zoomGraph(1.25)">＋</button>
          <button type="button" title="缩小图谱" @click="zoomGraph(0.8)">－</button>
          <button type="button" title="适应画布" @click="fitGraph">适应</button>
        </div>
        <div ref="graphContainer" class="h-full w-full" />
      </div>

      <button v-if="rightCollapsed" class="rail-toggle right" @click="rightCollapsed = false"><ChevronLeft class="h-4 w-4" /></button>
      <button v-else class="rail-toggle right" @click="rightCollapsed = true"><ChevronRight class="h-4 w-4" /></button>

      <aside v-if="!rightCollapsed" class="side-column">
        <div class="panel-card">
          <div class="panel-head">
            <div class="font-semibold">节点详情</div>
            <button class="tiny-btn" @click="propertyBoxOpen = !propertyBoxOpen"><ChevronDown class="h-4 w-4 transition" :class="{ 'rotate-180': !propertyBoxOpen }" /></button>
          </div>
          <div v-if="propertyBoxOpen" class="panel-body">
            <div v-if="store.selectedNode" class="space-y-3">
              <div class="rounded-xl border border-slate-100 bg-slate-50 p-3">
                <div class="text-sm font-semibold text-slate-900">{{ store.selectedNode.label }}</div>
                <div class="mt-2 flex flex-wrap gap-1.5"><span class="tag">{{ store.selectedNode.type }}</span><span class="tag">{{ store.selectedNode.category }}</span><span class="tag origin">{{ selectedOrigin }}</span></div>
              </div>
              <div class="property-list"><div v-for="row in selectedProperties" :key="row.key"><span>{{ row.label }}</span><b>{{ row.value }}</b></div></div>
              <div class="source-explain">
                <div class="source-explain-title">来源解释</div>
                <p>{{ selectedSourceExplanation }}</p>
                <div v-if="selectedDerivationSources.length" class="source-evidence">
                  <span>推理依据</span>
                  <button v-for="source in selectedDerivationSources" :key="source.id" @click="store.selectNode(source); cy?.getElementById(source.id).select()">{{ source.label }}</button>
                </div>
              </div>
            </div>
            <div v-else class="empty-state"><Box class="h-8 w-8" /><span>选择节点查看本体属性、来源和生命周期</span></div>
          </div>
        </div>

        <div class="panel-card">
          <div class="panel-head">
            <div class="font-semibold">动态图谱生命周期</div>
            <button class="tiny-btn" @click="lifecycleBoxOpen = !lifecycleBoxOpen"><ChevronDown class="h-4 w-4 transition" :class="{ 'rotate-180': !lifecycleBoxOpen }" /></button>
          </div>
          <div v-if="lifecycleBoxOpen" class="panel-body lifecycle-body overflow-auto">
            <div v-if="!store.mutations.length" class="empty-mini">暂无变更记录</div>
            <div v-for="m in store.mutations" :key="m.id" class="mutation-row">
              <div class="mutation-icon" :class="m.mutationType"><GitMerge v-if="m.mutationType === 'NODE_MERGED'" class="h-3.5 w-3.5" /><Sparkles v-else class="h-3.5 w-3.5" /></div>
              <div class="min-w-0"><b>{{ m.mutationType }}</b><p>{{ m.reason || '本体生命周期变更' }}</p><small>{{ Math.round(m.confidence * 100) }}% · {{ m.ruleId || '人工/Agent' }}</small></div>
            </div>
          </div>
        </div>

        <div class="panel-card">
          <div class="panel-head">
            <div class="font-semibold">规则与 Agent</div>
            <button class="tiny-btn" @click="ruleBoxOpen = !ruleBoxOpen"><ChevronDown class="h-4 w-4 transition" :class="{ 'rotate-180': !ruleBoxOpen }" /></button>
          </div>
          <div v-if="ruleBoxOpen" class="panel-body max-h-[300px] overflow-auto">
            <div class="sub-title"><WandSparkles class="h-3.5 w-3.5" />启用派生规则</div>
            <div v-for="rule in store.rules" :key="rule.id" class="rule-row"><span class="rule-priority">P{{ rule.priority }}</span><div><b>{{ rule.name }}</b><p>{{ rule.outputType }}</p></div></div>
            <div class="sub-title mt-4"><Bot class="h-3.5 w-3.5" />待审批扩充建议</div>
            <div v-if="!pendingProposals.length" class="empty-mini">暂无 Agent 建议</div>
            <div v-for="p in pendingProposals" :key="p.id" class="proposal-row">
              <div class="min-w-0">
                <b>{{ p.name }}</b>
                <p>{{ proposalTypeLabel(p.proposalType) }} · 置信度 {{ Math.round(p.confidence * 100) }}%</p>
                <p v-if="p.parentClass">建议归入：{{ p.parentClass }}</p>
                <p v-if="p.description" class="proposal-description">{{ p.description }}</p>
                <p v-if="p.evidence?.length" class="proposal-evidence">依据：{{ p.evidence.join('；') }}</p>
              </div>
              <button @click="approveProposal(p.id)">批准</button>
            </div>
          </div>
        </div>
      </aside>
    </section>

    <div v-if="showCreate" class="modal-mask" @click.self="showCreate = false">
      <div class="modal-card">
        <div class="modal-head"><div><b>新建本体实例</b><p>作为 ASSERTED / MANUAL 事实写入 Neo4j</p></div><button @click="showCreate=false"><X class="h-4 w-4" /></button></div>
        <div class="form-grid">
          <label class="full"><span>实体名称</span><input v-model="createForm.name" placeholder="例如：备用侦察无人机" /></label>
          <label><span>本体类型</span><select v-model="createForm.ontologyType"><option>ForceUnit</option><option>Equipment</option><option>Target</option></select></label>
          <label><span>作战角色</span><select v-model="createForm.operationalRole"><option value="reconnaissance">侦察感知</option><option value="command">指挥决策</option><option value="firepower">火力打击</option><option value="assessment">毁伤评估</option><option value="enemyTarget">敌方目标</option></select></label>
          <label class="full"><span>Canonical Key（用于后续实体消歧，可选）</span><input v-model="createForm.canonicalKey" placeholder="相同真实实体使用相同 key 可被消歧引擎发现" /></label>
        </div>
        <div class="mt-4"><div class="mb-2 flex items-center justify-between text-xs font-semibold text-slate-600"><span>固定属性</span><button class="text-blue-600" @click="propertyRows.push({key:'',value:''})">+ 属性</button></div>
          <div v-for="(row, i) in propertyRows" :key="i" class="mb-2 grid grid-cols-[1fr_1.4fr_28px] gap-2"><input v-model="row.key" class="form-input" placeholder="属性名" /><input v-model="row.value" class="form-input" placeholder="属性值" /><button class="text-slate-400" @click="propertyRows.splice(i,1)">×</button></div>
        </div>
        <div class="modal-actions"><button class="soft-btn" @click="showCreate=false">取消</button><button class="primary-btn" @click="createEntity">创建实体</button></div>
      </div>
    </div>

    <div v-if="showCreateRelation" class="modal-mask" @click.self="showCreateRelation = false">
      <div class="modal-card">
        <div class="modal-head"><div><b>新建实体关系</b><p>关系会直接写入 Neo4j，并进入动态本体生命周期审计。</p></div><button @click="showCreateRelation=false"><X class="h-4 w-4" /></button></div>
        <div class="form-grid">
          <label class="full"><span>起点实体</span><select v-model="relationForm.sourceId"><option value="" disabled>请选择</option><option v-for="n in relationEntityOptions" :key="'s-'+n.id" :value="n.id">{{ n.label }} · {{ n.category }}</option></select></label>
          <label class="full"><span>关系类型</span><select v-model="relationForm.relationType"><option value="OPERATES">OPERATES · 部队操作装备</option><option value="RELATED_TO">RELATED_TO · 一般领域关联</option><option value="SAME_AS">SAME_AS · 已确认同一实体</option><option value="POSSIBLY_SAME_AS">POSSIBLY_SAME_AS · 待确认同一实体</option></select></label>
          <label class="full"><span>终点实体</span><select v-model="relationForm.targetId"><option value="" disabled>请选择</option><option v-for="n in relationEntityOptions" :key="'t-'+n.id" :value="n.id">{{ n.label }} · {{ n.category }}</option></select></label>
        </div>
        <div class="mt-3 rounded-xl border border-blue-100 bg-blue-50 p-3 text-xs leading-5 text-blue-700">这里不允许输入任意 Cypher 关系类型；后端使用白名单约束，避免从 UI 注入未经本体约束的关系。</div>
        <div class="modal-actions"><button class="soft-btn" @click="showCreateRelation=false">取消</button><button class="primary-btn" @click="createRelation">创建关系</button></div>
      </div>
    </div>

    <div v-if="showResolution" class="modal-mask" @click.self="showResolution = false">
      <div class="modal-card wide">
        <div class="modal-head"><div><b>实体消歧与融合</b><p>低置信度仅建立 POSSIBLY_SAME_AS；高置信度经人工确认后可 APOC 物理融合。</p></div><button @click="showResolution=false"><X class="h-4 w-4" /></button></div>
        <div v-if="!store.resolutionCandidates.length" class="empty-state py-12"><GitPullRequestArrow class="h-8 w-8" /><span>当前没有检测到重复实体。可新建同 canonicalKey 的测试实例验证“消失”链路。</span></div>
        <div v-for="c in store.resolutionCandidates" :key="c.leftId + c.rightId" class="resolution-row">
          <div class="pair"><b>{{ c.leftName }}</b><GitMerge class="h-4 w-4 text-slate-400" /><b>{{ c.rightName }}</b></div>
          <div class="grow"><p>{{ c.basis }}</p><small>{{ c.recommendation }}</small></div>
          <div class="score">{{ Math.round(c.confidence * 100) }}%</div>
          <button class="soft-btn" :disabled="mergeBusy" @click="resolveCandidate(c,false)">仅关联</button>
          <button class="primary-btn" :disabled="mergeBusy" @click="resolveCandidate(c,true)">确认融合</button>
        </div>
      </div>
    </div>

    <div v-if="showAgent" class="modal-mask" @click.self="showAgent = false">
      <div class="modal-card">
        <div class="modal-head"><div><b>Ontology_Resolution_Agent</b><p>DeepSeek 只提出 PROPOSED 草案，不直接修改本体。</p></div><button @click="showAgent=false"><X class="h-4 w-4" /></button></div>
        <label class="block"><span class="text-xs font-semibold text-slate-600">分析目标</span><textarea v-model="agentFocus" class="mt-2 min-h-36 w-full rounded-xl border border-slate-200 p-3 text-sm outline-none focus:border-blue-400" /></label>
        <div class="mt-3 rounded-xl border border-amber-100 bg-amber-50 p-3 text-xs leading-5 text-amber-800">Agent 会读取当前节点类型、关系类型、实例样本、已派生事件和规则，寻找“本体表达能力不足”，而不是重复抽取已有实体。</div>
        <div class="modal-actions"><button class="soft-btn" @click="showAgent=false">取消</button><button class="primary-btn" :disabled="agentBusy" @click="askAgent"><BrainCircuit class="h-4 w-4" />{{ agentBusy ? '分析中…' : '生成扩充建议' }}</button></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.metric{border:1px solid #e7ecf2;background:#fff;border-radius:12px;padding:12px 14px;box-shadow:0 1px 3px rgba(15,23,42,.04)}.metric span{display:block;font-size:10px;color:#8490a1}.metric strong{display:block;margin-top:5px;font-size:20px;color:#182234}.metric.violet strong{color:#7c3aed}.metric.amber strong{color:#b7791f}
.toolbar-card{display:flex;justify-content:space-between;align-items:center;border:1px solid #e7ecf2;background:#fff;border-radius:12px;padding:7px;box-shadow:0 1px 3px rgba(15,23,42,.04)}.mode-tabs{display:flex;gap:3px}.mode-tabs button{display:inline-flex;align-items:center;gap:5px;padding:7px 11px;border-radius:8px;font-size:12px;color:#64748b}.mode-tabs button.active{background:#edf4ff;color:#2563eb;font-weight:600}
.workspace{position:relative;display:grid;grid-template-columns:244px minmax(0,1fr) 340px;gap:10px;min-height:690px}.workspace.left-off{grid-template-columns:minmax(0,1fr) 340px}.workspace.right-off{grid-template-columns:244px minmax(0,1fr)}.workspace.left-off.right-off{grid-template-columns:minmax(0,1fr)}.side-column{display:flex;flex-direction:column;gap:10px;min-width:0}.panel-card,.graph-stage{border:1px solid #e7ecf2;background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(15,23,42,.04);overflow:hidden}.panel-head{display:flex;align-items:center;justify-content:space-between;padding:11px 12px;border-bottom:1px solid #f0f2f5;font-size:12px;color:#263346}.panel-body{padding:10px}.count{margin-left:4px;color:#2563eb;font-size:10px}.tiny-btn,.icon-btn{display:inline-flex;align-items:center;justify-content:center;border:1px solid #e7ebf0;background:#fff;border-radius:8px;color:#6b7789}.tiny-btn{width:26px;height:26px}.icon-btn{width:30px;height:30px}.icon-btn:hover,.tiny-btn:hover{background:#f7f9fc}
.search-box{display:flex;align-items:center;gap:5px;flex:1;border:1px solid #e4e9ef;border-radius:8px;padding:6px 8px;color:#9aa5b5}.search-box input{min-width:0;width:100%;outline:none;font-size:11px;color:#334155}.mini-select{width:78px;border:1px solid #e4e9ef;border-radius:8px;padding:5px;font-size:10px;color:#64748b;background:#fff}.list-row{width:100%;display:flex;align-items:center;gap:8px;padding:8px 4px;border-bottom:1px solid #f5f6f8;text-align:left}.list-row:hover{background:#fafcff}.list-row b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;color:#334155}.list-row small{display:block;margin-top:2px;font-size:9px;color:#9aa5b5}.node-dot{width:8px;height:8px;border-radius:99px;flex:0 0 auto}.relation-row{padding:8px 3px;border-bottom:1px solid #f5f6f8;font-size:9.5px;color:#5e6a7b}.relation-row span{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.relation-row em{display:inline-block;margin:3px 0;padding:1px 5px;border-radius:99px;background:#f1f5f9;color:#64748b;font-style:normal;font-size:8.5px}
.graph-stage{position:relative;min-width:0;background-image:radial-gradient(#e9edf3 1px,transparent 1px);background-size:20px 20px}.graph-legend{position:absolute;z-index:4;right:12px;top:10px;display:flex;flex-wrap:wrap;gap:8px;border:1px solid #e8edf3;background:rgba(255,255,255,.94);border-radius:9px;padding:6px 8px;font-size:9px;color:#6b7789}.graph-legend span{display:flex;align-items:center;gap:4px}.graph-legend i{width:7px;height:7px;border-radius:50%}.graph-legend .asserted{background:#6f98dd}.graph-legend .derived{background:#8b5cf6}.graph-legend .rule{background:#4f7ff0}.graph-legend .proposal{background:#d9a62e}
.graph-controls{position:absolute;z-index:4;left:12px;bottom:12px;display:flex;gap:4px;border:1px solid #e8edf3;background:rgba(255,255,255,.94);border-radius:9px;padding:4px;box-shadow:0 1px 3px rgba(15,23,42,.08)}.graph-controls button{min-width:28px;height:26px;border-radius:6px;color:#526173;font-size:12px}.graph-controls button:hover{background:#edf4ff;color:#2563eb}.graph-controls button:last-child{padding:0 8px;font-size:9px}
.rail-toggle{position:absolute;z-index:10;top:50%;display:flex;width:22px;height:44px;align-items:center;justify-content:center;border:1px solid #e1e6ed;background:#fff;color:#94a3b8;box-shadow:0 2px 8px rgba(15,23,42,.06)}.rail-toggle.left{left:234px;border-radius:0 9px 9px 0}.left-off .rail-toggle.left{left:-1px}.rail-toggle.right{right:330px;border-radius:9px 0 0 9px}.right-off .rail-toggle.right{right:-1px}
.empty-state{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:8px;color:#a4adba;text-align:center;font-size:10px;min-height:130px}.empty-mini{padding:10px;text-align:center;font-size:10px;color:#9ca6b3}.tag{display:inline-flex;border:1px solid #e3e8ee;background:#f8fafc;border-radius:99px;padding:2px 6px;font-size:9px;color:#64748b}.tag.origin{background:#f3e8ff;border-color:#ead8ff;color:#7c3aed}.property-list>div{display:grid;grid-template-columns:88px 1fr;gap:8px;padding:7px 0;border-bottom:1px solid #f3f5f7;font-size:9.5px}.property-list span{color:#8a95a5}.property-list b{font-weight:500;color:#3e4a5b;word-break:break-all}.mutation-row{display:flex;gap:8px;padding:8px 0;border-bottom:1px solid #f2f4f7}.mutation-icon{display:flex;width:24px;height:24px;flex:0 0 auto;align-items:center;justify-content:center;border-radius:7px;background:#f3e8ff;color:#7c3aed}.mutation-icon.NODE_MERGED{background:#fff4df;color:#b7791f}.mutation-row b{display:block;font-size:9.5px;color:#344054}.mutation-row p{margin-top:2px;font-size:9px;color:#7b8797;line-height:1.4}.mutation-row small{display:block;margin-top:3px;font-size:8px;color:#a0a9b5}.lifecycle-body{min-height:360px;max-height:480px}.source-explain{margin-top:12px;border:1px solid #dbe7f7;background:#f8fbff;border-radius:10px;padding:10px}.source-explain-title{font-size:10px;font-weight:700;color:#315fAD}.source-explain p{margin-top:5px;font-size:9.5px;line-height:1.6;color:#5f6f83}.source-evidence{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-top:8px}.source-evidence>span{font-size:9px;color:#8a95a5}.source-evidence button{border:1px solid #d8e4f5;background:#fff;border-radius:999px;padding:3px 7px;font-size:8.5px;color:#3f6fb8}.source-evidence button:hover{background:#edf4ff}.sub-title{display:flex;align-items:center;gap:5px;font-size:9.5px;font-weight:600;color:#526173}.rule-row,.proposal-row{display:flex;align-items:center;gap:8px;padding:8px 0;border-bottom:1px solid #f3f5f7}.rule-priority{display:flex;width:28px;height:22px;align-items:center;justify-content:center;border-radius:7px;background:#edf4ff;font-size:8px;color:#4f7ff0}.rule-row b,.proposal-row b{font-size:9.5px;color:#364152}.rule-row p,.proposal-row p{font-size:8.5px;color:#98a2b3}.proposal-row{justify-content:space-between}.proposal-row button{font-size:9px;color:#2563eb}
.soft-btn,.primary-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;border-radius:9px;padding:7px 11px;font-size:11px;font-weight:500}.soft-btn{border:1px solid #e1e7ee;background:#fff;color:#526173}.soft-btn:hover{background:#f8fafc}.primary-btn{border:1px solid #2563eb;background:#2563eb;color:#fff}.primary-btn:hover{background:#1d4ed8}.soft-btn:disabled,.primary-btn:disabled{opacity:.45;cursor:not-allowed}
.modal-mask{position:fixed;inset:0;z-index:80;display:flex;align-items:center;justify-content:center;background:rgba(15,23,42,.22);backdrop-filter:blur(2px);padding:20px}.modal-card{width:min(560px,94vw);max-height:86vh;overflow:auto;border:1px solid #e4e9ef;background:#fff;border-radius:16px;padding:18px;box-shadow:0 18px 60px rgba(15,23,42,.18)}.modal-card.wide{width:min(920px,96vw)}.modal-head{display:flex;justify-content:space-between;align-items:flex-start;padding-bottom:14px;border-bottom:1px solid #eef1f4}.modal-head b{font-size:14px;color:#1f2937}.modal-head p{margin-top:3px;font-size:10px;color:#8b96a5}.modal-head button{color:#94a3b8}.form-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:16px}.form-grid label span{display:block;margin-bottom:5px;font-size:10px;font-weight:600;color:#637083}.form-grid label.full{grid-column:1/-1}.form-grid input,.form-grid select,.form-input{width:100%;border:1px solid #dfe5ec;border-radius:9px;padding:8px 9px;font-size:11px;outline:none;background:#fff}.form-grid input:focus,.form-grid select:focus,.form-input:focus{border-color:#7aa5ed}.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:18px}.resolution-row{display:grid;grid-template-columns:220px minmax(0,1fr) 54px 72px 78px;gap:10px;align-items:center;padding:12px 0;border-bottom:1px solid #eef1f4}.resolution-row .pair{display:flex;align-items:center;gap:7px;font-size:10px;color:#344054}.resolution-row .grow p{font-size:10px;color:#526173}.resolution-row .grow small{font-size:9px;color:#98a2b3}.resolution-row .score{font-size:12px;font-weight:700;color:#2563eb}
@media(max-width:1200px){.workspace{grid-template-columns:210px minmax(0,1fr) 300px}.rail-toggle.left{left:200px}.rail-toggle.right{right:290px}}@media(max-width:900px){.workspace,.workspace.left-off,.workspace.right-off,.workspace.left-off.right-off{grid-template-columns:1fr}.side-column{display:none}.rail-toggle{display:none}.graph-stage{min-height:620px}.resolution-row{grid-template-columns:1fr}.mode-tabs{overflow:auto}}
.attribution-launch,.attribution-panel{border:1px solid #e7ecf2;background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(15,23,42,.04)}.attribution-launch{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:13px 16px}.attribution-target{min-width:220px}.attribution-panel{padding:16px}.attribution-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}.attribution-summary{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px;margin-top:14px}.attribution-summary>div{border:1px solid #eef1f5;border-radius:9px;padding:9px 11px}.attribution-summary span{display:block;font-size:9px;color:#8a95a5}.attribution-summary strong{display:block;margin-top:4px;font-size:18px;color:#182234}.attribution-columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin-top:16px}.attribution-columns h4,.critical-list h4{margin-bottom:8px;font-size:11px;font-weight:700;color:#344054}.attribution-row{padding:7px 0;border-bottom:1px solid #f1f3f6;font-size:10px;color:#526173}.attribution-row b{color:#2563eb}.attribution-bar{height:5px;margin-top:5px;border-radius:99px;background:#edf2fa;overflow:hidden}.attribution-bar i{display:block;height:100%;border-radius:inherit;background:#5d8fe5}.attribution-bar.entity i{background:#8b6bd1}.attribution-bar.phase i{background:#4eab83}.attribution-row small{display:block;margin-top:4px;font-size:8px;color:#98a2b3}.critical-list{margin-top:16px;padding-top:12px;border-top:1px solid #eef1f5}.critical-list span{display:inline-flex;margin:0 6px 6px 0;border:1px solid #f2dca8;border-radius:99px;background:#fff9e9;padding:4px 8px;font-size:9px;color:#8a6414}@media(max-width:900px){.attribution-launch{align-items:stretch;flex-direction:column}.attribution-target{width:100%}.attribution-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.attribution-columns{grid-template-columns:1fr;gap:10px}}
</style>
