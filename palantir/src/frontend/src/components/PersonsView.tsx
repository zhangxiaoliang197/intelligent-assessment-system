import { useNavigate } from 'react-router-dom';
import { useState } from 'react';
import {
  Users,
  ArrowLeft,
  Shield,
  Briefcase,
  Building,
  UserCheck,
  HardHat,
} from 'lucide-react';
import { usePersons } from '../hooks/useApi';
import type { Person } from '../types';
import EntityActionModal from './EntityActionModal';
import Pagination from './Pagination';

const clearanceColors: Record<string, { bg: string; text: string }> = {
  L1: { bg: 'bg-slate-500/10', text: 'text-slate-400' },
  L2: { bg: 'bg-blue-500/10', text: 'text-blue-400' },
  L3: { bg: 'bg-purple-500/10', text: 'text-purple-400' },
  L4: { bg: 'bg-orange-500/10', text: 'text-orange-400' },
  L5: { bg: 'bg-red-500/10', text: 'text-red-400' },
};

const personTypeIcon = (personType: string) => {
  return personType === 'Contractor' ? (
    <HardHat className="w-4 h-4 text-orange-400" />
  ) : (
    <UserCheck className="w-4 h-4 text-cyan-400" />
  );
};

export default function PersonsView() {
  const { data: persons, isLoading, isError } = usePersons();
  const navigate = useNavigate();
  const [modalEntity, setModalEntity] = useState<{ id: string; name: string } | null>(null);
  const [page, setPage] = useState(1);
  const PAGE_SIZE = 10;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-pulse text-cyan-400">Loading persons...</div>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-red-400">Failed to load persons</div>
      </div>
    );
  }

  const employees = persons?.filter((p) => p.personType === 'Employee') ?? [];
  const contractors = persons?.filter((p) => p.personType === 'Contractor') ?? [];

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
          <h2 className="text-2xl font-bold text-gray-100">Persons Tracked</h2>
          <p className="text-sm text-gray-500 mt-1">
            {persons?.length ?? 0} individuals linked to the water supply network
          </p>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="aegis-card p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <Users className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Total</p>
              <p className="text-2xl font-bold text-gray-100">{persons?.length ?? 0}</p>
            </div>
          </div>
        </div>
        <div className="aegis-card p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-cyan-500/10 flex items-center justify-center">
              <UserCheck className="w-5 h-5 text-cyan-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Employees</p>
              <p className="text-2xl font-bold text-cyan-400">{employees.length}</p>
            </div>
          </div>
        </div>
        <div className="aegis-card p-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-lg bg-orange-500/10 flex items-center justify-center">
              <HardHat className="w-5 h-5 text-orange-400" />
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase tracking-wider">Contractors</p>
              <p className="text-2xl font-bold text-orange-400">{contractors.length}</p>
            </div>
          </div>
        </div>
      </div>

      {/* Persons Table */}
      <div className="aegis-card overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--aegis-border)]">
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Person
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Type
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Role
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Clearance
              </th>
              <th className="text-left text-xs text-gray-500 uppercase tracking-wider px-5 py-3">
                Organization
              </th>
            </tr>
          </thead>
          <tbody>
            {persons
              ?.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE)
              .map((p: Person) => {
              const clr = clearanceColors[p.clearance] ?? clearanceColors.L1;
              return (
                <tr
                  key={p.personId}
                    onClick={() => setModalEntity({ id: p.personId, name: p.name })}
                  className="border-b border-[var(--aegis-border)] hover:bg-white/5 cursor-pointer transition-colors"
                >
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-3">
                      <div className="w-9 h-9 rounded-full bg-purple-500/10 flex items-center justify-center">
                        <span className="text-sm font-bold text-purple-400">
                          {p.name
                            .split(' ')
                            .map((w) => w[0])
                            .join('')
                            .slice(0, 2)}
                        </span>
                      </div>
                      <div>
                        <p className="text-sm font-medium text-gray-200">{p.name}</p>
                        <p className="text-xs text-gray-600 font-mono">{p.personId}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      {personTypeIcon(p.personType)}
                      <span className="text-sm text-gray-300">{p.personType}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <div className="flex items-center gap-2">
                      <Briefcase className="w-3.5 h-3.5 text-gray-500" />
                      <span className="text-sm text-gray-400">{p.role}</span>
                    </div>
                  </td>
                  <td className="px-5 py-4">
                    <span
                      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium ${clr.bg} ${clr.text}`}
                    >
                      <Shield className="w-3 h-3" />
                      {p.clearance}
                    </span>
                  </td>
                  <td className="px-5 py-4">
                    {p.organizationName ? (
                      <div className="flex items-center gap-2">
                        <Building className="w-3.5 h-3.5 text-gray-500" />
                        <span className="text-sm text-gray-400">{p.organizationName}</span>
                      </div>
                    ) : (
                      <span className="text-sm text-gray-600 italic">—</span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Pagination
        currentPage={page}
        totalItems={persons?.length ?? 0}
        pageSize={PAGE_SIZE}
        onPageChange={setPage}
      />

      {modalEntity && (
        <EntityActionModal
          entityId={modalEntity.id}
          entityType="person"
          entityName={modalEntity.name}
          onClose={() => setModalEntity(null)}
        />
      )}
    </div>
  );
}
