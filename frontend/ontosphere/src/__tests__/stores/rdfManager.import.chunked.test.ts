// @vitest-environment node

/**
 * Performance-path tests for the chunked importSerialized + progress events and
 * the incremental per-graph triple counters.
 *
 * These cover the two optimizations:
 *   1. Chunked import: large files are inserted in chunks (no per-quad existence
 *      pre-check), and importProgress events stream liveness during the load.
 *   2. Incremental graph counters: getGraphCounts returns from a maintained
 *      Map instead of a full store scan, and stays exactly accurate across a
 *      sequence of mutations (import / add / remove / graph-clear).
 */

import { describe, test, expect, beforeEach } from "vitest";
import { initRdfManagerWorker } from "../utils/initRdfManagerWorker";
import { rdfManager } from "../../utils/rdfManager";

const GRAPH = "urn:vg:data";

/** Build a deterministic turtle document with `n` distinct triples. */
function buildLargeTurtle(n: number): string {
  const lines: string[] = ["@prefix ex: <http://example.com/> ."];
  for (let i = 0; i < n; i++) {
    lines.push(`ex:s${i} ex:p ex:o${i} .`);
  }
  return lines.join("\n") + "\n";
}

/** Sum a counts map over all graphs. */
function totalCount(counts: Record<string, number>): number {
  return Object.values(counts).reduce((s, n) => s + n, 0);
}

/**
 * Recompute graph counts directly from the store by paging every quad, so we
 * can assert the incremental counter equals a real recount. We page across all
 * VocabGraph graphs the test touches plus the default graph.
 */
async function manualRecount(graphs: string[]): Promise<Record<string, number>> {
  const out: Record<string, number> = {};
  for (const g of graphs) {
    // The counter buckets the true default graph under "urn:vg:default";
    // fetchQuadsPage resolves the true default graph from the literal "default".
    const fetchGraph = g === "urn:vg:default" ? "default" : g;
    const page = await rdfManager.fetchQuadsPage({
      graphName: fetchGraph,
      offset: 0,
      limit: 0, // 0 == no limit in fetchQuadsPage
      serialize: true,
    });
    const total = (page && (page as any).total) ?? 0;
    if (total > 0) out[g] = total;
  }
  return out;
}

describe("rdfManager chunked import + progress events", () => {
  beforeEach(async () => {
    await initRdfManagerWorker();
    rdfManager.clear();
    await new Promise((r) => setTimeout(r, 100));
  });

  test("imports a multi-thousand-triple turtle with the correct triple count", async () => {
    const N = 12000; // > 2 chunks at chunk size 5000
    const ttl = buildLargeTurtle(N);

    await rdfManager.loadRDFIntoGraph(ttl, GRAPH, "text/turtle");
    await new Promise((r) => setTimeout(r, 300));

    const counts = await rdfManager.getGraphCounts();
    expect(counts[GRAPH]).toBe(N);
  });

  test("re-importing the same file does not produce duplicate triples (dedup still works)", async () => {
    const N = 6000;
    const ttl = buildLargeTurtle(N);

    await rdfManager.loadRDFIntoGraph(ttl, GRAPH, "text/turtle");
    await new Promise((r) => setTimeout(r, 300));
    const first = await rdfManager.getGraphCounts();
    expect(first[GRAPH]).toBe(N);

    // Import the exact same content again — N3 Store dedupes, count is unchanged.
    await rdfManager.loadRDFIntoGraph(ttl, GRAPH, "text/turtle");
    await new Promise((r) => setTimeout(r, 300));
    const second = await rdfManager.getGraphCounts();
    expect(second[GRAPH]).toBe(N);
  });

  test("emits importProgress events with increasing loaded counts during a large import", async () => {
    const N = 13000; // 3 chunks → at least 3 progress events
    const ttl = buildLargeTurtle(N);

    const progress: Array<{ id: string; loaded: number; total?: number; graphName?: string }> = [];
    const unsubscribe = (rdfManager as any).onImportProgress(
      (payload: { id: string; loaded: number; total?: number; graphName?: string }) => {
        progress.push(payload);
      },
    );

    try {
      await rdfManager.loadRDFIntoGraph(ttl, GRAPH, "text/turtle");
      await new Promise((r) => setTimeout(r, 400));
    } finally {
      unsubscribe();
    }

    // At least one progress event must have fired.
    expect(progress.length).toBeGreaterThanOrEqual(1);

    // loaded counts must be monotonically non-decreasing and end at the total.
    let prev = -1;
    for (const p of progress) {
      expect(p.loaded).toBeGreaterThanOrEqual(prev);
      expect(p.graphName).toBe(GRAPH);
      expect(p.total).toBe(N);
      prev = p.loaded;
    }
    expect(progress[progress.length - 1].loaded).toBe(N);
  });
});

