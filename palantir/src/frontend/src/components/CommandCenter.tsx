import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Send, Loader2, Brain, Eye, Zap, Sparkles,
  ChevronDown, ChevronRight, Terminal, Shield,
  AlertTriangle, Bell, Radio, Maximize2, RotateCcw,
  MessageSquare,
} from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { commandCenterApi, type AgentStep } from '../services/api';
import type { AgentProfile, CommandCenterStep } from '../types';
import MarkdownModal from './MarkdownModal';

/* ═══════════════════════════════════════════════════════════════
   Types
   ═══════════════════════════════════════════════════════════════ */

interface DisplayStep {
  id: number;
  type: CommandCenterStep['type'] | 'user';
  content: string;
  collapsed?: boolean;
  agentId?: string;
}

/* ═══════════════════════════════════════════════════════════════
   Markdown renderer (dark theme)
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

const AGENT_COLORS: Record<string, string> = {
  centcom: 'red',
  civilcom: 'blue',
  opscom: 'amber',
  sentinel: 'rose',
};

function agentColor(agentId: string): string {
  return AGENT_COLORS[agentId] || 'cyan';
}

function StepIcon({ type }: { type: DisplayStep['type'] }) {
  switch (type) {
    case 'agent': return <Shield className="w-4 h-4 text-cyan-400" />;
    case 'thought': return <Brain className="w-4 h-4 text-violet-400" />;
    case 'cypher': return <Terminal className="w-4 h-4 text-emerald-400" />;
    case 'observation': return <Eye className="w-4 h-4 text-cyan-400" />;
    case 'alert': return <Bell className="w-4 h-4 text-rose-400 animate-bounce" />;
    case 'answer': return <Sparkles className="w-4 h-4 text-emerald-400" />;
    case 'user': return <MessageSquare className="w-4 h-4 text-blue-400" />;
    default: return <Zap className="w-4 h-4 text-gray-400" />;
  }
}

function stepLabel(type: DisplayStep['type']): string {
  switch (type) {
    case 'agent': return 'Agent Active';
    case 'thought': return 'Reasoning';
    case 'cypher': return 'Neo4j Query';
    case 'observation': return 'Data Retrieved';
    case 'alert': return '⚠ ALERT';
    case 'answer': return 'Analysis';
    case 'user': return 'Query';
    default: return type;
  }
}

function stepStyles(type: DisplayStep['type']): string {
  switch (type) {
    case 'agent': return 'border-l-cyan-500/40 bg-cyan-500/5';
    case 'thought': return 'border-l-violet-500/40 bg-violet-500/5';
    case 'cypher': return 'border-l-emerald-500/40 bg-emerald-500/5';
    case 'observation': return 'border-l-cyan-500/40 bg-cyan-500/5';
    case 'alert': return 'border-l-rose-500/60 bg-rose-500/10 animate-pulse';
    case 'answer': return 'border-l-emerald-500/40 bg-emerald-500/5';
    case 'user': return 'border-l-blue-500/40 bg-blue-500/5';
    default: return 'border-l-gray-500/40 bg-gray-500/5';
  }
}

/* ═══════════════════════════════════════════════════════════════
   Cypher display helper — shows query with highlighted keywords
   ═══════════════════════════════════════════════════════════════ */

