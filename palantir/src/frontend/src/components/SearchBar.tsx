import { useState, useRef, useCallback } from 'react';
import { useSearch } from '../hooks/useApi';
import { Search, X, ExternalLink, Brain, Sparkles, Loader2, Zap, Eye, Maximize2,
         FileVideo, FileText, FlaskConical, User, Monitor, Mail, ClipboardCheck, Camera, KeyRound, Database, AlertTriangle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { aiApi, type AgentStep } from '../services/api';
import MarkdownModal from './MarkdownModal';
import type { SearchHit } from '../types';

interface Props {
  onClose: () => void;
}

// ── Markdown components (dark theme) ──
const mdComponents = {
  h1: ({ children, ...p }: any) => <h1 {...p} className="text-lg font-bold text-gray-100 mt-4 mb-2 pb-1 border-b border-[var(--aegis-border)]">{children}</h1>,
  h2: ({ children, ...p }: any) => <h2 {...p} className="text-base font-bold text-gray-200 mt-3 mb-1.5">{children}</h2>,
  h3: ({ children, ...p }: any) => <h3 {...p} className="text-sm font-semibold text-gray-300 mt-2 mb-1">{children}</h3>,
  p:  ({ children, ...p }: any) => <p {...p} className="text-sm text-gray-300 mb-2 leading-relaxed">{children}</p>,
  ul: ({ children, ...p }: any) => <ul {...p} className="list-disc list-inside text-sm text-gray-300 mb-2 space-y-0.5 ml-1">{children}</ul>,
  ol: ({ children, ...p }: any) => <ol {...p} className="list-decimal list-inside text-sm text-gray-300 mb-2 space-y-0.5 ml-1">{children}</ol>,
  li: ({ children, ...p }: any) => <li {...p} className="text-sm text-gray-300 leading-relaxed">{children}</li>,
  strong: ({ children, ...p }: any) => <strong {...p} className="font-semibold text-gray-100">{children}</strong>,
  em: ({ children, ...p }: any) => <em {...p} className="italic text-gray-400">{children}</em>,
  code: ({ children, className, ...p }: any) => {
    const isBlock = className?.includes('language-');
    return isBlock
      ? <code {...p} className={`${className} text-xs`}>{children}</code>
      : <code {...p} className="px-1 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-xs font-mono">{children}</code>;
  },
  pre: ({ children, ...p }: any) => <pre {...p} className="p-2 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] overflow-x-auto mb-2 text-xs">{children}</pre>,
  table: ({ children, ...p }: any) => <div className="overflow-x-auto mb-2"><table {...p} className="w-full text-sm">{children}</table></div>,
  thead: ({ children, ...p }: any) => <thead {...p} className="border-b border-[var(--aegis-border)]">{children}</thead>,
  th: ({ children, ...p }: any) => <th {...p} className="text-left px-2 py-1.5 text-xs text-gray-400 uppercase tracking-wider font-medium">{children}</th>,
  td: ({ children, ...p }: any) => <td {...p} className="px-2 py-1.5 text-sm text-gray-300 border-b border-[var(--aegis-border)]/50">{children}</td>,
  blockquote: ({ children, ...p }: any) => <blockquote {...p} className="border-l-2 border-cyan-500/40 pl-3 py-0.5 my-2 text-gray-400 italic">{children}</blockquote>,
  hr: () => <hr className="border-[var(--aegis-border)] my-3" />,
  a: ({ href, children, ...p }: any) => <a {...p} href={href} className="text-cyan-400 hover:text-cyan-300 underline" target="_blank" rel="noopener">{children}</a>,
};

interface DisplayStep {
  id: number;
  type: AgentStep['type'];
  content: string;
}

export default function SearchBar({ onClose }: Props) {
  const [query, setQuery] = useState('');
  const { data: results, isLoading } = useSearch(query);
  const navigate = useNavigate();

  // Agentic search state
  const [agentSteps, setAgentSteps] = useState<DisplayStep[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [agentDone, setAgentDone] = useState(false);
  const [agentError, setAgentError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stepIdRef = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);

  const addStep = useCallback((step: AgentStep) => {
    setAgentSteps(prev => [...prev, { id: stepIdRef.current++, ...step }]);
    setTimeout(() => scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' }), 50);
  }, []);

  const startAgenticSearch = useCallback(() => {
    if (!query.trim() || isStreaming) return;
    setAgentSteps([]);
    setAgentDone(false);
    setAgentError(null);
    setIsStreaming(true);
    stepIdRef.current = 0;

    abortRef.current = aiApi.agenticSearchStream(
      query.trim(),
      addStep,
      () => { setIsStreaming(false); setAgentDone(true); },
      (err) => { setAgentError(err); setIsStreaming(false); },
    );
  }, [query, isStreaming, addStep]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      startAgenticSearch();
    }
    if (e.key === 'Escape') onClose();
  };

  const handleSelect = (id: string) => {
    navigate(`/graph/${id}`);
    onClose();
  };

  const cancelSearch = () => {
    abortRef.current?.abort();
    setIsStreaming(false);
  };

  // Final answer from agent
  const answerStep = agentSteps.find(s => s.type === 'answer');
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const thinkingSteps = agentSteps.filter(s => s.type !== 'answer');

  return (
    <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-md flex items-start justify-center pt-16" onClick={onClose}>
      <div className="w-full max-w-3xl p-4 animate-slide-in max-h-[80vh] flex flex-col rounded-xl border border-[var(--aegis-border)] shadow-2xl shadow-black/50" style={{ background: '#0d1320' }} onClick={e => e.stopPropagation()}>

        {/* ── Search input ── */}
        <div className="flex items-center gap-3 pb-3 border-b border-[var(--aegis-border)]">
          <Search className="w-5 h-5 text-cyan-400" />
          <input
            type="text"
            value={query}
            onChange={(e) => { setQuery(e.target.value); setAgentDone(false); setAgentSteps([]); setAgentError(null); }}
            onKeyDown={handleKeyDown}
            placeholder="Agentic search — describe what you need to investigate..."
            className="flex-1 bg-transparent text-lg outline-none text-gray-100 placeholder-gray-500"
            autoFocus
          />
          {isStreaming ? (
            <button onClick={cancelSearch} className="text-red-400 hover:text-red-300 text-xs border border-red-500/30 px-2 py-1 rounded">
              Cancel
            </button>
          ) : query.trim().length >= 2 ? (
            <button
              onClick={startAgenticSearch}
              className="flex items-center gap-1.5 text-cyan-400 hover:text-cyan-300 text-xs border border-cyan-500/30 px-2 py-1 rounded hover:bg-cyan-500/10 transition-colors"
            >
              <Sparkles className="w-3.5 h-3.5" />
              Analyze
            </button>
          ) : null}
          <button onClick={onClose} className="text-gray-500 hover:text-gray-300 ml-1">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* ── Content area ── */}
        <div ref={scrollRef} className="mt-3 overflow-auto flex-1 min-h-0">

          {/* Agent thinking steps */}
          {thinkingSteps.length > 0 && (
            <div className="mb-3 space-y-1.5">
              {thinkingSteps.map(step => (
                <div key={step.id} className={`flex items-start gap-2 text-xs px-2 py-1.5 rounded ${
                  step.type === 'thought' ? 'bg-violet-500/5 text-violet-300' :
                  step.type === 'action' ? 'bg-amber-500/5 text-amber-300' :
                  'bg-cyan-500/5 text-cyan-300'
                }`}>
                  {step.type === 'thought' ? <Brain className="w-3.5 h-3.5 mt-0.5 shrink-0" /> :
                   step.type === 'action' ? <Zap className="w-3.5 h-3.5 mt-0.5 shrink-0" /> :
                   <Eye className="w-3.5 h-3.5 mt-0.5 shrink-0" />}
                  <span className="line-clamp-2">{step.content}</span>
                </div>
              ))}
              {isStreaming && (
                <div className="flex items-center gap-2 text-xs text-gray-500 px-2 py-1">
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                  Agent analyzing ({thinkingSteps.length} steps)...
                </div>
              )}
            </div>
          )}

          {/* Agent answer — rich markdown */}
          {answerStep && (
            <div className="mb-4 p-4 rounded-lg bg-[var(--aegis-surface-2)] border border-emerald-500/20">
              <div className="flex items-center gap-2 mb-3 text-emerald-400 text-sm font-medium">
                <Sparkles className="w-4 h-4" />
                Agentic Analysis
                <button
                  onClick={() => setPreviewContent(answerStep.content)}
                  className="ml-auto flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-emerald-400 hover:bg-emerald-500/15 border border-emerald-500/20 hover:border-emerald-500/40 transition-all"
                  title="Open full report view"
                >
                  <Maximize2 className="w-3 h-3" />
                  Preview
                </button>
              </div>
              <div className="prose prose-invert max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {answerStep.content}
                </ReactMarkdown>
              </div>
            </div>
          )}

          {/* Error */}
          {agentError && (
            <div className="mb-3 p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 text-sm">
              {agentError}
            </div>
          )}

          {/* OpenSearch results (events + intel documents) */}
          {isLoading && !isStreaming && agentSteps.length === 0 && (
            <div className="text-center py-6 text-gray-500 text-sm">Searching...</div>
          )}

          {query.length >= 2 && results?.hits && results.hits.length > 0 && (
            <div className={answerStep ? 'border-t border-[var(--aegis-border)] pt-3 mt-2' : ''}>
              {answerStep && (
                <p className="text-xs text-gray-500 mb-2 uppercase tracking-wider">Search Results ({results.totalCount})</p>
              )}

              {/* Group results by source type */}
              {(() => {
                const eventHits = results.hits.filter(h => h.sourceType !== 'document');
                const docHits = results.hits.filter(h => h.sourceType === 'document');
                return (
                  <>
                    {docHits.length > 0 && (
                      <div className="mb-3">
                        <p className="text-[10px] uppercase tracking-widest text-cyan-500/60 mb-1.5 px-1">
                          📚 Intel Documents ({docHits.length})
                        </p>
                        {docHits.slice(0, 10).map((hit) => (
                          <DocHitRow key={hit.id} hit={hit} onSelect={handleSelect} />
                        ))}
                      </div>
                    )}
                    {eventHits.length > 0 && (
                      <div>
                        <p className="text-[10px] uppercase tracking-widest text-amber-500/60 mb-1.5 px-1">
                          ⚡ Events ({eventHits.length})
                        </p>
                        {eventHits.slice(0, 10).map((hit) => (
                          <button
                            key={hit.id}
                            onClick={() => handleSelect(hit.id)}
                            className="w-full flex items-center gap-3 p-2.5 rounded-lg hover:bg-white/5 transition-colors text-left group"
                          >
                            <div className={`w-2 h-2 rounded-full shrink-0 ${
                              hit.type === 'PhysicalAnomaly' ? 'bg-red-400' :
                              hit.type === 'CyberAlert' ? 'bg-purple-400' :
                              hit.type === 'UnauthorizedAccess' ? 'bg-orange-400' : 'bg-blue-400'
                            }`} />
                            <div className="flex-1 min-w-0">
                              <p className="text-sm text-gray-200 truncate">{hit.description}</p>
                              <div className="flex items-center gap-2 mt-0.5">
                                <span className="text-xs text-gray-500">{hit.type} · {hit.id}</span>
                                {hit.facilityName && <span className="text-[10px] text-gray-600">📍 {hit.facilityName}</span>}
                              </div>
                            </div>
                            <ExternalLink className="w-3.5 h-3.5 text-gray-600 group-hover:text-cyan-400 transition-colors shrink-0" />
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                );
              })()}
            </div>
          )}

          {results?.hits.length === 0 && query.length >= 2 && !isStreaming && agentSteps.length === 0 && (
            <div className="text-center py-6 text-gray-500 text-sm">
              No results for "{query}"
            </div>
          )}

          {query.length < 2 && agentSteps.length === 0 && (
            <div className="text-center py-8 text-gray-600 text-sm">
              <Sparkles className="w-5 h-5 mx-auto mb-2 text-cyan-500/40" />
              Describe what you want to investigate and press <kbd className="px-1.5 py-0.5 rounded bg-[var(--aegis-surface-2)] text-gray-400 text-xs border border-[var(--aegis-border)]">Enter</kbd> for agentic analysis
            </div>
          )}
        </div>
      </div>

      {/* Markdown Preview Modal */}
      {previewContent && (
        <MarkdownModal
          content={previewContent}
          title="Agentic Search Report"
          onClose={() => setPreviewContent(null)}
        />
      )}
    </div>
  );
}

// ── Document type icon + color mapping ──
const DOC_TYPE_CONFIG: Record<string, { icon: typeof FileText; color: string; label: string; bg: string }> = {
  video_transcription:   { icon: FileVideo,      color: 'text-pink-400',    bg: 'bg-pink-500/10',    label: 'Video' },
  maintenance_report:    { icon: FileText,        color: 'text-blue-400',    bg: 'bg-blue-500/10',    label: 'Maintenance' },
  lab_analysis:          { icon: FlaskConical,    color: 'text-green-400',   bg: 'bg-green-500/10',   label: 'Lab Analysis' },
  worker_profile:        { icon: User,            color: 'text-amber-400',   bg: 'bg-amber-500/10',   label: 'Profile' },
  scada_log:             { icon: Monitor,         color: 'text-purple-400',  bg: 'bg-purple-500/10',  label: 'SCADA Log' },
  email:                 { icon: Mail,            color: 'text-sky-400',     bg: 'bg-sky-500/10',     label: 'Email' },
  regulatory_inspection: { icon: ClipboardCheck,  color: 'text-orange-400',  bg: 'bg-orange-500/10',  label: 'Inspection' },
  incident_photo:        { icon: Camera,          color: 'text-rose-400',    bg: 'bg-rose-500/10',    label: 'Photo' },
  access_badge_record:   { icon: KeyRound,        color: 'text-teal-400',    bg: 'bg-teal-500/10',    label: 'Badge' },
  database_extract:      { icon: Database,        color: 'text-indigo-400',  bg: 'bg-indigo-500/10',  label: 'DB Extract' },
};

const CLASSIFICATION_COLORS: Record<string, string> = {
  RESTRICTED:   'bg-red-500/20 text-red-400 border-red-500/30',
  CONFIDENTIAL: 'bg-amber-500/20 text-amber-400 border-amber-500/30',
  INTERNAL:     'bg-gray-500/20 text-gray-400 border-gray-500/30',
};

function DocHitRow({ hit, onSelect }: { hit: SearchHit; onSelect: (id: string) => void }) {
  const cfg = DOC_TYPE_CONFIG[hit.docType ?? hit.type] ?? { icon: FileText, color: 'text-gray-400', bg: 'bg-gray-500/10', label: hit.type };
  const Icon = cfg.icon;
  const classColor = CLASSIFICATION_COLORS[hit.classification ?? ''] ?? CLASSIFICATION_COLORS.INTERNAL;

  return (
    <button onClick={() => onSelect(hit.id)} className="w-full flex items-start gap-3 p-2.5 rounded-lg hover:bg-white/5 transition-colors text-left group">
      <div className={`w-8 h-8 rounded-lg ${cfg.bg} flex items-center justify-center shrink-0 mt-0.5`}>
        <Icon className={`w-4 h-4 ${cfg.color}`} />
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-200 truncate">{hit.description}</p>
        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${cfg.bg} ${cfg.color} font-medium`}>
            {cfg.label}
          </span>
          {hit.classification && (
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border ${classColor} font-medium`}>
              {hit.classification}
            </span>
          )}
          {hit.facilityName && (
            <span className="text-[10px] text-gray-500">📍 {hit.facilityName}</span>
          )}
          {hit.personName && (
            <span className="text-[10px] text-gray-500">👤 {hit.personName}</span>
          )}
          {hit.sourceFile && (
            <span className="text-[10px] text-gray-600 font-mono truncate max-w-[180px]" title={hit.sourceFile}>
              📎 {hit.sourceFile}
            </span>
          )}
        </div>
      </div>
      <div className="flex flex-col items-end gap-1 shrink-0">
        <span className="text-[10px] text-gray-600">{hit.score.toFixed(1)}</span>
        {hit.id && <span className="text-[10px] text-gray-600 font-mono">{hit.id}</span>}
      </div>
    </button>
  );
}
