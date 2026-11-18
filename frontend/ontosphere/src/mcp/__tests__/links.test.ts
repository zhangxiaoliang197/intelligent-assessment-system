// src/mcp/__tests__/links.test.ts
// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Create mocks in vi.hoisted so their implementations survive vi.clearAllMocks().
const { mockAddTriple, mockRemoveTriple, mockFetchQuadsPage, mockGetWorkspaceRefs } = vi.hoisted(() => ({
  mockAddTriple: vi.fn().mockResolvedValue(undefined),
  mockRemoveTriple: vi.fn().mockResolvedValue(undefined),
  mockFetchQuadsPage: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  mockGetWorkspaceRefs: vi.fn().mockReturnValue({
    ctx: { model: { elements: [], links: [], requestLinks: vi.fn().mockResolvedValue(undefined) } },
    navigateToIri: vi.fn(),
  }),
}));

vi.mock('@/utils/rdfManager', () => ({
  rdfManager: {
    addTriple: mockAddTriple,
    removeTriple: mockRemoveTriple,
    fetchQuadsPage: mockFetchQuadsPage,
  },
}));

vi.mock('@/mcp/workspaceContext', () => ({
  getWorkspaceRefs: mockGetWorkspaceRefs,
}));

// No-op provenance recorder — recording is covered in provenance.test.ts.
vi.mock('@/mcp/provenance', () => ({
  getProvenanceRecorder: () => ({ recordEdit: vi.fn().mockResolvedValue(null) }),
}));

import { rdfManager } from '@/utils/rdfManager';
import { linkTools } from '../tools/links';

const addLink = linkTools.find((t) => t.name === 'addTriple')!;
const removeLink = linkTools.find((t) => t.name === 'removeLink')!;
const getLinks = linkTools.find((t) => t.name === 'getLinks')!;

beforeEach(() => {
  vi.clearAllMocks();
  mockAddTriple.mockResolvedValue(undefined);
  mockRemoveTriple.mockResolvedValue(undefined);
  mockFetchQuadsPage.mockResolvedValue({ items: [], total: 0 });
  mockGetWorkspaceRefs.mockReturnValue({
    ctx: { model: { elements: [], links: [], requestLinks: vi.fn().mockResolvedValue(undefined) } },
    navigateToIri: vi.fn(),
  });
});

describe('addTriple', () => {
  it('calls addTriple with correct args and returns success', async () => {
    const result = await addLink.handler({
      subjectIri: 'http://s',
      predicateIri: 'http://p',
      objectIri: 'http://o',
    });
    expect(mockAddTriple).toHaveBeenCalledWith('http://s', 'http://p', 'http://o');
    expect(result).toEqual({
      success: true,
      data: { added: { s: 'http://s', p: 'http://p', o: 'http://o' } },
    });
  });

  it('returns error when a param is missing', async () => {
    const result = await addLink.handler({ subjectIri: 'http://s', predicateIri: 'http://p' });
    expect(result).toEqual({
      success: false,
      error: 'subjectIri, predicateIri, and objectIri are all required. Call help({tool:"addTriple"}) for the full schema.',
    });
    expect(mockAddTriple).not.toHaveBeenCalled();
  });

  it('returns error when params are null/undefined', async () => {
    const result = await addLink.handler(null);
    expect(result).toEqual({
      success: false,
      error: 'subjectIri, predicateIri, and objectIri are all required. Call help({tool:"addTriple"}) for the full schema.',
    });
  });
});

