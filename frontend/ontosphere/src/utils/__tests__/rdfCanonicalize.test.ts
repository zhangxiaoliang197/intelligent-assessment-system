// src/utils/__tests__/rdfCanonicalize.test.ts
// @vitest-environment node
//
// Proves the W3C RDFC-1.0 canonicalization guarantees (W3C Recommendation,
// 2024-05-21, https://www.w3.org/TR/rdf-canon/): isomorphism invariance,
// round-trippable output, non-isomorphic discrimination, named-graph support,
// and determinism.
import { describe, it, expect } from 'vitest';
import { Parser, DataFactory } from 'n3';
import { canonicalizeQuads, canonicalHash } from '../rdfCanonicalize';

const { namedNode, literal, blankNode, quad, defaultGraph } = DataFactory;

function parseNQuads(text: string) {
  return new Parser({ format: 'application/n-quads' }).parse(text);
}

describe('rdfCanonicalize — W3C RDFC-1.0', () => {
  it('isomorphic graphs with DIFFERENT blank-node labels and DIFFERENT order → same canonical form + same hash', async () => {
    // Graph A: _:a knows _:b ; _:a name "Alice" ; _:b name "Bob"
    const graphA = parseNQuads(
      [
        '_:a <http://ex/knows> _:b .',
        '_:a <http://ex/name> "Alice" .',
        '_:b <http://ex/name> "Bob" .',
      ].join('\n') + '\n',
    );

    // Graph B: identical structure, different bnode labels (_:x/_:y) and reordered.
    const graphB = parseNQuads(
      [
        '_:y <http://ex/name> "Bob" .',
        '_:x <http://ex/name> "Alice" .',
        '_:x <http://ex/knows> _:y .',
      ].join('\n') + '\n',
    );

    const canonA = await canonicalizeQuads(graphA);
    const canonB = await canonicalizeQuads(graphB);
    expect(canonA).toBe(canonB);

    const hashA = await canonicalHash(graphA);
    const hashB = await canonicalHash(graphB);
    expect(hashA).toBe(hashB);
    // SHA-256 hex digest is 64 chars.
    expect(hashA).toMatch(/^[0-9a-f]{64}$/);
  });

  it('a graph with NO blank nodes → canonical form is stable and re-parseable (round-trip)', async () => {
    const quads = [
      quad(
        namedNode('http://ex/Alice'),
        namedNode('http://ex/knows'),
        namedNode('http://ex/Bob'),
        defaultGraph(),
      ),
      quad(
        namedNode('http://ex/Alice'),
        namedNode('http://ex/age'),
        literal('30', namedNode('http://www.w3.org/2001/XMLSchema#integer')),
        defaultGraph(),
      ),
    ];

    const canonical = await canonicalizeQuads(quads);
    // Re-parse the canonical N-Quads — it must be valid and recover both triples.
    const reparsed = parseNQuads(canonical);
    expect(reparsed).toHaveLength(2);

    // Canonicalizing the re-parsed quads yields the identical form (stable).
    const canonicalAgain = await canonicalizeQuads(reparsed);
    expect(canonicalAgain).toBe(canonical);
  });

  it('two NON-isomorphic graphs → different hashes', async () => {
    const graph1 = [
      quad(
        namedNode('http://ex/Alice'),
        namedNode('http://ex/knows'),
        namedNode('http://ex/Bob'),
        defaultGraph(),
      ),
    ];
    const graph2 = [
      quad(
        namedNode('http://ex/Alice'),
        namedNode('http://ex/knows'),
        namedNode('http://ex/Carol'), // different object
        defaultGraph(),
      ),
    ];

    const hash1 = await canonicalHash(graph1);
    const hash2 = await canonicalHash(graph2);
    expect(hash1).not.toBe(hash2);
  });

  it('named-graph dataset canonicalization preserves graph terms', async () => {
    const quads = [
      quad(
        namedNode('http://ex/Alice'),
        namedNode('http://ex/name'),
        literal('Alice'),
        namedNode('urn:vg:data'),
      ),
      quad(
        blankNode('r1'),
        namedNode('http://ex/onProperty'),
        namedNode('http://ex/hasPart'),
        namedNode('urn:vg:ontologies'),
      ),
    ];

    const canonical = await canonicalizeQuads(quads);
    // Each named graph IRI must appear in the canonical N-Quads (4th term).
    expect(canonical).toContain('<urn:vg:data>');
    expect(canonical).toContain('<urn:vg:ontologies>');

    // Isomorphic dataset with a relabelled blank node in the named graph → same hash.
    const quadsRelabelled = [
      quad(
        blankNode('restrictionX'),
        namedNode('http://ex/onProperty'),
        namedNode('http://ex/hasPart'),
        namedNode('urn:vg:ontologies'),
      ),
      quad(
        namedNode('http://ex/Alice'),
        namedNode('http://ex/name'),
        literal('Alice'),
        namedNode('urn:vg:data'),
      ),
    ];
    expect(await canonicalHash(quads)).toBe(await canonicalHash(quadsRelabelled));
  });

  it('determinism: same input canonicalized twice → identical output and hash', async () => {
    const quads = parseNQuads(
      [
        '_:b0 <http://ex/p> _:b1 .',
        '_:b1 <http://ex/q> _:b2 .',
        '_:b2 <http://ex/r> _:b0 .',
      ].join('\n') + '\n',
    );

    const c1 = await canonicalizeQuads(quads);
    const c2 = await canonicalizeQuads(quads);
    expect(c1).toBe(c2);

    const h1 = await canonicalHash(quads);
    const h2 = await canonicalHash(quads);
    expect(h1).toBe(h2);
  });

  it('empty dataset → stable empty canonical form and a constant hash', async () => {
    const c = await canonicalizeQuads([]);
    expect(c).toBe('');
    const h1 = await canonicalHash([]);
    const h2 = await canonicalHash([]);
    expect(h1).toBe(h2);
  });
});
