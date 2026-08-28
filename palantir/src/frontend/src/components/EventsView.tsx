import { useEvents } from '../hooks/useApi';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useState } from 'react';
import { Activity, Filter } from 'lucide-react';
import EntityActionModal from './EntityActionModal';
import Pagination from './Pagination';

const EVENT_TYPES = [
  'All',
  'SensorReading',
  'Access',
  'Maintenance',
  'SystemStatus',
  'QualityCheck',
  'PhysicalAnomaly',
  'UnauthorizedAccess',
  'CyberAlert',
  'CitizenReport',
];

const EVENT_TYPE_ICONS: Record<string, string> = {
  SensorReading: '📡',
  Access: '🎫',
  Maintenance: '🔧',
  SystemStatus: '💚',
  QualityCheck: '🧪',
  PhysicalAnomaly: '⚡',
  UnauthorizedAccess: '🚪',
  CyberAlert: '🔒',
  CitizenReport: '📢',
};

export default function EventsView() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [typeFilter, setTypeFilter] = useState<string>(
    searchParams.get('eventType') ?? 'All'
  );

  // Support both legacy minSeverity (from dashboard critical alerts link) and exact severity
  const initialSeverity = searchParams.has('minSeverity')
    ? -Number(searchParams.get('minSeverity'))   // negative = "min" mode (from dashboard)
    : searchParams.has('severity')
    ? Number(searchParams.get('severity'))
    : -1;  // -1 = "All"

  const [severityFilter, setSeverityFilter] = useState<number>(initialSeverity);

  // Build query params: negative = minSeverity, 0+ = exact severity, -1 = all
  const queryParams = {
    eventType: typeFilter === 'All' ? undefined : typeFilter,
    minSeverity: severityFilter < -1 ? Math.abs(severityFilter) : undefined,
    severity: severityFilter >= 0 ? severityFilter : undefined,
  };

  const { data: events, isLoading } = useEvents(queryParams);
  const navigate = useNavigate();
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;
  const [modalEntity, setModalEntity] = useState<{
    id: string;
    name: string;
  } | null>(null);

  const handleSeverityClick = (s: number) => {
    // s: -1 = All, 0 = SEV-0, 1 = SEV-1, etc.
    setSeverityFilter(s);
    const p = new URLSearchParams(searchParams);
    p.delete('minSeverity');
    p.delete('severity');
    if (s >= 0) p.set('severity', String(s));
    setSearchParams(p, { replace: true });
  };

  return (
    <div className="space-y-6 animate-slide-in">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-gray-100">Event Feed</h2>
          <p className="text-xs text-gray-500 mt-1">
            All detected events across monitored facilities
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-gray-400">
          <Activity className="w-4 h-4" />
          {events?.length ?? 0} events
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-4 items-center">
        <div className="flex items-center gap-2">
          <Filter className="w-4 h-4 text-gray-500" />
          <span className="text-xs text-gray-500">Type:</span>
          <div className="flex gap-1">
            {EVENT_TYPES.map((t) => (
              <button
                key={t}
                onClick={() => {
                  setTypeFilter(t);
                  const p = new URLSearchParams(searchParams);
                  if (t === 'All') p.delete('eventType'); else p.set('eventType', t);
                  setSearchParams(p, { replace: true });
                }}
                className={`px-2.5 py-1 rounded-lg text-xs transition-colors ${
                  typeFilter === t
                    ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                    : 'bg-[var(--aegis-surface-2)] text-gray-500 border border-transparent hover:text-gray-300'
                }`}
              >
                {t === 'All' ? 'All' : `${EVENT_TYPE_ICONS[t] || ''} ${t}`}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-500">Severity:</span>
          <div className="flex gap-1">
            {([-1, 0, 1, 2, 3, 4, 5] as number[]).map((s) => {
              const SEVERITY_COLORS: Record<number, string> = {
                0: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
                1: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
                2: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
                3: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
                4: 'bg-red-500/20 text-red-400 border-red-500/30',
                5: 'bg-rose-600/30 text-rose-300 border-rose-500/40',
              };
              const active = severityFilter === s;
              const colorClass = active && s >= 0 ? SEVERITY_COLORS[s] : '';
              return (
                <button
                  key={s}
                  onClick={() => handleSeverityClick(s)}
                  className={`min-w-[1.75rem] h-7 px-1.5 rounded-lg text-xs transition-colors border ${
                    active
                      ? colorClass || 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
                      : 'bg-[var(--aegis-surface-2)] text-gray-500 border-transparent hover:text-gray-300'
                  }`}
                >
                  {s === -1 ? 'All' : s}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="text-center py-8 text-cyan-400 animate-pulse">
          Loading events...
        </div>
      ) : (
        <div className="aegis-card divide-y divide-[var(--aegis-border)]">
          {events
            ?.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
            .map((evt) => (
            <div
              key={evt.eventId}
              onClick={() =>
                setModalEntity({ id: evt.eventId, name: evt.description.slice(0, 60) })
              }
              className="flex items-center gap-4 p-4 hover:bg-white/5 cursor-pointer transition-colors"
            >
              {/* Severity indicator */}
              <div className="w-1 h-12 rounded-full" style={{
                backgroundColor: evt.severity >= 5 ? '#ef4444' :
                  evt.severity >= 4 ? '#f97316' :
                  evt.severity >= 3 ? '#fbbf24' :
                  evt.severity >= 2 ? '#60a5fa' :
                  evt.severity >= 1 ? '#94a3b8' : '#34d399'
              }} />

              {/* Icon */}
              <div className="text-xl flex-shrink-0 w-8 text-center">
                {EVENT_TYPE_ICONS[evt.eventType] || '📋'}
              </div>

              {/* Content */}
              <div className="flex-1">
                <p className="text-sm text-gray-200">{evt.description}</p>
                <div className="flex items-center gap-4 mt-1">
                  <span className="text-xs text-gray-500">{evt.eventId}</span>
                  <span className="text-xs text-gray-600">
                    {new Date(evt.timestamp).toLocaleString()}
                  </span>
                  {evt.facilityName && (
                    <span className="text-xs text-blue-400">📍 {evt.facilityName}</span>
                  )}
                  {evt.personName && (
                    <span className="text-xs text-purple-400">👤 {evt.personName}</span>
                  )}
                </div>
              </div>

              {/* Type badge */}
              <span className="px-2 py-1 rounded text-[10px] bg-[var(--aegis-surface-2)] text-gray-400 border border-[var(--aegis-border)]">
                {evt.eventType}
              </span>

              {/* Severity badge */}
              <span className={`px-2 py-1 rounded text-xs font-mono font-bold border ${
                evt.severity === 0 ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30' :
                evt.severity === 1 ? 'bg-slate-500/20 text-slate-300 border-slate-500/30' :
                evt.severity === 2 ? 'bg-blue-500/20 text-blue-400 border-blue-500/30' :
                evt.severity === 3 ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30' :
                evt.severity === 4 ? 'bg-orange-500/20 text-orange-300 border-orange-500/30' :
                'bg-red-600/30 text-red-300 border-red-500/40'
              }`}>
                {evt.severity === 0 ? '✅ OK' : `SEV-${evt.severity}`}
              </span>
            </div>
          ))}
        </div>
      )}

      <Pagination
        currentPage={page}
        totalItems={events?.length ?? 0}
        pageSize={PAGE_SIZE}
        onPageChange={setPage}
      />

      {modalEntity && (
        <EntityActionModal
          entityId={modalEntity.id}
          entityType="event"
          entityName={modalEntity.name}
          onClose={() => setModalEntity(null)}
        />
      )}
    </div>
  );
}
