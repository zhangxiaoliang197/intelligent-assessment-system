// src/components/Canvas/core/__tests__/structuralGroups.test.ts
// @vitest-environment node

import { describe, it, expect } from "vitest";
import {
  computeStructuralGroups,
} from "../structuralGroups";
import type { WorkerQuad } from "../../../../utils/rdfSerialization";

// ── helpers ──────────────────────────────────────────────────────────────────

function nn(value: string) {
  return { termType: "NamedNode" as const, value };
}

function bn(value: string) {
  return { termType: "BlankNode" as const, value };
}

const DEFAULT_GRAPH = { termType: "DefaultGraph" as const, value: "" };

function quad(
  subject: ReturnType<typeof nn> | ReturnType<typeof bn>,
  predicateValue: string,
  object: ReturnType<typeof nn> | ReturnType<typeof bn>,
): WorkerQuad {
  return {
    subject,
    predicate: nn(predicateValue),
    object,
    graph: DEFAULT_GRAPH,
  };
}

const SC = "http://www.w3.org/2000/01/rdf-schema#subClassOf";
const REST = "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest";
const NIL = "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil";
const INTERSECTION = "http://www.w3.org/2002/07/owl#intersectionOf";
const UNION = "http://www.w3.org/2002/07/owl#unionOf";

const A = "http://example.org/A";
const B = "http://example.org/B";
const C = "http://example.org/C";
const LIST1 = "_:list1";
const LIST2 = "_:list2";
const CLASS1 = "http://example.org/MyClass";

// ── tests ─────────────────────────────────────────────────────────────────────

describe("computeStructuralGroups", () => {
  it("returns empty map for empty quad array", () => {
    const { groupMap: result } = computeStructuralGroups([]);
    expect(result.size).toBe(0);
  });

  describe("subclass chains", () => {
    it("simple A subClassOf B: A maps to B, B is not mapped", () => {
      const quads: WorkerQuad[] = [quad(nn(A), SC, nn(B))];
      const { groupMap: result } = computeStructuralGroups(quads);

      expect(result.get(A)).toBe(B);
      expect(result.has(B)).toBe(false);
    });

    it("chain A subClassOf B subClassOf C: both A and B map to C", () => {
      const quads: WorkerQuad[] = [
        quad(nn(A), SC, nn(B)),
        quad(nn(B), SC, nn(C)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);

      expect(result.get(A)).toBe(C);
      expect(result.get(B)).toBe(C);
      expect(result.has(C)).toBe(false);
    });

    it("cycle A subClassOf B subClassOf A: neither is mapped", () => {
      const quads: WorkerQuad[] = [
        quad(nn(A), SC, nn(B)),
        quad(nn(B), SC, nn(A)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);

      expect(result.has(A)).toBe(false);
      expect(result.has(B)).toBe(false);
    });

    it("skips blank node subjects in subclass chains", () => {
      const quads: WorkerQuad[] = [quad(bn("b0"), SC, nn(B))];
      const { groupMap: result } = computeStructuralGroups(quads);
      expect(result.has("b0")).toBe(false);
    });

    it("skips blank node objects in subclass chains", () => {
      const quads: WorkerQuad[] = [quad(nn(A), SC, bn("b0"))];
      const { groupMap: result } = computeStructuralGroups(quads);
      expect(result.has(A)).toBe(false);
    });
  });

  describe("OWL collection cons-cells", () => {
    it("owl:intersectionOf with 2-element list: both cons-cell IRIs map to the class", () => {
      // CLASS1 owl:intersectionOf (LIST1 rdf:rest LIST2 rdf:rest nil)
      const quads: WorkerQuad[] = [
        quad(nn(CLASS1), INTERSECTION, bn(LIST1)),
        quad(bn(LIST1), REST, bn(LIST2)),
        quad(bn(LIST2), REST, nn(NIL)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);

      expect(result.get(LIST1)).toBe(CLASS1);
      expect(result.get(LIST2)).toBe(CLASS1);
      expect(result.has(NIL)).toBe(false);
    });

    it("owl:unionOf single-element list: cons-cell maps to class", () => {
      const quads: WorkerQuad[] = [
        quad(nn(CLASS1), UNION, bn(LIST1)),
        quad(bn(LIST1), REST, nn(NIL)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);

      expect(result.get(LIST1)).toBe(CLASS1);
    });

    it("stops walking if a cycle appears in rdf:rest chain", () => {
      // LIST1 → LIST2 → LIST1 (cycle)
      const quads: WorkerQuad[] = [
        quad(nn(CLASS1), INTERSECTION, bn(LIST1)),
        quad(bn(LIST1), REST, bn(LIST2)),
        quad(bn(LIST2), REST, bn(LIST1)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);

      // Both mapped before cycle is detected
      expect(result.get(LIST1)).toBe(CLASS1);
      expect(result.get(LIST2)).toBe(CLASS1);
    });

    it("does not map rdf:nil as a collection member", () => {
      const quads: WorkerQuad[] = [
        quad(nn(CLASS1), INTERSECTION, nn(NIL)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);
      expect(result.has(NIL)).toBe(false);
    });
  });

  describe("mixed: subclass + collection in same call", () => {
    it("handles both independently and correctly", () => {
      const quads: WorkerQuad[] = [
        // Subclass: A → B → C
        quad(nn(A), SC, nn(B)),
        quad(nn(B), SC, nn(C)),
        // Collection: CLASS1 intersectionOf (LIST1, LIST2)
        quad(nn(CLASS1), INTERSECTION, bn(LIST1)),
        quad(bn(LIST1), REST, bn(LIST2)),
        quad(bn(LIST2), REST, nn(NIL)),
      ];
      const { groupMap: result } = computeStructuralGroups(quads);

      // Subclass results
      expect(result.get(A)).toBe(C);
      expect(result.get(B)).toBe(C);
      expect(result.has(C)).toBe(false);

      // Collection results
      expect(result.get(LIST1)).toBe(CLASS1);
      expect(result.get(LIST2)).toBe(CLASS1);
    });
  });
});
