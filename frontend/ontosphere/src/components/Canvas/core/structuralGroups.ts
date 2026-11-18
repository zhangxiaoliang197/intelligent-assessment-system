// src/components/Canvas/core/structuralGroups.ts

export type StructuralGroupMap = Map<string, string>; // memberIri → groupRootIri
export type SubclassParentMap = Map<string, string>;  // childIri → directParentIri

export interface StructuralGroupResult {
  groupMap: StructuralGroupMap;
  subclassParent: SubclassParentMap;
}

export interface RdfQuadLike {
  subject: { termType: string; value: string };
  predicate: { termType: string; value: string };
  object: { termType: string; value: string };
}

const RDFS_SUBCLASS_OF =
  "http://www.w3.org/2000/01/rdf-schema#subClassOf";
const RDF_REST =
  "http://www.w3.org/1999/02/22-rdf-syntax-ns#rest";
const RDF_NIL =
  "http://www.w3.org/1999/02/22-rdf-syntax-ns#nil";

const OWL_COLLECTION_PREDICATES = new Set([
  "http://www.w3.org/2002/07/owl#intersectionOf",
  "http://www.w3.org/2002/07/owl#unionOf",
  "http://www.w3.org/2002/07/owl#oneOf",
  "http://www.w3.org/2002/07/owl#disjointUnionOf",
  "http://www.w3.org/2002/07/owl#propertyChainAxiom",
  "http://www.w3.org/2002/07/owl#hasKey",
  "http://www.w3.org/2003/11/swrl#body",
  "http://www.w3.org/2003/11/swrl#head",
]);
// TODO: extend subclass grouping to rdfs:subPropertyOf for property hierarchies

/** Returns group membership map and raw subclass parent map. */
export function computeStructuralGroups(
  allQuads: readonly RdfQuadLike[],
): StructuralGroupResult {
  // ── 1. Build indexes ────────────────────────────────────────────────────────

  // subClassOf: child IRI → first parent IRI (NamedNodes only)
  const subclassParent = new Map<string, string>();

  // rdf:rest: consCell IRI → next node IRI
  const restNext = new Map<string, string>();

  // collection head: class IRI → list head IRI
  const collectionHeads: Array<{ classIri: string; headIri: string }> = [];

  for (const quad of allQuads) {
    const { subject, predicate, object } = quad;

    if (predicate.value === RDFS_SUBCLASS_OF) {
      // Only NamedNode subjects and objects
      if (
        subject.termType === "NamedNode" &&
        object.termType === "NamedNode" &&
        subject.value !== object.value
      ) {
        if (!subclassParent.has(subject.value)) {
          subclassParent.set(subject.value, object.value);
        }
      }
    } else if (predicate.value === RDF_REST) {
      if (
        subject.termType !== "DefaultGraph" &&
        subject.termType !== "Literal" &&
        object.termType !== "DefaultGraph" &&
        object.termType !== "Literal"
      ) {
        restNext.set(subject.value, object.value);
      }
    } else if (OWL_COLLECTION_PREDICATES.has(predicate.value)) {
      if (
        subject.termType === "NamedNode" &&
        object.termType !== "DefaultGraph" &&
        object.termType !== "Literal"
      ) {
        collectionHeads.push({
          classIri: subject.value,
          headIri: object.value,
        });
      }
    }
  }

  const result: StructuralGroupMap = new Map();

  // ── 2. Subclass chains ──────────────────────────────────────────────────────

  const rootCache = new Map<string, string | undefined>();

  /**
   * Walk up the subclass chain to find the transitive root.
   * Returns undefined if the node is the root (no parent) or if a cycle is
   * detected that would make the node its own root.
   */
  function findRoot(iri: string): string | undefined {
    if (rootCache.has(iri)) {
      return rootCache.get(iri);
    }

    const visited = new Set<string>();
    let current = iri;

    while (true) {
      if (visited.has(current)) {
        // Cycle detected — the starting node has no distinct root
        rootCache.set(iri, undefined);
        return undefined;
      }
      visited.add(current);

      const parent = subclassParent.get(current);
      if (parent === undefined) {
        // current IS the root
        rootCache.set(iri, current);
        return current;
      }
      current = parent;
    }
  }

  for (const child of subclassParent.keys()) {
    const root = findRoot(child);
    // Only map when root is different from child (child is not the root itself)
    if (root !== undefined && root !== child) {
      result.set(child, root);
    }
  }

  // ── 3. OWL collection cons-cells ────────────────────────────────────────────

  for (const { classIri, headIri } of collectionHeads) {
    const visited = new Set<string>();
    let current: string | undefined = headIri;

    while (current !== undefined && current !== RDF_NIL) {
      if (visited.has(current)) break; // cycle guard
      visited.add(current);

      // Map this cons-cell node → the owning class
      result.set(current, classIri);

      current = restNext.get(current);
    }
  }

  return { groupMap: result, subclassParent };
}

/**
 * Re-root a structural group map so every root is an on-canvas IRI.
 *
 * When a root isn't on canvas, walk down the subclass tree and find the
 * first descendants that ARE on canvas — each becomes a sub-group root
 * owning only its own on-canvas subclass descendants.
 */
export function rerootForCanvas(
  groupMap: StructuralGroupMap,
  subclassParent: SubclassParentMap,
  onCanvas: ReadonlySet<string>,
): StructuralGroupMap {
  // Build children map (parent → children) from parent map
  const children = new Map<string, string[]>();
  for (const [child, parent] of subclassParent) {
    if (!children.has(parent)) children.set(parent, []);
    children.get(parent)!.push(child);
  }

  // Collect off-canvas roots
  const rootToMembers = new Map<string, Set<string>>();
  for (const [member, root] of groupMap) {
    if (!rootToMembers.has(root)) rootToMembers.set(root, new Set());
    rootToMembers.get(root)!.add(member);
  }

  const result: StructuralGroupMap = new Map(groupMap);

  for (const [root, members] of rootToMembers) {
    if (onCanvas.has(root)) continue; // root on canvas — keep as-is

    // Walk down from the off-canvas root to find on-canvas sub-roots.
    // Each on-canvas node in the subtree becomes a sub-root owning its
    // own on-canvas descendants.
    const subRoots = new Map<string, string[]>(); // subRoot → members

    function assignSubRoot(iri: string, currentSubRoot: string | null): void {
      const isOnCanvas = onCanvas.has(iri) && members.has(iri);
      if (isOnCanvas) {
        currentSubRoot = iri;
      }
      if (currentSubRoot && iri !== currentSubRoot && isOnCanvas) {
        if (!subRoots.has(currentSubRoot)) subRoots.set(currentSubRoot, []);
        subRoots.get(currentSubRoot)!.push(iri);
      }
      for (const child of children.get(iri) ?? []) {
        assignSubRoot(child, currentSubRoot);
      }
    }

    assignSubRoot(root, null);

    // Rewrite groupMap entries: members of sub-roots point to their sub-root
    for (const [subRoot, subMembers] of subRoots) {
      for (const m of subMembers) {
        result.set(m, subRoot);
      }
      // Sub-root itself is no longer a member of the old root
      result.delete(subRoot);
    }
    // Members not claimed by any sub-root become standalone — remove mapping
    for (const m of members) {
      if (result.get(m) === root) result.delete(m);
    }
  }

  return result;
}
