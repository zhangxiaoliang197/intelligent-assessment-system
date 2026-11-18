// src/mcp/tools/nodes.ts
import * as Reactodia from '@reactodia/workspace';
import type { McpTool } from '@/mcp/types';
import { rdfManager } from '@/utils/rdfManager';
import { getWorkspaceRefs } from '@/mcp/workspaceContext';
import { focusElementOnCanvas } from './layout';
import { expandIri } from './iriUtils';
import { abbreviateIri } from './graph';
import { ADD_NODE_PIPELINE_DELAY_MS } from '@/utils/canvasConstants';
import { useShaclResultStore } from '@/stores/shaclResultStore';
import { getProvenanceRecorder, type ProvQuad } from '@/mcp/provenance';

const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const RDFS_LABEL = 'http://www.w3.org/2000/01/rdf-schema#label';

/** Classify an object value as iri / bnode / literal for faithful revert. */
function classifyObjectType(value: string): ProvQuad['ot'] {
  if (value.startsWith('_:')) return 'bnode';
  if (/^[a-zA-Z][a-zA-Z0-9+\-.]*:/.test(value)) return 'iri';
  return 'literal';
}

function getLabel(data: Reactodia.ElementModel | undefined): string {
  return (data?.properties?.[RDFS_LABEL]?.[0] as { value?: string } | undefined)?.value ?? '';
}

function findEntityElement(iri: string, model: Reactodia.DataDiagramModel): Reactodia.EntityElement | undefined {
  return model.elements.find(
    e => e instanceof Reactodia.EntityElement && (e as Reactodia.EntityElement).iri === iri
  ) as Reactodia.EntityElement | undefined;
}

