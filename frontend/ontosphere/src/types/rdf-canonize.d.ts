// Ambient typings for the `rdf-canonize` package (Digital Bazaar), which ships
// no bundled TypeScript declarations. Covers the subset of the v5 API used by
// Ontosphere: the async `canonize` entry point implementing W3C RDFC-1.0.
declare module 'rdf-canonize' {
  import type * as RDF from '@rdfjs/types';

  export interface CanonizeOptions {
    /** Canonicalization algorithm. Use 'RDFC-1.0' (W3C Rec) — 'URDNA2015' is the legacy alias. */
    algorithm: 'RDFC-1.0' | 'URDNA2015' | 'URGNA2012';
    /** Output serialisation. 'application/n-quads' returns the canonical N-Quads string. */
    format?: 'application/n-quads';
    /** Optional cap on permutations explored for deeply nested blank nodes. */
    maxDeepIterations?: number;
    /** Optional digest used internally (defaults to SHA-256 for RDFC-1.0). */
    messageDigestAlgorithm?: string;
  }

  /**
   * Canonicalize an RDF dataset (array of RDF/JS quads) per the chosen algorithm.
   * With `format: 'application/n-quads'` resolves to the canonical N-Quads string.
   */
  export function canonize(
    dataset: RDF.Quad[] | RDF.BaseQuad[],
    options: CanonizeOptions,
  ): Promise<string>;

  export const NQuads: unknown;
  export const IdentifierIssuer: unknown;
}
