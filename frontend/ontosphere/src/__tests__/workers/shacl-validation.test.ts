// @vitest-environment node
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const SH = 'http://www.w3.org/ns/shacl#';
const OWL_CLASS = 'http://www.w3.org/2002/07/owl#Class';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label';
const RDFS_COMMENT = 'http://www.w3.org/2000/01/rdf-schema#comment';
const EX = 'http://example.org/';

interface ShaclViolation {
  focusNode: string | null;
  path: string | null;
  severity: string | null;
  message: string | null;
  sourceShape: string | null;
  constraint: string | null;
  source: 'shacl';
}

async function loadEngine() {
  const { Validator } = await import('shacl-engine') as any;
  const { targetResolvers } = await import('shacl-engine/sparql.js') as any;
  const dataModelMod = await import('@rdfjs/data-model') as any;
  const datasetMod = await import('@rdfjs/dataset') as any;
  const N3 = await import('n3');

  const factory = dataModelMod.default ?? dataModelMod;
  const dataset = datasetMod.default?.dataset ?? datasetMod.dataset;

  return { Validator, targetResolvers, factory, dataset, N3 };
}

function parseTurtle(content: string, N3: any, factory: any, dataset: () => any) {
  const parser = new N3.Parser();
  const quads = parser.parse(content);
  const ds = dataset();
  for (const q of quads) {
    const s = q.subject.termType === 'BlankNode' ? factory.blankNode(q.subject.value) : factory.namedNode(q.subject.value);
    const p = factory.namedNode(q.predicate.value);
    let o;
    if (q.object.termType === 'Literal') {
      o = factory.literal(q.object.value, q.object.language || (q.object.datatype ? factory.namedNode(q.object.datatype.value) : undefined));
    } else if (q.object.termType === 'BlankNode') {
      o = factory.blankNode(q.object.value);
    } else {
      o = factory.namedNode(q.object.value);
    }
    ds.add(factory.quad(s, p, o));
  }
  return ds;
}

function mapResults(report: any, shapesDs: any): ShaclViolation[] {
  const SH_PROPERTY = SH + 'property';
  const propShapeToNodeShape = new Map<string, string>();
  for (const q of [...shapesDs] as any[]) {
    if (q.predicate.value === SH_PROPERTY && q.subject.termType === 'NamedNode') {
      propShapeToNodeShape.set(q.object.value, q.subject.value);
    }
  }
  return (report.results ?? []).map((r: any) => {
    let shapeVal = r.shape?.ptr?.term?.value ?? null;
    if (shapeVal && propShapeToNodeShape.has(shapeVal)) {
      shapeVal = propShapeToNodeShape.get(shapeVal)!;
    }
    const pathVal = Array.isArray(r.path) ? (r.path[0]?.predicates?.[0]?.value ?? null) : (r.path?.value ?? null);
    const msgVal = Array.isArray(r.message)
      ? r.message.map((m: any) => m.value).join('; ')
      : (typeof r.message === 'string' ? r.message : (r.message?.value ?? null));
    return {
      focusNode: r.focusNode?.value ?? null,
      path: pathVal,
      severity: r.severity?.value?.replace(SH, 'sh:') ?? null,
      message: msgVal,
      sourceShape: shapeVal,
      constraint: r.constraintComponent?.value ?? null,
      source: 'shacl' as const,
    };
  });
}

const SHAPES_TTL = readFileSync(resolve(__dirname, 'fixtures/test-shapes.ttl'), 'utf-8');
const DATA_TTL = readFileSync(resolve(__dirname, 'fixtures/test-data.ttl'), 'utf-8');

