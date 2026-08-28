import { useEffect, useRef, useState, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import cytoscape from 'cytoscape';
import { useCaseGraph, useGraphExplore, useRiskCases } from '../hooks/useApi';
import {
  ZoomIn, ZoomOut, Maximize2, RotateCcw, Info, ChevronLeft,
  MousePointerClick, Network, Loader2, X, Crosshair,
  CircleDot, ArrowRight, Sparkles, Eye, EyeOff,
} from 'lucide-react';
import type { GraphData, GraphNode, DiscoveredPath, LinkAnalysisResult } from '../types';
import RiskInvestigation from './RiskInvestigation';
import LinkAnalysisPanel from './LinkAnalysisPanel';
import { graphApi } from '../services/api';

const NODE_COLORS: Record<string, string> = {
  RiskCase: '#ef4444',
  SuspectedSabotage: '#ef4444',
  Facility: '#3b82f6',
  WaterTreatmentPlant: '#3b82f6',
  PumpStation: '#2563eb',
  Reservoir: '#1d4ed8',
  DistributionNode: '#60a5fa',
  Event: '#f59e0b',
  PhysicalAnomalyEvent: '#ef4444',
  AccessEvent: '#f97316',
  CyberAlertEvent: '#a855f7',
  CitizenReportEvent: '#06b6d4',
  MaintenanceEvent: '#64748b',
  Person: '#10b981',
  Employee: '#10b981',
  Contractor: '#f59e0b',
  Asset: '#8b5cf6',
  PLC: '#a855f7',
  Valve: '#7c3aed',
  Pump: '#6d28d9',
  Camera: '#5b21b6',
  Organization: '#06b6d4',
  Sensor: '#14b8a6',
  Location: '#f472b6',
  Document: '#22d3ee',
};

const NODE_SHAPES: Record<string, string> = {
  RiskCase: 'diamond',
  SuspectedSabotage: 'diamond',
  Facility: 'hexagon',
  Event: 'round-rectangle',
  Person: 'ellipse',
  Asset: 'round-triangle',
  Organization: 'barrel',
  Sensor: 'round-pentagon',
  Location: 'star',
  Document: 'round-rectangle',
};

// Event node types to toggle visibility
function isEventType(type: string): boolean {
  return type.includes('Event') || type === 'SensorReading' || type === 'Maintenance'
    || type === 'Access' || type === 'QualityCheck' || type === 'SystemStatus';
}

function getNodeShape(type: string): string {
  for (const [key, shape] of Object.entries(NODE_SHAPES)) {
    if (type.includes(key) || type === key) return shape;
  }
  return 'ellipse';
}

function getNodeColor(type: string): string {
  return NODE_COLORS[type] || '#64748b';
}

function graphDataToCyElements(data: GraphData) {
  const nodes = data.nodes.map((n) => ({
    data: {
      id: n.id,
      label: n.label,
      type: n.type,
      color: getNodeColor(n.type),
      shape: getNodeShape(n.type),
      ...n.properties,
    },
  }));

  const edges = data.edges.map((e) => ({
    data: {
      id: e.id,
      source: e.source,
      target: e.target,
      label: e.type.replace(/_/g, ' '),
      ...e.properties,
    },
  }));

  return [...nodes, ...edges];
}

export default function GraphExplorer() {
  const { nodeId } = useParams<{ nodeId: string }>();
  const navigate = useNavigate();
  const containerRef = useRef<HTMLDivElement>(null);
  const cyRef = useRef<cytoscape.Core | null>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [exploreId, setExploreId] = useState<string | null>(nodeId || null);

  // ── Link Analysis State ──
  const [selectMode, setSelectMode] = useState(false);
  const [multiSelected, setMultiSelected] = useState<Set<string>>(new Set());
  const [linkResult, setLinkResult] = useState<LinkAnalysisResult | null>(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [highlightedPath, setHighlightedPath] = useState<DiscoveredPath | null>(null);
  const [showEvents, setShowEvents] = useState(false);

  // Detect if it's a case or generic node
  const isCaseId = exploreId?.startsWith('CASE-');
  const { data: caseGraph } = useCaseGraph(isCaseId ? exploreId : null);
  const { data: nodeGraph } = useGraphExplore(!isCaseId ? exploreId : null);
  const graphData = isCaseId ? caseGraph : nodeGraph;

  // Get case info for the AI panel title
  const { data: allCases } = useRiskCases();
  const currentCase = isCaseId && allCases
    ? allCases.find((c) => c.caseId === exploreId)
    : null;

  useEffect(() => {
    if (nodeId) setExploreId(nodeId);
  }, [nodeId]);

  // Auto-load first risk case when no node is selected
  useEffect(() => {
    if (!exploreId && allCases && allCases.length > 0) {
      const first = allCases[0].caseId;
      setExploreId(first);
      navigate(`/graph/${first}`, { replace: true });
    }
  }, [exploreId, allCases, navigate]);

  // If the explored node is not found in the graph, redirect to first case
  useEffect(() => {
    if (graphData && graphData.nodes.length === 0 && exploreId && allCases && allCases.length > 0) {
      const first = allCases[0].caseId;
      setExploreId(first);
      navigate(`/graph/${first}`, { replace: true });
    }
  }, [graphData, exploreId, allCases, navigate]);

  // ── Toggle multi-select on a node ──
  const toggleMultiSelect = useCallback((nodeId: string) => {
    setMultiSelected(prev => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId);
      else next.add(nodeId);
      return next;
    });
  }, []);

  // ── Run link analysis ──
  const runLinkAnalysis = useCallback(async () => {
    if (multiSelected.size < 2) return;
    setIsAnalyzing(true);
    try {
      const result = await graphApi.analyzeLinks([...multiSelected]);
      setLinkResult(result);
    } catch (err) {
      console.error('Link analysis failed:', err);
    } finally {
      setIsAnalyzing(false);
    }
  }, [multiSelected]);

  // ── Close link analysis ──
  const closeLinkAnalysis = useCallback(() => {
    setLinkResult(null);
    setHighlightedPath(null);
    setSelectMode(false);
    setMultiSelected(new Set());
    // Remove overlay styles
    const cy = cyRef.current;
    if (cy) {
      cy.elements().removeClass('link-path link-path-hidden link-path-node link-dimmed');
    }
  }, []);

  // ── Highlight path on graph ──
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    // Clear old highlights
    cy.elements().removeClass('link-path link-path-hidden link-path-node link-dimmed');

    if (!highlightedPath) return;

    // Dim everything first
    cy.elements().addClass('link-dimmed');

    // Extract node IDs from the path's nodeSequence
    // nodeSequence is like ["Person:García", "Facility:ETAP"], but we need actual IDs
    // The result.graph has the actual nodes, so we match via the path's fromId/toId and graph edges
    const pathNodeIds = new Set<string>();
    const pathEdgeKeys = new Set<string>();

    // We need to find the actual path in the graph data
    // The paths contain fromId and toId, and we can trace through the graph
    if (linkResult) {
      // Find all nodes that match this path's node sequence
      for (const node of linkResult.graph.nodes) {
        const nodeLabel = `${node.type}:${node.label}`;
        if (highlightedPath.nodeSequence.some(seq => seq === nodeLabel || node.label === seq.split(':').slice(1).join(':'))) {
          pathNodeIds.add(node.id);
        }
      }
      // Always include from/to
      pathNodeIds.add(highlightedPath.fromId);
      pathNodeIds.add(highlightedPath.toId);

      // Find edges between path nodes
      for (const edge of linkResult.graph.edges) {
        if (pathNodeIds.has(edge.source) && pathNodeIds.has(edge.target)) {
          pathEdgeKeys.add(edge.id);
        }
      }
    }

    // Apply highlight styles
    cy.nodes().forEach(node => {
      if (pathNodeIds.has(node.data('id'))) {
        node.removeClass('link-dimmed');
        node.addClass('link-path-node');
      }
    });

    cy.edges().forEach(edge => {
      if (pathEdgeKeys.has(edge.data('id'))) {
        edge.removeClass('link-dimmed');
        edge.addClass(highlightedPath.length > 1 ? 'link-path-hidden' : 'link-path');
      }
    });
  }, [highlightedPath, linkResult]);

  // ── Update multi-select visual ring on nodes ──
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.nodes().forEach(node => {
      if (multiSelected.has(node.data('id'))) {
        node.addClass('multi-selected');
      } else {
        node.removeClass('multi-selected');
      }
    });
  }, [multiSelected]);

  // ── Toggle event nodes visibility ──
  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) return;

    cy.batch(() => {
      cy.nodes().forEach((node: any) => {
        if (isEventType(node.data('type') || '')) {
          if (showEvents) {
            node.style('display', 'element');
            node.connectedEdges().forEach((edge: any) => {
              const src = edge.source();
              const tgt = edge.target();
              if (src.style('display') !== 'none' && tgt.style('display') !== 'none') {
                edge.style('display', 'element');
              }
            });
          } else {
            node.style('display', 'none');
            node.connectedEdges().style('display', 'none');
          }
        }
      });
    });
  }, [showEvents, graphData]);

  useEffect(() => {
    if (!containerRef.current || !graphData) return;

    const elements = graphDataToCyElements(graphData);
    if (elements.length === 0) return;

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
            width: 45,
            height: 45,
            color: '#e2e8f0',
            'font-size': '10px',
            'text-margin-y': -8,
            'text-valign': 'top',
            'text-halign': 'center',
            'border-width': 2,
            'border-color': '#0a0e17',
            'text-outline-width': 2,
            'text-outline-color': '#0a0e17',
            'overlay-padding': 6,
            'transition-property': 'border-color, border-width, width, height, opacity',
            'transition-duration': 300,
          },
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': 3,
            'border-color': '#06b6d4',
            width: 55,
            height: 55,
          },
        },
        {
          selector: 'node.multi-selected',
          style: {
            'border-width': 4,
            'border-color': '#06b6d4',
            'border-style': 'double' as any,
            width: 55,
            height: 55,
            'overlay-color': '#06b6d4',
            'overlay-opacity': 0.15,
          },
        },
        {
          selector: 'node[type="RiskCase"], node[type="SuspectedSabotage"]',
          style: {
            width: 60,
            height: 60,
            'font-size': '12px',
            'font-weight': 'bold',
          },
        },
        {
          selector: 'edge',
          style: {
            label: 'data(label)',
            width: 1.5,
            'line-color': '#334155',
            'target-arrow-color': '#334155',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            color: '#475569',
            'font-size': '8px',
            'text-rotation': 'autorotate',
            'text-outline-width': 1.5,
            'text-outline-color': '#0a0e17',
            'transition-property': 'line-color, target-arrow-color, width, opacity',
            'transition-duration': 300,
          },
        },
        {
          selector: 'edge:selected',
          style: {
            'line-color': '#06b6d4',
            'target-arrow-color': '#06b6d4',
            width: 3,
          },
        },
        // ── Link Analysis Overlays ──
        {
          selector: '.link-dimmed',
          style: {
            opacity: 0.15,
          },
        },
        {
          selector: '.link-path',
          style: {
            'line-color': '#10b981',
            'target-arrow-color': '#10b981',
            width: 3,
            opacity: 1,
            'z-index': 10,
          },
        },
        {
          selector: '.link-path-hidden',
          style: {
            'line-color': '#ef4444',
            'target-arrow-color': '#ef4444',
            width: 4,
            'line-style': 'dashed',
            opacity: 1,
            'z-index': 10,
          },
        },
        {
          selector: '.link-path-node',
          style: {
            'border-width': 4,
            'border-color': '#f59e0b',
            width: 55,
            height: 55,
            opacity: 1,
            'z-index': 10,
            'overlay-color': '#f59e0b',
            'overlay-opacity': 0.12,
          },
        },
      ],
      layout: {
        name: 'cose',
        animate: true,
        animationDuration: 800,
        nodeRepulsion: () => 8000,
        idealEdgeLength: () => 120,
        gravity: 0.25,
        padding: 50,
      },
      minZoom: 0.2,
      maxZoom: 3,
    });

    cy.on('tap', 'node', (evt) => {
      const node = evt.target;
      const id = node.data('id');

      // If in select mode, toggle multi-select
      if (selectMode) {
        toggleMultiSelect(id);
        return;
      }

      setSelectedNode({
        id,
        label: node.data('label'),
        type: node.data('type'),
        properties: node.data(),
      });
    });

    cy.on('dbltap', 'node', (evt) => {
      if (selectMode) return; // Don't navigate in select mode
      const id = evt.target.data('id');
      navigate(`/graph/${id}`);
    });

    cy.on('tap', (evt) => {
      if (evt.target === cy && !selectMode) setSelectedNode(null);
    });

    cyRef.current = cy;

    // Re-apply multi-select visual if nodes were previously selected
    if (multiSelected.size > 0) {
      cy.nodes().forEach(node => {
        if (multiSelected.has(node.data('id'))) {
          node.addClass('multi-selected');
        }
      });
    }

    // Hide event nodes by default
    if (!showEvents) {
      cy.batch(() => {
        cy.nodes().forEach((node: any) => {
          if (isEventType(node.data('type') || '')) {
            node.style('display', 'none');
            node.connectedEdges().style('display', 'none');
          }
        });
      });
    }

    return () => {
      cy.destroy();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graphData, navigate, selectMode]);

  const handleZoomIn = () => cyRef.current?.zoom(cyRef.current.zoom() * 1.3);
  const handleZoomOut = () => cyRef.current?.zoom(cyRef.current.zoom() * 0.7);
  const handleFit = () => cyRef.current?.fit(undefined, 50);
  const handleReset = () => {
    cyRef.current?.layout({ name: 'cose', animate: true } as any).run();
  };

  const showLinkPanel = linkResult && !isCaseId;

  // ── Current step for the guided flow ──
  const linkStep: 0 | 1 | 2 | 3 =
    !selectMode ? 0
    : multiSelected.size < 2 ? 1
    : !linkResult ? 2
    : 3;

  return (
    <div className="h-full flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          {isCaseId && (
            <button
              onClick={() => navigate('/cases')}
              className="w-8 h-8 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-400 hover:text-cyan-400 hover:border-cyan-500/50 transition-colors"
              title="Back to Risk Cases"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}
          <div>
            <h2 className="text-xl font-bold text-gray-100">
              {currentCase ? currentCase.title : 'Graph Explorer'}
            </h2>
            <p className="text-xs text-gray-500 mt-1">
              {currentCase
                ? `Risk ${currentCase.riskScore.toFixed(1)}/10 · ${currentCase.linkedEventsCount} events · ${currentCase.facilityName ?? 'Multiple facilities'}`
                : 'Navigate entities and relationships · Double-click to expand'}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* ── Link Analysis Main Button ── */}
          {!isCaseId && graphData && (
            <button
              onClick={() => {
                if (selectMode) {
                  closeLinkAnalysis();
                } else {
                  setSelectMode(true);
                  setSelectedNode(null);
                  setLinkResult(null);
                }
              }}
              className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition-all ${
                selectMode
                  ? 'bg-cyan-500/20 border-2 border-cyan-400/60 text-cyan-300 shadow-[0_0_20px_rgba(6,182,212,0.25)]'
                  : 'bg-gradient-to-r from-cyan-500/15 to-blue-500/15 border-2 border-cyan-500/30 text-cyan-400 hover:from-cyan-500/25 hover:to-blue-500/25 hover:border-cyan-400/50 hover:shadow-[0_0_20px_rgba(6,182,212,0.2)]'
              }`}
            >
              <Network className="w-4 h-4" />
              {selectMode ? 'Exit Link Analysis' : '🔗 Link Analysis'}
            </button>
          )}

          {/* Quick case buttons */}
          {!nodeId && !selectMode && allCases && allCases.length > 0 && (
            <>
              {allCases.slice(0, 3).map((c) => (
                <button
                  key={c.caseId}
                  onClick={() => {
                    setExploreId(c.caseId);
                    navigate(`/graph/${c.caseId}`);
                  }}
                  className="px-3 py-1.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs hover:bg-red-500/20 transition-colors max-w-[160px] truncate"
                  title={c.title}
                >
                  ⚠ {c.title.length > 18 ? c.title.slice(0, 18) + '…' : c.title}
                </button>
              ))}
            </>
          )}
        </div>
      </div>

      {/* ── Link Analysis Step Guide ── */}
      {selectMode && (
        <div className="link-guide-bar flex items-center gap-0 px-4 py-3 rounded-xl bg-[var(--aegis-surface)] border border-cyan-500/20">
          {/* Step 1 */}
          <div className={`flex items-center gap-2 flex-1 ${linkStep >= 1 ? 'opacity-100' : 'opacity-40'}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all ${
              linkStep === 1 ? 'bg-cyan-500 text-white shadow-[0_0_12px_rgba(6,182,212,0.5)] animate-pulse-glow' : linkStep > 1 ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-[var(--aegis-surface-2)] text-gray-500 border border-[var(--aegis-border)]'
            }`}>
              {linkStep > 1 ? '✓' : '1'}
            </div>
            <div className="min-w-0">
              <p className={`text-xs font-medium ${linkStep === 1 ? 'text-cyan-300' : linkStep > 1 ? 'text-emerald-400' : 'text-gray-500'}`}>
                Select nodes
              </p>
              <p className="text-[10px] text-gray-500 truncate">
                {linkStep === 1 ? `Click on 2+ entities (${multiSelected.size} selected)` : linkStep > 1 ? `${multiSelected.size} nodes selected` : 'Click entities'}
              </p>
            </div>
          </div>

          <ArrowRight className="w-4 h-4 text-gray-600 mx-2 shrink-0" />

          {/* Step 2 */}
          <div className={`flex items-center gap-2 flex-1 ${linkStep >= 2 ? 'opacity-100' : 'opacity-40'}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all ${
              linkStep === 2 ? 'bg-cyan-500 text-white shadow-[0_0_12px_rgba(6,182,212,0.5)] animate-pulse-glow' : linkStep > 2 ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-[var(--aegis-surface-2)] text-gray-500 border border-[var(--aegis-border)]'
            }`}>
              {linkStep > 2 ? '✓' : '2'}
            </div>
            <div className="min-w-0">
              <p className={`text-xs font-medium ${linkStep === 2 ? 'text-cyan-300' : linkStep > 2 ? 'text-emerald-400' : 'text-gray-500'}`}>
                Analyze
              </p>
              <p className="text-[10px] text-gray-500 truncate">Find hidden connections</p>
            </div>
            {linkStep === 2 && (
              <button
                onClick={runLinkAnalysis}
                disabled={isAnalyzing}
                className="ml-auto px-3 py-1.5 rounded-lg text-xs font-semibold bg-cyan-500 text-white hover:bg-cyan-400 disabled:opacity-50 transition-all shadow-[0_0_15px_rgba(6,182,212,0.3)] animate-pulse-glow shrink-0"
              >
                {isAnalyzing ? (
                  <span className="flex items-center gap-1.5">
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    Analyzing…
                  </span>
                ) : (
                  <span className="flex items-center gap-1.5">
                    <Sparkles className="w-3.5 h-3.5" />
                    Find Connections
                  </span>
                )}
              </button>
            )}
          </div>

          <ArrowRight className="w-4 h-4 text-gray-600 mx-2 shrink-0" />

          {/* Step 3 */}
          <div className={`flex items-center gap-2 flex-1 ${linkStep >= 3 ? 'opacity-100' : 'opacity-40'}`}>
            <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 transition-all ${
              linkStep === 3 ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40' : 'bg-[var(--aegis-surface-2)] text-gray-500 border border-[var(--aegis-border)]'
            }`}>
              {linkStep === 3 ? '✓' : '3'}
            </div>
            <div className="min-w-0">
              <p className={`text-xs font-medium ${linkStep === 3 ? 'text-emerald-400' : 'text-gray-500'}`}>
                Investigate
              </p>
              <p className="text-[10px] text-gray-500 truncate">
                {linkStep === 3 ? 'Hover paths to highlight · AI explain' : 'Review & explain with AI'}
              </p>
            </div>
          </div>

          {/* Clear / Exit */}
          <button
            onClick={closeLinkAnalysis}
            className="ml-3 w-7 h-7 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-500 hover:text-red-400 hover:border-red-500/50 transition-colors shrink-0"
            title="Exit link analysis"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      <div className="flex-1 flex gap-4 min-h-0">
        {/* Graph Container */}
        <div className={`${showLinkPanel || isCaseId ? 'w-1/2' : 'flex-1'} aegis-card relative overflow-hidden`}>
          <div ref={containerRef} className="w-full h-full min-h-[500px]" />

          {/* Select Mode Overlay — Active step indicator */}
          {selectMode && linkStep === 1 && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 flex items-center gap-2.5 px-5 py-2.5 rounded-xl bg-cyan-500/10 border border-cyan-500/30 backdrop-blur-sm z-10 shadow-[0_0_20px_rgba(6,182,212,0.15)]">
              <Crosshair className="w-4 h-4 text-cyan-400 animate-pulse" />
              <span className="text-sm text-cyan-300 font-medium">
                Click on entities to select them
              </span>
              {multiSelected.size > 0 && (
                <span className="ml-1 px-2 py-0.5 rounded-full bg-cyan-500/20 text-[11px] text-cyan-300 font-bold">
                  {multiSelected.size}
                </span>
              )}
              {multiSelected.size === 1 && (
                <span className="text-[11px] text-gray-400 ml-1">
                  · select 1 more
                </span>
              )}
            </div>
          )}

          {/* Selected Nodes Chips */}
          {selectMode && multiSelected.size > 0 && (
            <div className="absolute bottom-16 left-4 right-4 flex flex-wrap gap-1.5 z-10">
              {[...multiSelected].map(id => {
                const node = cyRef.current?.getElementById(id);
                const label = node?.data('label') || id;
                const color = node?.data('color') || '#64748b';
                return (
                  <span
                    key={id}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] text-gray-200 bg-[var(--aegis-surface)]/95 border border-cyan-500/30 backdrop-blur-sm shadow-sm"
                  >
                    <span className="w-2.5 h-2.5 rounded-full ring-2 ring-cyan-500/30" style={{ backgroundColor: color }} />
                    {label}
                    <button
                      onClick={(e) => { e.stopPropagation(); toggleMultiSelect(id); }}
                      className="ml-0.5 text-gray-500 hover:text-red-400 transition-colors"
                    >
                      ×
                    </button>
                  </span>
                );
              })}
            </div>
          )}

          {/* Controls */}
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

            {/* Show/Hide Events Toggle */}
            <div className="mt-1 pt-1 border-t border-[var(--aegis-border)]" />
            <button
              onClick={() => setShowEvents(prev => !prev)}
              title={showEvents ? 'Hide Events' : 'Show Events'}
              className={`w-8 h-8 rounded-lg border flex items-center justify-center transition-all ${
                showEvents
                  ? 'bg-amber-500/20 border-amber-500/40 text-amber-400'
                  : 'bg-[var(--aegis-surface-2)] border-[var(--aegis-border)] text-gray-500 hover:text-amber-400 hover:border-amber-500/40'
              }`}
            >
              {showEvents ? <Eye className="w-4 h-4" /> : <EyeOff className="w-4 h-4" />}
            </button>
          </div>

          {/* Legend */}
          <div className="absolute bottom-4 left-4 aegis-card p-3">
            <p className="text-xs text-gray-500 mb-2 font-medium">Legend</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1">
              {[
                { label: 'Risk Case', color: '#ef4444' },
                { label: 'Facility', color: '#3b82f6' },
                { label: 'Event', color: '#f59e0b' },
                { label: 'Person', color: '#10b981' },
                { label: 'Asset', color: '#8b5cf6' },
                { label: 'Organization', color: '#06b6d4' },
                { label: 'Document', color: '#22d3ee' },
              ].map(({ label, color }) => (
                <div key={label} className="flex items-center gap-1.5">
                  <div
                    className="w-2.5 h-2.5 rounded-full"
                    style={{ backgroundColor: color }}
                  />
                  <span className="text-[10px] text-gray-400">{label}</span>
                </div>
              ))}
              {/* Link analysis legend items */}
              {linkResult && (
                <>
                  <div className="col-span-2 mt-1 pt-1 border-t border-[var(--aegis-border)]" />
                  <div className="flex items-center gap-1.5">
                    <div className="w-4 h-0.5 bg-emerald-400 rounded" />
                    <span className="text-[10px] text-gray-400">Direct</span>
                  </div>
                  <div className="flex items-center gap-1.5">
                    <div className="w-4 h-0.5 bg-red-400 rounded border-dashed" style={{ borderTop: '2px dashed #ef4444', height: 0 }} />
                    <span className="text-[10px] text-gray-400">Hidden</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* Loading state — waiting for auto-redirect */}
          {!graphData && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="text-center">
                <Loader2 className="w-8 h-8 text-cyan-500/50 mx-auto animate-spin" />
                <p className="text-gray-500 text-sm mt-3">Loading graph...</p>
              </div>
            </div>
          )}

          {/* Link Analysis CTA — floating, visible when graph is loaded but not in select mode */}
          {graphData && !selectMode && !isCaseId && !selectedNode && (
            <div className="absolute bottom-4 right-4 z-10 animate-slide-in">
              <button
                onClick={() => {
                  setSelectMode(true);
                  setSelectedNode(null);
                  setLinkResult(null);
                }}
                className="group flex items-center gap-2 px-4 py-2.5 rounded-xl bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border border-cyan-500/25 text-cyan-400 text-xs font-medium hover:from-cyan-500/20 hover:to-blue-500/20 hover:border-cyan-400/50 hover:shadow-[0_0_20px_rgba(6,182,212,0.2)] transition-all"
              >
                <Network className="w-4 h-4 group-hover:animate-pulse" />
                <span>
                  <span className="font-semibold">Link Analysis</span>
                  <span className="text-gray-500 ml-1.5">— find hidden connections</span>
                </span>
              </button>
            </div>
          )}
        </div>

        {/* Detail Panel (single node) */}
        {selectedNode && !selectMode && !showLinkPanel && (
          <div className="w-80 aegis-card p-4 overflow-auto animate-slide-in">
            <div className="flex items-center gap-3 mb-4 pb-3 border-b border-[var(--aegis-border)]">
              <div
                className="w-10 h-10 rounded-lg flex items-center justify-center"
                style={{ backgroundColor: getNodeColor(selectedNode.type) + '20' }}
              >
                <div
                  className="w-4 h-4 rounded-full"
                  style={{ backgroundColor: getNodeColor(selectedNode.type) }}
                />
              </div>
              <div>
                <p className="text-sm font-medium text-gray-200">
                  {selectedNode.label}
                </p>
                <p className="text-xs text-gray-500">{selectedNode.type}</p>
              </div>
            </div>

            <div className="space-y-2">
              {Object.entries(selectedNode.properties)
                .filter(
                  ([key]) =>
                    !['id', 'label', 'type', 'color', 'shape'].includes(key)
                )
                .map(([key, value]) => (
                  <div key={key}>
                    <p className="text-[10px] text-gray-500 uppercase tracking-wider">
                      {key.replace(/([A-Z])/g, ' $1')}
                    </p>
                    <p className="text-xs text-gray-300 mt-0.5">
                      {String(value)}
                    </p>
                  </div>
                ))}
            </div>

            <button
              onClick={() => {
                setExploreId(selectedNode.id);
                navigate(`/graph/${selectedNode.id}`);
              }}
              className="w-full mt-4 px-3 py-2 rounded-lg bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 text-xs hover:bg-cyan-500/20 transition-colors"
            >
              Investigate this entity →
            </button>
          </div>
        )}

        {/* Link Analysis Panel */}
        {showLinkPanel && (
          <div className="w-1/2 aegis-card overflow-hidden flex flex-col">
            <LinkAnalysisPanel
              result={linkResult}
              selectedNodes={[...multiSelected]}
              onHighlightPath={setHighlightedPath}
              onClose={closeLinkAnalysis}
            />
          </div>
        )}

        {/* AI Investigation Panel – only for risk cases */}
        {isCaseId && exploreId && (
          <div className="w-1/2 aegis-card overflow-hidden flex flex-col">
            <RiskInvestigation
              caseId={exploreId}
              caseTitle={currentCase?.title ?? exploreId}
            />
          </div>
        )}
      </div>
    </div>
  );
}
