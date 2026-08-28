import { useState, useEffect, useRef, useCallback } from 'react';
import { useParams, useSearchParams, useNavigate } from 'react-router-dom';
import {
  Bot, Send, Sparkles, Loader2, Brain, Eye, Zap,
  ChevronDown, ChevronRight, Database, Search,
  ArrowLeft, Clock, RotateCcw, Building2, User, Activity, Maximize2,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { aiApi, type AgentStep } from '../services/api';
import MarkdownModal from './MarkdownModal';

/* ═══════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════ */

interface DisplayStep {
  id: number;
  type: AgentStep['type'] | 'user';
  content: string;
  collapsed?: boolean;
}

/* ═══════════════════════════════════════════════════════════════
   Markdown renderer components (dark theme)
   ═══════════════════════════════════════════════════════════════ */

const mdComponents = {
  h1: ({ children, ...p }: any) => <h1 {...p} className="text-xl font-bold text-gray-100 mt-5 mb-3 pb-2 border-b border-[var(--aegis-border)]">{children}</h1>,
  h2: ({ children, ...p }: any) => <h2 {...p} className="text-lg font-bold text-gray-200 mt-4 mb-2">{children}</h2>,
  h3: ({ children, ...p }: any) => <h3 {...p} className="text-base font-semibold text-gray-300 mt-3 mb-1.5">{children}</h3>,
  p: ({ children, ...p }: any) => <p {...p} className="text-sm text-gray-300 mb-2.5 leading-relaxed">{children}</p>,
  ul: ({ children, ...p }: any) => <ul {...p} className="list-disc list-inside text-sm text-gray-300 mb-2.5 space-y-1 ml-1">{children}</ul>,
  ol: ({ children, ...p }: any) => <ol {...p} className="list-decimal list-inside text-sm text-gray-300 mb-2.5 space-y-1 ml-1">{children}</ol>,
  li: ({ children, ...p }: any) => <li {...p} className="text-sm text-gray-300 leading-relaxed">{children}</li>,
  strong: ({ children, ...p }: any) => <strong {...p} className="font-semibold text-gray-100">{children}</strong>,
  em: ({ children, ...p }: any) => <em {...p} className="italic text-gray-400">{children}</em>,
  code: ({ children, className, ...p }: any) => {
    const isBlock = className?.includes('language-');
    return isBlock
      ? <code {...p} className={`${className} text-xs`}>{children}</code>
      : <code {...p} className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 text-xs font-mono">{children}</code>;
  },
  pre: ({ children, ...p }: any) => <pre {...p} className="p-3 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] overflow-x-auto mb-3 text-xs">{children}</pre>,
  table: ({ children, ...p }: any) => <div className="overflow-x-auto mb-3"><table {...p} className="w-full text-sm">{children}</table></div>,
  thead: ({ children, ...p }: any) => <thead {...p} className="border-b border-[var(--aegis-border)]">{children}</thead>,
  th: ({ children, ...p }: any) => <th {...p} className="text-left px-3 py-2 text-xs text-gray-400 uppercase tracking-wider font-medium">{children}</th>,
  td: ({ children, ...p }: any) => <td {...p} className="px-3 py-2 text-sm text-gray-300 border-b border-[var(--aegis-border)]/50">{children}</td>,
  blockquote: ({ children, ...p }: any) => <blockquote {...p} className="border-l-2 border-cyan-500/40 pl-4 py-1 my-3 text-gray-400 italic">{children}</blockquote>,
  hr: () => <hr className="border-[var(--aegis-border)] my-4" />,
  a: ({ href, children, ...p }: any) => <a {...p} href={href} className="text-cyan-400 hover:text-cyan-300 underline" target="_blank" rel="noopener">{children}</a>,
};

/* ═══════════════════════════════════════════════════════════════
   Step rendering helpers
   ═══════════════════════════════════════════════════════════════ */

function StepIcon({ type }: { type: DisplayStep['type'] }) {
  switch (type) {
    case 'thought': return <Brain className="w-4 h-4 text-violet-400" />;
    case 'action': return <Zap className="w-4 h-4 text-amber-400" />;
    case 'observation': return <Eye className="w-4 h-4 text-cyan-400" />;
    case 'answer': return <Sparkles className="w-4 h-4 text-emerald-400" />;
    case 'user': return <Search className="w-4 h-4 text-blue-400" />;
    default: return <Database className="w-4 h-4 text-gray-400" />;
  }
}

function stepLabel(type: DisplayStep['type']): string {
  switch (type) {
    case 'thought': return 'Reasoning';
    case 'action': return 'Action';
    case 'observation': return 'Observation';
    case 'answer': return 'Answer';
    case 'user': return 'Question';
    default: return type;
  }
}

function stepStyles(type: DisplayStep['type']): string {
  switch (type) {
    case 'thought': return 'border-l-violet-500/40 bg-violet-500/5';
    case 'action': return 'border-l-amber-500/40 bg-amber-500/5';
    case 'observation': return 'border-l-cyan-500/40 bg-cyan-500/5';
    case 'answer': return 'border-l-emerald-500/40 bg-emerald-500/5';
    case 'user': return 'border-l-blue-500/40 bg-blue-500/5';
    default: return 'border-l-gray-500/40 bg-gray-500/5';
  }
}

const ENTITY_ICONS: Record<string, typeof Building2> = {
  facility: Building2,
  person: User,
  event: Activity,
};

const TIME_LABELS: Record<string, string> = {
  '24h': 'Last 24h',
  '48h': 'Last 48h',
  '7d': 'Last 7 days',
  '30d': 'Last 30 days',
};

/* ═══════════════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════════════ */

export default function EntityInvestigation() {
  const { entityType, entityId } = useParams<{
    entityType: string;
    entityId: string;
  }>();
  const [searchParams] = useSearchParams();
  const timeRange = searchParams.get('timeRange') ?? '24h';
  const navigate = useNavigate();

  const [steps, setSteps] = useState<DisplayStep[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [investigationDone, setInvestigationDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [iterationCount, setIterationCount] = useState(0);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stepIdRef = useRef(0);

  const scroll = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scroll(); }, [steps, scroll]);

  useEffect(() => {
    startInvestigation();
    return () => { abortRef.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entityType, entityId]);

  const nextId = () => ++stepIdRef.current;

  const addStep = (step: AgentStep) => {
    if (step.type === 'thought') {
      setIterationCount((c) => c + 1);
    }
    setSteps((prev) => [
      ...prev,
      { id: nextId(), type: step.type, content: step.content, collapsed: false },
    ]);
  };

  const startInvestigation = () => {
    if (!entityType || !entityId) return;
    setIsStreaming(true);
    setError(null);
    setSteps([]);
    setIterationCount(0);
    setInvestigationDone(false);

    abortRef.current = aiApi.investigateEntityStream(
      entityType,
      entityId,
      timeRange,
      addStep,
      () => { setIsStreaming(false); setInvestigationDone(true); },
      (err) => { setError(err); setIsStreaming(false); },
    );
  };

  const sendMessage = (text: string) => {
    if (!text.trim() || isStreaming || !entityType || !entityId) return;

    setSteps((prev) => [...prev, { id: nextId(), type: 'user', content: text.trim() }]);
    setInput('');
    setIsStreaming(true);
    setError(null);
    setIterationCount(0);

    const history = steps
      .filter((s) => s.type === 'answer' || s.type === 'user')
      .map((s) => `${s.type === 'user' ? 'User' : 'Assistant'}: ${s.content}`)
      .join('\n\n');

    abortRef.current = aiApi.chatEntityStream(
      entityType,
      entityId,
      timeRange,
      text.trim(),
      history,
      addStep,
      () => setIsStreaming(false),
      (err) => { setError(err); setIsStreaming(false); },
    );
  };

  const toggleCollapse = (id: number) => {
    setSteps((prev) =>
      prev.map((s) => (s.id === id ? { ...s, collapsed: !s.collapsed } : s)),
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  const EntityIcon = ENTITY_ICONS[entityType ?? 'event'] ?? Activity;

  return (
    <div className="h-full flex flex-col gap-4 animate-slide-in">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button
            onClick={() => navigate(-1)}
            className="w-8 h-8 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-400 hover:text-cyan-400 hover:border-cyan-500/50 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>
          <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 border border-purple-500/30 flex items-center justify-center">
            <EntityIcon className="w-5 h-5 text-purple-400" />
          </div>
          <div>
            <h2 className="text-xl font-bold text-gray-100">
              AI Investigation
            </h2>
            <p className="text-xs text-gray-500">
              <span className="font-mono">{entityId}</span>
              <span className="mx-2 text-gray-700">·</span>
              <span className="inline-flex items-center gap-1">
                <Clock className="w-3 h-3" />
                {TIME_LABELS[timeRange] ?? timeRange}
              </span>
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {!isStreaming && (
            <button
              onClick={startInvestigation}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-purple-500/10 border border-purple-500/30 text-purple-400 text-xs hover:bg-purple-500/20 transition-colors"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Re-investigate
            </button>
          )}
          <button
            onClick={() => navigate(`/graph/${entityId}`)}
            className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-400 text-xs hover:bg-blue-500/20 transition-colors"
          >
            View Graph →
          </button>
        </div>
      </div>

      {/* Main content */}
      <div className="flex-1 flex gap-4 min-h-0">
        <div className="flex-1 aegis-card flex flex-col overflow-hidden">
          {/* Steps stream */}
          <div className="flex-1 overflow-auto p-4 space-y-2">
            {steps.map((step) => (
              <div
                key={step.id}
                className={`rounded-lg border-l-2 ${stepStyles(step.type)} transition-all`}
              >
                <button
                  onClick={() =>
                    step.type !== 'answer' &&
                    step.type !== 'user' &&
                    toggleCollapse(step.id)
                  }
                  className="w-full flex items-center gap-2 px-3 py-2 text-left"
                >
                  <StepIcon type={step.type} />
                  <span className="text-[11px] font-semibold text-gray-400 uppercase tracking-wider">
                    {stepLabel(step.type)}
                  </span>
                  {step.type === 'answer' && (
                    <button
                      onClick={(e) => { e.stopPropagation(); setPreviewContent(step.content); }}
                      className="ml-auto flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-emerald-400 hover:bg-emerald-500/15 border border-emerald-500/20 hover:border-emerald-500/40 transition-all"
                      title="Open full report view"
                    >
                      <Maximize2 className="w-3 h-3" />
                      Preview
                    </button>
                  )}
                  {step.type !== 'answer' && step.type !== 'user' && (
                    step.collapsed
                      ? <ChevronRight className="w-3 h-3 text-gray-600 ml-auto" />
                      : <ChevronDown className="w-3 h-3 text-gray-600 ml-auto" />
                  )}
                </button>

                {!step.collapsed && (
                  <div className="px-3 pb-3">
                    {step.type === 'answer' ? (
                      <div className="text-sm leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                          {step.content}
                        </ReactMarkdown>
                      </div>
                    ) : (
                      <div
                        className={`text-sm leading-relaxed whitespace-pre-wrap break-words ${
                          step.type === 'user'
                            ? 'text-blue-300'
                            : step.type === 'observation'
                              ? 'text-cyan-300/80 font-mono text-xs'
                              : 'text-gray-400'
                        }`}
                      >
                        {step.content}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {isStreaming && (
              <div className="flex items-center gap-2 px-3 py-2 text-gray-500 text-xs">
                <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
                <span>Agent is reasoning… (step {iterationCount})</span>
              </div>
            )}

            {error && (
              <div className="text-center px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
                {error}
              </div>
            )}

            <div ref={endRef} />
          </div>

          {/* Chat input */}
          {investigationDone && (
            <div className="p-3 border-t border-[var(--aegis-border)]">
              <div className="flex items-end gap-2">
                <textarea
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Ask the agent about this entity…"
                  rows={1}
                  className="flex-1 resize-none rounded-xl bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-purple-500/50 transition-colors"
                  disabled={isStreaming}
                />
                <button
                  onClick={() => sendMessage(input)}
                  disabled={isStreaming || !input.trim()}
                  className="w-10 h-10 rounded-xl bg-purple-500/20 border border-purple-500/30 flex items-center justify-center text-purple-400 hover:bg-purple-500/30 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
              <p className="text-[9px] text-gray-700 mt-1.5 text-center">
                AEGIS AI Agent · ReAct · Ontology-driven · Ollama GPU
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Markdown Preview Modal */}
      {previewContent && (
        <MarkdownModal
          content={previewContent}
          title={`${entityType} ${entityId} — Investigation`}
          onClose={() => setPreviewContent(null)}
        />
      )}
    </div>
  );
}
