// src/mcp/__tests__/metadataTools.test.ts
// @vitest-environment node
import { describe, it, expect, vi, beforeEach } from 'vitest';

// --- mocks must be declared before importing the module under test ---
vi.mock('@/utils/rdfManager', () => ({
  rdfManager: {
    sparqlQuery: vi.fn(),
    getGraphCounts: vi.fn(),
    getNamespaces: vi.fn(),
  },
}));

import { metadataTools } from '../tools/metadataTools';
import { rdfManager } from '@/utils/rdfManager';

const FOAF = 'http://xmlns.com/foaf/0.1/';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';

const tool = (name: string) => {
  const t = metadataTools.find(t => t.name === name);
  if (!t) throw new Error(`Tool not found: ${name}`);
  return t;
};

/**
 * Route the mocked sparqlQuery by inspecting the query text so each COUNT /
 * GROUP BY / scrape query returns a deterministic fixture result.
 */
function wireSparql() {
  (rdfManager.sparqlQuery as ReturnType<typeof vi.fn>).mockImplementation(
    async (sparql: string) => {
      const q = sparql.replace(/\s+/g, ' ');
      // class partition (GROUP BY ?class)
      if (q.includes('GROUP BY ?class')) {
        return {
          type: 'select',
          rows: [
            { class: FOAF + 'Person', n: '6' },
            { class: 'http://example.org/Project', n: '3' },
          ],
        };
      }
      // property partition (GROUP BY ?p)
      if (q.includes('GROUP BY ?p')) {
        return {
          type: 'select',
          rows: [
            { p: FOAF + 'knows', n: '12' },
            { p: 'http://example.org/worksOn', n: '8' },
          ],
        };
      }
      // owl:Ontology metadata scrape
      if (q.includes('owl#Ontology')) {
        return {
          type: 'select',
          rows: [
            { p: 'http://purl.org/dc/terms/title', o: 'Scraped Title' },
            { p: 'http://purl.org/dc/terms/description', o: 'Scraped Desc' },
          ],
        };
      }
      // scalar counts — distinguish by the COUNT expression. The projection
      // alias is `?cnt` (SPARQL 1.1 forbids reusing an in-scope var as an
      // alias), so the result rows are keyed by `cnt`.
      if (q.includes('COUNT(DISTINCT ?s)')) return { type: 'select', rows: [{ cnt: '10' }] };
      if (q.includes('COUNT(DISTINCT ?o)')) return { type: 'select', rows: [{ cnt: '25' }] };
      if (q.includes('COUNT(DISTINCT ?c)')) return { type: 'select', rows: [{ cnt: '3' }] };
      if (q.includes('COUNT(DISTINCT ?p)')) return { type: 'select', rows: [{ cnt: '5' }] };
      if (q.includes('COUNT(*)')) return { type: 'select', rows: [{ cnt: '42' }] };
      return { type: 'select', rows: [] };
    },
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  wireSparql();
  (rdfManager.getGraphCounts as ReturnType<typeof vi.fn>).mockResolvedValue({
    'urn:vg:data': 42,
    'urn:vg:inferred': 5,
  });
  (rdfManager.getNamespaces as ReturnType<typeof vi.fn>).mockReturnValue([
    { prefix: 'foaf', uri: FOAF },
    { prefix: 'ex', uri: 'http://example.org/' },
  ]);
});

describe('generateDatasetMetadata tool', () => {
  it('returns turtle + summary with expected counts', async () => {
    const result = (await tool('generateDatasetMetadata').handler({})) as any;
    expect(result.success).toBe(true);
    const { turtle, summary } = result.data;

    expect(typeof turtle).toBe('string');
    expect(turtle).toContain('a void:Dataset, dcat:Dataset');
    expect(turtle).toMatch(/void:triples\s+42\b/);
    expect(turtle).toContain('void:class <http://xmlns.com/foaf/0.1/Person> ; void:entities 6');

    expect(summary.triples).toBe(42);
    expect(summary.classes).toBe(3);
    expect(summary.properties).toBe(5);
    expect(summary.subjects).toBe(10);
    expect(summary.topClasses[0]).toEqual({ classIri: FOAF + 'Person', entities: 6 });
    expect(summary.topProperties[0]).toEqual({ propertyIri: FOAF + 'knows', triples: 12 });

    // L1: scalar COUNT queries must project to a distinct `?cnt` alias and must
    // never reuse an in-scope WHERE variable as the projection alias (SPARQL 1.1
    // forbids `... AS ?c) ... WHERE { ... ?c }`).
    const queries = (rdfManager.sparqlQuery as ReturnType<typeof vi.fn>).mock.calls.map(
      c => String(c[0]).replace(/\s+/g, ' '),
    );
    const scalarCountQueries = queries.filter(q => /\(COUNT\(/.test(q) && !/GROUP BY/.test(q));
    expect(scalarCountQueries.length).toBeGreaterThan(0);
    for (const q of scalarCountQueries) {
      expect(q).toContain('AS ?cnt)');
      // No scalar count reuses ?c as an alias (the original fragile form).
      expect(q).not.toMatch(/AS \?c\)/);
    }
  });

  it('uses scraped owl:Ontology metadata for title/description', async () => {
    const result = (await tool('generateDatasetMetadata').handler({})) as any;
    expect(result.success).toBe(true);
    expect(result.data.turtle).toContain('dcterms:title "Scraped Title"');
    expect(result.data.turtle).toContain('dcterms:description "Scraped Desc"');
  });

  it('includes inferred triples in the total when includeInferred=true', async () => {
    const result = (await tool('generateDatasetMetadata').handler({
      includeInferred: true,
    })) as any;
    expect(result.success).toBe(true);
    // 42 (data) + 5 (inferred) from getGraphCounts
    expect(result.data.summary.triples).toBe(47);
    expect(result.data.turtle).toMatch(/void:triples\s+47\b/);
  });

  it('exposes used vocabularies in the summary', async () => {
    const result = (await tool('generateDatasetMetadata').handler({})) as any;
    const foaf = result.data.summary.vocabularies.find((v: any) => v.uri === FOAF);
    expect(foaf).toBeDefined();
    expect(foaf.prefix).toBe('foaf');
  });

  it('returns an error result when gathering throws', async () => {
    (rdfManager.sparqlQuery as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('boom'),
    );
    (rdfManager.getGraphCounts as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('boom'),
    );
    const result = (await tool('generateDatasetMetadata').handler({})) as any;
    expect(result.success).toBe(false);
    expect(result.error).toContain('boom');
  });
});
