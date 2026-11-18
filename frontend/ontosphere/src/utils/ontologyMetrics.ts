/**
 * @fileoverview Pure ontology-metrics math.
 *
 * This module contains ONLY pure functions: the component gathers raw counts
 * (via SPARQL COUNT queries and getGraphCounts) and hands them here to derive
 * the displayed ratios. Keeping the math here makes it unit-testable without a
 * worker, a DOM, or any I/O.
 *
 * IMPORTANT — these "quality" ratios are deliberately simple heuristics. They
 * are *OQuaRE-flavored* (inspired by the structural metrics OQuaRE builds on)
 * but they are NOT a certified OQuaRE assessment. Treat them as quick,
 * directional signals, not a formal quality score.
 */

/** Raw counts gathered by the panel before any ratios are derived. */
export interface OntologyRawCounts {
  /** Total triples in the asserted data graph (urn:vg:data). */
  totalTriples: number;
  /** Distinct rdfs:Class / owl:Class subjects. */
  classCount: number;
  /** Distinct owl:ObjectProperty subjects. */
  objectPropertyCount: number;
  /** Distinct owl:DatatypeProperty subjects. */
  datatypePropertyCount: number;
  /** Distinct owl:NamedIndividual subjects. */
  namedIndividualCount: number;
  /** Distinct subjects of any triple in the data graph. */
  subjectCount: number;
  /** Distinct classes carrying at least one rdfs:label. */
  labeledClassCount: number;
  /** Asserted triples (urn:vg:data) — usually equals totalTriples. */
  assertedTriples: number;
  /** Inferred triples produced by reasoning (urn:vg:inferred). */
  inferredTriples: number;
}

/** Derived, display-ready heuristic ratios. All are non-negative finite numbers. */
export interface OntologyMetrics {
  /** objectProperties + datatypeProperties. */
  totalPropertyCount: number;
  /** Average properties per class = totalProperties / classes (0 if no classes). */
  avgPropertiesPerClass: number;
  /** classes / properties (0 if no properties). */
  classToPropertyRatio: number;
  /** Fraction of classes carrying an rdfs:label, in [0, 1] (0 if no classes). */
  labeledClassRatio: number;
  /** inferred / asserted (0 if nothing asserted). */
  inferredToAssertedRatio: number;
  /** Convenience percentage form of labeledClassRatio, in [0, 100]. */
  labeledClassPercent: number;
}

/** Divide guarding against division by zero; returns 0 when the denominator is 0. */
function safeRatio(numerator: number, denominator: number): number {
  if (!Number.isFinite(numerator) || !Number.isFinite(denominator)) return 0;
  if (denominator === 0) return 0;
  return numerator / denominator;
}

/** Coerce an arbitrary count-like value into a non-negative finite integer-ish number. */
function nonNeg(value: number | undefined | null): number {
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n) || n < 0) return 0;
  return n;
}

/**
 * Compute the derived heuristic metrics from raw gathered counts.
 *
 * Pure: same input → same output, no side effects. Robust to missing/NaN/negative
 * inputs (treated as 0) so the panel never renders NaN.
 */
export function computeOntologyMetrics(raw: Partial<OntologyRawCounts>): OntologyMetrics {
  const classCount = nonNeg(raw.classCount);
  const objectPropertyCount = nonNeg(raw.objectPropertyCount);
  const datatypePropertyCount = nonNeg(raw.datatypePropertyCount);
  const labeledClassCount = nonNeg(raw.labeledClassCount);
  const assertedTriples = nonNeg(raw.assertedTriples);
  const inferredTriples = nonNeg(raw.inferredTriples);

  const totalPropertyCount = objectPropertyCount + datatypePropertyCount;
  const labeledClassRatio = safeRatio(labeledClassCount, classCount);

  return {
    totalPropertyCount,
    avgPropertiesPerClass: safeRatio(totalPropertyCount, classCount),
    classToPropertyRatio: safeRatio(classCount, totalPropertyCount),
    labeledClassRatio,
    inferredToAssertedRatio: safeRatio(inferredTriples, assertedTriples),
    labeledClassPercent: labeledClassRatio * 100,
  };
}

/** Format a ratio for compact display (e.g. 2.5), trimming trailing zeros. */
export function formatRatio(value: number, fractionDigits = 2): string {
  if (!Number.isFinite(value)) return '—';
  const fixed = value.toFixed(fractionDigits);
  return fixed.replace(/\.?0+$/, '') || '0';
}

/** Format a [0,1] ratio as a whole-number percentage string (e.g. "50%"). */
export function formatPercent(ratio: number): string {
  if (!Number.isFinite(ratio)) return '—';
  return `${Math.round(ratio * 100)}%`;
}
