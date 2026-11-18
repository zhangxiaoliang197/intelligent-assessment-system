// @vitest-environment node
//
// Integration test for the searchTerms grounding/retrieval path. Drives the
// REAL rdfManager worker runtime end-to-end:
//   loadRDFIntoGraph(ttl, "urn:vg:ontologies") → rdfManager.searchTerms(...)
//
// Pure store query (no Konclude / SharedArrayBuffer), so it runs fast in Node.

import { describe, test, expect, beforeEach } from "vitest";
import { initRdfManagerWorker } from "../../__tests__/utils/initRdfManagerWorker";
import { rdfManager } from "../../utils/rdfManager";
import {
  validateRdfWorkerCommandInput,
  RDF_WORKER_COMMANDS,
} from "../../utils/rdfManager.workerProtocol";

const PMD = "https://w3id.org/pmd/co/";
const EX = "http://example.org/";

// A tiny labelled TBox: two classes, one object property, one datatype property,
// and one class with NO rdfs:label (local-name match only).
const TBOX = `
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix pmd: <${PMD}> .
@prefix ex: <${EX}> .

pmd:ProcessingNode a owl:Class ;
  rdfs:label "Processing Node" .

pmd:Specimen a owl:Class ;
  skos:prefLabel "Specimen" .

pmd:characteristic a owl:ObjectProperty ;
  rdfs:label "characteristic" .

pmd:value a owl:DatatypeProperty ;
  rdfs:label "value" .

ex:UnlabelledMaterial a owl:Class .
`;

async function seedTBox() {
  // forceGraph=true → every quad lands in urn:vg:ontologies.
  await rdfManager.loadRDFIntoGraph(TBOX, "urn:vg:ontologies", "text/turtle", undefined, true);
  await new Promise((r) => setTimeout(r, 200));
}

describe("searchTerms (grounding / retrieval)", () => {
  beforeEach(async () => {
    await initRdfManagerWorker();
    rdfManager.clear();
    await new Promise((r) => setTimeout(r, 100));
    await seedTBox();
  });

  test("finds a class by a label substring", async () => {
    const results = await rdfManager.searchTerms("Specimen");
    const iris = results.map((r) => r.iri);
    expect(iris).toContain(`${PMD}Specimen`);
    const hit = results.find((r) => r.iri === `${PMD}Specimen`)!;
    expect(hit.label).toBe("Specimen");
    expect(hit.kind).toBe("class");
  });

  test("matches a label substring (case-insensitive) across multiple terms", async () => {
    const results = await rdfManager.searchTerms("process");
    const iris = results.map((r) => r.iri);
    expect(iris).toContain(`${PMD}ProcessingNode`);
  });

  test("kinds filter: asking for objectProperty does not return classes", async () => {
    const results = await rdfManager.searchTerms("characteristic", { kinds: ["objectProperty"] });
    const iris = results.map((r) => r.iri);
    expect(iris).toContain(`${PMD}characteristic`);
    // No class should appear.
    expect(results.every((r) => r.kind === "objectProperty")).toBe(true);
    expect(iris).not.toContain(`${PMD}Specimen`);
    expect(iris).not.toContain(`${PMD}ProcessingNode`);
  });

  test("kinds filter excludes terms of other kinds entirely", async () => {
    // "value" matches the datatype property only; restrict to classes → empty.
    const asClass = await rdfManager.searchTerms("value", { kinds: ["class"] });
    expect(asClass.map((r) => r.iri)).not.toContain(`${PMD}value`);

    const asDatatype = await rdfManager.searchTerms("value", { kinds: ["datatypeProperty"] });
    expect(asDatatype.map((r) => r.iri)).toContain(`${PMD}value`);
  });

  test("local-name match works when no rdfs:label exists", async () => {
    const results = await rdfManager.searchTerms("UnlabelledMaterial");
    const hit = results.find((r) => r.iri === `${EX}UnlabelledMaterial`);
    expect(hit).toBeDefined();
    expect(hit!.label).toBe("");
    expect(hit!.kind).toBe("class");
  });

  test("ranking puts an exact-label match first", async () => {
    // Exact label "Specimen" must outrank "ProcessingNode" (whose local name and
    // label only contain the longer token "process", not "specimen").
    const results = await rdfManager.searchTerms("Specimen");
    expect(results.length).toBeGreaterThan(0);
    expect(results[0].iri).toBe(`${PMD}Specimen`);
  });

  test("resolves a well-known prefix for matched terms", async () => {
    // The PMDco namespace (https://w3id.org/pmd/co/) is registered as "pmdco"
    // in the well-known registry; the worker may also surface the TTL's own
    // "pmd" alias if it was synced. Either is an acceptable resolution.
    const results = await rdfManager.searchTerms("Specimen");
    const hit = results.find((r) => r.iri === `${PMD}Specimen`)!;
    expect(["pmdco", "pmd"]).toContain(hit.prefix);
  });

  test("no-match query returns [] (no crash)", async () => {
    const noMatch = await rdfManager.searchTerms("zzz-nonexistent-term-xyz");
    expect(noMatch).toEqual([]);
  });
});

describe("searchTerms worker protocol validator", () => {
  test("searchTerms is a registered command", () => {
    expect(RDF_WORKER_COMMANDS).toContain("searchTerms");
  });

  test("accepts a valid query, optional kinds, and limit", () => {
    expect(() => validateRdfWorkerCommandInput("searchTerms", { query: "process" })).not.toThrow();
    expect(() =>
      validateRdfWorkerCommandInput("searchTerms", { query: "x", kinds: ["class"], limit: 10 }),
    ).not.toThrow();
  });

  test("rejects an empty / whitespace-only query", () => {
    expect(() => validateRdfWorkerCommandInput("searchTerms", { query: "" })).toThrow();
    expect(() => validateRdfWorkerCommandInput("searchTerms", { query: "   " })).toThrow();
  });

  test("rejects a non-string query and an invalid kind", () => {
    expect(() => validateRdfWorkerCommandInput("searchTerms", { query: 5 })).toThrow();
    expect(() =>
      validateRdfWorkerCommandInput("searchTerms", { query: "x", kinds: ["bogus"] }),
    ).toThrow();
  });
});
