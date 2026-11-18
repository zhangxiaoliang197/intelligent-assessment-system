// src/mcp/__tests__/nodes.test.ts
// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Create mocks in vi.hoisted so their implementations survive vi.clearAllMocks().
// In Vitest 4.1+, mockReturnValue set *after* clearAllMocks is not reliably
// preserved across async gaps (e.g. the 400ms ADD_NODE_PIPELINE_DELAY in addNode).
// Hoisting the fns with an initial implementation avoids the issue.
const {
  mockAddTriple,
  mockRemoveAllQuadsForIri,
  mockFetchQuadsPage,
  mockApplyBatch,
  mockGetNamespaces,
  mockGetWorkspaceRefs,
  mockFocusElementOnCanvas,
  mockLookupAll,
  mockLookup,
  mockModel,
} = vi.hoisted(() => {
  const model = {
    elements: [] as any[],
    createElement: vi.fn(),
    removeElement: vi.fn(),
    requestElementData: vi.fn().mockResolvedValue(undefined),
    requestLinks: vi.fn().mockResolvedValue(undefined),
    history: { execute: vi.fn() },
  };
  const lookupAll = vi.fn();
  const lookup = vi.fn();
  return {
    mockAddTriple: vi.fn(),
    mockRemoveAllQuadsForIri: vi.fn().mockResolvedValue(undefined),
    mockFetchQuadsPage: vi.fn().mockResolvedValue({ items: [], total: 0, offset: 0, limit: 0 }),
    mockApplyBatch: vi.fn().mockResolvedValue(undefined),
    mockGetNamespaces: vi.fn().mockReturnValue([]),
    mockGetWorkspaceRefs: vi.fn().mockReturnValue({
      ctx: { model, view: {} },
      dataProvider: { lookupAll, lookup },
    }),
    mockFocusElementOnCanvas: vi.fn(),
    mockLookupAll: lookupAll,
    mockLookup: lookup,
    mockModel: model,
  };
});

vi.mock('@/utils/rdfManager', () => ({
  rdfManager: {
    addTriple: mockAddTriple,
    removeAllQuadsForIri: mockRemoveAllQuadsForIri,
    fetchQuadsPage: mockFetchQuadsPage,
    applyBatch: mockApplyBatch,
    getNamespaces: mockGetNamespaces,
  },
}));

vi.mock('@/mcp/workspaceContext', () => ({
  getWorkspaceRefs: mockGetWorkspaceRefs,
}));

// Provenance recording is exercised in provenance.test.ts; here a no-op recorder
// keeps the rdfManager mock assertions (applyBatch call counts) free of the
// extra urn:vg:provenance writes the real recorder would make.
vi.mock('@/mcp/provenance', () => ({
  getProvenanceRecorder: () => ({ recordEdit: vi.fn().mockResolvedValue(null) }),
}));

vi.mock('@/mcp/tools/layout', () => ({
  focusElementOnCanvas: mockFocusElementOnCanvas,
}));

vi.mock('@/stores/shaclResultStore', () => ({
  useShaclResultStore: {
    getState: vi.fn(() => ({ errors: [], warnings: [], shaclShapesLoaded: false })),
  },
}));

import { rdfManager } from '@/utils/rdfManager';
import { getWorkspaceRefs } from '@/mcp/workspaceContext';
import { nodeTools } from '../tools/nodes';

const addNode = nodeTools.find((t) => t.name === 'addNode')!;
const removeNode = nodeTools.find((t) => t.name === 'removeNode')!;
const getNodes = nodeTools.find((t) => t.name === 'getNodes')!;
const getNodeDetails = nodeTools.find((t) => t.name === 'getNodeDetails')!;
const updateNode = nodeTools.find((t) => t.name === 'updateNode')!;

const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';

