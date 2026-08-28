import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Network, Bot, Clock, X } from 'lucide-react';

interface Props {
  entityId: string;
  entityType: 'event' | 'facility' | 'person';
  entityName: string;
  onClose: () => void;
}

const TIME_RANGES = [
  { value: '24h', label: '24 h' },
  { value: '48h', label: '48 h' },
  { value: '7d', label: '7 days' },
  { value: '30d', label: '30 days' },
];

export default function EntityActionModal({
  entityId,
  entityType,
  entityName,
  onClose,
}: Props) {
  const navigate = useNavigate();
  const [timeRange, setTimeRange] = useState('24h');

  const typeLabels: Record<string, string> = {
    event: 'Event',
    facility: 'Facility',
    person: 'Person',
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-slide-in"
      onClick={onClose}
    >
      <div
        className="aegis-card p-6 w-[440px] shadow-2xl shadow-black/50"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <div className="min-w-0 flex-1">
            <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">
              {typeLabels[entityType] || entityType}
            </p>
            <h3 className="text-lg font-bold text-gray-100 truncate">
              {entityName}
            </h3>
            <p className="text-xs text-gray-600 font-mono truncate">{entityId}</p>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-gray-500 hover:text-gray-300 transition-colors ml-3"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Time Range */}
        <div className="mb-5">
          <div className="flex items-center gap-2 mb-2">
            <Clock className="w-3.5 h-3.5 text-gray-500" />
            <span className="text-xs text-gray-500">
              Agent time window
            </span>
          </div>
          <div className="flex gap-2">
            {TIME_RANGES.map((tr) => (
              <button
                key={tr.value}
                onClick={() => setTimeRange(tr.value)}
                className={`flex-1 px-3 py-2 rounded-lg text-xs font-medium transition-colors border ${
                  timeRange === tr.value
                    ? 'bg-cyan-500/20 text-cyan-400 border-cyan-500/30'
                    : 'bg-[var(--aegis-surface-2)] text-gray-500 border-transparent hover:text-gray-300 hover:border-[var(--aegis-border)]'
                }`}
              >
                {tr.label}
              </button>
            ))}
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex gap-3">
          <button
            onClick={() => {
              onClose();
              navigate(`/graph/${entityId}`);
            }}
            className="flex-1 flex items-center justify-center gap-2.5 px-4 py-3.5 rounded-xl bg-blue-500/10 border border-blue-500/30 text-blue-400 text-sm font-medium hover:bg-blue-500/20 transition-colors"
          >
            <Network className="w-5 h-5" />
            View Graph
          </button>
          <button
            onClick={() => {
              onClose();
              navigate(
                `/investigate/${entityType}/${entityId}?timeRange=${timeRange}`,
              );
            }}
            className="flex-1 flex items-center justify-center gap-2.5 px-4 py-3.5 rounded-xl bg-gradient-to-r from-purple-500/20 to-pink-500/20 border border-purple-500/30 text-purple-400 text-sm font-medium hover:from-purple-500/30 hover:to-pink-500/30 transition-all"
          >
            <Bot className="w-5 h-5" />
            Ask Agent
          </button>
        </div>
      </div>
    </div>
  );
}
