// src/mcp/tools/links.ts
import type { McpTool } from '../types';
import { rdfManager } from '@/utils/rdfManager';
import { getWorkspaceRefs } from '@/mcp/workspaceContext';
import { getProvenanceRecorder, type ProvQuad } from '@/mcp/provenance';
import { expandIri } from './iriUtils';
import * as Reactodia from '@reactodia/workspace';

/** Classify an object value as iri / bnode / literal for faithful revert. */
function classifyObjectType(value: string): ProvQuad['ot'] {
  if (value.startsWith('_:')) return 'bnode';
  if (/^[a-zA-Z][a-zA-Z0-9+\-.]*:/.test(value)) return 'iri';
  return 'literal';
}

interface LinkParams {
  subjectIri?: string;
  predicateIri?: string;
  objectIri?: string;
  // common aliases accepted silently
  s?: string; subject?: string;
  p?: string; predicate?: string;
  o?: string; object?: string;
  limit?: number;
  // BUG A — optional graph + object-term metadata so an agent applying a
  // suggestedRepair removes the EXACT axiom (the MIPS axiom may live in
  // urn:vg:ontologies, and its object may be a typed/lang literal). These map
  // 1:1 onto suggestedRepairs' action.args (graph/objectDatatype/objectLanguage/
  // objectTermType). Absent ⇒ the legacy data-graph string-coerced behaviour.
  graphName?: string;
  objectDatatype?: string;
  objectLanguage?: string;
  objectIsLiteral?: boolean;
}

