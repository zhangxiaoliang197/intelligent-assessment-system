import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { translateUi } from './translations-zh';

describe('Chinese ontology interface', () => {
  it('covers every non-technical string in the pinned native editor language bundle', () => {
    const source = JSON.parse(readFileSync(new URL('../../node_modules/@reactodia/workspace/i18n/translations/en.reactodia-translation.json', import.meta.url), 'utf8'));
    const missing = Object.values(source).filter(v => typeof v === 'object').flatMap(v => Object.values(v as object))
      .filter((v: unknown) => typeof v === 'string' && /[A-Za-z]{3}/.test(v.replace(/\{\{.*?\}\}/g, '')) && translateUi(v) === v);
    expect(missing).toEqual([]);
  });
  it('preserves machine-readable queries, resources and formats', () => {
    for (const value of ['SELECT ?s WHERE { ?s ?p ?o }', 'https://example.org/Save', 'urn:vg:inferred', 'owl:Class', '@prefix ql: <https://example.org/qinglan/> .']) expect(translateUi(value)).toBe(value);
    expect(translateUi('Showing page 2 of 8 — 153 triples')).toBe('第 2 页，共 8 页，153 条三元组');
    expect(translateUi('Run reasoning')).toBe('执行本体推理');
  });
});
