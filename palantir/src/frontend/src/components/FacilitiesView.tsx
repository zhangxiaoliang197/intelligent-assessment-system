import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import {
  Building2,
  MapPin,
  Radio,
  Package,
  ArrowLeft,
  AlertTriangle,
  CheckCircle,
  XCircle,
} from 'lucide-react';
import { useFacilities } from '../hooks/useApi';
import type { Facility } from '../types';
import EntityActionModal from './EntityActionModal';
import Pagination from './Pagination';

const criticalityColors: Record<string, { bg: string; text: string; border: string }> = {
  CRITICAL: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/30' },
  HIGH: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/30' },
  MEDIUM: { bg: 'bg-yellow-500/10', text: 'text-yellow-400', border: 'border-yellow-500/30' },
  LOW: { bg: 'bg-green-500/10', text: 'text-green-400', border: 'border-green-500/30' },
};

const statusIcon = (status: string) => {
  switch (status.toLowerCase()) {
    case 'operational':
      return <CheckCircle className="w-4 h-4 text-green-400" />;
    case 'maintenance':
      return <AlertTriangle className="w-4 h-4 text-yellow-400" />;
    default:
      return <XCircle className="w-4 h-4 text-red-400" />;
  }
};

const typeLabels: Record<string, string> = {
  WaterTreatmentPlant: 'Water Treatment Plant',
  PumpStation: 'Pump Station',
  Reservoir: 'Reservoir',
  DistributionNode: 'Distribution Node',
};

export default function FacilitiesView() {
  const { data: facilities, isLoading, isError } = useFacilities();
  const navigate = useNavigate();
  const [modalEntity, setModalEntity] = useState<{ id: string; name: string } | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-pulse text-cyan-400">Loading facilities...</div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-red-400">Failed to load facilities</div>
      </div>
    );
  }

  return (
    <div className="space-y-6 animate-slide-in">
      {/* Header */}
      <div className="flex items-center gap-4">
        <button
          onClick={() => navigate('/')}
          className="p-2 rounded-lg hover:bg-white/5 text-gray-400 hover:text-gray-200 transition-colors"
        >
          <ArrowLeft className="w-5 h-5" />
        </button>
        <div>
          <h2 className="text-2xl font-bold text-gray-100">Facilities</h2>
          <p className="text-sm text-gray-500 mt-1">
            {facilities?.length ?? 0} monitored facilities in the water supply network
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        {['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((level) => {
          const count = facilities?.filter((f) => f.criticality === level).length ?? 0;
          const colors = criticalityColors[level];
          return (
            <div key={level} className={`aegis-card p-4 border ${colors.border}`}>
              <p className="text-xs text-gray-500 uppercase tracking-wider">{level}</p>
              <p className={`text-2xl font-bold mt-1 ${colors.text}`}>{count}</p>
            </div>
          );
        })}
      </div>

      {/* Facilities Table */}
      <div className="aegis-card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--aegis-border)]">
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Facility
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Type
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Status
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Criticality
              </th>
              <th className="text-center text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Sensors
              </th>
              <th className="text-center text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Assets
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Location
              </th>
            </tr>
          </thead>
          <tbody>
            {facilities
              ?.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
              .map((f: Facility) => {
              const colors = criticalityColors[f.criticality] ?? criticalityColors.LOW;
              return (
                <tr
                  key={f.facilityId}
                    onClick={() => setModalEntity({ id: f.facilityId, name: f.name })}
                  className="border-b border-[var(--aegis-border)] hover:bg-white/5 cursor-pointer transition-colors"
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-lg bg-blue-500/10 flex items-center justify-center">
                        <Building2 className="w-4 h-4 text-blue-400" />
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-200">{f.name}</p>
                        <p className="text-xs text-gray-600 font-mono">{f.facilityId}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4 text-sm text-gray-400">
                    {typeLabels[f.type] ?? f.type}
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      {statusIcon(f.status)}
                      <span className="text-sm text-gray-300">{f.status}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <span
                      className={`inline-flex px-2 py-1 rounded text-xs font-medium ${colors.bg} ${colors.text}`}
                    >
                      {f.criticality}
                    </span>
                  </td>
                  <td className="px-5 py-4 text-center">
                    <div className="flex items-center justify-center gap-1 text-sm text-gray-400">
                      <Radio className="w-3.5 h-3.5 text-cyan-500" />
                      {f.sensorCount}
                    </div>
                  </td>
                  <td className="px-5 py-4 text-center">
                    <div className="flex items-center justify-center gap-1 text-sm text-gray-400">
                      <Package className="w-3.5 h-3.5 text-purple-500" />
                      {f.assetCount}
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-1 text-sm text-gray-500">
                      <MapPin className="w-3.5 h-3.5" />
                      <span className="font-mono text-xs">
                        {f.latitude.toFixed(4)}, {f.longitude.toFixed(4)}
                      </span>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Pagination
        currentPage={page}
        totalItems={facilities?.length ?? 0}
        pageSize={PAGE_SIZE}
        onPageChange={setPage}
      />

      {modalEntity && (
        <EntityActionModal
          entityId={modalEntity.id}
          entityType="facility"
          entityName={modalEntity.name}
          onClose={() => setModalEntity(null)}
        />
      )}
    </div>
  );
}