export const linkTools: McpTool[] = [
  {
    name: 'addTriple',
    description: 'Add a simple RDF triple between named entities (IRIs) or attach a literal annotation. Use for: object-property links between known IRIs (e.g. ex:Pizza rdf:type ex:Food), data/annotation properties (e.g. rdfs:label "Pizza"@en), and rdf:type assertions. Object-property triples render on canvas immediately; literal triples appear when the subject node is expanded via expandNode. OWL RESTRICTIONS via blank-node labels — 4 addTriple calls per restriction (use a distinct label per restriction: _:b0, _:b1, _:b2 …): addTriple("_:b0","rdf:type","owl:Restriction") [MUST be owl:Restriction, NOT owl:Class] + addTriple("_:b0","owl:onProperty","ex:hasPart") + addTriple("_:b0","owl:someValuesFrom","ex:SalamiTopping") + addTriple("ex:SalamiPizza","owl:equivalentClass","_:b0"). Same label → same IRI → restrictions collapse — always use a distinct label per restriction. Alternatively use loadRdf with Turtle blank-node syntax for all triples in one call.',
    inputSchema: {
      type: 'object',
      properties: {
        subjectIri: { type: 'string' },
        predicateIri: { type: 'string' },
        objectIri: { type: 'string' },
      },
      required: ['subjectIri', 'predicateIri', 'objectIri'],
    },
    handler: async (params: unknown) => {
      try {
        const raw = (params ?? {}) as LinkParams;
        const rawS = raw.subjectIri ?? raw.subject ?? raw.s;
        const rawP = raw.predicateIri ?? raw.predicate ?? raw.p;
        const rawO = raw.objectIri ?? raw.object ?? raw.o;
        // Normalize ":bN" → "_:bN": model sometimes omits the underscore in blank-node labels
        const normBlank = (v: string): string => /^:b\d+$/.test(v) ? `_:${v.slice(1)}` : v;
        const subjectIri = rawS ? expandIri(normBlank(rawS)) : undefined;
        const predicateIri = rawP ? expandIri(rawP) : undefined;
        // objectIri may be a plain literal — only expand if it looks like a prefixed IRI
        const objectIri = rawO ? expandIri(normBlank(rawO)) : undefined;
        if (!subjectIri || !predicateIri || !objectIri) {
          return { success: false as const, error: 'subjectIri, predicateIri, and objectIri are all required. Call help({tool:"addTriple"}) for the full schema.' };
        }
        const expandError = [subjectIri, predicateIri, objectIri].find(v => v.startsWith('Unknown prefix:'));
        if (expandError) return { success: false as const, error: expandError };
        if (subjectIri.startsWith('[') || objectIri.startsWith('[')) {
          return { success: false as const, error: 'Inline Turtle blank node syntax "[ ... ]" is not a valid IRI. Use an explicit blank node label instead, e.g. "_:b0". Call addTriple("_:b0","rdf:type","owl:Restriction") then addTriple("_:b0","owl:onProperty","ex:hasPart") etc. Each distinct restriction needs a distinct label.' };
        }
        // IRIs never contain spaces — catch Turtle fragments passed as IRIs
        // (e.g. "ex:hasPart someValuesFrom ex:Foo" or "Pizza and hasTopping some Foo")
        if (/ /.test(subjectIri) || / /.test(objectIri)) {
          const badIri = [subjectIri, objectIri].find(v => / /.test(v)) ?? '';
          // Detect corrupted blank-node: leading whitespace before colon (e.g. "     :r1" → should be "_:r1")
          const blankNodeHint = /^\s+:/.test(badIri)
            ? ` You passed "${badIri}" — this is a blank-node label with leading spaces instead of underscore. Use "_:${badIri.trim().slice(1)}" (must start with "_:", not spaces).`
            : ` You passed "${badIri}".`;
          return { success: false as const, error: `IRI contains spaces and is not valid.${blankNodeHint} For OWL restrictions prefer loadRdf with Turtle (no @prefix needed — ex: owl: are pre-loaded): loadRdf({turtle:"ex:SalamiPizza owl:equivalentClass [ a owl:Restriction ; owl:onProperty ex:hasPart ; owl:someValuesFrom ex:SalamiTopping ] ."})` };
        }
        rdfManager.addTriple(subjectIri, predicateIri, objectIri);

        // Provenance must NEVER flip a successful mutation to success:false.
        // Record in its own guard (including the object-type classification,
        // which could throw on hostile input) so a provenance fault only logs.
        try {
          await getProvenanceRecorder().recordEdit({
            tool: 'addTriple',
            added: [{ s: subjectIri, p: predicateIri, o: objectIri, ot: classifyObjectType(objectIri) }],
          });
        } catch (provErr) {
          console.warn('[addTriple] provenance recordEdit failed (mutation still applied)', provErr);
        }

        const { ctx } = getWorkspaceRefs();
        const model = ctx.model;
        await model.requestLinks({
          addedElements: [subjectIri as Reactodia.ElementIri, objectIri as Reactodia.ElementIri],
        });

        const { navigateToIri } = getWorkspaceRefs();
        navigateToIri?.(subjectIri);

        return { success: true as const, data: { added: { s: subjectIri, p: predicateIri, o: objectIri } } };
      } catch (e) {
        return { success: false as const, error: String(e) };
      }
    },
  },
  {
    name: 'removeLink',
    description: 'Remove ANY triple from the RDF store, given its subject, predicate and object. Despite the name it is not limited to object-property edges: the object may be an IRI (an ABox edge or a TBox axiom such as owl:disjointWith / rdfs:subClassOf) OR a literal value (an annotation). To remove the EXACT axiom a reasoner repair points at — which may physically live in an imported ontology graph and/or carry a typed/language-tagged literal — pass the optional graphName (e.g. "urn:vg:ontologies") and, for literal objects, objectIsLiteral=true with objectDatatype/objectLanguage. These map 1:1 onto explainDiagnostics.suggestedRepairs action.args (graph / objectDatatype / objectLanguage / objectTermType), so an agent can apply a suggested repair faithfully. Omitting them targets the default data graph and coerces the object to a string/IRI (legacy behaviour).',
    inputSchema: {
      type: 'object',
      properties: {
        subjectIri: { type: 'string' },
        predicateIri: { type: 'string' },
        objectIri: { type: 'string' },
        graphName: { type: 'string', description: 'Named graph the triple lives in (e.g. "urn:vg:ontologies"). Defaults to urn:vg:data. Required to remove an imported-schema axiom — a data-graph removal would silently match nothing.' },
        objectIsLiteral: { type: 'boolean', description: 'Set true when the object is a literal value (not an IRI) so it is matched as a Literal term, not string-coerced into an IRI.' },
        objectDatatype: { type: 'string', description: 'Datatype IRI of a literal object (e.g. xsd:integer) so "42"^^xsd:integer is matched exactly and a same-lexical "42" string is left untouched.' },
        objectLanguage: { type: 'string', description: 'Language tag of a literal object (e.g. "en").' },
      },
      required: ['subjectIri', 'predicateIri', 'objectIri'],
    },
    handler: async (params: unknown) => {
      try {
        const raw = (params ?? {}) as LinkParams;
        const rawS = raw.subjectIri ?? raw.subject ?? raw.s;
        const rawP = raw.predicateIri ?? raw.predicate ?? raw.p;
        const rawO = raw.objectIri ?? raw.object ?? raw.o;
        const subjectIri = rawS ? expandIri(rawS) : undefined;
        const predicateIri = rawP ? expandIri(rawP) : undefined;
        // BUG A: a literal object is NOT an IRI — never expand-prefix it.
        const isLiteral =
          raw.objectIsLiteral === true ||
          typeof raw.objectDatatype === 'string' ||
          typeof raw.objectLanguage === 'string';
        const objectIri = rawO
          ? (isLiteral ? rawO : expandIri(rawO))
          : undefined;
        if (!subjectIri || !predicateIri || objectIri === undefined) {
          return { success: false as const, error: 'subjectIri, predicateIri, and objectIri are all required' };
        }
        const toCheck = isLiteral ? [subjectIri, predicateIri] : [subjectIri, predicateIri, objectIri];
        const expandError = toCheck.find(v => v.startsWith('Unknown prefix:'));
        if (expandError) return { success: false as const, error: expandError };

        // BUG A: target the EXACT graph + object term. removeTriple takes a 4th
        // graphName arg and coerces a structured literal object ({value,type,
        // datatype,language}) to a Literal term, so an agent can remove an
        // imported-ontology axiom or a typed literal — not just a data-graph IRI.
        const graphName = raw.graphName || 'urn:vg:data';
        const objectArg: unknown = isLiteral
          ? {
              value: objectIri,
              type: 'literal',
              ...(raw.objectDatatype ? { datatype: raw.objectDatatype } : {}),
              ...(raw.objectLanguage ? { language: raw.objectLanguage } : {}),
            }
          : objectIri;
        rdfManager.removeTriple(subjectIri, predicateIri, objectArg, graphName);

        // Provenance is best-effort; a fault must not flip the successful removal.
        try {
          await getProvenanceRecorder().recordEdit({
            tool: 'removeLink',
            removed: [{
              s: subjectIri,
              p: predicateIri,
              o: objectIri,
              ot: isLiteral ? 'literal' : classifyObjectType(objectIri),
              ...(raw.graphName ? { g: raw.graphName } : {}),
              ...(raw.objectDatatype ? { dt: raw.objectDatatype } : {}),
              ...(raw.objectLanguage ? { lang: raw.objectLanguage } : {}),
            }],
          });
        } catch (provErr) {
          console.warn('[removeLink] provenance recordEdit failed (mutation still applied)', provErr);
        }

        return { success: true as const, data: { removed: { s: subjectIri, p: predicateIri, o: objectIri } } };
      } catch (e) {
        return { success: false as const, error: String(e) };
      }
    },
  },
  {
    name: 'getLinks',
    description: 'Return edges currently in the graph.',
    inputSchema: {
      type: 'object',
      properties: {
        subjectIri: { type: 'string' },
        predicateIri: { type: 'string' },
        objectIri: { type: 'string' },
        limit: { type: 'integer', default: 100 },
      },
    },
    handler: async (params: unknown) => {
      try {
        const { subjectIri, predicateIri, objectIri, limit } = (params ?? {}) as LinkParams;
        const { items } = await rdfManager.fetchQuadsPage({
          graphName: 'urn:vg:data',
          filter: { subject: subjectIri, predicate: predicateIri, object: objectIri },
          limit: limit ?? 100,
        });
        const links = (items ?? []).map((q: { subject: string; predicate: string; object: string }) => ({
          subject: q.subject,
          predicate: q.predicate,
          object: q.object,
        }));
        return { success: true as const, data: { links } };
      } catch (e) {
        return { success: false as const, error: String(e) };
      }
    },
  },
];
