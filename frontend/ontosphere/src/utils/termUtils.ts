import type { NamedNode } from "n3";
import { useOntologyStore } from "../stores/ontologyStore";
import {
  assertPlainObject,
  assertString,
  isPlainObject,
} from "./guards";
import {
  normalizeString,
} from "./normalizers";
import type { NamespaceEntry } from "../constants/namespaces";

// Re-export canonical type so callers that previously imported NamespaceRegistryEntry from termUtils still work.
export type { NamespaceEntry };
export type NamespaceRegistryEntry = NamespaceEntry;

type RegistryInput = NamespaceEntry[] | Record<string, string> | undefined;

interface TermDataOverrides {
  registry?: RegistryInput;
}

interface OntologyStoreSnapshot {
  namespaceRegistry: NamespaceEntry[];
}

function coerceNamespaceEntry(value: unknown, context: string): NamespaceEntry {
  assertPlainObject(value, context);
  const record = value as Record<string, unknown>;
  const prefix = normalizeString(record.prefix ?? "", `${context}.prefix`, {
    allowEmpty: true,
  });
  // Accept both .uri (new canonical) and .namespace (legacy inputs from tests/adapters)
  const uriRaw = record.uri ?? record.namespace;
  const uri = normalizeString(uriRaw, `${context}.uri`);
  const color =
    typeof record.color === "string" && record.color.trim().length > 0
      ? record.color.trim()
      : undefined;
  return { prefix, uri, ...(color !== undefined ? { color } : {}) };
}

function coerceNamespaceRegistry(
  source: RegistryInput,
  context: string,
): NamespaceEntry[] {
  if (typeof source === "undefined") return [];
  if (Array.isArray(source)) {
    return source.map((entry, index) =>
      coerceNamespaceEntry(entry, `${context}[${index}]`),
    );
  }
  if (isPlainObject(source)) {
    return Object.entries(source as Record<string, unknown>).map(
      ([prefix, uri]) => {
        assertString(uri, `${context}.${prefix}`);
        return coerceNamespaceEntry(
          { prefix, uri },
          `${context}.${prefix}`,
        );
      },
    );
  }
  throw new Error(`${context} must be an array or record of namespaces`);
}

function readOntologyStoreSnapshot(): OntologyStoreSnapshot {
  const getState =
    useOntologyStore && typeof (useOntologyStore as any).getState === "function"
      ? (useOntologyStore as any).getState
      : null;
  if (!getState) {
    return {
      namespaceRegistry: [],
    };
  }
  const state = getState() as Record<string, unknown>;
  return {
    namespaceRegistry: coerceNamespaceRegistry(
      state.namespaceRegistry as RegistryInput,
      "ontologyStore.namespaceRegistry",
    ),
  };
}

function resolveTermData(overrides?: TermDataOverrides): OntologyStoreSnapshot {
  let snapshot: OntologyStoreSnapshot | null = null;
  const ensureSnapshot = () => {
    if (!snapshot) snapshot = readOntologyStoreSnapshot();
    return snapshot;
  };

  const haveRegistryOverride =
    overrides && Object.prototype.hasOwnProperty.call(overrides, "registry");

  return {
    namespaceRegistry: haveRegistryOverride
      ? coerceNamespaceRegistry(overrides!.registry, "termData.registry")
      : ensureSnapshot().namespaceRegistry,
  };
}

/**
 * Extract the local name from a URI or prefixed name.
 */
export function shortLocalName(value?: string): string {
  if (!value) return "";
  const source = value.trim();
  if (!source) return "";
  const delimiters = ["#", "/", ":"];
  let position = -1;
  for (const delimiter of delimiters) {
    const idx = source.lastIndexOf(delimiter);
    if (idx > position) position = idx;
  }
  return position >= 0 ? source.slice(position + 1) : source;
}

/**
 * Normalize registry input to NamespaceEntry[] for compatibility with legacy map callers.
 */
