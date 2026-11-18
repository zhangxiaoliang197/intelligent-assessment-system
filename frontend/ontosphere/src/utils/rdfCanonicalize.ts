// src/utils/rdfCanonicalize.ts
//
// W3C RDF Dataset Canonicalization (RDFC-1.0) for Ontosphere.
//
// Implements the canonical N-Quads form and a content-addressable hash of an
// RDF dataset, per the W3C Recommendation "RDF Dataset Canonicalization"
// (RDFC-1.0, W3C Recommendation, 2024-05-21,
//  https://www.w3.org/TR/rdf-canon/). RDFC-1.0 is the standardisation of the
// URDNA2015 algorithm: it assigns deterministic labels to blank nodes via an
// iterative hashing of their position in the graph, so that two datasets that
// are ISOMORPHIC — identical up to blank-node relabelling and triple order —
// produce byte-for-byte identical canonical output (and therefore the same
// hash). This is the foundation for:
//   • reproducible benchmark snapshots (a graph has one stable identity),
//   • deterministic graph diffing (compare canonical forms, not raw dumps),
//   • standards-compliant dataset identity (content addressing).
//
// Engine: the mature, browser-compatible `rdf-canonize` package (Digital
// Bazaar). It implements RDFC-1.0 with SHA-256 via the Web Crypto API, runs in
// both browsers (Vite/ESM) and Node, and accepts RDF/JS quads directly — which
// is exactly the term shape N3.js produces, so no term conversion is required.
//
// Zero-backend: everything here runs client-side. No network, no server.

import * as canonize from 'rdf-canonize';
import type * as RDF from '@rdfjs/types';

/** The single canonicalization algorithm identifier mandated by the W3C Rec. */
const RDFC_ALGORITHM = 'RDFC-1.0';

/**
 * A minimal structural quad shape. N3.js `Quad` objects satisfy this (their
 * terms expose `termType`/`value`, and Literal terms carry `datatype`/
 * `language`), and so do any other RDF/JS-compliant quads, so callers can pass
 * `n3` quads straight through.
 */
export type CanonicalizableQuad = RDF.Quad | RDF.BaseQuad;

/** Hash algorithms exposed for content-addressing the canonical form. */
export type CanonicalHashAlgorithm = 'SHA-256' | 'SHA-384' | 'SHA-512';

/**
 * Produce the W3C RDFC-1.0 canonical N-Quads serialisation of a dataset.
 *
 * The output is deterministic: any two datasets that are isomorphic (equal up
 * to blank-node labelling and quad ordering) yield the identical string. The
 * default graph and any named graphs are all canonicalised together as a single
 * RDF dataset (graph terms are preserved in the canonical N-Quads).
 *
 * @param quads RDF/JS / N3 quads spanning the default and any named graphs.
 * @returns Canonical N-Quads (sorted, c14n-labelled blank nodes), UTF-8 text.
 */
export async function canonicalizeQuads(
  quads: Iterable<CanonicalizableQuad>,
): Promise<string> {
  const dataset = Array.from(quads);
  // rdf-canonize accepts an RDF/JS dataset (array of quads) directly.
  const canonical = (await canonize.canonize(dataset as unknown as RDF.Quad[], {
    algorithm: RDFC_ALGORITHM,
    format: 'application/n-quads',
  })) as string;
  return canonical;
}

/**
 * Compute a content hash (hex digest) of a dataset's RDFC-1.0 canonical form.
 *
 * Because the canonical form is invariant under blank-node relabelling and
 * triple reordering, this hash is a stable content-addressable identifier for
 * the graph: isomorphic graphs share a hash, non-isomorphic graphs (almost
 * always) differ. Uses Web Crypto (`crypto.subtle`), available in browsers and
 * Node ≥ 15.
 *
 * @param quads RDF/JS / N3 quads to canonicalise and hash.
 * @param algorithm Digest algorithm (default 'SHA-256').
 * @returns Lowercase hex digest of the canonical N-Quads bytes.
 */
export async function canonicalHash(
  quads: Iterable<CanonicalizableQuad>,
  algorithm: CanonicalHashAlgorithm = 'SHA-256',
): Promise<string> {
  const canonical = await canonicalizeQuads(quads);
  const bytes = new TextEncoder().encode(canonical);
  const digest = await getSubtleCrypto().digest(algorithm, bytes);
  return hex(new Uint8Array(digest));
}

/** Resolve the Web Crypto SubtleCrypto in both browser and Node contexts. */
function getSubtleCrypto(): SubtleCrypto {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (!c || !c.subtle) {
    throw new Error(
      'Web Crypto (crypto.subtle) is unavailable — required for canonical hashing.',
    );
  }
  return c.subtle;
}

/** Render a byte array as a lowercase hex string. */
function hex(bytes: Uint8Array): string {
  let out = '';
  for (let i = 0; i < bytes.length; i++) {
    out += bytes[i].toString(16).padStart(2, '0');
  }
  return out;
}
