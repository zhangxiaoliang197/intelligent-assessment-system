import { useEffect, useRef, useMemo, useState } from 'react';
import { useEvents } from '../hooks/useApi';
import { useNavigate } from 'react-router-dom';
import { DataSet } from 'vis-data';
import { Timeline } from 'vis-timeline';
import 'vis-timeline/styles/vis-timeline-graph2d.min.css';
import { Clock, Filter, Activity, BarChart3, Layers } from 'lucide-react';

// ── Colores por tipo de evento ──
const TYPE_COLORS: Record<string, string> = {
  PhysicalAnomaly: '#ef4444',
  UnauthorizedAccess: '#f97316',
  CyberAlert: '#a855f7',
  CitizenReport: '#06b6d4',
  Maintenance: '#64748b',
  Access: '#10b981',
  SensorReading: '#3b82f6',
  QualityCheck: '#eab308',
  SystemStatus: '#6366f1',
};

const SEVERITY_LABELS = ['Info', 'Low', 'Medium', 'High', 'Critical', 'Emergency'];
const SEVERITY_COLORS = ['#64748b', '#22d3ee', '#eab308', '#f97316', '#ef4444', '#dc2626'];

export default function TimelineView() {
  const { data: events, isLoading } = useEvents();
  const timelineRef = useRef<HTMLDivElement>(null);
  const tlInstanceRef = useRef<Timeline | null>(null);
  const navigate = useNavigate();
  const [minSeverity, setMinSeverity] = useState(2); // Medium by default — filters noise

  // Filtrar eventos por severidad mínima
  const filtered = useMemo(() => {
    if (!events) return [];
    return events.filter((e) => e.severity >= minSeverity);
  }, [events, minSeverity]);

  // Conteo por tipo para la leyenda
  const typeCounts = useMemo(() => {
    const map = new Map<string, number>();
    filtered.forEach((e) => map.set(e.eventType, (map.get(e.eventType) || 0) + 1));
    return map;
  }, [filtered]);

  // Resumen por severidad
  const sevCounts = useMemo(() => {
    const map = new Map<number, number>();
    if (!events) return map;
    events.forEach((e) => map.set(e.severity, (map.get(e.severity) || 0) + 1));
    return map;
  }, [events]);

  useEffect(() => {
    if (!timelineRef.current || filtered.length === 0) return;

    // Grupos = swim lanes por tipo de evento
    const typeSet = new Set(filtered.map((e) => e.eventType));
    const groups = new DataSet(
      Array.from(typeSet).map((type) => ({
        id: type,
        content: `<div style="display:flex;align-items:center;gap:6px">
          <span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${TYPE_COLORS[type] || '#64748b'}"></span>
          <span style="color:#d1d5db;font-size:12px;font-weight:500">${type}</span>
          <span style="color:#6b7280;font-size:10px">(${typeCounts.get(type) || 0})</span>
        </div>`,
        style: `border-left: 3px solid ${TYPE_COLORS[type] || '#64748b'};`,
      }))
    );

    // Items — cada evento con color basado en severidad
    const items = new DataSet(
      filtered.map((evt) => ({
        id: evt.eventId,
        group: evt.eventType,
        content: `<span style="font-size:11px">${evt.description.length > 50 ? evt.description.slice(0, 50) + '…' : evt.description}</span>`,
        start: new Date(evt.timestamp),
        style: `
          background-color: ${SEVERITY_COLORS[evt.severity]}18;
          border-color: ${SEVERITY_COLORS[evt.severity]};
          border-left: 3px solid ${SEVERITY_COLORS[evt.severity]};
          color: ${SEVERITY_COLORS[evt.severity]};
          border-radius: 4px;
          padding: 2px 6px;
          font-size: 11px;
        `,
        title: `${evt.description}\n\nType: ${evt.eventType}\nSeverity: ${SEVERITY_LABELS[evt.severity]} (${evt.severity})\nDate: ${new Date(evt.timestamp).toLocaleString('en-US')}\n${evt.facilityName ? 'Facility: ' + evt.facilityName : ''}`,

      }))
    );

    if (tlInstanceRef.current) {
      tlInstanceRef.current.destroy();
    }

    const timeline = new Timeline(timelineRef.current, items, groups, {
      height: '100%',
      min: new Date('2025-12-01'),
      max: new Date('2026-03-15'),
      start: new Date('2026-01-15'),
      end: new Date('2026-02-28'),
      zoomMin: 1000 * 60 * 60 * 2,      // 2 horas
      zoomMax: 1000 * 60 * 60 * 24 * 90, // 90 días
      orientation: 'top',
      showCurrentTime: true,
      stack: true,
      selectable: true,
      groupOrder: 'content',
      margin: { item: { horizontal: 5, vertical: 5 } },
      tooltip: { followMouse: true, overflowMethod: 'flip' },
    });

    timeline.on('select', (props: { items: string[] }) => {
      if (props.items.length > 0) {
        navigate(`/graph/${props.items[0]}`);
      }
    });

    tlInstanceRef.current = timeline;

    return () => {
      timeline.destroy();
      tlInstanceRef.current = null;
    };
  }, [filtered, navigate, typeCounts]);

  return (
    <div className="h-full flex flex-col gap-3">
      {/* ── Header + filtros ── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-xl font-bold text-gray-100 flex items-center gap-2">
            <Activity className="w-5 h-5 text-cyan-400" />
            Event Timeline
          </h2>
          <p className="text-xs text-gray-500 mt-1">
            {filtered.length} events (of {events?.length || 0}) · Grouped by type · Click to investigate
          </p>
        </div>

        {/* Filtro de severidad mínima */}
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-gray-500" />
          <span className="text-xs text-gray-500">Min severity:</span>
          {SEVERITY_LABELS.map((label, i) => (
            <button
              key={i}
              onClick={() => setMinSeverity(i)}
              className={`px-2 py-1 rounded text-xs transition-all flex items-center gap-1 ${
                minSeverity === i
                  ? 'border font-medium'
                  : minSeverity <= i
                  ? 'text-gray-400 hover:text-gray-200'
                  : 'text-gray-600 hover:text-gray-400'
              }`}
              style={
                minSeverity === i
                  ? {
                      backgroundColor: SEVERITY_COLORS[i] + '25',
                      borderColor: SEVERITY_COLORS[i] + '50',
                      color: SEVERITY_COLORS[i],
                    }
                  : {}
              }
            >
              {label}
              <span className="text-[10px] opacity-60">({sevCounts.get(i) || 0})</span>
            </button>
          ))}
        </div>
      </div>

      {/* ── Leyenda de tipos ── */}
      <div className="flex flex-wrap gap-x-4 gap-y-1 px-1">
        {Array.from(typeCounts.entries())
          .sort(([, a], [, b]) => b - a)
          .map(([type, count]) => (
            <div key={type} className="flex items-center gap-1.5">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: TYPE_COLORS[type] || '#64748b' }} />
              <span className="text-[11px] text-gray-400">{type}</span>
              <span className="text-[10px] text-gray-600">{count}</span>
            </div>
          ))}
      </div>

      {/* ── Timeline ── */}
      <div className="flex-1 aegis-card overflow-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center h-full">
            <div className="flex items-center gap-2 text-cyan-400 animate-pulse">
              <Clock className="w-5 h-5" /> Loading timeline...
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-gray-500">
            <Layers className="w-8 h-8 text-gray-600" />
            <p className="text-sm">No events with severity ≥ {SEVERITY_LABELS[minSeverity]}</p>
            <button
              onClick={() => setMinSeverity(0)}
              className="text-xs text-cyan-400 hover:text-cyan-300"
            >
              Show all
            </button>
          </div>
        ) : (
          <div ref={timelineRef} className="w-full h-full min-h-[500px]" />
        )}
      </div>
    </div>
  );
}