export function normalizeRegistry(
  input?: RegistryInput,
): NamespaceEntry[] {
  return coerceNamespaceRegistry(input, "normalizeRegistry.input");
}

/**
 * Locate the registry entry whose uri best matches the provided IRI.
 * Prefers the longest matching uri.
 */
export function findRegistryEntryForIri(
  targetIri: string,
  registryInput?: RegistryInput,
): NamespaceEntry | undefined {
  const iri = normalizeString(targetIri, "findRegistryEntryForIri.targetIri");
  const { namespaceRegistry } = resolveTermData({
    registry: registryInput,
  });
  let winner: NamespaceEntry | undefined;
  for (const entry of namespaceRegistry) {
    if (!entry.uri) continue;
    if (!iri.startsWith(entry.uri)) continue;
    if (!winner || entry.uri.length > winner.uri.length) {
      winner = entry;
    }
  }
  return winner;
}

/**
 * Expand a prefixed name using the namespace registry.
 */
export function expandPrefixed(
  value: string,
  registryInput?: RegistryInput,
): string {
  const term = normalizeString(value, "expandPrefixed.value");
  if (term.includes("://") || term.startsWith("_:")) return term;
  const idx = term.indexOf(":");
  if (idx < 0) return term;
  const prefix = term.slice(0, idx);
  const local = term.slice(idx + 1);
  const { namespaceRegistry } = resolveTermData({ registry: registryInput });
  if (!namespaceRegistry.length) return term;
  const entry = namespaceRegistry.find((candidate) => {
    if (!candidate.uri) return false;
    if (candidate.prefix === prefix) return true;
    if (prefix === ":" || prefix === "") {
      return candidate.prefix === ":" || candidate.prefix === "";
    }
    return false;
  });
  if (!entry) return term;
  return `${entry.uri}${local}`;
}

/**
 * Convert an IRI into a prefixed representation using the namespace registry.
 * Returns the original IRI if no matching namespace is available.
 */
export function toPrefixed(
  iri: string,
  registryInput?: RegistryInput,
): string {
  const target = normalizeString(iri, "toPrefixed.iri");
  if (target.startsWith("_:")) return target;
  if (target.startsWith("urn:vg:bnode:")) return `_:${target.slice("urn:vg:bnode:".length)}`;
  const entry = findRegistryEntryForIri(target, registryInput);
  if (!entry) return target;

  // Check if this is an exact match (entity-specific prefix, not a namespace base)
  // If the namespace exactly matches the IRI, return just the prefix with colon
  if (entry.uri === target) {
    const prefix = entry.prefix ?? "";
    if (!prefix || prefix === ":") {
      return `:`;
    }
    return `${prefix}:`;
  }

  const local =
    target.startsWith(entry.uri) && entry.uri.length < target.length
      ? target.slice(entry.uri.length)
      : shortLocalName(target);
  const prefix = entry.prefix ?? "";
  if (!prefix || prefix === ":") {
    return `:${local}`;
  }
  return `${prefix}:${local}`;
}

/**
 * Resolve a palette color for the provided IRI using the namespace registry
 * and optional palette overrides keyed by prefix.
 *
 * Color resolution uses only the namespace registry.
 */
export function getNodeColor(
  targetIri: string,
  palette?: Record<string, string>,
  overrides?: TermDataOverrides,
): string | undefined {
  const iri = normalizeString(targetIri, "getNodeColor.targetIri");

  const entry = findRegistryEntryForIri(iri, overrides?.registry);

  // Primary: namespace registry color
  if (entry && entry.color) return entry.color;

  // Secondary: palette color keyed by prefix
  if (palette && entry && entry.prefix) {
    const prefix = entry.prefix;
    const paletteColor =
      palette[prefix] ??
      palette[prefix.toLowerCase()] ??
      palette[prefix.toUpperCase()];
    if (paletteColor) return paletteColor;
  }

  return undefined;
}
