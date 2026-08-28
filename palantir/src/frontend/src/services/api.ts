import axios from 'axios';
import type {
  DashboardStats,
  Event,
  Facility,
  GraphData,
  LinkAnalysisResult,
  Person,
  RiskCase,
  SearchResult,
  TimelineEvent,
  AgentProfile,
  RiskPropagationRequest,
  RiskPropagationResult,
  CommandCenterStep,
} from '../types';

const api = axios.create({
  baseURL: '/api',
});

export const dashboardApi = {
  getStats: () => api.get<DashboardStats>('/dashboard/stats').then((r) => r.data),
};

export const facilitiesApi = {
  getAll: () => api.get<Facility[]>('/facilities').then((r) => r.data),
};

export const eventsApi = {
  getAll: (params?: {
    eventType?: string;
    minSeverity?: number;
    severity?: number;
    facilityId?: string;
  }) => api.get<Event[]>('/events', { params }).then((r) => r.data),
};

export const personsApi = {
  getAll: () => api.get<Person[]>('/persons').then((r) => r.data),
};

export const riskCasesApi = {
  getAll: () => api.get<RiskCase[]>('/riskcases').then((r) => r.data),
  getCaseGraph: (caseId: string) =>
    api.get<GraphData>(`/riskcases/${caseId}/graph`).then((r) => r.data),
};

export const graphApi = {
  explore: (nodeId: string, depth = 2) =>
    api.get<GraphData>(`/graph/explore/${nodeId}`, { params: { depth } }).then((r) => r.data),

  analyzeLinks: (nodeIds: string[], maxDepth = 6) =>
    api.post<LinkAnalysisResult>('/graph/link-analysis', { nodeIds, maxDepth }).then((r) => r.data),
};

export const timelineApi = {
  get: (from: string, to: string, facilityId?: string) =>
    api
      .get<TimelineEvent[]>('/timeline', { params: { from, to, facilityId } })
      .then((r) => r.data),
};

export const searchApi = {
  search: (q: string, page = 1) =>
    api.get<SearchResult>('/search', { params: { q, page } }).then((r) => r.data),
};

export const seedApi = {
  seed: () => api.post('/seed').then((r) => r.data),
};

// ── AI Agent Investigation (Server-Sent Events) ──

export interface AgentStep {
  type: 'thought' | 'action' | 'observation' | 'answer';
  content: string;
}