describe('removeLink', () => {
  it('calls removeTriple with correct args (default data graph) and returns success', async () => {
    const result = await removeLink.handler({
      subjectIri: 'http://s',
      predicateIri: 'http://p',
      objectIri: 'http://o',
    });
    // BUG A: removeTriple is now called with the graph as a 4th arg (defaults to
    // urn:vg:data when graphName is omitted) and the IRI object passes through.
    expect(mockRemoveTriple).toHaveBeenCalledWith('http://s', 'http://p', 'http://o', 'urn:vg:data');
    expect(result).toEqual({
      success: true,
      data: { removed: { s: 'http://s', p: 'http://p', o: 'http://o' } },
    });
  });

  it('returns error when a param is missing', async () => {
    const result = await removeLink.handler({ subjectIri: 'http://s' });
    expect(result).toEqual({
      success: false,
      error: 'subjectIri, predicateIri, and objectIri are all required',
    });
    expect(mockRemoveTriple).not.toHaveBeenCalled();
  });

  // BUG A — an AGENT applying a suggestedRepair on an imported-ontology axiom must
  // hit urn:vg:ontologies, not the hardcoded urn:vg:data (which would no-op).
  it('BUG A: removeLink with graphName=urn:vg:ontologies removes the ontologies-graph triple', async () => {
    const result = await removeLink.handler({
      subjectIri: 'http://A',
      predicateIri: 'http://www.w3.org/2002/07/owl#disjointWith',
      objectIri: 'http://B',
      graphName: 'urn:vg:ontologies',
    });
    expect(result).toMatchObject({ success: true });
    // The 4th arg targets the EXACT graph the axiom physically lives in.
    expect(mockRemoveTriple).toHaveBeenCalledWith(
      'http://A',
      'http://www.w3.org/2002/07/owl#disjointWith',
      'http://B',
      'urn:vg:ontologies',
    );
  });

  it('BUG A: WITHOUT graphName the same call would target urn:vg:data (and miss the ontologies axiom)', async () => {
    await removeLink.handler({
      subjectIri: 'http://A',
      predicateIri: 'http://www.w3.org/2002/07/owl#disjointWith',
      objectIri: 'http://B',
    });
    // Default graph is urn:vg:data — a removal here would not touch the
    // ontologies-graph axiom, demonstrating why graphName is required.
    expect(mockRemoveTriple).toHaveBeenCalledWith(
      'http://A',
      'http://www.w3.org/2002/07/owl#disjointWith',
      'http://B',
      'urn:vg:data',
    );
    const [, , , graph] = mockRemoveTriple.mock.calls[0];
    expect(graph).not.toBe('urn:vg:ontologies');
  });

  it('BUG A: a typed-literal object is removed as the EXACT typed term (not string-coerced)', async () => {
    const XSD_INT = 'http://www.w3.org/2001/XMLSchema#integer';
    const result = await removeLink.handler({
      subjectIri: 'http://i',
      predicateIri: 'http://age',
      objectIri: '42',
      objectIsLiteral: true,
      objectDatatype: XSD_INT,
    });
    expect(result).toMatchObject({ success: true });
    const [s, p, o, graph] = mockRemoveTriple.mock.calls[0];
    expect(s).toBe('http://i');
    expect(p).toBe('http://age');
    expect(graph).toBe('urn:vg:data');
    // The object is a structured Literal term carrying the datatype, so the
    // worker matches "42"^^xsd:integer exactly — a same-lexical "42" string is
    // left untouched.
    expect(o).toEqual({ value: '42', type: 'literal', datatype: XSD_INT });
  });

  it('BUG A: a language-tagged literal object passes through its language tag', async () => {
    const result = await removeLink.handler({
      subjectIri: 'http://i',
      predicateIri: 'http://www.w3.org/2000/01/rdf-schema#label',
      objectIri: 'Pizza',
      objectLanguage: 'en',
    });
    expect(result).toMatchObject({ success: true });
    const [, , o] = mockRemoveTriple.mock.calls[0];
    expect(o).toEqual({ value: 'Pizza', type: 'literal', language: 'en' });
  });
});

describe('getLinks', () => {
  it('returns mapped quads from fetchQuadsPage', async () => {
    const mockItems = [
      { subject: 'http://s1', predicate: 'http://p1', object: 'http://o1' },
      { subject: 'http://s2', predicate: 'http://p2', object: 'http://o2' },
    ];
    mockFetchQuadsPage.mockResolvedValue({ items: mockItems, total: 2 });

    const result = await getLinks.handler({ subjectIri: 'http://s1', limit: 50 });
    expect(mockFetchQuadsPage).toHaveBeenCalledWith({
      graphName: 'urn:vg:data',
      filter: { subject: 'http://s1', predicate: undefined, object: undefined },
      limit: 50,
    });
    expect(result).toEqual({
      success: true,
      data: {
        links: [
          { subject: 'http://s1', predicate: 'http://p1', object: 'http://o1' },
          { subject: 'http://s2', predicate: 'http://p2', object: 'http://o2' },
        ],
      },
    });
  });

  it('defaults limit to 100 when not provided', async () => {
    mockFetchQuadsPage.mockResolvedValue({ items: [], total: 0 });
    await getLinks.handler({});
    expect(mockFetchQuadsPage).toHaveBeenCalledWith(
      expect.objectContaining({ limit: 100 })
    );
  });
});
