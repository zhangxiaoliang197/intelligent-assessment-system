// @vitest-environment node
// Tests the non-logical axiom filter used inside KoncludeWrapper.explainInconsistency.
// The filter is implemented as an inline lambda in rdfManager.runtime.ts.  This test
// exercises the same predicate logic in isolation so it can run without SharedArrayBuffer
// or a live Konclude WASM instance.
import { describe, it, expect } from "vitest";
import * as N3 from "n3";

const { namedNode, literal, quad } = N3.DataFactory;

// ---------------------------------------------------------------------------
// Replicate the filter exactly as written in rdfManager.runtime.ts so the
// test stays coupled to the intended logic.
// ---------------------------------------------------------------------------
const ANNOTATION_PREDICATES = new Set([
  "http://www.w3.org/2000/01/rdf-schema#label",
  "http://www.w3.org/2000/01/rdf-schema#comment",
  "http://www.w3.org/2000/01/rdf-schema#seeAlso",
  "http://www.w3.org/2000/01/rdf-schema#isDefinedBy",
  // skos
  "http://www.w3.org/2004/02/skos/core#prefLabel",
  "http://www.w3.org/2004/02/skos/core#altLabel",
  "http://www.w3.org/2004/02/skos/core#hiddenLabel",
  "http://www.w3.org/2004/02/skos/core#note",
  "http://www.w3.org/2004/02/skos/core#definition",
  "http://www.w3.org/2004/02/skos/core#example",
  "http://www.w3.org/2004/02/skos/core#scopeNote",
  "http://www.w3.org/2004/02/skos/core#editorialNote",
  "http://www.w3.org/2004/02/skos/core#changeNote",
  "http://www.w3.org/2004/02/skos/core#historyNote",
  // dc / dcterms
  "http://purl.org/dc/elements/1.1/title",
  "http://purl.org/dc/elements/1.1/description",
  "http://purl.org/dc/elements/1.1/creator",
  "http://purl.org/dc/elements/1.1/date",
  "http://purl.org/dc/terms/title",
  "http://purl.org/dc/terms/description",
  "http://purl.org/dc/terms/creator",
  "http://purl.org/dc/terms/date",
  "http://purl.org/dc/terms/created",
  "http://purl.org/dc/terms/modified",
]);
const OWL_DECLARATION_OBJECTS = new Set([
  "http://www.w3.org/2002/07/owl#Class",
  "http://www.w3.org/2002/07/owl#ObjectProperty",
  "http://www.w3.org/2002/07/owl#DatatypeProperty",
  "http://www.w3.org/2002/07/owl#AnnotationProperty",
  "http://www.w3.org/2002/07/owl#NamedIndividual",
  "http://www.w3.org/2002/07/owl#Ontology",
]);
const RDF_TYPE_URI = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type";

