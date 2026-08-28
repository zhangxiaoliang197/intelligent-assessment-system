import type { CausalGraphResult, CausalGraphNode } from './causal';
export type DynamicGraph = CausalGraphResult;
export interface OntologyMutation { id:string; mutationType:'NODE_CREATED'|'NODE_MERGED'|'ONTOLOGY_EXPANDED'|string; subjectId:string; targetId?:string|null; reason:string; confidence:number; createdAt:string; metadata:Record<string,unknown>; }
export interface ResolutionCandidate { candidateId:string; sourceId:string; sourceName:string; targetId:string; targetName:string; score:number; evidence:string[]; status:string; }
export interface OntologyProposal { id:string; proposalType:string; name:string; parentClass:string; description:string; confidence:number; evidenceCount:number; suggestedProperties:string[]; suggestedRelations:string[]; status:string; createdAt:string; }
export interface CreateEntityPayload { name:string; ontologyType:string; operationalRole:string; properties:Record<string,string>; }
export type DynamicNode = CausalGraphNode;
