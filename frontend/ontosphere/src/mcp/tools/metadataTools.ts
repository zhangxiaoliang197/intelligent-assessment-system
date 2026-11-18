// src/mcp/tools/metadataTools.ts
//
// MCP tool: generateDatasetMetadata — VoID + DCAT description of the current
// dataset for FAIR publishing.
//
// This file owns the DATA-GATHERING half of the feature: it runs SPARQL
// COUNT / GROUP BY queries (plus getGraphCounts / getNamespaces) against the
// live store via rdfManager's public methods, then hands the assembled
// `DatasetFacts` to the pure generator in voidGenerator.ts, which owns the
// RDF-GENERATION half. The split keeps the generator unit-testable without a
// worker.

import type { McpTool, McpResult } from '@/mcp/types';
import { rdfManager } from '@/utils/rdfManager';
import {
  generateDatasetMetadata,
  type DatasetFacts,
  type ClassPartition,
  type PropertyPartition,
  type DatasetMetadata,
} from '@/utils/voidGenerator';

const DATA_GRAPH = 'urn:vg:data';
const INFERRED_GRAPH = 'urn:vg:inferred';
const PARTITION_LIMIT = 50;

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';

/** FROM clauses for the graphs we count over. */
function fromClause(includeInferred: boolean): string {
  const graphs = includeInferred ? [DATA_GRAPH, INFERRED_GRAPH] : [DATA_GRAPH];
  return graphs.map(g => `FROM <${g}>`).join('\n');
}

/** Run a SELECT and return the rows, or [] on failure/non-select. */
async function selectRows(sparql: string): Promise<Array<Record<string, string>>> {
  const res = await rdfManager.sparqlQuery(sparql, { limit: 10000 });
  if (res && res.type === 'select' && Array.isArray(res.rows)) {
    return res.rows as Array<Record<string, string>>;
  }
  return [];
}

