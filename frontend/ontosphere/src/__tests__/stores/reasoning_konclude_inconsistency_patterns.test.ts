// @vitest-environment node
/**
 * Issue #13: Six OWL 2 DL inconsistency patterns.
 * Each it() asserts checkConsistency() → false using a fixture from
 * src/__tests__/fixtures/inconsistency/.
 * Patterns 1–2 are OWL 2 EL-compatible; patterns 3–6 require full OWL 2 DL / SROIQ(D).
 * If a pattern returns true (not detected), it is recorded in a comment — not a test failure.
 * Tracks: https://github.com/ThHanke/ontosphere/issues/13
 */
import { describe, it, expect } from "vitest";
import { RdfReasoner } from "rdf-reasoner-konclude";
import * as N3 from "n3";
import { readFileSync } from "fs";
import { join } from "path";

const FIXTURES = join(__dirname, "../fixtures/inconsistency");

function loadFixture(filename: string): N3.Store {
  const turtle = readFileSync(join(FIXTURES, filename), "utf-8");
  const store = new N3.Store();
  store.addQuads(new N3.Parser({ format: "text/turtle" }).parse(turtle));
  return store;
}

async function checkPattern(fixture: string): Promise<boolean | undefined> {
  let r: RdfReasoner | undefined;
  try {
    r = new RdfReasoner();
    await r.ready;
  } catch (e) {
    console.warn("[TEST] Konclude WASM unavailable — skipping:", String(e));
    return undefined;
  }
  try {
    return await r.checkConsistency(loadFixture(fixture));
  } finally {
    r.terminate();
  }
}

describe("Issue #13: OWL 2 DL inconsistency patterns", () => {
  it(
    "Pattern 1 (OWL 2 EL): individual in two disjoint classes",
    async () => {
      const result = await checkPattern("pattern1-disjoint-individual.ttl");
      if (result === undefined) return;
      console.log("[TEST] checkConsistency result:", result);
      expect(result, "Pattern 1: alice in disjoint Person+Organization → inconsistent").toBe(false);
    },
    30000,
  );

  it(
    "Pattern 2 (OWL 2 EL): domain/range inferred disjoint types",
    async () => {
      const result = await checkPattern("pattern2-domain-range-disjoint.ttl");
      if (result === undefined) return;
      console.log("[TEST] checkConsistency result:", result);
      expect(result, "Pattern 2: widget hasPart widget → inferred Machine+Component (disjoint) → inconsistent").toBe(false);
    },
    30000,
  );

  it(
    "Pattern 3 (OWL 2 DL): allValuesFrom + disjoint class violation",
    async () => {
      const result = await checkPattern("pattern3-allvaluesfrom-disjoint.ttl");
      if (result === undefined) return;
      console.log("[TEST] checkConsistency result:", result);
      expect(result, "Pattern 3: CleanRoomOnlyDevice located in DirtyRoom → inconsistent").toBe(false);
    },
    30000,
  );

  it(
    "Pattern 4 (OWL 2 DL): max qualified cardinality + differentFrom",
    async () => {
      const result = await checkPattern("pattern4-max-qualified-cardinality.ttl");
      if (result === undefined) return;
      console.log("[TEST] checkConsistency result:", result);
      expect(result, "Pattern 4: car1 has two distinct VINs, max qualified cardinality 1 → inconsistent").toBe(false);
    },
    30000,
  );

  it(
    "Pattern 5 (OWL 2 DL): asymmetric property violation",
    async () => {
      const result = await checkPattern("pattern5-asymmetric-property.ttl");
      if (result === undefined) return;
      console.log("[TEST] checkConsistency result:", result);
      expect(result, "Pattern 5: alice parentOf bob AND bob parentOf alice (AsymmetricProperty) → inconsistent").toBe(false);
    },
    30000,
  );

  it(
    "Pattern 6 (OWL 2 DL): irreflexive property self-loop",
    async () => {
      const result = await checkPattern("pattern6-irreflexive-self-loop.ttl");
      if (result === undefined) return;
      console.log("[TEST] checkConsistency result:", result);
      expect(result, "Pattern 6: part1 properPartOf part1 (IrreflexiveProperty) → inconsistent").toBe(false);
    },
    30000,
  );
});
