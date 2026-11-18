import { describe, it, expect } from 'vitest';
import {
  computeOntologyMetrics,
  formatRatio,
  formatPercent,
} from '../ontologyMetrics';

describe('computeOntologyMetrics', () => {
  it('derives ratios from a typical ontology fixture (10 classes, 30 props, 5 labeled)', () => {
    const m = computeOntologyMetrics({
      classCount: 10,
      objectPropertyCount: 20,
      datatypePropertyCount: 10,
      labeledClassCount: 5,
      assertedTriples: 200,
      inferredTriples: 50,
    });

    expect(m.totalPropertyCount).toBe(30);
    // 30 props / 10 classes
    expect(m.avgPropertiesPerClass).toBe(3);
    // 10 classes / 30 props
    expect(m.classToPropertyRatio).toBeCloseTo(1 / 3, 10);
    // 5 of 10 classes labeled
    expect(m.labeledClassRatio).toBe(0.5);
    expect(m.labeledClassPercent).toBe(50);
    // 50 inferred / 200 asserted
    expect(m.inferredToAssertedRatio).toBe(0.25);
  });

  it('guards against division by zero (no classes / no props / nothing asserted)', () => {
    const m = computeOntologyMetrics({
      classCount: 0,
      objectPropertyCount: 0,
      datatypePropertyCount: 0,
      labeledClassCount: 0,
      assertedTriples: 0,
      inferredTriples: 0,
    });
    expect(m.totalPropertyCount).toBe(0);
    expect(m.avgPropertiesPerClass).toBe(0);
    expect(m.classToPropertyRatio).toBe(0);
    expect(m.labeledClassRatio).toBe(0);
    expect(m.labeledClassPercent).toBe(0);
    expect(m.inferredToAssertedRatio).toBe(0);
  });

  it('treats missing / negative / NaN inputs as zero (never produces NaN)', () => {
    const m = computeOntologyMetrics({
      classCount: -5,
      objectPropertyCount: Number.NaN,
      datatypePropertyCount: undefined,
      labeledClassCount: 999,
      assertedTriples: -1,
      inferredTriples: 3,
    });
    expect(Number.isNaN(m.avgPropertiesPerClass)).toBe(false);
    expect(m.totalPropertyCount).toBe(0);
    expect(m.avgPropertiesPerClass).toBe(0);
    expect(m.inferredToAssertedRatio).toBe(0);
  });

  it('handles a fully-labeled, property-rich ontology', () => {
    const m = computeOntologyMetrics({
      classCount: 4,
      objectPropertyCount: 4,
      datatypePropertyCount: 4,
      labeledClassCount: 4,
      assertedTriples: 100,
      inferredTriples: 200,
    });
    expect(m.labeledClassRatio).toBe(1);
    expect(m.labeledClassPercent).toBe(100);
    expect(m.avgPropertiesPerClass).toBe(2);
    expect(m.inferredToAssertedRatio).toBe(2);
  });
});

describe('formatRatio', () => {
  it('trims trailing zeros', () => {
    expect(formatRatio(3)).toBe('3');
    expect(formatRatio(2.5)).toBe('2.5');
    expect(formatRatio(0.3333333, 2)).toBe('0.33');
    expect(formatRatio(0)).toBe('0');
  });

  it('renders an em dash for non-finite input', () => {
    expect(formatRatio(Number.NaN)).toBe('—');
    expect(formatRatio(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('formatPercent', () => {
  it('renders a rounded percent', () => {
    expect(formatPercent(0.5)).toBe('50%');
    expect(formatPercent(0.333)).toBe('33%');
    expect(formatPercent(1)).toBe('100%');
  });

  it('renders an em dash for non-finite input', () => {
    expect(formatPercent(Number.NaN)).toBe('—');
  });
});
