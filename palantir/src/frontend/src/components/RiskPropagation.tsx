import { useEffect, useRef, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import cytoscape from 'cytoscape';
import {
  ZoomIn, ZoomOut, Maximize2, RotateCcw, Loader2, Play, RotateCw,
  AlertTriangle, Shield, Building2, Users, Activity,
  Waves, Target, ChevronDown, ChevronRight, Crosshair,
} from 'lucide-react';
import type {
  RiskPropagationResult,
  PropagationWave,
  GraphData,
  GraphNode,
  RiskCase,
} from '../types';
import { riskPropagationApi, graphApi } from '../services/api';
import { useRiskCases } from '../hooks/useApi';

/* ═══════════════════════════════════════════════════════════════
   Color & Shape Maps
   ═══════════════════════════════════════════════════════════════ */

const NODE_COLORS: Record<string, string> = {
  RiskCase: '#ef4444', SuspectedSabotage: '#ef4444',
  Facility: '#3b82f6', WaterTreatmentPlant: '#3b82f6',
  PumpStation: '#2563eb', Reservoir: '#1d4ed8', DistributionNode: '#60a5fa',
  Event: '#f59e0b', Person: '#10b981', Employee: '#10b981',
  Contractor: '#f59e0b', Asset: '#8b5cf6', Organization: '#06b6d4',
  Sensor: '#14b8a6', Document: '#22d3ee',
};

const NODE_SHAPES: Record<string, string> = {
  RiskCase: 'diamond', SuspectedSabotage: 'diamond',
  Facility: 'hexagon', Event: 'round-rectangle',
  Person: 'ellipse', Asset: 'round-triangle',
  Organization: 'barrel', Sensor: 'round-pentagon',
  Document: 'round-rectangle',
};

function getNodeColor(type: string): string {
  return NODE_COLORS[type] || '#64748b';
}

function getNodeShape(type: string): string {
  for (const [key, shape] of Object.entries(NODE_SHAPES)) {
    if (type.includes(key) || type === key) return shape;
  }
  return 'ellipse';
}

/* ═══════════════════════════════════════════════════════════════
   Risk gradient helpers
   ═══════════════════════════════════════════════════════════════ */

function riskToColor(risk: number): string {
  if (risk >= 7) return '#ef4444';       // red — critical
  if (risk >= 5) return '#f97316';       // orange — high
  if (risk >= 3) return '#eab308';       // yellow — medium
  if (risk >= 1) return '#22c55e';       // green — low
  return '#64748b';                       // gray — minimal
}

function riskToGlow(risk: number): string {
  if (risk >= 7) return 'rgba(239,68,68,0.6)';
  if (risk >= 5) return 'rgba(249,115,22,0.5)';
  if (risk >= 3) return 'rgba(234,179,8,0.4)';
  if (risk >= 1) return 'rgba(34,197,94,0.3)';
  return 'rgba(100,116,139,0.2)';
}

function riskLabel(category: string): string {
  switch (category) {
    case 'critical': return '🔴 CRITICAL';
    case 'high': return '🟠 HIGH';
    case 'medium': return '🟡 MEDIUM';
    case 'low': return '🟢 LOW';
    case 'minimal': return '⚪ MINIMAL';
    default: return category;
  }
}

function riskBadgeStyle(category: string): string {
  switch (category) {
    case 'critical': return 'bg-red-500/20 text-red-400 border-red-500/30';
    case 'high': return 'bg-orange-500/20 text-orange-400 border-orange-500/30';
    case 'medium': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
    case 'low': return 'bg-green-500/20 text-green-400 border-green-500/30';
    default: return 'bg-gray-500/20 text-gray-400 border-gray-500/30';
  }
}

/* ═══════════════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════════════ */

export default function RiskPropagation() {
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const { data: allCases } = useRiskCases();

  // ── State ──
  const [sourceInput, setSourceInput] = useState('');
  const [result, setResult] = useState<RiskPropagationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [maxDepth, setMaxDepth] = useState(5);
  const [decayFactor, setDecayFactor] = useState(0.6);
  const [animating, setAnimating] = useState(false);
  const [currentWave, setCurrentWave] = useState(-1);
  const [expandedWave, setExpandedWave] = useState<number | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);

  // ── Propagate risk ──
  const propagate = useCallback(async (nodeId: string) => {
    if (!nodeId.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setCurrentWave(-1);
    setAnimating(false);
    setSelectedNode(null);

    try {
      const res = await riskPropagationApi.propagate({
        sourceNodeId: nodeId.trim(),
        maxDepth,
        decayFactor,
      });
      setResult(res);
    } catch (err: any) {
      setError(err?.response?.data?.message || err?.message || 'Propagation failed');
    } finally {
      setLoading(false);
    }
  }, [maxDepth, decayFactor]);

  // ── Build Cytoscape graph when result arrives ──
  useEffect(() => {
    if (!containerRef.current || !result) return;

    const { affectedGraph } = result;
    if (!affectedGraph || affectedGraph.nodes.length === 0) return;

    const elements: cytoscape.ElementDefinition[] = [];

    // Add nodes
    for (const n of affectedGraph.nodes) {
      const risk = (n.properties?.propagatedRisk as number) ?? 0;
      const wave = (n.properties?.waveDepth as number) ?? 0;
      const isSource = n.id === result.sourceNodeId;

      elements.push({
        data: {
          id: n.id,
          label: n.label,
          type: n.type,
          color: isSource ? '#ffffff' : riskToColor(risk),
          shape: getNodeShape(n.type),
          risk,
          wave,
          isSource,
          originalColor: getNodeColor(n.type),
          ...n.properties,
        },
      });
    }

    // Add edges
    for (const e of affectedGraph.edges) {
      elements.push({
        data: {
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.type.replace(/_/g, ' '),
          ...e.properties,
        },
      });
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements,
      style: [
        {
          selector: 'node',
          style: {
            label: 'data(label)',
            'background-color': 'data(color)',
            shape: 'data(shape)' as any,
            width: 40,
            height: 40,
            color: '#e2e8f0',
            'font-size': '9px',
            'text-margin-y': -8,
            'text-valign': 'top',
            'text-halign': 'center',
            'border-width': 2,
            'border-color': '#0a0e17',
            'text-outline-width': 2,
            'text-outline-color': '#0a0e17',
            'transition-property': 'background-color, border-color, border-width, width, height, opacity',
            'transition-duration': 500,
            opacity: 0.25,
          },
        },
        {
          selector: 'node[?isSource]',
          style: {
            width: 65,
            height: 65,
            'border-width': 4,
            'border-color': '#ef4444',
            'background-color': '#ef4444',
            'font-size': '12px',
            'font-weight': 'bold',
            opacity: 1,
            'overlay-color': '#ef4444',
            'overlay-opacity': 0.2,
          },
        },
        {
          selector: 'node.wave-visible',
          style: {
            opacity: 1,
          },
        },
        {
          selector: 'node.wave-pulse',
          style: {
            'border-width': 4,
            'border-color': 'data(color)',
            width: 55,
            height: 55,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': 4,
            'border-color': '#06b6d4',
            width: 55,
            height: 55,
          },
        },
        {
          selector: 'edge',
          style: {
            label: 'data(label)',
            width: 1.5,
            'line-color': '#1e293b',
            'target-arrow-color': '#1e293b',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            color: '#334155',
            'font-size': '7px',
            'text-rotation': 'autorotate',
            'text-outline-width': 1.5,
            'text-outline-color': '#0a0e17',
            opacity: 0.15,
            'transition-property': 'line-color, target-arrow-color, width, opacity',
            'transition-duration': 500,
          },
        },
        {
          selector: 'edge.wave-visible',
          style: {
            'line-color': '#475569',
            'target-arrow-color': '#475569',
            opacity: 0.6,
            width: 2,
          },
        },
        {
          selector: 'edge.wave-propagation',
          style: {
            'line-color': '#f59e0b',
            'target-arrow-color': '#f59e0b',
            width: 3,
            'line-style': 'dashed',
            opacity: 1,
          },
        },
      ],
      layout: {
        name: 'concentric',
        concentric: (node: any) => {
          const wave = node.data('wave') || 0;
          const isSource = node.data('isSource');
          return isSource ? 100 : (10 - wave);
        },
        levelWidth: () => 1,
        animate: true,
        animationDuration: 1000,
        padding: 60,
        minNodeSpacing: 40,
      },
      minZoom: 0.15,
      maxZoom: 3,
    });

    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      setSelectedNode({
        id: node.data('id'),
        label: node.data('label'),
        type: node.data('type'),
        properties: node.data(),
      });
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy) setSelectedNode(null);
    });

    cyRef.current = cy;

    // Make source node always visible
    cy.nodes('[?isSource]').addClass('wave-visible');

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
      cy.destroy();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result]);

  // ── Shockwave Animation ──
  const playShockwave = useCallback(() => {
    if (!result || !cyRef.current) return;
    const cy = cyRef.current;

    // Reset all nodes to dimmed
    cy.nodes().removeClass('wave-visible wave-pulse');
    cy.edges().removeClass('wave-visible wave-propagation');
    cy.nodes('[?isSource]').addClass('wave-visible');

    setAnimating(true);
    setCurrentWave(-1);

    const waves = result.waves;
    let waveIndex = 0;

    const animateNextWave = () => {
      if (waveIndex >= waves.length) {
        setAnimating(false);
        return;
      }

      const wave = waves[waveIndex];
      setCurrentWave(wave.depth);

      // Reveal nodes in this wave
      const nodeIds = wave.nodes.map((n) => n.id);
      for (const id of nodeIds) {
        const node = cy.getElementById(id);
        if (node.length) {
          node.addClass('wave-visible wave-pulse');

          // Animate edges connecting to parent
          const parentId = wave.nodes.find((n) => n.id === id)?.parentId;
          if (parentId) {
            cy.edges().forEach((edge) => {
              const src = edge.data('source');
              const tgt = edge.data('target');
              if ((src === parentId && tgt === id) || (src === id && tgt === parentId)) {
                edge.addClass('wave-visible wave-propagation');
              }
            });
          }
        }
      }

      // Remove pulse after brief delay
      setTimeout(() => {
        for (const id of nodeIds) {
          const node = cy.getElementById(id);
          if (node.length) node.removeClass('wave-pulse');
        }
        // Downgrade edges from propagation to visible
        cy.edges('.wave-propagation').forEach((edge) => {
          const src = edge.data('source');
          const tgt = edge.data('target');
          const srcInWave = nodeIds.includes(src);
          const tgtInWave = nodeIds.includes(tgt);
          if (srcInWave || tgtInWave) {
            edge.removeClass('wave-propagation');
            edge.addClass('wave-visible');
          }
        });
      }, 800);

      waveIndex++;
      setTimeout(animateNextWave, 1200);
    };

    // Start after brief initial pause
    setTimeout(animateNextWave, 500);
  }, [result]);

  // ── Show all waves at once ──
  const showAllWaves = useCallback(() => {
    if (!cyRef.current) return;
    const cy = cyRef.current;
    cy.nodes().addClass('wave-visible');
    cy.edges().addClass('wave-visible');
    setCurrentWave(result?.waves.length ?? 0);
    setAnimating(false);
  }, [result]);

  // ── Zoom controls ──
  const handleZoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.3);
  const handleZoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() * 0.7);
  const handleFit = () => cyRef.current?.fit(undefined, 50);
  const handleReset = () => {
    cyRef.current?.layout({
      name: 'concentric',
      concentric: (node: any) => {
        const isSource = node.data('isSource');
        const wave = node.data('wave') || 0;
        return isSource ? 100 : (10 - wave);
      },
      levelWidth: () => 1,
      animate: true,
    } as any).run();
  };

  return (
    <div className="h-full flex flex-col gap-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100">
            🌊 Risk Propagation
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Shockwave Analysis · BFS Risk Decay · Impact Prediction
          </p>
        </div>
      </div>

      <div className="flex-1 flex gap-4 min-h-0">
        {/* ── Left: Controls + Waves Panel ── */}
        <div className="w-80 flex flex-col gap-4">
          {/* Source Selection */}
          <div className="aegis-card p-4 space-y-4">
            <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
              <Target className="w-4 h-4 text-red-400" />
              Propagation Source
            </h3>

            {/* Quick-select from risk cases */}
            {allCases && allCases.length > 0 && (
              <div>
                <p className="text-[10px] text-gray-600 uppercase tracking-wider mb-2">Risk Cases</p>
                <div className="space-y-1.5 max-h-36 overflow-auto">
                  {allCases.map((c: RiskCase) => (
                    <button
                      key={c.caseId}
                      onClick={() => { setSourceInput(c.caseId); propagate(c.caseId); }}
                      className={`w-full flex items-center gap-2 px-3 py-2 rounded-lg border text-left text-xs transition-all ${
                        sourceInput === c.caseId
                          ? 'bg-red-500/15 border-red-500/40 text-red-300'
                          : 'bg-[var(--aegis-surface-2)] border-[var(--aegis-border)] text-gray-400 hover:text-gray-200 hover:border-gray-600'
                      }`}
                    >
                      <AlertTriangle className="w-3.5 h-3.5 text-red-400 flex-shrink-0" />
                      <span className="truncate flex-1">{c.title}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-red-500/20 text-red-400">
                        {c.riskScore.toFixed(1)}
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* Custom node ID */}
            <div>
              <p className="text-[10px] text-gray-600 uppercase tracking-wider mb-1.5">Or enter Node ID</p>
              <div className="flex gap-2">
                <input
                  value={sourceInput}
                  onChange={(e) => setSourceInput(e.target.value)}
                  placeholder="e.g. CASE-001, FAC-01..."
                  className="flex-1 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] px-3 py-2 text-xs text-gray-200 placeholder-gray-600 focus:outline-none focus:border-red-500/50"
                  onKeyDown={(e) => e.key === 'Enter' && propagate(sourceInput)}
                />
                <button
                  onClick={() => propagate(sourceInput)}
                  disabled={loading || !sourceInput.trim()}
                  className="px-3 py-2 rounded-lg bg-red-500/20 border border-red-500/30 text-red-400 text-xs font-semibold hover:bg-red-500/30 transition-colors disabled:opacity-30"
                >
                  {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Crosshair className="w-4 h-4" />}
                </button>
              </div>
            </div>

            {/* Parameters */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-gray-500 uppercase tracking-wider">Max Depth</label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={maxDepth}
                  onChange={(e) => setMaxDepth(Number(e.target.value))}
                  className="w-full mt-1 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-red-500/50"
                />
              </div>
              <div>
                <label className="text-[10px] text-gray-500 uppercase tracking-wider">Decay Factor</label>
                <input
                  type="number"
                  min={0.1}
                  max={0.99}
                  step={0.05}
                  value={decayFactor}
                  onChange={(e) => setDecayFactor(Number(e.target.value))}
                  className="w-full mt-1 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] px-3 py-1.5 text-xs text-gray-200 focus:outline-none focus:border-red-500/50"
                />
              </div>
            </div>
          </div>

          {/* ── Summary Stats ── */}
          {result && (
            <div className="aegis-card p-4 space-y-3">
              <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                <Activity className="w-4 h-4 text-amber-400" />
                Impact Summary
              </h3>
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2.5 rounded-lg bg-red-500/10 border border-red-500/20 text-center">
                  <p className="text-lg font-bold text-red-400">{result.summary.criticalNodes}</p>
                  <p className="text-[10px] text-gray-500">Critical</p>
                </div>
                <div className="p-2.5 rounded-lg bg-orange-500/10 border border-orange-500/20 text-center">
                  <p className="text-lg font-bold text-orange-400">{result.summary.highRiskNodes}</p>
                  <p className="text-[10px] text-gray-500">High Risk</p>
                </div>
                <div className="p-2.5 rounded-lg bg-blue-500/10 border border-blue-500/20 text-center">
                  <p className="text-lg font-bold text-blue-400">{result.summary.facilitiesAffected}</p>
                  <p className="text-[10px] text-gray-500">Facilities</p>
                </div>
                <div className="p-2.5 rounded-lg bg-emerald-500/10 border border-emerald-500/20 text-center">
                  <p className="text-lg font-bold text-emerald-400">{result.summary.personsAffected}</p>
                  <p className="text-[10px] text-gray-500">Persons</p>
                </div>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">Total affected</span>
                <span className="text-gray-300 font-semibold">{result.summary.totalAffectedNodes} nodes</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">Max propagated risk</span>
                <span className="text-red-400 font-semibold">{result.summary.maxPropagatedRisk.toFixed(2)}</span>
              </div>
              {result.summary.criticalPaths.length > 0 && (
                <div>
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">Critical Paths</p>
                  <div className="space-y-1">
                    {result.summary.criticalPaths.map((path, i) => (
                      <p key={i} className="text-[11px] text-red-300 font-mono bg-red-500/5 px-2 py-1 rounded">
                        {path}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* ── Propagation Waves ── */}
          {result && result.waves.length > 0 && (
            <div className="aegis-card p-4 flex-1 overflow-auto">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-200 flex items-center gap-2">
                  <Waves className="w-4 h-4 text-cyan-400" />
                  Propagation Waves
                </h3>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={playShockwave}
                    disabled={animating}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-400 text-[10px] font-semibold hover:bg-amber-500/25 transition-colors disabled:opacity-30"
                  >
                    <Play className="w-3 h-3" />
                    Replay
                  </button>
                  <button
                    onClick={showAllWaves}
                    className="flex items-center gap-1 px-2 py-1 rounded-lg bg-cyan-500/15 border border-cyan-500/30 text-cyan-400 text-[10px] font-semibold hover:bg-cyan-500/25 transition-colors"
                  >
                    Show All
                  </button>
                </div>
              </div>

              <div className="space-y-2">
                {result.waves.map((wave: PropagationWave) => (
                  <div
                    key={wave.depth}
                    className={`rounded-lg border transition-all ${
                      currentWave === wave.depth
                        ? 'border-amber-500/40 bg-amber-500/5 shadow-[0_0_15px_rgba(245,158,11,0.15)]'
                        : currentWave > wave.depth || currentWave === -1
                          ? 'border-[var(--aegis-border)] bg-[var(--aegis-surface-2)]'
                          : 'border-[var(--aegis-border)] bg-[var(--aegis-surface-2)] opacity-40'
                    }`}
                  >
                    <button
                      onClick={() => setExpandedWave(expandedWave === wave.depth ? null : wave.depth)}
                      className="w-full flex items-center gap-2 px-3 py-2.5 text-left"
                    >
                      <span className={`text-xs font-bold px-2 py-0.5 rounded-full border ${riskBadgeStyle(wave.riskCategory)}`}>
                        D{wave.depth}
                      </span>
                      <div className="flex-1 min-w-0">
                        <span className="text-xs text-gray-300 font-medium">
                          {wave.nodes.length} node{wave.nodes.length > 1 ? 's' : ''}
                        </span>
                        <span className="text-[10px] text-gray-500 ml-2">
                          Risk: {wave.riskLevel.toFixed(2)}
                        </span>
                      </div>
                      <span className={`text-[10px] font-bold ${riskBadgeStyle(wave.riskCategory).split(' ')[1]}`}>
                        {wave.riskCategory.toUpperCase()}
                      </span>
                      {expandedWave === wave.depth
                        ? <ChevronDown className="w-3 h-3 text-gray-500" />
                        : <ChevronRight className="w-3 h-3 text-gray-500" />
                      }
                    </button>

                    {expandedWave === wave.depth && (
                      <div className="px-3 pb-3 space-y-1.5">
                        {wave.nodes.map((node) => (
                          <div
                            key={node.id}
                            className="flex items-center gap-2 px-2 py-1.5 rounded-lg bg-[var(--aegis-surface)] hover:bg-white/5 cursor-pointer transition-colors"
                            onClick={() => {
                              const cyNode = cyRef.current?.getElementById(node.id);
                              if (cyNode?.length) {
                                cyRef.current?.animate({
                                  center: { eles: cyNode },
                                  zoom: 1.5,
                                } as any, { duration: 500 });
                                cyNode.select();
                              }
                            }}
                          >
                            <div
                              className="w-3 h-3 rounded-full flex-shrink-0"
                              style={{ backgroundColor: riskToColor(node.inheritedRisk) }}
                            />
                            <span className="text-xs text-gray-300 truncate flex-1">
                              {node.label}
                            </span>
                            <span className="text-[10px] text-gray-500">
                              {node.type}
                            </span>
                            <span className="text-[10px] font-mono text-amber-400">
                              {node.inheritedRisk.toFixed(2)}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {error && (
            <div className="aegis-card p-4 text-center">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}
        </div>

        {/* ── Right: Graph Visualization ── */}
        <div className="flex-1 flex flex-col gap-4">
          <div className="flex-1 aegis-card relative overflow-hidden">
            {result ? (
              <>
                <div ref={containerRef} className="w-full h-full min-h-[500px]" />

                {/* Animation overlay */}
                {animating && (
                  <div className="absolute top-4 left-1/2 -translate-x-1/2 flex items-center gap-2.5 px-5 py-2.5 rounded-xl bg-amber-500/10 border border-amber-500/30 backdrop-blur-sm z-10 shadow-[0_0_20px_rgba(245,158,11,0.15)]">
                    <Waves className="w-4 h-4 text-amber-400 animate-pulse" />
                    <span className="text-sm text-amber-300 font-medium">
                      Wave {currentWave} propagating…
                    </span>
                  </div>
                )}

                {/* Zoom controls */}
                <div className="absolute top-4 right-4 flex flex-col gap-2">
                  {[
                    { icon: ZoomIn, action: handleZoomIn, title: 'Zoom In' },
                    { icon: ZoomOut, action: handleZoomOut, title: 'Zoom Out' },
                    { icon: Maximize2, action: handleFit, title: 'Fit to Screen' },
                    { icon: RotateCcw, action: handleReset, title: 'Reset Layout' },
                  ].map(({ icon: Icon, action, title }) => (
                    <button
                      key={title}
                      onClick={action}
                      title={title}
                      className="w-8 h-8 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-400 hover:text-cyan-400 hover:border-cyan-500/50 transition-colors"
                    >
                      <Icon className="w-4 h-4" />
                    </button>
                  ))}

                  <div className="mt-1 pt-1 border-t border-[var(--aegis-border)]" />

                  {/* Play shockwave */}
                  <button
                    onClick={playShockwave}
                    disabled={animating}
                    title="Play Shockwave"
                    className="w-8 h-8 rounded-lg bg-amber-500/20 border border-amber-500/30 flex items-center justify-center text-amber-400 hover:bg-amber-500/30 transition-colors disabled:opacity-30"
                  >
                    <Play className="w-4 h-4" />
                  </button>
                </div>

                {/* Source info */}
                <div className="absolute bottom-4 left-4 aegis-card p-3">
                  <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1.5">Source</p>
                  <div className="flex items-center gap-2">
                    <div className="w-4 h-4 rounded-full bg-red-500 ring-2 ring-red-500/30" />
                    <div>
                      <p className="text-xs font-semibold text-gray-200">{result.sourceLabel}</p>
                      <p className="text-[10px] text-gray-500">{result.sourceType} · Risk {result.sourceRisk.toFixed(1)}</p>
                    </div>
                  </div>
                  <div className="mt-2 pt-2 border-t border-[var(--aegis-border)]">
                    <p className="text-[10px] text-gray-500 mb-1">Risk Gradient</p>
                    <div className="flex items-center gap-1">
                      {['#ef4444', '#f97316', '#eab308', '#22c55e', '#64748b'].map((c) => (
                        <div key={c} className="w-5 h-2 rounded-full" style={{ backgroundColor: c }} />
                      ))}
                    </div>
                    <div className="flex items-center justify-between mt-0.5">
                      <span className="text-[8px] text-gray-600">Critical</span>
                      <span className="text-[8px] text-gray-600">Minimal</span>
                    </div>
                  </div>
                </div>

                {/* Selected node detail */}
                {selectedNode && (
                  <div className="absolute top-4 left-4 w-64 aegis-card p-3 z-10">
                    <div className="flex items-center gap-2 mb-2 pb-2 border-b border-[var(--aegis-border)]">
                      <div
                        className="w-4 h-4 rounded-full"
                        style={{ backgroundColor: riskToColor(selectedNode.properties.risk as number || 0) }}
                      />
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-semibold text-gray-200 truncate">{selectedNode.label}</p>
                        <p className="text-[10px] text-gray-500">{selectedNode.type}</p>
                      </div>
                    </div>
                    <div className="space-y-1.5">
                      {selectedNode.properties.risk !== undefined && (
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] text-gray-500">Propagated Risk</span>
                          <span className="text-xs font-bold" style={{ color: riskToColor(selectedNode.properties.risk as number) }}>
                            {(selectedNode.properties.risk as number).toFixed(2)}
                          </span>
                        </div>
                      )}
                      {selectedNode.properties.wave !== undefined && (
                        <div className="flex items-center justify-between">
                          <span className="text-[10px] text-gray-500">Wave Depth</span>
                          <span className="text-xs text-gray-300">{selectedNode.properties.wave as number}</span>
                        </div>
                      )}
                      <button
                        onClick={() => navigate(`/graph/${selectedNode.id}`)}
                        className="w-full mt-2 px-2 py-1.5 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-[10px] hover:bg-cyan-500/20 transition-colors text-center"
                      >
                        Open in Graph Explorer →
                      </button>
                    </div>
                  </div>
                )}
              </>
            ) : (
              /* Empty state */
              <div className="h-full flex items-center justify-center">
                <div className="text-center max-w-sm">
                  <div className="text-6xl mb-4">🌊</div>
                  <h3 className="text-lg font-bold text-gray-200 mb-2">Risk Propagation Engine</h3>
                  <p className="text-sm text-gray-500 mb-4">
                    Select a risk case or enter a node ID to simulate how risk propagates
                    through the knowledge graph. Watch the shockwave expand in real-time.
                  </p>
                  {loading && (
                    <div className="flex items-center justify-center gap-2 text-amber-400">
                      <Loader2 className="w-5 h-5 animate-spin" />
                      <span className="text-sm">Computing propagation…</span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
