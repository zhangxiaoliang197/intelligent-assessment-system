// @vitest-environment node

/**
 * Dataset-faithful export round-trip tests.
 *
 * Verifies that the N-Quads and TriG exporters collect quads from ALL urn:vg:* graphs
 * (data, inferred, shapes, ontologies, workflows) and preserve each quad's graph IRI, so
 * the five-graph partition round-trips on re-parse. Contrast with Turtle/JSON-LD/RDF-XML,
 * which intentionally flatten everything into a single default graph.
 *
 * Implementation owned by:
 *   - src/workers/rdfManager.runtime.ts  (normalizeExportFormat + exportGraph handler)
 *   - src/utils/rdfManager.impl.ts        (exportToNQuads / exportToTriG)
 */

import { describe, test, expect, beforeEach } from "vitest";
import { Parser } from "n3";
import { initRdfManagerWorker } from "../utils/initRdfManagerWorker";
import { rdfManager } from "../../utils/rdfManager";

const EX = "http://example.org/";

// One distinct subject per graph so we can assert each graph survives the round-trip.
const PER_GRAPH: Record<string, string> = {
  "urn:vg:data": `@prefix ex: <${EX}> . ex:alice ex:name "Alice" .`,
  "urn:vg:inferred": `@prefix ex: <${EX}> . ex:alice a ex:Person .`,
  "urn:vg:shapes": `@prefix ex: <${EX}> . ex:AliceShape ex:targetClass ex:Person .`,
  "urn:vg:ontologies": `@prefix ex: <${EX}> . ex:Person ex:label "Person" .`,
  "urn:vg:workflows": `@prefix ex: <${EX}> . ex:wf1 ex:status "active" .`,
};

async function seedAllGraphs() {
  for (const [graph, ttl] of Object.entries(PER_GRAPH)) {
    // forceGraph=true → every incoming quad is pinned into `graph`.
    await rdfManager.loadRDFIntoGraph(ttl, graph, "text/turtle", undefined, true);
  }
  await new Promise((r) => setTimeout(r, 300));
}

/** Parse a serialized dataset string and bucket quad keys by graph IRI. */
function quadsByGraph(content: string, format: string): Map<string, Set<string>> {
  const parser = new Parser({ format } as any);
  const quads = parser.parse(content);
  const map = new Map<string, Set<string>>();
  for (const q of quads) {
    const g = q.graph?.value || "";
    if (!map.has(g)) map.set(g, new Set());
    map.get(g)!.add(`${q.subject.value} ${q.predicate.value} ${q.object.value}`);
  }
  return map;
}

describe("dataset-faithful export (N-Quads / TriG)", () => {
  beforeEach(async () => {
    await initRdfManagerWorker();
    rdfManager.clear();
    await new Promise((r) => setTimeout(r, 100));
    await seedAllGraphs();
  });

  test("N-Quads output contains every urn:vg:* graph IRI", async () => {
    const out = await rdfManager.exportToNQuads();
    for (const graph of Object.keys(PER_GRAPH)) {
      expect(out, `missing graph ${graph} in N-Quads`).toContain(graph);
    }
    // Each seeded triple's subject must be present.
    expect(out).toContain(`${EX}alice`);
    expect(out).toContain(`${EX}AliceShape`);
    expect(out).toContain(`${EX}wf1`);
  });

  test("TriG output contains every urn:vg:* graph IRI", async () => {
    const out = await rdfManager.exportToTriG();
    for (const graph of Object.keys(PER_GRAPH)) {
      expect(out, `missing graph ${graph} in TriG`).toContain(graph);
    }
  });

  test("N-Quads round-trips quads back into the same graphs", async () => {
    const out = await rdfManager.exportToNQuads();
    const byGraph = quadsByGraph(out, "application/n-quads");

    // Every seeded graph must reappear with its distinctive triple.
    expect(byGraph.get("urn:vg:data")?.has(`${EX}alice ${EX}name Alice`)).toBe(true);
    expect(byGraph.get("urn:vg:inferred")?.has(
      `${EX}alice http://www.w3.org/1999/02/22-rdf-syntax-ns#type ${EX}Person`,
    )).toBe(true);
    expect(byGraph.get("urn:vg:shapes")?.has(`${EX}AliceShape ${EX}targetClass ${EX}Person`)).toBe(true);
    expect(byGraph.get("urn:vg:ontologies")?.has(`${EX}Person ${EX}label Person`)).toBe(true);
    expect(byGraph.get("urn:vg:workflows")?.has(`${EX}wf1 ${EX}status active`)).toBe(true);

    // No seeded triple leaked into the default graph.
    expect(byGraph.has("")).toBe(false);
  });

  test("TriG round-trips quads back into the same graphs", async () => {
    const out = await rdfManager.exportToTriG();
    const byGraph = quadsByGraph(out, "application/trig");
    expect(byGraph.get("urn:vg:data")?.has(`${EX}alice ${EX}name Alice`)).toBe(true);
    expect(byGraph.get("urn:vg:shapes")?.has(`${EX}AliceShape ${EX}targetClass ${EX}Person`)).toBe(true);
    expect(byGraph.get("urn:vg:workflows")?.has(`${EX}wf1 ${EX}status active`)).toBe(true);
  });

  test("Turtle export stays single-graph (flattens, no graph IRIs)", async () => {
    const out = await rdfManager.exportToTurtle();
    // Turtle cannot encode quads; none of the urn:vg graph IRIs appear as graph terms.
    // (They may not appear at all — Turtle export only collects urn:vg:data + grounded inferred.)
    expect(out).not.toContain("urn:vg:shapes");
    expect(out).not.toContain("urn:vg:workflows");
  });
});