function isNonLogical(q: N3.Quad): boolean {
  const pred = q.predicate.value;
  if (ANNOTATION_PREDICATES.has(pred)) return true;
  if (pred === RDF_TYPE_URI && OWL_DECLARATION_OBJECTS.has(q.object.value)) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Convenience URIs
// ---------------------------------------------------------------------------
const EX = "http://ex/";
const OWL_DISJOINT = "http://www.w3.org/2002/07/owl#disjointWith";
const RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label";
const RDFS_COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment";
const SKOS_PREF_LABEL = "http://www.w3.org/2004/02/skos/core#prefLabel";
const DC_TITLE = "http://purl.org/dc/elements/1.1/title";
const DCT_DESCRIPTION = "http://purl.org/dc/terms/description";
const OWL_CLASS = "http://www.w3.org/2002/07/owl#Class";
const OWL_NAMED_INDIVIDUAL = "http://www.w3.org/2002/07/owl#NamedIndividual";
const OWL_OBJECT_PROPERTY = "http://www.w3.org/2002/07/owl#ObjectProperty";

// ---------------------------------------------------------------------------
// Helper — build the candidate set the same way the filter does
// ---------------------------------------------------------------------------
function candidatesFrom(quads: N3.Quad[]): N3.Quad[] {
  return quads.filter((q) => !isNonLogical(q));
}

// ---------------------------------------------------------------------------
describe("axiomFilter (non-logical triple exclusion)", () => {
  it("excludes rdfs:label triples", () => {
    const labelTriple = quad(namedNode(EX + "Employee"), namedNode(RDFS_LABEL), literal("Employee class"));
    expect(isNonLogical(labelTriple)).toBe(true);
  });

  it("excludes rdfs:comment triples", () => {
    const commentTriple = quad(namedNode(EX + "Employee"), namedNode(RDFS_COMMENT), literal("A comment"));
    expect(isNonLogical(commentTriple)).toBe(true);
  });

  it("excludes skos:prefLabel triples", () => {
    const skosTriple = quad(namedNode(EX + "Employee"), namedNode(SKOS_PREF_LABEL), literal("Employee"));
    expect(isNonLogical(skosTriple)).toBe(true);
  });

  it("excludes dc:title triples", () => {
    const dcTriple = quad(namedNode(EX + "Employee"), namedNode(DC_TITLE), literal("Employee"));
    expect(isNonLogical(dcTriple)).toBe(true);
  });

  it("excludes dcterms:description triples", () => {
    const dctTriple = quad(namedNode(EX + "Employee"), namedNode(DCT_DESCRIPTION), literal("desc"));
    expect(isNonLogical(dctTriple)).toBe(true);
  });

  it("excludes rdf:type owl:Class declarations", () => {
    const decl = quad(namedNode(EX + "Employee"), namedNode(RDF_TYPE_URI), namedNode(OWL_CLASS));
    expect(isNonLogical(decl)).toBe(true);
  });

  it("excludes rdf:type owl:NamedIndividual declarations", () => {
    const decl = quad(namedNode(EX + "frank"), namedNode(RDF_TYPE_URI), namedNode(OWL_NAMED_INDIVIDUAL));
    expect(isNonLogical(decl)).toBe(true);
  });

  it("excludes rdf:type owl:ObjectProperty declarations", () => {
    const decl = quad(namedNode(EX + "manages"), namedNode(RDF_TYPE_URI), namedNode(OWL_OBJECT_PROPERTY));
    expect(isNonLogical(decl)).toBe(true);
  });

  it("KEEPS rdf:type triples that classify individuals into domain classes (logical assertions)", () => {
    // e.g. frank rdf:type ex:Employee — this is a logical assertion, NOT a declaration
    const typeAssertion = quad(namedNode(EX + "frank"), namedNode(RDF_TYPE_URI), namedNode(EX + "Employee"));
    expect(isNonLogical(typeAssertion)).toBe(false);
  });

  it("KEEPS owl:disjointWith axioms", () => {
    const disjoint = quad(namedNode(EX + "Employee"), namedNode(OWL_DISJOINT), namedNode(EX + "Contractor"));
    expect(isNonLogical(disjoint)).toBe(false);
  });

  it("KEEPS rdfs:subClassOf axioms", () => {
    const subClass = quad(
      namedNode(EX + "Manager"),
      namedNode("http://www.w3.org/2000/01/rdf-schema#subClassOf"),
      namedNode(EX + "Employee"),
    );
    expect(isNonLogical(subClass)).toBe(false);
  });

  it("candidate set for a known inconsistency excludes rdfs:label but retains logical axioms", () => {
    // Scenario: frank is both Employee and Contractor, and they are declared disjoint.
    // The ontology also has labels and an OWL class declaration — those must be filtered.
    const allTriples: N3.Quad[] = [
      // logical axioms that CAUSE the inconsistency
      quad(namedNode(EX + "frank"), namedNode(RDF_TYPE_URI), namedNode(EX + "Employee")),
      quad(namedNode(EX + "frank"), namedNode(RDF_TYPE_URI), namedNode(EX + "Contractor")),
      quad(namedNode(EX + "Employee"), namedNode(OWL_DISJOINT), namedNode(EX + "Contractor")),
      // non-logical triples that MUST be excluded
      quad(namedNode(EX + "frank"), namedNode(RDFS_LABEL), literal("Frank")),
      quad(namedNode(EX + "Employee"), namedNode(RDFS_COMMENT), literal("An employee")),
      quad(namedNode(EX + "Employee"), namedNode(RDF_TYPE_URI), namedNode(OWL_CLASS)),
      quad(namedNode(EX + "Contractor"), namedNode(RDF_TYPE_URI), namedNode(OWL_CLASS)),
      quad(namedNode(EX + "frank"), namedNode(RDF_TYPE_URI), namedNode(OWL_NAMED_INDIVIDUAL)),
      quad(namedNode(EX + "Employee"), namedNode(SKOS_PREF_LABEL), literal("Employee")),
    ];

    const candidates = candidatesFrom(allTriples);

    // Only the 3 logical axioms remain
    expect(candidates).toHaveLength(3);

    const predicates = candidates.map((q) => q.predicate.value);
    expect(predicates).toContain(RDF_TYPE_URI); // frank rdf:type Employee and Contractor
    expect(predicates).toContain(OWL_DISJOINT);

    // Non-logical predicates must NOT be present
    expect(predicates).not.toContain(RDFS_LABEL);
    expect(predicates).not.toContain(RDFS_COMMENT);
    expect(predicates).not.toContain(SKOS_PREF_LABEL);

    // Verify the rdfs:label triple is absent by content
    const hasLabel = candidates.some(
      (q) => q.predicate.value === RDFS_LABEL,
    );
    expect(hasLabel).toBe(false);

    // Verify owl:Class declarations are absent
    const hasOwlClassDecl = candidates.some(
      (q) => q.predicate.value === RDF_TYPE_URI && q.object.value === OWL_CLASS,
    );
    expect(hasOwlClassDecl).toBe(false);

    // Verify the disjointness axiom IS present
    const hasDisjoint = candidates.some(
      (q) => q.predicate.value === OWL_DISJOINT,
    );
    expect(hasDisjoint).toBe(true);
  });
});