export const aiApi = {
  /**
   * Stream an AI agent investigation of a risk case via SSE.
   * The agent sends structured steps: thought, action, observation, answer.
   */
  investigateStream: (
    caseId: string,
    onStep: (step: AgentStep) => void,
    onDone: () => void,
    onError: (e: string) => void,
  ) => {
    const abortController = new AbortController();
    fetch(`/api/ai/investigate/${caseId}`, {
      method: 'POST',
      signal: abortController.signal,
    })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          onDone();
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            try {
              const step = JSON.parse(data) as AgentStep;
              if (step.content?.startsWith('[ERROR]')) { onError(step.content); onDone(); return; }
              onStep(step);
            } catch {
              // Legacy fallback: treat as answer text
              onStep({ type: 'answer', content: data.replace(/\\n/g, '\n') });
            }
          }
        }
        onDone();
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err));
        onDone();
      });

    return abortController;
  },

  /**
   * Stream a follow-up chat message — also agent-powered.
   */
  chatStream: (
    caseId: string,
    message: string,
    history: string,
    onStep: (step: AgentStep) => void,
    onDone: () => void,
    onError: (e: string) => void,
  ) => {
    const abortController = new AbortController();
    fetch(`/api/ai/chat/${caseId}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message, history }),
      signal: abortController.signal,
    })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          onDone();
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });

          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            try {
              const step = JSON.parse(data) as AgentStep;
              onStep(step);
            } catch {
              onStep({ type: 'answer', content: data.replace(/\\n/g, '\n') });
            }
          }
        }
        onDone();
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err));
        onDone();
      });

    return abortController;
  },

  /**
   * Stream an AI agent investigation of any entity (facility, person, event) via SSE.
   */
  investigateEntityStream: (
    entityType: string,
    entityId: string,
    timeRange: string,
    onStep: (step: AgentStep) => void,
    onDone: () => void,
    onError: (e: string) => void,
  ) => {
    const abortController = new AbortController();
    fetch('/api/ai/investigate-entity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entityType, entityId, timeRange }),
      signal: abortController.signal,
    })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          onDone();
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            try {
              const step = JSON.parse(data) as AgentStep;
              if (step.content?.startsWith('[ERROR]')) { onError(step.content); onDone(); return; }
              onStep(step);
            } catch {
              onStep({ type: 'answer', content: data.replace(/\\n/g, '\n') });
            }
          }
        }
        onDone();
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err));
        onDone();
      });
    return abortController;
  },

  /**
   * Stream agentic search – enriches Elasticsearch results with AI analysis.
   */
  agenticSearchStream: (
    query: string,
    onStep: (step: AgentStep) => void,
    onDone: () => void,
    onError: (e: string) => void,
  ) => {
    const abortController = new AbortController();
    fetch('/api/ai/agentic-search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query }),
      signal: abortController.signal,
    })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          onDone();
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            try {
              const step = JSON.parse(data) as AgentStep;
              if (step.content?.startsWith('[ERROR]')) { onError(step.content); onDone(); return; }
              onStep(step);
            } catch {
              onStep({ type: 'answer', content: data.replace(/\\n/g, '\n') });
            }
          }
        }
        onDone();
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err));
        onDone();
      });
    return abortController;
  },

  /**
   * Stream a follow-up chat for entity investigations.
   */
  chatEntityStream: (
    entityType: string,
    entityId: string,
    timeRange: string,
    message: string,
    history: string,
    onStep: (step: AgentStep) => void,
    onDone: () => void,
    onError: (e: string) => void,
  ) => {
    const abortController = new AbortController();
    fetch('/api/ai/chat-entity', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ entityType, entityId, timeRange, message, history }),
      signal: abortController.signal,
    })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          onDone();
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            try {
              const step = JSON.parse(data) as AgentStep;
              onStep(step);
            } catch {
              onStep({ type: 'answer', content: data.replace(/\\n/g, '\n') });
            }
          }
        }
        onDone();
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err));
        onDone();
      });
    return abortController;
  },
};

// ── Command Center (Multi-Agent NL→Cypher) ──

export const commandCenterApi = {
  getAgents: () =>
    api.get<AgentProfile[]>('/commandcenter/agents').then((r) => r.data),

  queryStream: (
    agentId: string,
    query: string,
    history: string | null,
    onStep: (step: CommandCenterStep) => void,
    onDone: () => void,
    onError: (e: string) => void,
  ) => {
    const abortController = new AbortController();
    fetch('/api/commandcenter/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ agentId, query, history }),
      signal: abortController.signal,
    })
      .then(async (resp) => {
        if (!resp.ok || !resp.body) {
          onError(`HTTP ${resp.status}`);
          onDone();
          return;
        }
        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split('\n');
          buffer = lines.pop() || '';

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            try {
              const step = JSON.parse(data) as CommandCenterStep;
              if (step.content?.startsWith('[ERROR]')) { onError(step.content); onDone(); return; }
              onStep(step);
            } catch {
              onStep({ type: 'answer', content: data.replace(/\\n/g, '\n') });
            }
          }
        }
        onDone();
      })
      .catch((err) => {
        if (err.name !== 'AbortError') onError(String(err));
        onDone();
      });
    return abortController;
  },
};

// ── Risk Propagation ──

export const riskPropagationApi = {
  propagate: (request: RiskPropagationRequest) =>
    api.post<RiskPropagationResult>('/riskpropagation/propagate', request).then((r) => r.data),
};
