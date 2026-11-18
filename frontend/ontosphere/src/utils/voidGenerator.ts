// src/utils/voidGenerator.ts
//
// Pure VoID + DCAT dataset-metadata generator.
//
// This module is intentionally free of any worker / rdfManager dependency: it
// takes a plain `DatasetFacts` object (counts, partitions, namespaces, optional
// scraped metadata) and emits a Turtle string plus a structured summary. The
// DATA-GATHERING (running SPARQL COUNT / GROUP BY queries against the live
// store) lives in the MCP tool layer; this file only does RDF-GENERATION, so it
// is unit-testable with fixture inputs and never needs a live worker.

import { WELL_KNOWN_BY_URL, WELL_KNOWN_BY_PREFIX } from './wellKnownOntologies';

// ---------------------------------------------------------------------------
// Vocabulary IRIs used in the output
// ---------------------------------------------------------------------------
const VOID = 'http://rdfs.org/ns/void#';
const DCAT = 'http://www.w3.org/ns/dcat#';
const DCT = 'http://purl.org/dc/terms/';
const FOAF = 'http://xmlns.com/foaf/0.1/';
const OWL = 'http://www.w3.org/2002/07/owl#';
const RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#';

/** Prefixes declared in every generated document. */
const OUTPUT_PREFIXES: Record<string, string> = {
  void: VOID,
  dcat: DCAT,
  dcterms: DCT,
  foaf: FOAF,
  owl: OWL,
  rdf: RDF,
  xsd: 'http://www.w3.org/2001/XMLSchema#',
};

// ---------------------------------------------------------------------------
// Input / output types
// ---------------------------------------------------------------------------

/** A single class partition entry: a class IRI and how many instances it has. */
export interface ClassPartition {
  classIri: string;
  entities: number;
}

/** A single property partition entry: a predicate IRI and how many triples use it. */
export interface PropertyPartition {
  propertyIri: string;
  triples: number;
}

/** Scraped dataset-level metadata (any of these may be absent). */
export interface DatasetMetadata {
  title?: string;
  description?: string;
  license?: string;
  /** Creator — either an IRI (foaf:Agent) or a plain-text name. */
  creator?: string;
  versionInfo?: string;
}

/**
 * Everything the pure generator needs. Gathered by the MCP tool via rdfManager;
 * supplied directly by fixtures in unit tests.
 */
export interface DatasetFacts {
  /** void:triples — total asserted (and optionally inferred) triple count. */
  triples: number;
  /** void:distinctSubjects (also used for void:entities). */
  distinctSubjects: number;
  /** void:distinctObjects. */
  distinctObjects: number;
  /** void:classes — number of distinct classes used. */
  classes: number;
  /** void:properties — number of distinct predicates used. */
  properties: number;
  /** Per-class instance counts (already sorted desc by the gatherer, or not). */
  classPartitions: ClassPartition[];
  /** Per-predicate triple counts. */
  propertyPartitions: PropertyPartition[];
  /** Namespace prefixes registered in the workspace ({ prefix, uri }). */
  namespaces: Array<{ prefix: string; uri: string }>;
  /** Optional scraped dataset metadata. */
  metadata?: DatasetMetadata;
  /** Whether inferred triples (urn:vg:inferred) were folded into the counts. */
  includeInferred?: boolean;
  /** Export distribution formats to advertise via dcat:distribution. */
  distributionFormats?: string[];
}

export interface GenerateOptions {
  /** IRI for the dcat:Dataset / void:Dataset subject. Default urn:vg:data. */
  datasetIri?: string;
  /** Cap on classPartition entries emitted. Default 20. */
  topClasses?: number;
  /** Cap on propertyPartition entries emitted. Default 20. */
  topProperties?: number;
}

/** A used-vocabulary descriptor for the structured summary. */
export interface VocabularySummary {
  prefix?: string;
  uri: string;
  name?: string;
}

export interface DatasetSummary {
  triples: number;
  classes: number;
  properties: number;
  subjects: number;
  distinctObjects: number;
  vocabularies: VocabularySummary[];
  topClasses: ClassPartition[];
  topProperties: PropertyPartition[];
}

