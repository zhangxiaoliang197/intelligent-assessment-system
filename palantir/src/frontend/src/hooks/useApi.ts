import { useQuery } from '@tanstack/react-query';
import {
  dashboardApi,
  eventsApi,
  facilitiesApi,
  graphApi,
  personsApi,
  riskCasesApi,
  searchApi,
  timelineApi,
} from '../services/api';

export const useDashboardStats = () =>
  useQuery({ queryKey: ['dashboard-stats'], queryFn: dashboardApi.getStats });

export const useFacilities = () =>
  useQuery({ queryKey: ['facilities'], queryFn: facilitiesApi.getAll });

export const useEvents = (params?: {
  eventType?: string;
  minSeverity?: number;
  severity?: number;
  facilityId?: string;
}) =>
  useQuery({
    queryKey: ['events', params],
    queryFn: () => eventsApi.getAll(params),
  });

export const usePersons = () =>
  useQuery({ queryKey: ['persons'], queryFn: personsApi.getAll });

export const useRiskCases = () =>
  useQuery({ queryKey: ['risk-cases'], queryFn: riskCasesApi.getAll });

export const useCaseGraph = (caseId: string | null) =>
  useQuery({
    queryKey: ['case-graph', caseId],
    queryFn: () => riskCasesApi.getCaseGraph(caseId!),
    enabled: !!caseId,
  });

export const useGraphExplore = (nodeId: string | null, depth = 2) =>
  useQuery({
    queryKey: ['graph-explore', nodeId, depth],
    queryFn: () => graphApi.explore(nodeId!, depth),
    enabled: !!nodeId,
  });

export const useTimeline = (from: string, to: string, facilityId?: string) =>
  useQuery({
    queryKey: ['timeline', from, to, facilityId],
    queryFn: () => timelineApi.get(from, to, facilityId),
  });

export const useSearch = (query: string) =>
  useQuery({
    queryKey: ['search', query],
    queryFn: () => searchApi.search(query),
    enabled: query.length >= 2,
  });
