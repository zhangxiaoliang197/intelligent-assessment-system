import { useState, useEffect, useRef, useCallback } from 'react';
import { useFacilities } from '../hooks/useApi';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import { Building2, X, Clock, Loader2, Bot, Sparkles, Network, Maximize2 } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { aiApi, type AgentStep } from '../services/api';
import type { Facility } from '../types';
import 'leaflet/dist/leaflet.css';
import MarkdownModal from './MarkdownModal';

const CRITICALITY_COLORS: Record<string, string> = {
  CRITICAL: '#dc2626',
  HIGH: '#ef4444',
  MEDIUM: '#f59e0b',
  LOW: '#10b981',
};

const TIME_RANGES = [
  { value: '24h', label: '24h' },
  { value: '48h', label: '48h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
];

/* ── Markdown components for dark theme ── */
const mdComponents = {
  h1: ({ children, ...p }: any) => <h1 {...p} className="text-lg font-bold text-gray-100 mt-4 mb-2 pb-1.5 border-b border-[var(--aegis-border)]">{children}</h1>,
  h2: ({ children, ...p }: any) => <h2 {...p} className="text-base font-bold text-gray-200 mt-3 mb-1.5">{children}</h2>,
  h3: ({ children, ...p }: any) => <h3 {...p} className="text-sm font-semibold text-gray-300 mt-2 mb-1">{children}</h3>,
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
  table: ({ children, ...p }: any) => <div className="overflow-x-auto mb-2"><table {...p} className="w-full text-xs">{children}</table></div>,
  thead: ({ children, ...p }: any) => <thead {...p} className="border-b border-[var(--aegis-border)]">{children}</thead>,
  th: ({ children, ...p }: any) => <th {...p} className="text-left px-2 py-1.5 text-[10px] text-gray-400 uppercase tracking-wider font-medium">{children}</th>,
  td: ({ children, ...p }: any) => <td {...p} className="px-2 py-1.5 text-xs text-gray-300 border-b border-[var(--aegis-border)]/50">{children}</td>,
  blockquote: ({ children, ...p }: any) => <blockquote {...p} className="border-l-2 border-cyan-500/40 pl-3 py-0.5 my-2 text-gray-400 italic text-xs">{children}</blockquote>,
  hr: () => <hr className="border-[var(--aegis-border)] my-3" />,
  a: ({ href, children, ...p }: any) => <a {...p} href={href} className="text-cyan-400 hover:text-cyan-300 underline" target="_blank" rel="noopener">{children}</a>,
};

export default function MapView() {
  const { data: facilities, isLoading } = useFacilities();
  const navigate = useNavigate();
  const [selected, setSelected] = useState<Facility | null>(null);
  const [timeRange, setTimeRange] = useState('7d');
  const [report, setReport] = useState('');
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stepCount, setStepCount] = useState(0);
  const [previewContent, setPreviewContent] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // Auto-generate report when facility selected or time range changes
  useEffect(() => {
    if (!selected) return;
    generateReport(selected.facilityId);
    return () => { abortRef.current?.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected, timeRange]);

  const scrollPanel = useCallback(() => {
    if (panelRef.current) panelRef.current.scrollTop = panelRef.current.scrollHeight;
  }, []);

  useEffect(() => { scrollPanel(); }, [report, scrollPanel]);

  const generateReport = (facilityId: string) => {
    abortRef.current?.abort();
    setReport('');
    setError(null);
    setIsGenerating(true);
    setStepCount(0);

    abortRef.current = aiApi.investigateEntityStream(
      'facility',
      facilityId,
      timeRange,
      (step: AgentStep) => {
        if (step.type === 'thought') setStepCount((c) => c + 1);
        if (step.type === 'answer') {
          setReport(step.content);
        }
      },
      () => setIsGenerating(false),
      (err) => { setError(err); setIsGenerating(false); },
    );
  };

  const closePanel = () => {
    abortRef.current?.abort();
    setSelected(null);
    setReport('');
    setError(null);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-pulse text-cyan-400">Loading geospatial data...</div>
      </div>
    );
  }

  const center: [number, number] = [40.42, -3.55];

  return (
    <div className="h-full flex flex-col gap-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100">Geospatial View</h2>
          <p className="text-xs text-gray-500 mt-1">
            Click a facility circle to generate an AI investigation report
          </p>
        </div>
        <div className="flex gap-3">
          {Object.entries(CRITICALITY_COLORS).map(([level, color]) => (
            <div key={level} className="flex items-center gap-1.5">
              <div className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: color }} />
              <span className="text-[10px] text-gray-400">{level}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Map + Report Panel */}
      <div className="flex-1 flex gap-4 min-h-0">
        {/* Map */}
        <div className={`${selected ? 'w-3/5' : 'w-full'} aegis-card overflow-hidden rounded-xl transition-all duration-300`}>
          <MapContainer
            center={center}
            zoom={10}
            className="w-full h-full min-h-[500px]"
            style={{ background: '#0d1117' }}
          >
            <TileLayer
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              attribution=""
            />

            {facilities?.map((f) => {
              if (!f.latitude || !f.longitude) return null;
              const color = CRITICALITY_COLORS[f.criticality] || '#64748b';
              const isSelected = selected?.facilityId === f.facilityId;

              return (
                <CircleMarker
                  key={f.facilityId}
                  center={[f.latitude, f.longitude]}
                  radius={isSelected ? 16 : f.criticality === 'CRITICAL' || f.criticality === 'HIGH' ? 14 : 10}
                  pathOptions={{
                    color: isSelected ? '#06b6d4' : color,
                    fillColor: color,
                    fillOpacity: isSelected ? 0.5 : 0.3,
                    weight: isSelected ? 3 : 2,
                  }}
                  eventHandlers={{
                    click: () => setSelected(f),
                  }}
                >
                  <Tooltip
                    permanent={false}
                    className="!bg-[var(--aegis-surface-2)] !border-[var(--aegis-border)] !text-gray-200 !rounded-lg !text-xs !px-3 !py-2"
                  >
                    <div className="flex items-center gap-2">
                      <Building2 className="w-3 h-3" />
                      <span className="font-medium">{f.name}</span>
                      <span className="text-gray-400 ml-1">({f.criticality})</span>
                    </div>
                  </Tooltip>
                </CircleMarker>
              );
            })}
          </MapContainer>
        </div>

        {/* Report Panel */}
        {selected && (
          <div className="w-2/5 aegis-card flex flex-col overflow-hidden rounded-xl animate-slide-in">
            {/* Panel Header */}
            <div className="p-4 border-b border-[var(--aegis-border)] flex-shrink-0">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <div className="w-8 h-8 rounded-lg bg-purple-500/10 border border-purple-500/30 flex items-center justify-center flex-shrink-0">
                    <Bot className="w-4 h-4 text-purple-400" />
                  </div>
                  <div className="min-w-0">
                    <h3 className="text-sm font-bold text-gray-100 truncate">{selected.name}</h3>
                    <p className="text-[10px] text-gray-500 font-mono">{selected.facilityId} · {selected.criticality}</p>
                  </div>
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => navigate(`/graph/${selected.facilityId}`)}
                    title="View Graph"
                    className="w-7 h-7 rounded-lg bg-blue-500/10 border border-blue-500/30 flex items-center justify-center text-blue-400 hover:bg-blue-500/20 transition-colors"
                  >
                    <Network className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={closePanel}
                    className="w-7 h-7 rounded-lg hover:bg-white/10 text-gray-500 hover:text-gray-300 flex items-center justify-center transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Time Range */}
              <div className="flex items-center gap-2">
                <Clock className="w-3 h-3 text-gray-500 flex-shrink-0" />
                <div className="flex gap-1">
                  {TIME_RANGES.map((tr) => (
                    <button
                      key={tr.value}
                      onClick={() => setTimeRange(tr.value)}
                      className={`px-2 py-1 rounded text-[10px] font-medium transition-colors border ${
                        timeRange === tr.value
                          ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
                          : 'bg-[var(--aegis-surface-2)] text-gray-500 border-transparent hover:text-gray-300'
                      }`}
                    >
                      {tr.label}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Report Content */}
            <div ref={panelRef} className="flex-1 overflow-auto p-4">
              {isGenerating && !report && (
                <div className="flex flex-col items-center justify-center h-full gap-3">
                  <div className="relative">
                    <div className="w-12 h-12 rounded-xl bg-purple-500/10 border border-purple-500/30 flex items-center justify-center">
                      <Loader2 className="w-6 h-6 animate-spin text-purple-400" />
                    </div>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-gray-400">Agent is investigating…</p>
                    <p className="text-[10px] text-gray-600 mt-1">Step {stepCount}</p>
                  </div>
                </div>
              )}

              {report && (
                <div className="animate-slide-in">
                  <div className="flex items-center gap-1.5 mb-3">
                    <Sparkles className="w-3.5 h-3.5 text-emerald-400" />
                    <span className="text-[10px] font-semibold text-emerald-400 uppercase tracking-wider">
                      Agent Report
                    </span>
                    <button
                      onClick={() => setPreviewContent(report)}
                      className="ml-auto flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium text-emerald-400 hover:bg-emerald-500/15 border border-emerald-500/20 hover:border-emerald-500/40 transition-all"
                      title="Open full report view"
                    >
                      <Maximize2 className="w-3 h-3" />
                      Preview
                    </button>
                  </div>
                  <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                    {report}
                  </ReactMarkdown>
                </div>
              )}

              {error && (
                <div className="text-center px-4 py-3 rounded-lg bg-red-500/10 border border-red-500/30 text-red-400 text-xs">
                  {error}
                </div>
              )}

              {isGenerating && report && (
                <div className="flex items-center gap-2 mt-3 text-gray-500 text-[10px]">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Actualizando…
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Markdown Preview Modal */}
      {previewContent && (
        <MarkdownModal
          content={previewContent}
          title={selected ? `${selected.name} — Facility Report` : 'Facility Report'}
          onClose={() => setPreviewContent(null)}
        />
      )}
    </div>
  );
}
