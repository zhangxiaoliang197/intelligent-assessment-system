import { useState, useRef, useCallback, useEffect } from 'react';
import {
  Link2, Eye, EyeOff, X, Sparkles, ChevronRight, ChevronDown,
  Loader2, Brain, Zap, AlertTriangle, ArrowRight, Network,
  TrendingUp, Shield, Maximize2,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { DiscoveredPath, LinkAnalysisResult } from '../types';
import { aiApi, type AgentStep } from '../services/api';
import MarkdownModal from './MarkdownModal';

/* ═══════════════════════════════════════════════════════════════
   Props
   ═══════════════════════════════════════════════════════════════ */

interface Props {
  result: LinkAnalysisResult;
  selectedNodes: string[];
  onHighlightPath: (path: DiscoveredPath | null) => void;
  onClose: () => void;
}

/* ═══════════════════════════════════════════════════════════════
   Helpers
   ═══════════════════════════════════════════════════════════════ */

function relevanceColor(r: number): string {
  if (r >= 0.5) return 'text-red-400';
  if (r >= 0.3) return 'text-orange-400';
  if (r >= 0.15) return 'text-yellow-400';
  return 'text-emerald-400';
}

function relevanceBg(r: number): string {
  if (r >= 0.5) return 'bg-red-500';
  if (r >= 0.3) return 'bg-orange-500';
  if (r >= 0.15) return 'bg-yellow-500';
  return 'bg-emerald-500';
}

function relevanceLabel(r: number): string {
  if (r >= 0.5) return 'Deep Hidden';
  if (r >= 0.3) return 'Hidden';
  if (r >= 0.15) return 'Indirect';
  return 'Direct';
}

function parseNodeLabel(seq: string): { type: string; name: string } {
  const colonIdx = seq.indexOf(':');
  if (colonIdx === -1) return { type: 'Unknown', name: seq };
  return { type: seq.slice(0, colonIdx), name: seq.slice(colonIdx + 1) };
}

const NODE_DOT_COLORS: Record<string, string> = {
  Person: 'bg-emerald-400',
  Employee: 'bg-emerald-400',
  Contractor: 'bg-amber-400',
  Facility: 'bg-blue-400',
  WaterTreatmentPlant: 'bg-blue-400',
  PumpStation: 'bg-blue-500',
  Event: 'bg-amber-400',
  RiskCase: 'bg-red-400',
  SuspectedSabotage: 'bg-red-400',
  Asset: 'bg-purple-400',
  Organization: 'bg-cyan-400',
  Sensor: 'bg-teal-400',
};

/* ── Markdown renderer (dark theme, compact) ── */

const mdComponents = {
  h1: ({ children, ...p }: any) => <h1 {...p} className="text-base font-bold text-gray-100 mt-3 mb-2 pb-1.5 border-b border-[var(--aegis-border)]">{children}</h1>,
  h2: ({ children, ...p }: any) => <h2 {...p} className="text-sm font-bold text-gray-200 mt-3 mb-1.5">{children}</h2>,
  h3: ({ children, ...p }: any) => <h3 {...p} className="text-sm font-semibold text-gray-300 mt-2 mb-1">{children}</h3>,
  h4: ({ children, ...p }: any) => <h4 {...p} className="text-xs font-semibold text-gray-300 mt-1.5 mb-0.5">{children}</h4>,
  p: ({ children, ...p }: any) => <p {...p} className="text-xs text-gray-300 mb-2 leading-relaxed">{children}</p>,
  ul: ({ children, ...p }: any) => <ul {...p} className="list-disc list-inside text-xs text-gray-300 mb-2 space-y-0.5 ml-1">{children}</ul>,
  ol: ({ children, ...p }: any) => <ol {...p} className="list-decimal list-inside text-xs text-gray-300 mb-2 space-y-0.5 ml-1">{children}</ol>,
  li: ({ children, ...p }: any) => <li {...p} className="text-xs text-gray-300 leading-relaxed">{children}</li>,
  strong: ({ children, ...p }: any) => <strong {...p} className="font-semibold text-gray-100">{children}</strong>,
  em: ({ children, ...p }: any) => <em {...p} className="italic text-gray-400">{children}</em>,
  code: ({ children, className, ...p }: any) => {
    const isBlock = className?.includes('language-');
    return isBlock
      ? <code {...p} className={`${className} text-[11px]`}>{children}</code>
      : <code {...p} className="px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-[11px] font-mono">{children}</code>;
  },
  pre: ({ children, ...p }: any) => <pre {...p} className="p-2.5 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] overflow-x-auto mb-2 text-[11px]">{children}</pre>,
  blockquote: ({ children, ...p }: any) => <blockquote {...p} className="border-l-2 border-cyan-500/40 pl-3 py-0.5 my-2 text-gray-400 italic text-xs">{children}</blockquote>,
  hr: () => <hr className="border-[var(--aegis-border)] my-3" />,
  a: ({ href, children, ...p }: any) => <a {...p} href={href} className="text-cyan-400 hover:text-cyan-300 underline" target="_blank" rel="noopener">{children}</a>,
};

/* ═══════════════════════════════════════════════════════════════
   AI Explain sub-component
   ═══════════════════════════════════════════════════════════════ */

function AiExplainSection({ paths, selectedNodes }: { paths: DiscoveredPath[]; selectedNodes: string[] }) {
  const [steps, setSteps] = useState<{ type: string; content: string }[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [started, setStarted] = useState(false);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: 'smooth' }); }, [steps]);

  const startExplain = useCallback(() => {
    setStarted(true);
    setIsStreaming(true);
    setSteps([]);

    const pathSummary = paths.map(p =>
      `${p.fromLabel} → ${p.nodeSequence.join(' → ')} → ${p.toLabel} (length=${p.length}, relevance=${p.relevance.toFixed(2)})`
    ).join('\n');

    const query = `Analyze these hidden connections between entities in a water infrastructure network. The following paths were discovered via link analysis:\n\n${pathSummary}\n\nWhat do these connections reveal? Are there potential security risks or suspicious patterns? Focus on indirect/hidden links.`;

    abortRef.current = aiApi.agenticSearchStream(
      query,
      (step: AgentStep) => setSteps(prev => [...prev, step]),
      () => setIsStreaming(false),
      () => setIsStreaming(false),
    );
  }, [paths]);

  useEffect(() => { return () => { abortRef.current?.abort(); }; }, []);

  if (!started) {
    return (
      <button
        onClick={startExplain}
        className="w-full mt-3 px-4 py-3 rounded-xl bg-gradient-to-r from-purple-500/10 to-pink-500/10 border border-purple-500/30 text-purple-300 text-sm font-medium hover:from-purple-500/20 hover:to-pink-500/20 hover:border-purple-400/50 transition-all flex items-center justify-center gap-2 group"
      >
        <Sparkles className="w-4 h-4 group-hover:animate-spin" />
        Explain with AI Agent
        <Brain className="w-4 h-4 opacity-50" />
      </button>
    );
  }

  return (
    <div className="mt-3 rounded-xl bg-[var(--aegis-surface-2)] border border-purple-500/20 overflow-hidden">
      <div className="px-3 py-2 border-b border-purple-500/20 flex items-center gap-2">
        <Brain className="w-4 h-4 text-purple-400" />
        <span className="text-xs font-medium text-purple-300">AI Analysis</span>
        {isStreaming && <Loader2 className="w-3 h-3 text-purple-400 animate-spin ml-auto" />}
      </div>
      <div className="p-3 max-h-80 overflow-auto space-y-2">
        {steps.map((step, i) => (
          <div key={i}>
            {step.type === 'answer' ? (
              <div className="text-xs leading-relaxed">
                <div className="flex items-center gap-1 mb-1">
                  <span className="text-emerald-400 font-medium">✨ </span>
                  <button
                    onClick={() => setPreviewContent(step.content)}
                    className="ml-auto flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium text-emerald-400 hover:bg-emerald-500/15 border border-emerald-500/20 hover:border-emerald-500/40 transition-all"
                    title="Open full report view"
                  >
                    <Maximize2 className="w-2.5 h-2.5" />
                    Preview
                  </button>
                </div>
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {step.content}
                </ReactMarkdown>
              </div>
            ) : (
              <div className="text-xs leading-relaxed text-gray-400 italic">
                {step.type === 'thought' && <span className="text-violet-400 font-medium">💭 </span>}
                {step.type === 'action' && <span className="text-amber-400 font-medium">⚡ </span>}
                {step.type === 'observation' && <span className="text-cyan-400 font-medium">👁 </span>}
                {step.content}
              </div>
            )}
          </div>
        ))}
        <div ref={endRef} />
      </div>

      {/* Markdown Preview Modal */}
      {previewContent && (
        <MarkdownModal
          content={previewContent}
          title="Link Analysis — AI Explanation"
          onClose={() => setPreviewContent(null)}
        />
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════ */

export default function LinkAnalysisPanel({ result, selectedNodes, onHighlightPath, onClose }: Props) {
  const [expandedPath, setExpandedPath] = useState<number | null>(null);
  const [highlightedIdx, setHighlightedIdx] = useState<number | null>(null);
  const [showHiddenOnly, setShowHiddenOnly] = useState(false);

  const sortedPaths = [...result.paths].sort((a, b) => b.relevance - a.relevance);
  const filteredPaths = showHiddenOnly ? sortedPaths.filter(p => p.length > 1) : sortedPaths;

  const directCount = result.paths.filter(p => p.length === 1).length;
  const hiddenCount = result.paths.filter(p => p.length > 1).length;

  const handlePathHover = (path: DiscoveredPath | null, idx: number | null) => {
    setHighlightedIdx(idx);
    onHighlightPath(path);
  };

  return (
    <div className="flex flex-col h-full animate-slide-in">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--aegis-border)]">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center">
          <Network className="w-5 h-5 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-200">Link Analysis</h3>
          <p className="text-[10px] text-gray-500">{selectedNodes.length} entities analyzed</p>
        </div>
        <button
          onClick={onClose}
          className="w-7 h-7 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-500 hover:text-gray-300 hover:border-gray-500/50 transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {/* Stats Bar */}
      <div className="px-4 py-3 border-b border-[var(--aegis-border)] bg-[var(--aegis-surface-2)]/50">
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center">
            <p className="text-lg font-bold text-cyan-400">{result.totalPathsFound}</p>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Paths</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-emerald-400">{directCount}</p>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Direct</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold text-red-400">{hiddenCount}</p>
            <p className="text-[10px] text-gray-500 uppercase tracking-wider">Hidden</p>
          </div>
        </div>
      </div>

      {/* Filter */}
      <div className="px-4 py-2 border-b border-[var(--aegis-border)] flex items-center justify-between">
        <span className="text-xs text-gray-500">
          {filteredPaths.length} {showHiddenOnly ? 'hidden links' : 'connections'}
        </span>
        <button
          onClick={() => setShowHiddenOnly(!showHiddenOnly)}
          className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all ${
            showHiddenOnly
              ? 'bg-red-500/20 border border-red-500/40 text-red-400'
              : 'bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] text-gray-400 hover:text-gray-300'
          }`}
        >
          {showHiddenOnly ? <EyeOff className="w-3 h-3" /> : <Eye className="w-3 h-3" />}
          {showHiddenOnly ? 'Hidden Only' : 'Show All'}
        </button>
      </div>

      {/* Paths List */}
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {filteredPaths.map((path, idx) => {
          const isExpanded = expandedPath === idx;
          const isHighlighted = highlightedIdx === idx;
          const isHidden = path.length > 1;

          return (
            <div
              key={`${path.fromId}-${path.toId}-${idx}`}
              className={`rounded-xl border transition-all duration-300 cursor-pointer ${
                isHighlighted
                  ? 'border-cyan-500/60 bg-cyan-500/10 shadow-[0_0_15px_rgba(6,182,212,0.2)]'
                  : isHidden
                    ? 'border-red-500/20 bg-red-500/5 hover:border-red-500/40'
                    : 'border-[var(--aegis-border)] bg-[var(--aegis-surface)] hover:border-[var(--aegis-border)]'
              }`}
              onMouseEnter={() => handlePathHover(path, idx)}
              onMouseLeave={() => handlePathHover(null, null)}
              onClick={() => setExpandedPath(isExpanded ? null : idx)}
            >
              {/* Path Header */}
              <div className="px-3 py-2.5 flex items-center gap-2">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className="text-gray-200 font-medium truncate">{path.fromLabel}</span>
                    <ArrowRight className="w-3 h-3 text-gray-600 flex-shrink-0" />
                    <span className="text-gray-200 font-medium truncate">{path.toLabel}</span>
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className={`text-[10px] font-medium ${relevanceColor(path.relevance)}`}>
                      {relevanceLabel(path.relevance)}
                    </span>
                    <span className="text-[10px] text-gray-600">•</span>
                    <span className="text-[10px] text-gray-500">
                      {path.length} hop{path.length !== 1 ? 's' : ''}
                    </span>
                    {isHidden && (
                      <>
                        <span className="text-[10px] text-gray-600">•</span>
                        <span className="text-[10px] text-red-400 flex items-center gap-0.5">
                          <AlertTriangle className="w-2.5 h-2.5" />
                          Hidden link
                        </span>
                      </>
                    )}
                  </div>
                </div>

                {/* Relevance Bar */}
                <div className="flex items-center gap-2 flex-shrink-0">
                  <div className="w-16 h-1.5 rounded-full bg-[var(--aegis-surface-2)] overflow-hidden">
                    <div
                      className={`h-full rounded-full ${relevanceBg(path.relevance)} transition-all duration-500`}
                      style={{ width: `${Math.max(path.relevance * 100, 8)}%` }}
                    />
                  </div>
                  {isExpanded ? (
                    <ChevronDown className="w-3.5 h-3.5 text-gray-500" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5 text-gray-500" />
                  )}
                </div>
              </div>

              {/* Expanded Path Detail */}
              {isExpanded && (
                <div className="px-3 pb-3 pt-1 border-t border-[var(--aegis-border)]">
                  {/* Node Chain Visualization */}
                  <div className="flex items-center gap-0 overflow-x-auto pb-2 mt-2">
                    {path.nodeSequence.map((seq, nodeIdx) => {
                      const { type, name } = parseNodeLabel(seq);
                      const dotColor = NODE_DOT_COLORS[type] || 'bg-gray-400';
                      return (
                        <div key={nodeIdx} className="flex items-center flex-shrink-0">
                          {nodeIdx > 0 && (
                            <div className="flex items-center mx-1">
                              <div className="w-6 h-px bg-gray-600" />
                              <div className="px-1 py-0.5 rounded bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)]">
                                <span className="text-[8px] text-gray-500 whitespace-nowrap">
                                  {path.relationshipSequence[nodeIdx - 1]?.replace(/_/g, ' ') || ''}
                                </span>
                              </div>
                              <div className="w-6 h-px bg-gray-600" />
                            </div>
                          )}
                          <div className="flex items-center gap-1 px-2 py-1 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)]">
                            <div className={`w-2 h-2 rounded-full ${dotColor}`} />
                            <span className="text-[10px] text-gray-300 whitespace-nowrap">{name}</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  {/* Metadata */}
                  <div className="flex items-center gap-3 mt-2 pt-2 border-t border-[var(--aegis-border)]/50">
                    <div className="flex items-center gap-1">
                      <TrendingUp className="w-3 h-3 text-gray-500" />
                      <span className="text-[10px] text-gray-500">
                        Relevance: {(path.relevance * 100).toFixed(0)}%
                      </span>
                    </div>
                    <div className="flex items-center gap-1">
                      <Link2 className="w-3 h-3 text-gray-500" />
                      <span className="text-[10px] text-gray-500">
                        {path.length} intermediate node{path.length > 2 ? 's' : path.length === 2 ? '' : 's'}
                      </span>
                    </div>
                    {isHidden && (
                      <div className="flex items-center gap-1">
                        <Shield className="w-3 h-3 text-red-400" />
                        <span className="text-[10px] text-red-400">Investigate</span>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {filteredPaths.length === 0 && (
          <div className="text-center py-8">
            <Link2 className="w-10 h-10 text-gray-700 mx-auto mb-2" />
            <p className="text-sm text-gray-500">
              {showHiddenOnly ? 'No hidden links found' : 'No paths found'}
            </p>
          </div>
        )}

        {/* AI Explain */}
        {result.paths.length > 0 && (
          <AiExplainSection paths={result.paths} selectedNodes={selectedNodes} />
        )}
      </div>

      {/* Footer Summary */}
      <div className="px-4 py-2.5 border-t border-[var(--aegis-border)] bg-[var(--aegis-surface-2)]/30">
        <p className="text-[10px] text-gray-500 leading-relaxed">{result.summary}</p>
      </div>
    </div>
  );
}
