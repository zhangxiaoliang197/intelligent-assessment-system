/** Project compatibility fix for Konclude's legacy RDF PlainLiteral / UTF-8 output. */
import { DataFactory, Store } from 'n3';
import type { Quad } from '@rdfjs/types';
import type { InferenceDelta } from 'rdf-reasoner-konclude';
const INFERRED = DataFactory.namedNode('urn:vg:inferred');
const PLAIN = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#PlainLiteral';

export function normalizeKoncludeLiterals(store: Store, delta: InferenceDelta): InferenceDelta {
  // This WASM build sometimes sign-extends UTF-8 bytes into U+FFxx characters.
  // Restore ONLY exact encodings of literals present in the asserted input, so
  // legitimate full-width text and newly entailed lexical values are preserved.
  const known = new Map<string, string>();
  for (const q of store) {
    if (q.graph.equals(INFERRED) || q.object.termType !== 'Literal') continue;
    const value = q.object.value;
    const encoded = Array.from(new TextEncoder().encode(value), byte => String.fromCharCode(byte > 127 ? 0xff00 | byte : byte)).join('');
    if (encoded !== value) known.set(encoded, value);
  }
  const normalize = (quad: Quad): Quad => {
    const term = quad.object;
    if (term.termType !== 'Literal') return quad;
    let value = known.get(term.value) ?? term.value;
    let object = term;
    if (term.datatype.value === PLAIN) {
      const match = value.match(/^(.*)@([a-zA-Z]+(?:-[a-zA-Z0-9]+)*)?$/s);
      if (match) { value = match[1]; object = DataFactory.literal(value, match[2] || undefined); }
      else object = DataFactory.literal(value);
    } else if (value !== term.value) {
      object = DataFactory.literal(value, term.language || term.datatype);
    }
    return object.equals(term) ? quad : DataFactory.quad(quad.subject, quad.predicate, object, quad.graph);
  };
  const asserted = (q: Quad) => ['urn:vg:data', 'urn:vg:ontologies'].some(graph => store.countQuads(q.subject, q.predicate, q.object, DataFactory.namedNode(graph)) > 0);
  for (const quad of store.getQuads(null, null, null, INFERRED)) {
    const normalized = normalize(quad);
    if (!normalized.equals(quad) || asserted(normalized)) {
      store.removeQuad(quad);
      if (!asserted(normalized)) store.addQuad(normalized);
    }
  }
  const unique = new Store(delta.added.map(normalize).filter(q => store.has(q)));
  return { added: [...unique], removed: delta.removed };
}