export interface GeneratedDatasetMetadata {
  turtle: string;
  summary: DatasetSummary;
}

// ---------------------------------------------------------------------------
// Turtle serialisation helpers
// ---------------------------------------------------------------------------

/** Default media types advertised when the caller does not pass any. */
const DEFAULT_DISTRIBUTION_FORMATS = ['turtle', 'jsonld', 'rdfxml', 'nquads', 'trig'];

const FORMAT_MEDIA_TYPES: Record<string, string> = {
  turtle: 'text/turtle',
  jsonld: 'application/ld+json',
  rdfxml: 'application/rdf+xml',
  nquads: 'application/n-quads',
  trig: 'application/trig',
  ntriples: 'application/n-triples',
};

/**
 * Escape a string literal for Turtle (quotes, backslashes, newlines, and any
 * remaining C0 control character). The explicit \n/\r/\t/\"/\\ escapes run
 * first; a final catch-all maps any leftover control char (U+0000–U+001F that
 * was not one of the handled ones) to a Turtle \\uXXXX numeric escape so the
 * literal is always valid for strict parsers. The catch-all cannot double-escape
 * the backslash introduced above because 0x5C is outside the C0 control range.
 */
function escapeLiteral(value: string): string {
  return value
    .replace(/\\/g, '\\\\')
    .replace(/"/g, '\\"')
    .replace(/\n/g, '\\n')
    .replace(/\r/g, '\\r')
    .replace(/\t/g, '\\t')
    // Catch-all for remaining C0 control chars (U+0000-U+001F): the \n, \r
    // and \t cases are already escaped above, so this only hits NUL, BEL,
    // BS, VT, FF and the other C0 controls. Emit them as Turtle \uXXXX
    // numeric escapes so the literal is valid even for strict parsers.
    // eslint-disable-next-line no-control-regex
    .replace(/[\x00-\x1F]/g, c =>
      '\\u' + c.charCodeAt(0).toString(16).toUpperCase().padStart(4, '0'),
    );
}

/**
 * Characters that an RDF 1.1 IRIREF must NOT contain: `< > " { } | ^ \`
 * (backtick), backslash, space, and control chars U+0000–U+0020. If an IRI
 * candidate contains any of these it cannot be written safely inside <...>
 * (doing so would let scraped/untrusted values inject or break triples).
 */
// eslint-disable-next-line no-control-regex
const FORBIDDEN_IRIREF_CHAR = /[\x00-\x20<>"{}|^`\\]/;

/**
 * True when `value` is safe to emit verbatim inside an IRIREF (<...>). Returns
 * false for any value containing a forbidden IRIREF character so the caller can
 * fall back to emitting a (safely escaped) string literal instead.
 */
function isSafeIriRef(value: string): boolean {
  return !FORBIDDEN_IRIREF_CHAR.test(value);
}

/**
 * Emit an IRI in <...> form when it is a safe IRIREF; otherwise fall back to an
 * escaped string literal so no forbidden character can break or inject triples.
 * This is the single choke point for every IRI we write.
 */
function iriRef(iri: string): string {
  return isSafeIriRef(iri) ? `<${iri}>` : strLiteral(iri);
}

/** Build a Turtle string literal, optionally typed/lang-tagged. */
function strLiteral(value: string): string {
  return `"${escapeLiteral(value)}"`;
}

/**
 * Is this string a safe absolute IRI (has a scheme) we can write as an IRIREF?
 * Requires a scheme prefix AND that the value contains no forbidden IRIREF
 * character, so dirty scraped values (with `< > " ;` etc.) are treated as NOT
 * IRIs and get emitted as escaped string literals instead.
 */
function looksLikeIri(value: string): boolean {
  return /^[a-zA-Z][a-zA-Z0-9+.-]*:[^\s]+$/.test(value) && isSafeIriRef(value);
}

// ---------------------------------------------------------------------------
// Vocabulary resolution
// ---------------------------------------------------------------------------

/**
 * From the set of namespace URIs actually used in the data, resolve a sorted,
 * de-duplicated list of vocabulary base IRIs together with prefix/name when the
 * namespace is a well-known vocabulary. Drives both void:vocabulary and
 * dct:conformsTo as well as the structured summary.
 */
function resolveVocabularies(
  usedNamespaceUris: Iterable<string>,
): VocabularySummary[] {
  const seen = new Set<string>();
  const out: VocabularySummary[] = [];
  for (const uri of usedNamespaceUris) {
    if (!uri || seen.has(uri)) continue;
    seen.add(uri);
    const prefixes = WELL_KNOWN_BY_URL.get(uri);
    const prefix = prefixes && prefixes.length > 0 ? prefixes[0] : undefined;
    const name = prefix ? WELL_KNOWN_BY_PREFIX[prefix]?.name : undefined;
    out.push({ uri, prefix, name });
  }
  // Stable ordering: well-known (named) first, then by URI.
  out.sort((a, b) => {
    if (!!a.name !== !!b.name) return a.name ? -1 : 1;
    return a.uri.localeCompare(b.uri);
  });
  return out;
}

/**
 * Derive the namespace base IRI of a term IRI. Splits at the last '#' or '/'.
 * Returns undefined for blank-node / non-IRI tokens.
 */
function namespaceOf(iri: string): string | undefined {
  if (!iri || iri.startsWith('_:') || iri.startsWith('urn:vg:bnode')) return undefined;
  const hash = iri.lastIndexOf('#');
  if (hash >= 0) return iri.slice(0, hash + 1);
  const slash = iri.lastIndexOf('/');
  if (slash >= 0) return iri.slice(0, slash + 1);
  return undefined;
}

// ---------------------------------------------------------------------------
// Main generator
// ---------------------------------------------------------------------------

/**
 * Produce a VoID + DCAT description of a dataset as Turtle plus a structured
 * summary. Pure: depends only on its inputs and the static well-known registry.
 */
export function generateDatasetMetadata(
  facts: DatasetFacts,
  opts: GenerateOptions = {},
): GeneratedDatasetMetadata {
  const datasetIri = opts.datasetIri ?? 'urn:vg:data';
  const topClasses = opts.topClasses ?? 20;
  const topProperties = opts.topProperties ?? 20;

  const classParts = [...facts.classPartitions]
    .sort((a, b) => b.entities - a.entities)
    .slice(0, topClasses);
  const propParts = [...facts.propertyPartitions]
    .sort((a, b) => b.triples - a.triples)
    .slice(0, topProperties);

  // Collect namespace URIs actually used: from registered prefixes whose URI
  // appears as the base of any class/property IRI, plus the base IRIs of the
  // partition terms directly (covers vocabularies without a registered prefix).
  const usedNamespaces = new Set<string>();
  const partitionIris = [
    ...classParts.map(c => c.classIri),
    ...propParts.map(p => p.propertyIri),
  ];
  const partitionBaseUris = new Set<string>();
  for (const iri of partitionIris) {
    const base = namespaceOf(iri);
    if (base) partitionBaseUris.add(base);
  }
  // Prefer registered namespace URIs (canonical form) when they match a used base.
  for (const ns of facts.namespaces) {
    if (!ns.uri) continue;
    if (partitionBaseUris.has(ns.uri)) usedNamespaces.add(ns.uri);
  }
  // Add any used base IRI not covered by a registered prefix.
  for (const base of partitionBaseUris) usedNamespaces.add(base);

  const vocabularies = resolveVocabularies(usedNamespaces);

  const meta = facts.metadata ?? {};
  const title = meta.title?.trim() || 'Ontosphere Dataset';
  const description =
    meta.description?.trim() ||
    `RDF dataset authored in Ontosphere: ${facts.triples} triples across ` +
      `${facts.classes} classes and ${facts.properties} properties` +
      `${facts.includeInferred ? ' (including inferred triples)' : ''}.`;

  const distFormats =
    facts.distributionFormats && facts.distributionFormats.length > 0
      ? facts.distributionFormats
      : DEFAULT_DISTRIBUTION_FORMATS;

  // ---- Turtle assembly --------------------------------------------------
  const lines: string[] = [];

  for (const [prefix, uri] of Object.entries(OUTPUT_PREFIXES)) {
    lines.push(`@prefix ${prefix}: <${uri}> .`);
  }
  lines.push('');

  const ds = iriRef(datasetIri);

  // Type declarations: both a void:Dataset and a dcat:Dataset.
  lines.push(`${ds} a void:Dataset, dcat:Dataset ;`);

  const dsStatements: string[] = [];
  dsStatements.push(`  dcterms:title ${strLiteral(title)}`);
  dsStatements.push(`  dcterms:description ${strLiteral(description)}`);

  if (meta.license) {
    dsStatements.push(
      `  dcterms:license ${looksLikeIri(meta.license) ? iriRef(meta.license) : strLiteral(meta.license)}`,
    );
  }
  if (meta.creator) {
    dsStatements.push(
      `  dcterms:creator ${looksLikeIri(meta.creator) ? iriRef(meta.creator) : strLiteral(meta.creator)}`,
    );
  }
  if (meta.versionInfo) {
    dsStatements.push(`  owl:versionInfo ${strLiteral(meta.versionInfo)}`);
  }

  // VoID statistics.
  dsStatements.push(`  void:triples ${facts.triples}`);
  dsStatements.push(`  void:entities ${facts.distinctSubjects}`);
  dsStatements.push(`  void:classes ${facts.classes}`);
  dsStatements.push(`  void:properties ${facts.properties}`);
  dsStatements.push(`  void:distinctSubjects ${facts.distinctSubjects}`);
  dsStatements.push(`  void:distinctObjects ${facts.distinctObjects}`);

  // Vocabularies used (void:vocabulary) + DCAT conformance (dct:conformsTo).
  for (const v of vocabularies) {
    dsStatements.push(`  void:vocabulary ${iriRef(v.uri)}`);
  }
  for (const v of vocabularies) {
    dsStatements.push(`  dcterms:conformsTo ${iriRef(v.uri)}`);
  }

  // DCAT distributions referencing the export formats.
  const distNodes: string[] = [];
  for (const fmt of distFormats) {
    distNodes.push(`_:dist_${fmt.replace(/[^a-zA-Z0-9]/g, '_')}`);
  }
  for (const node of distNodes) {
    dsStatements.push(`  dcat:distribution ${node}`);
  }

  // Class / property partitions as blank-node nested objects.
  for (let i = 0; i < classParts.length; i++) {
    dsStatements.push(`  void:classPartition _:classPart${i}`);
  }
  for (let i = 0; i < propParts.length; i++) {
    dsStatements.push(`  void:propertyPartition _:propPart${i}`);
  }

  lines.push(dsStatements.join(' ;\n') + ' .');
  lines.push('');

  // Distribution blank nodes.
  for (let i = 0; i < distFormats.length; i++) {
    const fmt = distFormats[i];
    const node = distNodes[i];
    const media = FORMAT_MEDIA_TYPES[fmt] ?? 'application/octet-stream';
    lines.push(
      `${node} a dcat:Distribution ; dcterms:format ${strLiteral(fmt)} ; dcat:mediaType ${strLiteral(media)} .`,
    );
  }
  if (distFormats.length > 0) lines.push('');

  // Class partitions.
  for (let i = 0; i < classParts.length; i++) {
    const cp = classParts[i];
    lines.push(
      `_:classPart${i} void:class ${iriRef(cp.classIri)} ; void:entities ${cp.entities} .`,
    );
  }
  if (classParts.length > 0) lines.push('');

  // Property partitions.
  for (let i = 0; i < propParts.length; i++) {
    const pp = propParts[i];
    lines.push(
      `_:propPart${i} void:property ${iriRef(pp.propertyIri)} ; void:triples ${pp.triples} .`,
    );
  }

  const turtle = lines.join('\n').replace(/\n+$/g, '') + '\n';

  // ---- Structured summary ----------------------------------------------
  const summary: DatasetSummary = {
    triples: facts.triples,
    classes: facts.classes,
    properties: facts.properties,
    subjects: facts.distinctSubjects,
    distinctObjects: facts.distinctObjects,
    vocabularies,
    topClasses: classParts,
    topProperties: propParts,
  };

  return { turtle, summary };
}