const addNode: McpTool = {
  name: 'addNode',
  description: 'Add an entity (node) to the canvas by IRI, with optional RDF type(s) and label.',
  inputSchema: {
    type: 'object',
    properties: {
      iri: { type: 'string' },
      typeIri: { type: 'string', description: 'Single rdf:type IRI. Use typeIris for multiple types.' },
      typeIris: {
        type: 'array',
        items: { type: 'string' },
        description: 'One or more rdf:type IRIs. Use this when an individual needs multiple types (e.g. ["owl:NamedIndividual","ex:SalamiTopping"]). Takes precedence over typeIri.',
      },
      label: { type: 'string' },
    },
    required: ['iri'],
  },
  handler: async (params) => {
    try {
      const raw = params as { iri?: string; typeIri?: string; typeIris?: string[]; type?: string; label?: string };
      if (!raw.iri) return { success: false, error: 'iri is required' };
      const iri = expandIri(raw.iri);
      if (iri.startsWith('Unknown prefix:')) return { success: false, error: iri };
      if (/ /.test(iri)) {
        const blankNodeHint = /^\s+:/.test(iri)
          ? ` You passed "${iri}" — blank-node label with leading spaces. Use "_:${iri.trim().slice(1)}" (must start with "_:", not spaces).`
          : ` You passed "${iri}".`;
        return { success: false, error: `Node IRI contains spaces and is not valid.${blankNodeHint}` };
      }

      // Resolve all type IRIs — typeIris array takes precedence over scalar typeIri/type
      const rawTypes: string[] = raw.typeIris?.length
        ? raw.typeIris
        : (raw.typeIri ?? raw.type) ? [(raw.typeIri ?? raw.type)!] : [];
      const typeIris: string[] = [];
      for (const t of rawTypes) {
        const expanded = expandIri(t);
        if (expanded.startsWith('Unknown prefix:')) return { success: false, error: expanded };
        typeIris.push(expanded);
      }
      const { label } = raw;

      // Batch all triples in one awaitable worker call so onSubjectsChange fires
      // only once, after all rdf:type and rdfs:label triples are already in the store.
      // Triples land in urn:vg:data → onSubjectsChange → filterByViewMode →
      // createElement in the correct view. No direct canvas mutation here.
      const adds: Array<{ s: string; p: string; o: string }> = [];
      for (const t of typeIris) adds.push({ s: iri, p: RDF_TYPE, o: t });
      if (label) adds.push({ s: iri, p: RDFS_LABEL, o: label });
      if (adds.length > 0) {
        await rdfManager.applyBatch({ adds });
        // Provenance must NEVER flip a successful mutation to success:false.
        try {
          await getProvenanceRecorder().recordEdit({
            tool: 'addNode',
            added: adds.map((a) => ({
              s: a.s,
              p: a.p,
              o: a.o,
              ot: a.p === RDFS_LABEL ? 'literal' : classifyObjectType(a.o),
            })),
          });
        } catch (provErr) {
          console.warn('[addNode] provenance recordEdit failed (mutation still applied)', provErr);
        }
      }

      // Wait for the RDF→canvas pipeline before navigating; navigateToIri handles view-switching.
      await new Promise(r => setTimeout(r, ADD_NODE_PIPELINE_DELAY_MS));
      const { navigateToIri } = getWorkspaceRefs();
      navigateToIri?.(iri);

      return { success: true, data: { iri, types: typeIris } };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const removeNode: McpTool = {
  name: 'removeNode',
  description: 'Remove an entity and all its triples from the canvas.',
  inputSchema: {
    type: 'object',
    properties: {
      iri: { type: 'string' },
    },
    required: ['iri'],
  },
  handler: async (params) => {
    try {
      const { iri } = params as { iri: string };
      const { ctx } = getWorkspaceRefs();

      // Capture the node's quads BEFORE deletion so the batch can be reverted.
      // BUG E: removeAllQuadsForIri deletes BOTH outgoing (subject-position) AND
      // incoming (object-position) edges, so we must capture both — otherwise an
      // incoming edge is unrevertable and the removed count under-reports.
      // BUG D: also preserve each literal object's datatype/language so revert
      // restores the exact typed/lang literal, not a plain xsd:string.
      const removedQuads: ProvQuad[] = [];
      try {
        const toProvQuad = (q: {
          subject: { value: string } | string;
          predicate: { value: string } | string;
          object: { value: string; termType?: string; datatype?: string; language?: string } | string;
        }): ProvQuad => {
          const s = typeof q.subject === 'string' ? q.subject : q.subject.value;
          const p = typeof q.predicate === 'string' ? q.predicate : q.predicate.value;
          const oVal = typeof q.object === 'string' ? q.object : q.object.value;
          const termType = typeof q.object === 'string' ? undefined : q.object.termType;
          const datatype = typeof q.object === 'string' ? undefined : q.object.datatype;
          const language = typeof q.object === 'string' ? undefined : q.object.language;
          const ot: ProvQuad['ot'] =
            termType === 'Literal' ? 'literal'
            : termType === 'BlankNode' ? 'bnode'
            : termType === 'NamedNode' ? 'iri'
            : classifyObjectType(oVal);
          return {
            s, p, o: oVal, ot,
            ...(ot === 'literal' && datatype ? { dt: datatype } : {}),
            ...(ot === 'literal' && language ? { lang: language } : {}),
          };
        };
        // BUG A: capture with serialize:false so the worker returns STRUCTURED
        // terms ({value, termType, datatype, language}) via serializeQuad. With
        // serialize:true the object is a flat lexical string (termToString), so
        // termType/datatype/language are always undefined — making the typed/lang
        // capture dead code and mis-tagging colon/IRI-like literals (e.g.
        // "a:b", "2026-..."^^xsd:dateTime) as 'iri' on revert (data corruption).
        const [outgoing, incoming] = await Promise.all([
          rdfManager.fetchQuadsPage({ graphName: 'urn:vg:data', filter: { subject: iri }, limit: 0, serialize: false }),
          rdfManager.fetchQuadsPage({ graphName: 'urn:vg:data', filter: { object: iri }, limit: 0, serialize: false }),
        ]);
        type RawQuad = Parameters<typeof toProvQuad>[0];
        const seen = new Set<string>();
        for (const q of [...(outgoing?.items ?? []), ...(incoming?.items ?? [])] as RawQuad[]) {
          const pq = toProvQuad(q);
          // De-dupe a self-loop (node is both subject and object of one triple).
          const k = `${pq.s} ${pq.p} ${pq.o} ${pq.ot ?? ''}`;
          if (seen.has(k)) continue;
          seen.add(k);
          removedQuads.push(pq);
        }
      } catch (err) {
        console.error('[removeNode] capture-before-delete failed', err);
      }

      const el = findEntityElement(iri, ctx.model);
      if (el) {
        ctx.model.removeElement(el.id);
      }
      await rdfManager.removeAllQuadsForIri(iri);

      if (removedQuads.length > 0) {
        // Provenance is best-effort; a fault must not flip the successful removal.
        try {
          await getProvenanceRecorder().recordEdit({ tool: 'removeNode', removed: removedQuads });
        } catch (provErr) {
          console.warn('[removeNode] provenance recordEdit failed (mutation still applied)', provErr);
        }
      }

      return { success: true, data: { removed: iri } };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const expandNode: McpTool = {
  name: 'expandNode',
  description: 'Expand canvas node(s) to show annotation properties. Pass iri to expand one node; omit iri to expand all nodes at once. Pass expand=false to collapse.',
  inputSchema: {
    type: 'object',
    properties: {
      iri: { type: 'string' },
      expand: { type: 'boolean', default: true },
    },
  },
  handler: async (params) => {
    try {
      const { iri, expand = true } = (params ?? {}) as { iri?: string; expand?: boolean };
      const { ctx } = getWorkspaceRefs();
      const model = ctx.model;
      if (!iri) {
        // Expand/collapse all canvas nodes
        for (const el of model.elements) {
          if (el instanceof Reactodia.EntityElement) {
            model.history.execute(Reactodia.setElementExpanded(el, expand));
          }
        }
        return { success: true, data: { expanded: model.elements.length } };
      }
      const el = findEntityElement(iri, model);
      if (!el) return { success: false, error: `Element not on canvas: ${iri}` };
      model.history.execute(Reactodia.setElementExpanded(el, expand));
      const { navigateToIri } = getWorkspaceRefs();
      navigateToIri?.(iri);
      return { success: true, data: { iri, expanded: expand } };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const getNodes: McpTool = {
  name: 'getNodes',
  description: 'Return entities currently on the canvas. Optionally filter by type IRI or label substring.',
  inputSchema: {
    type: 'object',
    properties: {
      typeIri: { type: 'string' },
      labelContains: { type: 'string' },
      limit: { type: 'integer', default: 100 },
      focusFirst: { type: 'boolean', default: false },
    },
  },
  handler: async (params) => {
    try {
      const { typeIri, labelContains, limit = 100, focusFirst = false } = params as {
        typeIri?: string;
        labelContains?: string;
        limit?: number;
        focusFirst?: boolean;
      };
      const { dataProvider, ctx } = getWorkspaceRefs();
      let items = await dataProvider.lookupAll();
      let fuzzyFallback = false;

      if (typeIri) {
        items = items.filter((item) => item.element.types?.includes(typeIri));
      }
      if (labelContains) {
        const lower = labelContains.toLowerCase();
        const exact = items.filter((item) =>
          getLabel(item.element).toLowerCase().includes(lower)
        );
        if (exact.length > 0) {
          items = exact;
        } else {
          // Fuzzy fallback: prefix lookup via dataProvider
          const fallback = await dataProvider.lookup({ text: labelContains, limit: 1 });
          items = fallback;
          fuzzyFallback = true;
        }
      }

      const clusterMap = new Map<string, string>();
      for (const el of ctx.model.elements) {
        if (el instanceof Reactodia.EntityGroup) {
          for (const member of el.items) {
            if (member.data.id) clusterMap.set(member.data.id, el.id);
          }
        }
      }

      const entities = items.slice(0, limit).map((item) => ({
        iri: item.element.id,
        label: getLabel(item.element),
        types: item.element.types,
        clusterId: clusterMap.get(item.element.id) ?? null,
      }));

      if (focusFirst) {
        const canvasMatch = entities.find(e =>
          ctx.model.elements.some(
            el => el instanceof Reactodia.EntityElement && (el as Reactodia.EntityElement).iri === e.iri
          )
        );
        if (canvasMatch) {
          const el = findEntityElement(canvasMatch.iri, ctx.model);
          if (el) focusElementOnCanvas(el, ctx);
        }
      }

      const result: Record<string, unknown> = { content: JSON.stringify(entities) };
      if (fuzzyFallback) result.fuzzyFallback = true;

      return { success: true, data: result };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const RDFS_LABEL_IRI = RDFS_LABEL;
const RDF_TYPE_IRI = RDF_TYPE;

/** Heuristic: does this string value look like an IRI or blank node? */
function classifyObject(value: string): 'iri' | 'literal' | 'bnode' {
  if (value.startsWith('_:')) return 'bnode';
  if (/^[a-zA-Z][a-zA-Z0-9+\-.]*:/.test(value)) return 'iri';
  return 'literal';
}

const getNodeDetails: McpTool = {
  name: 'getNodeDetails',
  description: 'Return all RDF properties (triples) for a specific entity IRI — both asserted (urn:vg:data) and inferred (urn:vg:inferred). Inferred triples are marked inferred:true in the result. Also navigates the canvas to the node, switching between ABox/TBox views if needed.',
  inputSchema: {
    type: 'object',
    required: ['iri'],
    properties: {
      iri: { type: 'string', description: 'IRI of the entity to inspect. Prefix notation supported (e.g. ex:Alice).' },
    },
  },
  handler: async (params) => {
    try {
      const raw = params as { iri?: string };
      if (!raw.iri) return { success: false, error: 'iri is required' };
      const iri = expandIri(raw.iri);
      if (iri.startsWith('Unknown prefix:')) return { success: false, error: iri };

      const [{ items: dataItems }, { items: inferredItems }] = await Promise.all([
        rdfManager.fetchQuadsPage({ graphName: 'urn:vg:data',     filter: { subject: iri }, limit: 0 }),
        rdfManager.fetchQuadsPage({ graphName: 'urn:vg:inferred', filter: { subject: iri }, limit: 0 }),
      ]);

      let label = '';
      const typeSet = new Set<string>();
      const properties: Array<{ predicate: string; object: string; objectType: 'iri' | 'literal' | 'bnode'; inferred?: boolean }> = [];

      for (const q of (dataItems ?? [])) {
        const objectType = classifyObject(q.object);
        properties.push({ predicate: q.predicate, object: q.object, objectType });
        if (q.predicate === RDFS_LABEL_IRI && !label) label = q.object;
        if (q.predicate === RDF_TYPE_IRI) typeSet.add(q.object);
      }
      for (const q of (inferredItems ?? [])) {
        if (q.predicate === RDFS_LABEL_IRI && !label) label = q.object;
        if (q.predicate === RDF_TYPE_IRI) typeSet.add(q.object);
        else {
          const objectType = classifyObject(q.object);
          properties.push({ predicate: q.predicate, object: q.object, objectType, inferred: true });
        }
      }

      const { navigateToIri } = getWorkspaceRefs();
      navigateToIri?.(iri);

      const abbrevTypes = [...typeSet].map(abbreviateIri);
      const abbrevProps = properties.map(p => ({
        ...p,
        predicate: abbreviateIri(p.predicate),
        object: p.objectType === 'iri' || p.objectType === 'bnode' ? abbreviateIri(p.object) : p.object,
      }));

      const shaclState = useShaclResultStore.getState();
      const shaclMessages = [
        ...shaclState.errors.filter(e => e.nodeId === iri).map(e => ({ severity: e.severity, rule: e.rule, message: e.message, sourceShape: e.sourceShape })),
        ...shaclState.warnings.filter(w => w.nodeId === iri).map(w => ({ severity: w.severity ?? 'warning', rule: w.rule, message: w.message, sourceShape: w.sourceShape })),
      ];

      return { success: true, data: { iri: abbreviateIri(iri), label, types: abbrevTypes, properties: abbrevProps, shaclMessages } };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const updateNode: McpTool = {
  name: 'updateNode',
  description: 'Update annotation properties of an existing entity without deleting it (preserves all edges). Only modifies asserted triples in urn:vg:data — inferred triples are never touched.',
  inputSchema: {
    type: 'object',
    required: ['iri'],
    properties: {
      iri: { type: 'string', description: 'IRI of the entity to update.' },
      label: { type: 'string', description: 'New rdfs:label value.' },
      typeIri: { type: 'string', description: 'Replace rdf:type with this IRI.' },
      setProperties: {
        type: 'array',
        description: 'Predicate/value pairs to set (replaces existing values for each predicate).',
        items: {
          type: 'object',
          required: ['predicateIri', 'value'],
          properties: {
            predicateIri: { type: 'string' },
            value: { type: 'string' },
          },
        },
      },
      removeProperties: {
        type: 'array',
        description: 'Predicates whose values should be removed entirely.',
        items: {
          type: 'object',
          required: ['predicateIri'],
          properties: {
            predicateIri: { type: 'string' },
          },
        },
      },
    },
  },
  handler: async (params) => {
    try {
      const raw = params as {
        iri?: string;
        label?: string;
        typeIri?: string;
        setProperties?: Array<{ predicateIri: string; value: string }>;
        removeProperties?: Array<{ predicateIri: string }>;
      };

      if (!raw.iri) return { success: false, error: 'iri is required' };
      const iri = expandIri(raw.iri);
      if (iri.startsWith('Unknown prefix:')) return { success: false, error: iri };

      const hasChanges =
        raw.label !== undefined ||
        raw.typeIri !== undefined ||
        (raw.setProperties && raw.setProperties.length > 0) ||
        (raw.removeProperties && raw.removeProperties.length > 0);
      if (!hasChanges) return { success: false, error: 'Provide at least one field to update (label, typeIri, setProperties, or removeProperties)' };

      // Build (predicate → newValue | null) map; null = remove only
      const changes = new Map<string, string | null>();

      if (raw.label !== undefined) changes.set(RDFS_LABEL_IRI, raw.label);

      if (raw.typeIri !== undefined) {
        const typeIri = expandIri(raw.typeIri);
        if (typeIri.startsWith('Unknown prefix:')) return { success: false, error: typeIri };
        changes.set(RDF_TYPE_IRI, typeIri);
      }

      for (const entry of raw.setProperties ?? []) {
        const pred = expandIri(entry.predicateIri);
        if (pred.startsWith('Unknown prefix:')) return { success: false, error: pred };
        changes.set(pred, entry.value);
      }

      for (const entry of raw.removeProperties ?? []) {
        const pred = expandIri(entry.predicateIri);
        if (pred.startsWith('Unknown prefix:')) return { success: false, error: pred };
        if (!changes.has(pred)) changes.set(pred, null);
      }

      // Capture existing concrete values for the touched predicates BEFORE the
      // batch, so provenance records the real removed triples (enabling a
      // faithful revert that restores prior values rather than only deleting).
      const touchedPredicates = new Set(changes.keys());
      const provRemoved: ProvQuad[] = [];
      try {
        // BUG A: serialize:false → structured terms so the datatype/language and
        // real termType (literal vs iri vs bnode) are populated. With serialize:true
        // the object is a flat lexical string and the prior-value revert would lose
        // the datatype/language and mis-classify colon-bearing literals as IRIs.
        const page = await rdfManager.fetchQuadsPage({
          graphName: 'urn:vg:data',
          filter: { subject: iri },
          limit: 0,
          serialize: false,
        });
        const items = (page?.items ?? []) as Array<{
          predicate: { value: string } | string;
          object: { value: string; termType?: string; datatype?: string; language?: string } | string;
        }>;
        for (const q of items) {
          const p = typeof q.predicate === 'string' ? q.predicate : q.predicate.value;
          if (!touchedPredicates.has(p)) continue;
          const oVal = typeof q.object === 'string' ? q.object : q.object.value;
          const termType = typeof q.object === 'string' ? undefined : q.object.termType;
          const datatype = typeof q.object === 'string' ? undefined : q.object.datatype;
          const language = typeof q.object === 'string' ? undefined : q.object.language;
          const ot: ProvQuad['ot'] =
            termType === 'Literal' ? 'literal'
            : termType === 'BlankNode' ? 'bnode'
            : termType === 'NamedNode' ? 'iri'
            : classifyObjectType(oVal);
          // BUG D: preserve datatype/language so revert restores the exact literal.
          provRemoved.push({
            s: iri, p, o: oVal, ot,
            ...(ot === 'literal' && datatype ? { dt: datatype } : {}),
            ...(ot === 'literal' && language ? { lang: language } : {}),
          });
        }
      } catch (err) {
        console.error('[updateNode] capture-before-update failed', err);
      }

      // Build batch: remove existing values for each touched predicate, then add new ones
      const removes: Array<{ s: string; p: string }> = [];
      const adds: Array<{ s: string; p: string; o: string }> = [];

      for (const [pred, newValue] of changes) {
        removes.push({ s: iri, p: pred });
        if (newValue !== null) adds.push({ s: iri, p: pred, o: newValue });
      }

      await rdfManager.applyBatch({ removes, adds }, 'urn:vg:data');

      // Provenance: the added quads are the new values; the removed quads are the
      // concrete prior values captured above (object-type aware for revert).
      // Wrapped in its own guard (incl. the classification arg-prep, which could
      // throw) so a provenance fault never flips the successful mutation.
      try {
        const provAdded: ProvQuad[] = adds.map((a) => ({
          s: a.s,
          p: a.p,
          o: a.o,
          ot: a.p === RDFS_LABEL_IRI ? 'literal' : classifyObjectType(a.o),
        }));
        await getProvenanceRecorder().recordEdit({
          tool: 'updateNode',
          added: provAdded,
          removed: provRemoved,
        });
      } catch (provErr) {
        console.warn('[updateNode] provenance recordEdit failed (mutation still applied)', provErr);
      }

      // Refresh canvas node card
      const { ctx } = getWorkspaceRefs();
      await ctx.model.requestElementData([iri as Reactodia.ElementIri]);

      const changedPredicates = [...changes.keys()];
      return { success: true, data: { updated: iri, changed: changedPredicates } };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const SEARCH_KINDS = ['class', 'objectProperty', 'datatypeProperty', 'property', 'individual'] as const;
type SearchKind = (typeof SEARCH_KINDS)[number];

const searchTerms: McpTool = {
  name: 'searchTerms',
  description:
    'Search existing ontology terms (classes / properties / individuals) by label or local name across all loaded ontologies (urn:vg:ontologies) and the asserted graph, so you can REUSE an existing IRI instead of minting a new ex: one. ALWAYS call this before creating a new class or property — if a pmdco:/bfo:/iof:/qudt: (etc.) term already exists, reuse it. Results are ranked (exact label > label prefix > label substring > local-name match) and include the resolved prefix when known. Covers terms already loaded into the store; it does not query remote registries (LOV/BioPortal). To pull in more vocabularies first, use loadOntology.',
  inputSchema: {
    type: 'object',
    required: ['query'],
    properties: {
      query: { type: 'string', description: 'Label or local-name substring to search for (case-insensitive), e.g. "process" or "Specimen".' },
      kinds: {
        type: 'array',
        items: { type: 'string', enum: [...SEARCH_KINDS] },
        description: 'Optional filter. Omit for classes + properties. "property" matches object, datatype and annotation properties.',
      },
      limit: { type: 'integer', default: 25, description: 'Maximum results to return.' },
    },
  },
  handler: async (params) => {
    try {
      const raw = (params ?? {}) as { query?: string; kinds?: string[]; limit?: number };
      const query = typeof raw.query === 'string' ? raw.query.trim() : '';
      if (!query) return { success: false, error: 'query is required' };

      let kinds: SearchKind[] | undefined;
      if (Array.isArray(raw.kinds) && raw.kinds.length > 0) {
        const valid: SearchKind[] = [];
        for (const k of raw.kinds) {
          if ((SEARCH_KINDS as readonly string[]).includes(k)) valid.push(k as SearchKind);
          else return { success: false, error: `Invalid kind "${k}". Allowed: ${SEARCH_KINDS.join(', ')}.` };
        }
        kinds = valid;
      }

      const limit = typeof raw.limit === 'number' && raw.limit > 0 ? raw.limit : 25;
      const matches = await rdfManager.searchTerms(query, { kinds, limit });

      const results = matches.map((m) => ({
        iri: abbreviateIri(m.iri),
        label: m.label,
        kind: m.kind,
        ...(m.prefix ? { prefix: m.prefix } : {}),
      }));

      const note =
        results.length > 0
          ? 'Reuse one of these IRIs instead of minting a new ex: term.'
          : 'No existing term matched. If a domain ontology likely defines it, load it via loadOntology before minting a new ex: IRI.';

      return { success: true, data: { results, note } };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

export const nodeTools: McpTool[] = [addNode, removeNode, expandNode, getNodes, getNodeDetails, updateNode, searchTerms];