describe("rdfManager incremental per-graph counters stay accurate", () => {
  beforeEach(async () => {
    await initRdfManagerWorker();
    rdfManager.clear();
    await new Promise((r) => setTimeout(r, 100));
  });

  test("getGraphCounts equals a full manual recount after import / add / remove / graph-clear", async () => {
    const touched = [GRAPH, "urn:vg:scratch"];

    // Baseline: after clear, the store still holds the seeded schema ontology
    // axioms (urn:vg:ontologies). The counter must already match a recount.
    const seedGraphs = [GRAPH, "urn:vg:scratch", "urn:vg:ontologies", "urn:vg:default"];

    // 1) Import a few thousand triples.
    const N = 4000;
    await rdfManager.loadRDFIntoGraph(buildLargeTurtle(N), GRAPH, "text/turtle");
    await new Promise((r) => setTimeout(r, 300));
    {
      const counts = await rdfManager.getGraphCounts();
      const recount = await manualRecount(seedGraphs);
      expect(counts[GRAPH]).toBe(N);
      expect(counts[GRAPH]).toBe(recount[GRAPH]);
    }

    // 2) Add a triple to a separate graph.
    await rdfManager.applyBatch(
      { adds: [{ subject: "http://example.com/a", predicate: "http://example.com/p", object: "http://example.com/b" }] },
      "urn:vg:scratch",
    );
    await new Promise((r) => setTimeout(r, 200));
    {
      const counts = await rdfManager.getGraphCounts();
      const recount = await manualRecount(seedGraphs);
      expect(counts["urn:vg:scratch"]).toBe(1);
      expect(counts["urn:vg:scratch"]).toBe(recount["urn:vg:scratch"]);
      expect(counts[GRAPH]).toBe(N);
    }

    // 3) Remove one triple from the imported graph.
    await rdfManager.applyBatch(
      { removes: [{ subject: "http://example.com/s0", predicate: "http://example.com/p", object: "http://example.com/o0" }] },
      GRAPH,
    );
    await new Promise((r) => setTimeout(r, 200));
    {
      const counts = await rdfManager.getGraphCounts();
      const recount = await manualRecount(seedGraphs);
      expect(counts[GRAPH]).toBe(N - 1);
      expect(counts[GRAPH]).toBe(recount[GRAPH]);
    }

    // 4) Clear the scratch graph entirely.
    rdfManager.removeGraph("urn:vg:scratch");
    await new Promise((r) => setTimeout(r, 200));
    {
      const counts = await rdfManager.getGraphCounts();
      const recount = await manualRecount(seedGraphs);
      expect(counts["urn:vg:scratch"]).toBeUndefined();
      expect(recount["urn:vg:scratch"]).toBeUndefined();
      expect(counts[GRAPH]).toBe(N - 1);
      expect(counts[GRAPH]).toBe(recount[GRAPH]);
    }

    // Whole-store sanity: total counter equals total recount across all graphs.
    {
      const counts = await rdfManager.getGraphCounts();
      const recount = await manualRecount(Object.keys(counts));
      expect(totalCount(counts)).toBe(totalCount(recount));
    }

    void touched;
  });
});