describe('SHACL validation pipeline integration', () => {
  it('conforming data produces no violations', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);

    const conformingTtl = `
      @prefix owl: <http://www.w3.org/2002/07/owl#> .
      @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
      <http://example.org/Good> a owl:Class ; rdfs:label "Good" ; rdfs:comment "A good class" .
    `;
    const dataDs = parseTurtle(conformingTtl, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });

    expect(report.conforms).toBe(true);
    expect(report.results.length).toBe(0);
  });

  it('class missing rdfs:label produces sh:Warning violation', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);
    const dataDs = parseTurtle(DATA_TTL, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    const labelViolation = violations.find(
      v => v.focusNode === EX + 'Organization' && v.path === RDFS_LABEL,
    );
    expect(labelViolation).toBeDefined();
    expect(labelViolation!.severity).toBe('sh:Warning');
    expect(labelViolation!.sourceShape).toBe('urn:test:ClassLabel');
  });

  it('class missing rdfs:comment produces sh:Info violation', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);
    const dataDs = parseTurtle(DATA_TTL, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    const commentViolation = violations.find(
      v => v.focusNode === EX + 'Animal' && v.path === RDFS_COMMENT,
    );
    expect(commentViolation).toBeDefined();
    expect(commentViolation!.severity).toBe('sh:Info');
    expect(commentViolation!.sourceShape).toBe('urn:test:ClassComment');
  });

  it('blank-node owl:Class produces no violations (SPARQL target excludes)', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);
    const dataDs = parseTurtle(DATA_TTL, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    const bnodeViolations = violations.filter(
      v => v.focusNode !== null && !v.focusNode.startsWith('http'),
    );
    expect(bnodeViolations.length).toBe(0);
  });

  it('skolemized blank node (urn:vg:bnode:*) is treated as IRI by SPARQL target', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);

    const skolemTtl = `
      @prefix owl: <http://www.w3.org/2002/07/owl#> .
      <urn:vg:bnode:abc123> a owl:Class .
    `;
    const dataDs = parseTurtle(skolemTtl, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    const skolemViolations = violations.filter(
      v => v.focusNode === 'urn:vg:bnode:abc123',
    );
    expect(skolemViolations.length).toBeGreaterThan(0);
  });

  it('owl:ObjectProperty missing label produces violation (sh:targetClass)', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);
    const dataDs = parseTurtle(DATA_TTL, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    const propViolation = violations.find(
      v => v.focusNode === EX + 'knows' && v.path === RDFS_LABEL,
    );
    expect(propViolation).toBeDefined();
    expect(propViolation!.severity).toBe('sh:Warning');
    expect(propViolation!.sourceShape).toBe('urn:test:ObjectPropertyLabel');
  });

  it('result mapping populates all ShaclViolation fields', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);
    const dataDs = parseTurtle(DATA_TTL, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    expect(violations.length).toBeGreaterThan(0);
    for (const v of violations) {
      expect(v.focusNode).toBeTruthy();
      expect(v.path).toBeTruthy();
      expect(v.severity).toMatch(/^sh:/);
      expect(v.sourceShape).toBeTruthy();
      expect(v.constraint).toBeTruthy();
      expect(v.source).toBe('shacl');
    }
  });

  it('violation count matches expected (no duplicates)', async () => {
    const { Validator, targetResolvers, factory, dataset, N3 } = await loadEngine();
    const shapesDs = parseTurtle(SHAPES_TTL, N3, factory, dataset);
    const dataDs = parseTurtle(DATA_TTL, N3, factory, dataset);

    const validator = new Validator(shapesDs, { factory, targetResolvers });
    const report = await validator.validate({ dataset: dataDs });
    const violations = mapResults(report, shapesDs);

    // Expected: Organization missing label (1) + Organization missing comment (0, has comment)
    //           Animal missing comment (1) + knows missing label (1)
    //           Person: fully conforming (0)
    //           _:restriction1: excluded by SPARQL target (0)
    // Organization has comment but no label → 1 violation (ClassLabel)
    // Animal has label but no comment → 1 violation (ClassComment)
    // knows has no label → 1 violation (ObjectPropertyLabel)
    // Total: 3 violations minimum
    expect(violations.length).toBeGreaterThanOrEqual(3);

    const focusNodePaths = violations.map(v => `${v.focusNode}|${v.path}`);
    const unique = new Set(focusNodePaths);
    expect(unique.size).toBe(focusNodePaths.length);
  });
});
