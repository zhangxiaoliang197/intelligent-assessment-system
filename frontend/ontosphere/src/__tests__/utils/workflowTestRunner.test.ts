import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockWorkerCall = vi.fn();

vi.mock('../../stores/ontologyStore', () => ({
  useOntologyStore: {
    getState: () => ({
      getRdfManager: () => ({ worker: { call: mockWorkerCall } }),
    }),
  },
}));

import { validateWorkflowExecution } from '../../utils/workflowTestRunner';

describe('workflowTestRunner', () => {
  beforeEach(() => {
    mockWorkerCall.mockReset();
  });

  it('returns valid for activity with code URL', async () => {
    const activityIri = 'urn:test:act1';
    const codeIri = 'urn:test:code1';

    mockWorkerCall.mockImplementation(async (method: string, params: any) => {
      if (method !== 'getQuads') return [];
      const { subject, predicate, graphName } = params;

      // Activity type check
      if (subject === activityIri && predicate?.includes('type') && graphName === 'urn:vg:data') {
        return [{ object: { value: 'http://www.w3.org/ns/prov#Activity' } }];
      }
      // prov:used
      if (subject === activityIri && predicate?.includes('used') && graphName === 'urn:vg:data') {
        return [{ object: { value: codeIri } }];
      }
      // prov:atLocation in workflows graph
      if (subject === codeIri && predicate?.includes('atLocation') && graphName === 'urn:vg:workflows') {
        return [{ object: { value: 'https://example.com/code.py' } }];
      }
      // rdf:type of code resource
      if (subject === codeIri && predicate?.includes('type') && graphName === 'urn:vg:workflows') {
        return [{ object: { value: 'https://schema.org/SoftwareSourceCode' } }];
      }
      // correspondsToStep — not present
      if (subject === activityIri && predicate?.includes('correspondsToStep')) {
        return [];
      }
      return [];
    });

    // Mock fetch for HEAD request
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200 });

    const result = await validateWorkflowExecution(activityIri);
    expect(result.valid).toBe(true);
    expect(result.errors).toEqual([]);
    expect(result.checks.find(c => c.name === 'code-url-found')?.passed).toBe(true);
    expect(result.checks.find(c => c.name === 'code-url-reachable')?.passed).toBe(true);
  });

  it('returns error for missing code URL', async () => {
    const activityIri = 'urn:test:act2';

    mockWorkerCall.mockImplementation(async (method: string, params: any) => {
      if (method !== 'getQuads') return [];
      const { subject, predicate, graphName } = params;

      if (subject === activityIri && predicate?.includes('type') && graphName === 'urn:vg:data') {
        return [{ object: { value: 'http://www.w3.org/ns/prov#Activity' } }];
      }
      // prov:used returns a resource but with no atLocation
      if (subject === activityIri && predicate?.includes('used') && graphName === 'urn:vg:data') {
        return [{ object: { value: 'urn:test:mystery' } }];
      }
      return [];
    });

    const result = await validateWorkflowExecution(activityIri);
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('No code URL found — ensure catalog is loaded');
  });

  it('returns error for activity with no prov:used links', async () => {
    const activityIri = 'urn:test:empty';

    mockWorkerCall.mockImplementation(async (method: string, params: any) => {
      if (method !== 'getQuads') return [];
      const { subject, predicate, graphName } = params;

      if (subject === activityIri && predicate?.includes('type') && graphName === 'urn:vg:data') {
        return [{ object: { value: 'http://www.w3.org/ns/prov#Activity' } }];
      }
      return [];
    });

    const result = await validateWorkflowExecution(activityIri);
    expect(result.valid).toBe(false);
    expect(result.errors).toContain('No prov:used resources found');
    expect(result.errors).toContain('No code URL found — ensure catalog is loaded');
  });

  it('returns error for unreachable code URL', async () => {
    const activityIri = 'urn:test:act3';
    const codeIri = 'urn:test:code3';

    mockWorkerCall.mockImplementation(async (method: string, params: any) => {
      if (method !== 'getQuads') return [];
      const { subject, predicate, graphName } = params;

      if (subject === activityIri && predicate?.includes('type') && graphName === 'urn:vg:data') {
        return [{ object: { value: 'http://www.w3.org/ns/prov#Activity' } }];
      }
      if (subject === activityIri && predicate?.includes('used') && graphName === 'urn:vg:data') {
        return [{ object: { value: codeIri } }];
      }
      if (subject === codeIri && predicate?.includes('atLocation') && graphName === 'urn:vg:workflows') {
        return [{ object: { value: 'https://example.com/missing.py' } }];
      }
      if (subject === codeIri && predicate?.includes('type') && graphName === 'urn:vg:workflows') {
        return [{ object: { value: 'https://schema.org/SoftwareSourceCode' } }];
      }
      return [];
    });

    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 404 });

    const result = await validateWorkflowExecution(activityIri);
    expect(result.valid).toBe(false);
    expect(result.checks.find(c => c.name === 'code-url-reachable')?.passed).toBe(false);
  });
});
