import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Bot, Send, Sparkles, Shield, AlertTriangle, Wrench, Lightbulb,
  Loader2, Brain, Eye, Zap, ChevronDown, ChevronRight,
  Database, Search, Maximize2,
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

interface Props {
  caseId: string;
  caseTitle: string;
}

/* ═══════════════════════════════════════════════════════════════
   Suggested prompts
   ═══════════════════════════════════════════════════════════════ */

const SUGGESTED_PROMPTS = [
  { icon: Wrench, label: 'How to fix the problem?', color: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10' },
  { icon: AlertTriangle, label: 'What is the real impact?', color: 'text-orange-400 border-orange-500/30 bg-orange-500/10' },
  { icon: Shield, label: 'How to prevent recurrence?', color: 'text-blue-400 border-blue-500/30 bg-blue-500/10' },
  { icon: Lightbulb, label: 'Which teams should act?', color: 'text-yellow-400 border-yellow-500/30 bg-yellow-500/10' },
];

/* ═══════════════════════════════════════════════════════════════
   Markdown renderer components (dark theme)
   ═══════════════════════════════════════════════════════════════ */

const mdComponents = {
  h1: ({ children, ...p }: any) => <h1 {...p} className="text-xl font-bold text-gray-100 mt-5 mb-3 pb-2 border-b border-[var(--aegis-border)]">{children}</h1>,
  h2: ({ children, ...p }: any) => <h2 {...p} className="text-lg font-bold text-gray-200 mt-4 mb-2">{children}</h2>,
  h3: ({ children, ...p }: any) => <h3 {...p} className="text-base font-semibold text-gray-300 mt-3 mb-1.5">{children}</h3>,
  h4: ({ children, ...p }: any) => <h4 {...p} className="text-sm font-semibold text-gray-300 mt-2 mb-1">{children}</h4>,
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
    case 'thought':
      return <Brain className="w-4 h-4 text-violet-400" />;
    case 'action':
      return <Zap className="w-4 h-4 text-amber-400" />;
    case 'observation':
      return <Eye className="w-4 h-4 text-cyan-400" />;
    case 'answer':
      return <Sparkles className="w-4 h-4 text-emerald-400" />;
    case 'user':
      return <Search className="w-4 h-4 text-blue-400" />;
    default:
      return <Database className="w-4 h-4 text-gray-400" />;
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
    case 'thought':
      return 'border-l-violet-500/40 bg-violet-500/5';
    case 'action':
      return 'border-l-amber-500/40 bg-amber-500/5';
    case 'observation':
      return 'border-l-cyan-500/40 bg-cyan-500/5';
    case 'answer':
      return 'border-l-emerald-500/40 bg-emerald-500/5';
    case 'user':
      return 'border-l-blue-500/40 bg-blue-500/5';
    default:
      return 'border-l-gray-500/40 bg-gray-500/5';
  }
}

/* ═══════════════════════════════════════════════════════════════
   Component
   ═══════════════════════════════════════════════════════════════ */

export default function RiskInvestigation({ caseId, caseTitle }: Props) {
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

  // Auto-investigate on mount
  useEffect(() => {
    startInvestigation();
    return () => { abortRef.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caseId]);

  const nextId = () => ++stepIdRef.current;

  const addStep = (step: AgentStep) => {
    if (step.type === 'thought' || step.type === 'action' || step.type === 'observation') {
      setIterationCount((c) => step.type === 'thought' ? c + 1 : c);
    }
    setSteps((prev) => [...prev, { id: nextId(), type: step.type, content: step.content, collapsed: false }]);
  };

  const startInvestigation = () => {
    setIsStreaming(true);
    setError(null);
    setSteps([]);
    setIterationCount(0);

    abortRef.current = aiApi.investigateStream(
      caseId,
      addStep,
      () => { setIsStreaming(false); setInvestigationDone(true); },
      (err) => { setError(err); setIsStreaming(false); },
    );
  };

  const sendMessage = (text: string) => {
    if (!text.trim() || isStreaming) return;

    setSteps((prev) => [...prev, { id: nextId(), type: 'user', content: text.trim() }]);
    setInput('');
    setIsStreaming(true);
    setError(null);
    setIterationCount(0);

    // Build history from answer steps
    const history = steps
      .filter((s) => s.type === 'answer' || s.type === 'user')
      .map((s) => `${s.type === 'user' ? 'User' : 'Assistant'}: ${s.content}`)
      .join('\n\n');

    abortRef.current = aiApi.chatStream(
      caseId,
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

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--aegis-border)]">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-purple-500 to-pink-600 flex items-center justify-center">
          <Bot className="w-5 h-5 text-white" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-gray-200 truncate">
            AEGIS AI Agent
          </h3>
          <p className="text-[10px] text-gray-500 truncate">{caseTitle}</p>
        </div>
        {isStreaming && (
          <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-purple-500/10 border border-purple-500/30">
            <Loader2 className="w-3 h-3 text-purple-400 animate-spin" />
            <span className="text-[10px] text-purple-400">
              Step {iterationCount}…
            </span>
          </div>
        )}
      </div>

      {/* Agent steps stream */}
      <div className="flex-1 overflow-auto p-3 space-y-2">
        {steps.map((step) => (
          <div
            key={step.id}
            className={`rounded-lg border-l-2 ${stepStyles(step.type)} transition-all`}
          >
            {/* Step header — clickable to collapse reasoning steps */}
            <button
              onClick={() => (step.type !== 'answer' && step.type !== 'user') && toggleCollapse(step.id)}
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

            {/* Step content */}
            {!step.collapsed && (
              <div className="px-3 pb-3">
                {step.type === 'answer' ? (
                  <div className="text-sm leading-relaxed">
                    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                      {step.content}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <div className={`text-sm leading-relaxed whitespace-pre-wrap break-words ${
                    step.type === 'user'
                      ? 'text-blue-300'
                      : step.type === 'observation'
                        ? 'text-cyan-300/80 font-mono text-xs'
                        : 'text-gray-400'
                  }`}>
                    {step.content}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}

        {/* Loading indicator between steps */}
        {isStreaming && (
          <div className="flex items-center gap-2 px-3 py-2 text-gray-500 text-xs">
            <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
            <span>Agent is reasoning…</span>
          </div>
        )}

        {error && (
          <div className="text-center px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
            {error}
          </div>
        )}

        <div ref={endRef} />
      </div>

      {/* Suggested prompts */}
      {investigationDone && !isStreaming && steps.filter((s) => s.type === 'user').length === 0 && (
        <div className="px-4 pb-2">
          <p className="text-[10px] text-gray-600 mb-2 uppercase tracking-wider">Suggested questions</p>
          <div className="grid grid-cols-2 gap-2">
            {SUGGESTED_PROMPTS.map((prompt) => (
              <button
                key={prompt.label}
                onClick={() => sendMessage(prompt.label)}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs text-left transition-colors hover:brightness-125 ${prompt.color}`}
              >
                <prompt.icon className="w-3.5 h-3.5 flex-shrink-0" />
                <span>{prompt.label}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input */}
      <div className="p-3 border-t border-[var(--aegis-border)]">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask the agent about this risk…"
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
          AEGIS AI Agent · ReAct · Ontology-driven reasoning · Ollama local
        </p>
      </div>

      {/* Markdown Preview Modal */}
      {previewContent && (
        <MarkdownModal
          content={previewContent}
          title={caseTitle}
          onClose={() => setPreviewContent(null)}
        />
      )}
    </div>
  );
}
