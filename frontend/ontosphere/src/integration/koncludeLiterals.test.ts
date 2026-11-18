import { describe, expect, it } from 'vitest';
import { DataFactory as f, Store } from 'n3';
import { normalizeKoncludeLiterals } from './koncludeLiterals';

describe('Konclude Chinese literal compatibility', () => {
  it('restores input UTF-8 values, normalizes PlainLiteral, and removes duplicate assertions', () => {
    const subject = f.namedNode('urn:equipment:R02'), predicate = f.namedNode('urn:status');
    const asserted = f.quad(subject, predicate, f.literal('就绪'), f.namedNode('urn:vg:data'));
    const broken = f.quad(subject, predicate, f.literal('￥ﾰﾱ￧ﾻﾪ', f.namedNode('http://www.w3.org/1999/02/22-rdf-syntax-ns#PlainLiteral')), f.namedNode('urn:vg:inferred'));
    const derived = f.quad(f.namedNode('urn:new'), predicate, broken.object, broken.graph);
    const untouched = f.quad(f.namedNode('urn:other'), predicate, f.literal('ＡＢＣ'), broken.graph);
    const store = new Store([asserted, broken, derived, untouched]);
    const delta = normalizeKoncludeLiterals(store, { added: [broken, derived, untouched], removed: [] });
    expect(delta.added).toHaveLength(2);
    expect(store.getQuads(derived.subject, predicate, null, broken.graph)[0].object.equals(f.literal('就绪'))).toBe(true);
    expect(store.has(untouched)).toBe(true);
    expect(store.getQuads(subject, predicate, null, broken.graph)).toHaveLength(0);
    expect(store.has(asserted)).toBe(true);
  });
});