/** Read a single scalar count from a `SELECT (COUNT(...) AS ?cnt)` query. */
async function scalarCount(sparql: string): Promise<number> {
  const rows = await selectRows(sparql);
  if (rows.length === 0) return 0;
  // SPARQL 1.1 forbids reusing an in-scope variable as a projection alias, so
  // every scalar count projects to a distinct `?cnt`. Fall back to the first
  // column for resilience against engines that name the column differently.
  const v = rows[0].cnt ?? Object.values(rows[0])[0];
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

const generateDatasetMetadataTool: McpTool = {
  name: 'generateDatasetMetadata',
  description:
    'Generate VoID + DCAT metadata describing the current dataset (triple/class/property ' +
    'counts, partitions, vocabularies used) for FAIR publishing.',
  inputSchema: {
    type: 'object',
    properties: {
      includeInferred: {
        type: 'boolean',
        default: false,
        description: 'Fold inferred triples (urn:vg:inferred) into the counts and partitions.',
      },
      format: {
        type: 'string',
        enum: ['turtle'],
        default: 'turtle',
        description: 'Serialisation of the metadata document. Only "turtle" is currently supported.',
      },
    },
  },
  async handler(params): Promise<McpResult> {
    try {
      const { includeInferred = false } = (params ?? {}) as {
        includeInferred?: boolean;
        format?: string;
      };
      const FROM = fromClause(includeInferred);

      // --- Scalar counts -------------------------------------------------
      // Total triples: prefer getGraphCounts (cheap, exact per-graph), fall
      // back to a SPARQL COUNT if a graph is absent from the counts map.
      let triples = 0;
      try {
        const counts = await rdfManager.getGraphCounts();
        triples = (counts[DATA_GRAPH] ?? 0) + (includeInferred ? counts[INFERRED_GRAPH] ?? 0 : 0);
      } catch {
        triples = 0;
      }
      if (triples === 0) {
        triples = await scalarCount(
          `SELECT (COUNT(*) AS ?cnt) ${FROM} WHERE { ?s ?p ?o }`,
        );
      }

      const distinctSubjects = await scalarCount(
        `SELECT (COUNT(DISTINCT ?s) AS ?cnt) ${FROM} WHERE { ?s ?p ?o }`,
      );
      const distinctObjects = await scalarCount(
        `SELECT (COUNT(DISTINCT ?o) AS ?cnt) ${FROM} WHERE { ?s ?p ?o }`,
      );
      const classes = await scalarCount(
        `SELECT (COUNT(DISTINCT ?c) AS ?cnt) ${FROM} WHERE { ?s <${RDF_TYPE}> ?c }`,
      );
      const properties = await scalarCount(
        `SELECT (COUNT(DISTINCT ?p) AS ?cnt) ${FROM} WHERE { ?s ?p ?o }`,
      );

      // --- Partitions ----------------------------------------------------
      const classRows = await selectRows(
        `SELECT ?class (COUNT(?s) AS ?n) ${FROM} WHERE { ?s <${RDF_TYPE}> ?class } ` +
          `GROUP BY ?class ORDER BY DESC(?n) LIMIT ${PARTITION_LIMIT}`,
      );
      const classPartitions: ClassPartition[] = classRows
        .filter(r => r.class)
        .map(r => ({ classIri: r.class, entities: Number(r.n) || 0 }));

      const propRows = await selectRows(
        `SELECT ?p (COUNT(*) AS ?n) ${FROM} WHERE { ?s ?p ?o } ` +
          `GROUP BY ?p ORDER BY DESC(?n) LIMIT ${PARTITION_LIMIT}`,
      );
      const propertyPartitions: PropertyPartition[] = propRows
        .filter(r => r.p)
        .map(r => ({ propertyIri: r.p, triples: Number(r.n) || 0 }));

      // --- Dataset-level metadata scraped from the data ------------------
      const metadata = await scrapeDatasetMetadata(FROM);

      const namespaces = rdfManager
        .getNamespaces()
        .map(ns => ({ prefix: ns.prefix, uri: ns.uri }));

      const facts: DatasetFacts = {
        triples,
        distinctSubjects,
        distinctObjects,
        classes,
        properties,
        classPartitions,
        propertyPartitions,
        namespaces,
        metadata,
        includeInferred,
      };

      const { turtle, summary } = generateDatasetMetadata(facts, {
        datasetIri: DATA_GRAPH,
      });

      return {
        success: true,
        data: {
          turtle,
          summary: {
            triples: summary.triples,
            classes: summary.classes,
            properties: summary.properties,
            subjects: summary.subjects,
            vocabularies: summary.vocabularies,
            topClasses: summary.topClasses,
            topProperties: summary.topProperties,
          },
        },
      };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

/**
 * Best-effort scrape of dataset-level metadata (title, description, license,
 * creator, version) from any owl:Ontology / dcat:Dataset / dcterms-annotated
 * subject in the data. Returns an empty object when nothing is found.
 */
async function scrapeDatasetMetadata(FROM: string): Promise<DatasetMetadata> {
  const meta: DatasetMetadata = {};
  const rows = await selectRows(
    `SELECT ?p ?o ${FROM} WHERE {
       ?s a <http://www.w3.org/2002/07/owl#Ontology> .
       ?s ?p ?o .
     } LIMIT 200`,
  );
  for (const r of rows) {
    const p = r.p;
    const o = r.o;
    if (!p || o == null) continue;
    switch (p) {
      case 'http://purl.org/dc/terms/title':
      case 'http://purl.org/dc/elements/1.1/title':
      case 'http://www.w3.org/2000/01/rdf-schema#label':
        if (!meta.title) meta.title = o;
        break;
      case 'http://purl.org/dc/terms/description':
      case 'http://purl.org/dc/elements/1.1/description':
      case 'http://www.w3.org/2000/01/rdf-schema#comment':
        if (!meta.description) meta.description = o;
        break;
      case 'http://purl.org/dc/terms/license':
        if (!meta.license) meta.license = o;
        break;
      case 'http://purl.org/dc/terms/creator':
      case 'http://purl.org/dc/elements/1.1/creator':
        if (!meta.creator) meta.creator = o;
        break;
      case 'http://www.w3.org/2002/07/owl#versionInfo':
        if (!meta.versionInfo) meta.versionInfo = o;
        break;
      default:
        break;
    }
  }
  return meta;
}

export const metadataTools: McpTool[] = [generateDatasetMetadataTool];
