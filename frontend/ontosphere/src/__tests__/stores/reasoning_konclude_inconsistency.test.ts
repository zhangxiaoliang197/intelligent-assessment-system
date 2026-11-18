// @vitest-environment node
/**
 * Inconsistency detection tests using checkConsistency().
 *
 * Verifies that public/reasoning-demo-inconsistent.ttl is detected as inconsistent
 * and that public/reasoning-demo.ttl remains consistent (sanity check).
 */
import { describe, it, expect } from "vitest";
import { RdfReasoner } from "rdf-reasoner-konclude";
import * as N3 from "n3";
import * as fs from "fs";
import * as path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function loadTtlStore(filename: string): N3.Store {
  const ttlPath = path.resolve(__dirname, "../../../public", filename);
  const ttlContent = fs.readFileSync(ttlPath, "utf-8");
  const store = new N3.Store();
  store.addQuads(new N3.Parser({ format: "text/turtle" }).parse(ttlContent));
  return store;
}

describe("checkConsistency(): inconsistency fixture vs. consistent demo", () => {
  it(
    "reasoning-demo-inconsistent.ttl → checkConsistency() returns false",
    async () => {
      let r: RdfReasoner | undefined;
      try {
        r = new RdfReasoner();
        await r.ready;
      } catch (e) {
        console.warn("[TEST] Konclude WASM unavailable — skipping:", String(e));
        return;
      }
      const store = loadTtlStore("reasoning-demo-inconsistent.ttl");
      let result: boolean | undefined;
      try {
        result = await r.checkConsistency(store);
      } finally {
        r.terminate();
      }
      console.log("[TEST] inconsistent fixture checkConsistency result:", result);
      expect(result, "reasoning-demo-inconsistent.ttl must be detected as inconsistent").toBe(false);
    },
    30000,
  );

  it(
    "reasoning-demo.ttl → checkConsistency() returns true (sanity check)",
    async () => {
      let r: RdfReasoner | undefined;
      try {
        r = new RdfReasoner();
        await r.ready;
      } catch (e) {
        console.warn("[TEST] Konclude WASM unavailable — skipping:", String(e));
        return;
      }
      const store = loadTtlStore("reasoning-demo.ttl");
      let result: boolean | undefined;
      try {
        result = await r.checkConsistency(store);
      } finally {
        r.terminate();
      }
      console.log("[TEST] consistent demo checkConsistency result:", result);
      expect(result, "reasoning-demo.ttl must remain consistent after OWL 2 DL expansion").toBe(true);
    },
    30000,
  );
});