function CypherBlock({ content }: { content: string }) {
  // content is JSON: { query: "...", explanation: "..." }
  let query = content;
  let explanation = '';
  try {
    const parsed = JSON.parse(content);
    query = parsed.query || content;
    explanation = parsed.explanation || '';
  } catch { /* use raw */ }

  // Highlight Cypher keywords
  const highlighted = query.replace(
    /\b(MATCH|WHERE|RETURN|WITH|ORDER BY|LIMIT|OPTIONAL MATCH|UNWIND|CREATE|MERGE|SET|DELETE|DETACH|CALL|YIELD|AS|AND|OR|NOT|IN|IS NULL|IS NOT NULL|CONTAINS|STARTS WITH|ENDS WITH|COUNT|SUM|AVG|COLLECT|DISTINCT)\b/gi,
    '<span class="text-cyan-400 font-semibold">$1</span>'
  );

  return (
    <div className="space-y-2">
      <div className="p-3 rounded-lg bg-[#0d1117] border border-emerald-500/20 overflow-x-auto">
        <pre className="text-xs font-mono text-emerald-300 whitespace-pre-wrap" dangerouslySetInnerHTML={{ __html: highlighted }} />
      </div>
      {explanation && (
        <p className="text-xs text-gray-400 italic px-1">{explanation}</p>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Suggested NL queries per agent
   ═══════════════════════════════════════════════════════════════ */

const SUGGESTED_QUERIES: Record<string, { label: string; icon: typeof Shield }[]> = {
  centcom: [
    { label: 'Which facilities have the most incidents in the last 30 days?', icon: Shield },
    { label: 'Show persons connected to more than one high-severity event', icon: AlertTriangle },
    { label: 'Find all sabotage cases and their linked entities', icon: Zap },
  ],
  civilcom: [
    { label: 'What communities are affected by water quality issues?', icon: Shield },
    { label: 'Show facilities with citizen complaints and their status', icon: AlertTriangle },
    { label: 'Which treatment plants serve the most population?', icon: Zap },
  ],
  opscom: [
    { label: 'Show all sensors with recent anomalous readings', icon: Shield },
    { label: 'Which assets need immediate maintenance?', icon: AlertTriangle },
    { label: 'List facilities with the most open risk cases', icon: Zap },
  ],
  sentinel: [
    { label: 'Scan for persons with access to multiple critical facilities', icon: Shield },
    { label: 'Detect unusual patterns: contractors near high-security zones', icon: AlertTriangle },
    { label: 'Alert on any facility with severity > 7 events today', icon: Zap },
  ],
};

/* ═══════════════════════════════════════════════════════════════
   Main Component
   ═══════════════════════════════════════════════════════════════ */

export default function CommandCenter() {
  const [agents, setAgents] = useState<AgentProfile[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<AgentProfile | null>(null);
  const [steps, setSteps] = useState<DisplayStep[]>([]);
  const [input, setInput] = useState('');
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const [alerts, setAlerts] = useState<{ message: string; severity: string; target: string }[]>([]);
  const endRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const stepIdRef = useRef(0);

  const scroll = useCallback(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => { scroll(); }, [steps, scroll]);

  // Load agents on mount
  useEffect(() => {
    commandCenterApi.getAgents().then((a) => {
      setAgents(a);
      if (a.length > 0) setSelectedAgent(a[0]);
    });
  }, []);

  const nextId = () => ++stepIdRef.current;

  const addStep = (step: CommandCenterStep) => {
    // Parse alert steps to accumulate alerts
    if (step.type === 'alert') {
      try {
        const alert = JSON.parse(step.content);
        setAlerts((prev) => [...prev, { message: alert.message || step.content, severity: alert.severity || 'warning', target: alert.target || '' }]);
      } catch {
        setAlerts((prev) => [...prev, { message: step.content, severity: 'warning', target: '' }]);
      }
    }

    setSteps((prev) => [
      ...prev,
      {
        id: nextId(),
        type: step.type,
        content: step.content,
        collapsed: false,
        agentId: selectedAgent?.id,
      },
    ]);
  };

  const sendQuery = (text: string) => {
    if (!text.trim() || isStreaming || !selectedAgent) return;

    setSteps((prev) => [...prev, { id: nextId(), type: 'user', content: text.trim() }]);
    setInput('');
    setIsStreaming(true);
    setError(null);

    // Build history from previous answer/user steps
    const history = steps
      .filter((s) => s.type === 'answer' || s.type === 'user')
      .map((s) => `${s.type === 'user' ? 'User' : 'Agent'}: ${s.content}`)
      .join('\n\n');

    abortRef.current = commandCenterApi.queryStream(
      selectedAgent.id,
      text.trim(),
      history || null,
      addStep,
      () => setIsStreaming(false),
      (err) => { setError(err); setIsStreaming(false); },
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendQuery(input);
    }
  };

  const clearChat = () => {
    abortRef.current?.abort();
    setSteps([]);
    setAlerts([]);
    setError(null);
    setIsStreaming(false);
    stepIdRef.current = 0;
  };

  const toggleCollapse = (id: number) => {
    setSteps((prev) =>
      prev.map((s) => (s.id === id ? { ...s, collapsed: !s.collapsed } : s)),
    );
  };

  const color = selectedAgent ? agentColor(selectedAgent.id) : 'cyan';

  return (
    <div className="h-full flex flex-col gap-4">
      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100">
            ⚡ Command Center
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            Multi-Agent Intelligence · Natural Language → Cypher → Analysis
          </p>
        </div>
        {alerts.length > 0 && (
          <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-rose-500/10 border border-rose-500/30 animate-pulse">
            <Bell className="w-4 h-4 text-rose-400" />
            <span className="text-xs text-rose-400 font-semibold">{alerts.length} Alert{alerts.length > 1 ? 's' : ''}</span>
          </div>
        )}
      </div>

      {/* ── Agent Selector Cards ── */}
      <div className="grid grid-cols-4 gap-3">
        {agents.map((agent) => {
          const c = agentColor(agent.id);
          const isActive = selectedAgent?.id === agent.id;
          return (
            <button
              key={agent.id}
              onClick={() => { setSelectedAgent(agent); clearChat(); }}
              className={`relative p-4 rounded-xl border-2 transition-all duration-300 text-left group ${
                isActive
                  ? `bg-${c}-500/10 border-${c}-400/60 shadow-[0_0_25px_rgba(var(--tw-shadow-color),0.2)]`
                  : `bg-[var(--aegis-surface)] border-[var(--aegis-border)] hover:border-${c}-500/40 hover:bg-${c}-500/5`
              }`}
              style={isActive ? {
                borderColor: `var(--agent-${agent.id}-border, rgba(100,100,100,0.6))`,
                boxShadow: `0 0 25px rgba(var(--agent-${agent.id}-glow, 100,100,100), 0.15)`,
              } : {}}
            >
              {/* Active indicator */}
              {isActive && (
                <div className="absolute top-2 right-2">
                  <Radio className={`w-3.5 h-3.5 text-${c}-400 animate-pulse`} />
                </div>
              )}

              <div className="text-2xl mb-2">{agent.icon}</div>
              <h3 className={`text-sm font-bold ${isActive ? 'text-gray-100' : 'text-gray-300'}`}>
                {agent.name}
              </h3>
              <p className={`text-[10px] uppercase tracking-wider font-medium mt-0.5 ${
                isActive ? `text-${c}-400` : 'text-gray-500'
              }`}>
                {agent.role}
              </p>
              <p className="text-[11px] text-gray-500 mt-2 line-clamp-2">
                {agent.description}
              </p>
            </button>
          );
        })}
      </div>

      {/* ── Main Chat Area ── */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Chat Panel */}
        <div className="flex-1 aegis-card flex flex-col overflow-hidden">
          {/* Chat Header */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-[var(--aegis-border)]">
            {selectedAgent && (
              <>
                <div className="text-xl">{selectedAgent.icon}</div>
                <div className="flex-1 min-w-0">
                  <h3 className="text-sm font-semibold text-gray-200">
                    {selectedAgent.name}
                  </h3>
                  <p className="text-[10px] text-gray-500 truncate">{selectedAgent.role} · NL → Cypher</p>
                </div>
              </>
            )}
            {isStreaming && (
              <div className={`flex items-center gap-1.5 px-2 py-1 rounded-full bg-${color}-500/10 border border-${color}-500/30`}>
                <Loader2 className={`w-3 h-3 text-${color}-400 animate-spin`} />
                <span className={`text-[10px] text-${color}-400`}>Processing…</span>
              </div>
            )}
            {steps.length > 0 && (
              <button
                onClick={clearChat}
                className="w-7 h-7 rounded-lg bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] flex items-center justify-center text-gray-500 hover:text-red-400 hover:border-red-500/50 transition-colors"
                title="Clear chat"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            )}
          </div>

          {/* Steps Stream */}
          <div className="flex-1 overflow-auto p-3 space-y-2">
            {steps.length === 0 && !isStreaming && selectedAgent && (
              <div className="h-full flex flex-col items-center justify-center text-center px-8">
                <div className="text-5xl mb-4">{selectedAgent.icon}</div>
                <h3 className="text-lg font-bold text-gray-200 mb-2">
                  {selectedAgent.name} Ready
                </h3>
                <p className="text-sm text-gray-500 mb-6 max-w-md">
                  Ask any question in natural language. The agent will translate it to a Neo4j Cypher query,
                  execute it against the knowledge graph, and analyze the results with its <strong className="text-gray-300">{selectedAgent.role}</strong> perspective.
                </p>

                {/* Suggested queries */}
                <div className="w-full max-w-lg space-y-2">
                  <p className="text-[10px] text-gray-600 uppercase tracking-wider mb-2">Try asking</p>
                  {(SUGGESTED_QUERIES[selectedAgent.id] || []).map((sq) => (
                    <button
                      key={sq.label}
                      onClick={() => sendQuery(sq.label)}
                      className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border text-left text-sm transition-all
                        bg-${color}-500/5 border-${color}-500/20 text-gray-300 hover:bg-${color}-500/10 hover:border-${color}-500/40`}
                    >
                      <sq.icon className={`w-4 h-4 text-${color}-400 flex-shrink-0`} />
                      <span>{sq.label}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {steps.map((step) => (
              <div
                key={step.id}
                className={`rounded-lg border-l-2 ${stepStyles(step.type)} transition-all`}
              >
                {/* Step header */}
                <button
                  onClick={() =>
                    step.type !== 'answer' && step.type !== 'user' && step.type !== 'alert' && toggleCollapse(step.id)
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
                  {step.type !== 'answer' && step.type !== 'user' && step.type !== 'alert' && (
                    step.collapsed
                      ? <ChevronRight className="w-3 h-3 text-gray-600 ml-auto" />
                      : <ChevronDown className="w-3 h-3 text-gray-600 ml-auto" />
                  )}
                </button>

                {/* Step content */}
                {!step.collapsed && (
                  <div className="px-3 pb-3">
                    {step.type === 'cypher' ? (
                      <CypherBlock content={step.content} />
                    ) : step.type === 'answer' ? (
                      <div className="text-sm leading-relaxed">
                        <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                          {step.content}
                        </ReactMarkdown>
                      </div>
                    ) : step.type === 'alert' ? (
                      <div className="flex items-start gap-3 p-3 rounded-lg bg-rose-500/10 border border-rose-500/30">
                        <AlertTriangle className="w-5 h-5 text-rose-400 flex-shrink-0 mt-0.5" />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-rose-300 font-medium">{(() => {
                            try { return JSON.parse(step.content).message || step.content; } catch { return step.content; }
                          })()}</p>
                          <p className="text-[10px] text-rose-400/60 mt-1">{(() => {
                            try {
                              const a = JSON.parse(step.content);
                              return `${a.type?.toUpperCase()} → ${a.target} · Severity: ${a.severity}`;
                            } catch { return ''; }
                          })()}</p>
                        </div>
                      </div>
                    ) : (
                      <div className={`text-sm leading-relaxed whitespace-pre-wrap break-words ${
                        step.type === 'user' ? 'text-blue-300' :
                        step.type === 'observation' ? 'text-cyan-300/80 font-mono text-xs' :
                        step.type === 'agent' ? `text-${agentColor(step.agentId || '')}-300 font-medium` :
                        'text-gray-400'
                      }`}>
                        {step.content}
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}

            {isStreaming && (
              <div className="flex items-center gap-2 px-3 py-2 text-gray-500 text-xs">
                <Loader2 className={`w-4 h-4 animate-spin text-${color}-400`} />
                <span>{selectedAgent?.name} is processing your query…</span>
              </div>
            )}

            {error && (
              <div className="text-center px-4 py-2 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
                {error}
              </div>
            )}

            <div ref={endRef} />
          </div>

          {/* Input */}
          <div className="p-3 border-t border-[var(--aegis-border)]">
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={selectedAgent ? `Ask ${selectedAgent.name} in natural language...` : 'Select an agent to begin...'}
                rows={1}
                className={`flex-1 resize-none rounded-xl bg-[var(--aegis-surface-2)] border border-[var(--aegis-border)] px-4 py-2.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-${color}-500/50 transition-colors`}
                disabled={isStreaming || !selectedAgent}
              />
              <button
                onClick={() => sendQuery(input)}
                disabled={isStreaming || !input.trim() || !selectedAgent}
                className={`w-10 h-10 rounded-xl bg-${color}-500/20 border border-${color}-500/30 flex items-center justify-center text-${color}-400 hover:bg-${color}-500/30 transition-colors disabled:opacity-30 disabled:cursor-not-allowed`}
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
            <p className="text-[9px] text-gray-700 mt-1.5 text-center">
              AEGIS Command Center · Multi-Agent · NL → Cypher · {selectedAgent?.name || '—'} · Ollama local
            </p>
          </div>
        </div>

        {/* ── Alerts Sidebar ── */}
        {alerts.length > 0 && (
          <div className="w-72 aegis-card p-4 overflow-auto animate-slide-in">
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-[var(--aegis-border)]">
              <Bell className="w-4 h-4 text-rose-400" />
              <h3 className="text-sm font-semibold text-gray-200">SENTINEL Alerts</h3>
              <span className="ml-auto px-2 py-0.5 rounded-full bg-rose-500/20 text-[10px] text-rose-400 font-bold">
                {alerts.length}
              </span>
            </div>
            <div className="space-y-3">
              {alerts.map((alert, i) => (
                <div
                  key={i}
                  className={`p-3 rounded-lg border ${
                    alert.severity === 'critical'
                      ? 'bg-red-500/10 border-red-500/30'
                      : alert.severity === 'warning'
                        ? 'bg-amber-500/10 border-amber-500/30'
                        : 'bg-blue-500/10 border-blue-500/30'
                  }`}
                >
                  <div className="flex items-center gap-2 mb-1">
                    <AlertTriangle className={`w-3.5 h-3.5 ${
                      alert.severity === 'critical' ? 'text-red-400' :
                      alert.severity === 'warning' ? 'text-amber-400' : 'text-blue-400'
                    }`} />
                    <span className={`text-[10px] uppercase font-bold tracking-wider ${
                      alert.severity === 'critical' ? 'text-red-400' :
                      alert.severity === 'warning' ? 'text-amber-400' : 'text-blue-400'
                    }`}>
                      {alert.severity}
                    </span>
                  </div>
                  <p className="text-xs text-gray-300">{alert.message}</p>
                  {alert.target && (
                    <p className="text-[10px] text-gray-500 mt-1">Target: {alert.target}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Markdown Preview Modal */}
      {previewContent && (
        <MarkdownModal
          content={previewContent}
          title={`${selectedAgent?.name || 'Agent'} Analysis`}
          onClose={() => setPreviewContent(null)}
        />
      )}
    </div>
  );
}