function makeItem(id: string, label: string | undefined, types: string[]) {
  return {
    element: {
      id,
      types,
      properties: label !== undefined ? { [RDFS_LABEL]: [{ value: label }] } : {},
    },
    inLinks: [],
    outLinks: [],
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockModel.elements = [];
  mockModel.createElement.mockReset();
  mockModel.removeElement.mockReset();
  mockModel.requestElementData.mockResolvedValue(undefined);
  mockModel.requestLinks.mockResolvedValue(undefined);
  mockModel.history.execute.mockReset();
  // Restore implementations cleared by clearAllMocks for mocks that handlers await
  mockApplyBatch.mockResolvedValue(undefined);
  mockRemoveAllQuadsForIri.mockResolvedValue(undefined);
  mockFetchQuadsPage.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 0 });
  // Restore getWorkspaceRefs to its default refs (clearAllMocks resets call history only,
  // but the implementation set in vi.hoisted persists — restore explicit refs here for clarity)
  mockGetWorkspaceRefs.mockReturnValue({
    ctx: { model: mockModel, view: {} },
    dataProvider: { lookupAll: mockLookupAll, lookup: mockLookup },
  });
});

describe('addNode', () => {
  it('calls addTriple twice when iri, typeIri, and label are provided', async () => {
    const result = await addNode.handler({
      iri: 'http://example.org/foo',
      typeIri: 'http://www.w3.org/2002/07/owl#Class',
      label: 'Foo',
    });

    expect(mockApplyBatch).toHaveBeenCalledTimes(1);
    expect(mockApplyBatch).toHaveBeenCalledWith({
      adds: [
        { s: 'http://example.org/foo', p: 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type', o: 'http://www.w3.org/2002/07/owl#Class' },
        { s: 'http://example.org/foo', p: 'http://www.w3.org/2000/01/rdf-schema#label', o: 'Foo' },
      ],
    });
    expect(result).toEqual({ success: true, data: { iri: 'http://example.org/foo', types: ['http://www.w3.org/2002/07/owl#Class'] } });
  });

  it('returns error when iri is missing', async () => {
    const result = await addNode.handler({});
    expect(result).toEqual({ success: false, error: 'iri is required' });
    expect(mockAddTriple).not.toHaveBeenCalled();
  });
});

describe('removeNode', () => {
  it('calls removeAllQuadsForIri with the given iri', async () => {
    const result = await removeNode.handler({ iri: 'http://example.org/bar' });
    expect(mockRemoveAllQuadsForIri).toHaveBeenCalledWith('http://example.org/bar');
    expect(result).toEqual({ success: true, data: { removed: 'http://example.org/bar' } });
  });
});

describe('getNodes', () => {
  const sampleItems = [
    makeItem('http://example.org/a', 'Alpha', ['http://www.w3.org/2002/07/owl#Class']),
    makeItem('http://example.org/b', 'Beta', ['http://www.w3.org/2002/07/owl#NamedIndividual']),
    makeItem('http://example.org/c', 'Gamma', ['http://www.w3.org/2002/07/owl#Class']),
  ];

  it('returns all entities as JSON in content field', async () => {
    mockLookupAll.mockResolvedValue(sampleItems);
    const result = await getNodes.handler({}) as { success: true; data: { content: string } };
    expect(result.success).toBe(true);
    const entities = JSON.parse(result.data.content);
    expect(entities).toHaveLength(3);
    expect(entities[0]).toMatchObject({ iri: 'http://example.org/a', label: 'Alpha', types: ['http://www.w3.org/2002/07/owl#Class'] });
  });

  it('filters by labelContains (case-insensitive)', async () => {
    mockLookupAll.mockResolvedValue(sampleItems);
    const result = await getNodes.handler({ labelContains: 'alp' }) as { success: true; data: { content: string } };
    expect(result.success).toBe(true);
    const entities = JSON.parse(result.data.content);
    expect(entities).toHaveLength(1);
    expect(entities[0].iri).toBe('http://example.org/a');
  });

  it('filters by typeIri', async () => {
    mockLookupAll.mockResolvedValue(sampleItems);
    const result = await getNodes.handler({ typeIri: 'http://www.w3.org/2002/07/owl#NamedIndividual' }) as { success: true; data: { content: string } };
    expect(result.success).toBe(true);
    const entities = JSON.parse(result.data.content);
    expect(entities).toHaveLength(1);
    expect(entities[0].iri).toBe('http://example.org/b');
  });

  it('falls back to fuzzy lookup when labelContains finds nothing, sets fuzzyFallback:true', async () => {
    mockLookupAll.mockResolvedValue(sampleItems);
    mockLookup.mockResolvedValue([makeItem('http://example.org/a', 'Alpha', [])]);
    const result = await getNodes.handler({ labelContains: 'Alphx' }) as { success: true; data: { content: string; fuzzyFallback?: boolean } };
    expect(result.success).toBe(true);
    expect(result.data.fuzzyFallback).toBe(true);
    const entities = JSON.parse(result.data.content);
    expect(entities).toHaveLength(1);
    expect(entities[0].iri).toBe('http://example.org/a');
    expect(mockLookup).toHaveBeenCalledWith({ text: 'Alphx', limit: 1 });
  });

  it('does not set fuzzyFallback when exact labelContains match found', async () => {
    mockLookupAll.mockResolvedValue(sampleItems);
    const result = await getNodes.handler({ labelContains: 'Alpha' }) as { success: true; data: { content: string; fuzzyFallback?: boolean } };
    expect(result.success).toBe(true);
    expect(result.data.fuzzyFallback).toBeUndefined();
    expect(mockLookup).not.toHaveBeenCalled();
  });

  it('returns empty list with fuzzyFallback:true when fuzzy also finds nothing', async () => {
    mockLookupAll.mockResolvedValue(sampleItems);
    mockLookup.mockResolvedValue([]);
    const result = await getNodes.handler({ labelContains: 'zzz' }) as { success: true; data: { content: string; fuzzyFallback?: boolean } };
    expect(result.success).toBe(true);
    expect(result.data.fuzzyFallback).toBe(true);
    const entities = JSON.parse(result.data.content);
    expect(entities).toHaveLength(0);
  });

  it('does not run fuzzy fallback when no labelContains provided', async () => {
    mockLookupAll.mockResolvedValue([]);
    const result = await getNodes.handler({}) as { success: true; data: { content: string; fuzzyFallback?: boolean } };
    expect(result.success).toBe(true);
    expect(result.data.fuzzyFallback).toBeUndefined();
    expect(mockLookup).not.toHaveBeenCalled();
  });
});

describe('getNodeDetails', () => {
  it('returns label, types, and all properties from asserted graph', async () => {
    mockFetchQuadsPage
      .mockResolvedValueOnce({
        items: [
          { subject: 'http://example.org/Alice', predicate: RDF_TYPE, object: 'http://example.org/Person', graph: 'urn:vg:data' },
          { subject: 'http://example.org/Alice', predicate: RDFS_LABEL, object: 'Alice', graph: 'urn:vg:data' },
          { subject: 'http://example.org/Alice', predicate: 'http://example.org/age', object: '30', graph: 'urn:vg:data' },
        ],
        total: 3,
      })
      .mockResolvedValueOnce({ items: [], total: 0 });

    const result = await getNodeDetails.handler({ iri: 'http://example.org/Alice' });
    expect(result).toEqual({
      success: true,
      data: {
        iri: 'ex:Alice',
        label: 'Alice',
        types: ['ex:Person'],
        properties: [
          { predicate: 'rdf:type', object: 'ex:Person', objectType: 'iri' },
          { predicate: 'rdfs:label', object: 'Alice', objectType: 'literal' },
          { predicate: 'ex:age', object: '30', objectType: 'literal' },
        ],
        shaclMessages: [],
      },
    });
  });

  it('returns empty properties array for node with no triples', async () => {
    mockFetchQuadsPage.mockResolvedValue({ items: [], total: 0 });
    const result = await getNodeDetails.handler({ iri: 'http://example.org/Empty' });
    expect(result).toEqual({
      success: true,
      data: { iri: 'ex:Empty', label: '', types: [], properties: [], shaclMessages: [] },
    });
  });

  it('returns error when iri is missing', async () => {
    const result = await getNodeDetails.handler({});
    expect(result).toEqual({ success: false, error: 'iri is required' });
  });

  it('expands prefixed IRI before querying', async () => {
    mockFetchQuadsPage.mockResolvedValue({ items: [], total: 0 });
    await getNodeDetails.handler({ iri: 'ex:Alice' });
    expect(mockFetchQuadsPage).toHaveBeenCalledWith(
      expect.objectContaining({ filter: { subject: 'http://example.org/Alice' } })
    );
  });

  it('classifies blank-node objects correctly', async () => {
    mockFetchQuadsPage.mockResolvedValue({
      items: [
        { subject: 'http://example.org/X', predicate: 'http://example.org/p', object: '_:b0', graph: 'urn:vg:data' },
      ],
      total: 1,
    });
    const result = await getNodeDetails.handler({ iri: 'http://example.org/X' }) as any;
    expect(result.data.properties[0].objectType).toBe('bnode');
  });
});

describe('updateNode', () => {
  it('updates label via applyBatch and refreshes canvas', async () => {
    const result = await updateNode.handler({
      iri: 'http://example.org/Alice',
      label: 'Alicia',
    });

    expect(mockApplyBatch).toHaveBeenCalledWith(
      {
        removes: [{ s: 'http://example.org/Alice', p: RDFS_LABEL }],
        adds: [{ s: 'http://example.org/Alice', p: RDFS_LABEL, o: 'Alicia' }],
      },
      'urn:vg:data'
    );
    expect(mockModel.requestElementData).toHaveBeenCalledWith(['http://example.org/Alice']);
    expect(result).toEqual({
      success: true,
      data: { updated: 'http://example.org/Alice', changed: [RDFS_LABEL] },
    });
  });

  it('replaces typeIri', async () => {
    await updateNode.handler({ iri: 'http://example.org/Bob', typeIri: 'http://example.org/Director' });
    expect(mockApplyBatch).toHaveBeenCalledWith(
      {
        removes: [{ s: 'http://example.org/Bob', p: RDF_TYPE }],
        adds: [{ s: 'http://example.org/Bob', p: RDF_TYPE, o: 'http://example.org/Director' }],
      },
      'urn:vg:data'
    );
  });

  it('handles setProperties and removeProperties', async () => {
    await updateNode.handler({
      iri: 'http://example.org/Carol',
      setProperties: [{ predicateIri: 'http://example.org/age', value: '35' }],
      removeProperties: [{ predicateIri: 'http://example.org/retired' }],
    });

    const call = mockApplyBatch.mock.calls[0][0];
    expect(call.removes).toContainEqual({ s: 'http://example.org/Carol', p: 'http://example.org/age' });
    expect(call.removes).toContainEqual({ s: 'http://example.org/Carol', p: 'http://example.org/retired' });
    expect(call.adds).toContainEqual({ s: 'http://example.org/Carol', p: 'http://example.org/age', o: '35' });
    expect(call.adds).not.toContainEqual(expect.objectContaining({ p: 'http://example.org/retired' }));
  });

  it('returns error when no mutation fields are provided', async () => {
    const result = await updateNode.handler({ iri: 'http://example.org/Alice' });
    expect(result).toEqual({
      success: false,
      error: expect.stringContaining('at least one field'),
    });
    expect(mockApplyBatch).not.toHaveBeenCalled();
  });

  it('returns error when iri is missing', async () => {
    const result = await updateNode.handler({});
    expect(result).toEqual({ success: false, error: 'iri is required' });
  });

  it('returns error for unknown prefix in predicateIri', async () => {
    const result = await updateNode.handler({
      iri: 'http://example.org/Alice',
      setProperties: [{ predicateIri: 'unknownns:prop', value: 'x' }],
    });
    expect(result.success).toBe(false);
    expect((result as any).error).toContain('Unknown prefix');
  });
});
