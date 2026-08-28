import axios from 'axios';
import type { CreateEntityPayload, DynamicGraph, OntologyMutation, OntologyProposal, ResolutionCandidate } from '@/types/dynamicOntology';
const http=axios.create({baseURL:'/api/dynamic-ontology',timeout:60000});
export const dynamicOntologyApi={
 snapshot:()=>http.get<DynamicGraph>('/snapshot').then(r=>r.data),
 mutations:(limit=50)=>http.get<OntologyMutation[]>('/mutations',{params:{limit}}).then(r=>r.data),
 runRules:()=>http.post<OntologyMutation[]>('/rules/run').then(r=>r.data),
 resolutionCandidates:()=>http.get<ResolutionCandidate[]>('/resolution/candidates').then(r=>r.data),
 merge:(sourceId:string,targetId:string,reason:string,confidence:number)=>http.post<OntologyMutation>('/resolution/merge',{sourceId,targetId,reason,confidence}).then(r=>r.data),
 createEntity:(payload:CreateEntityPayload)=>http.post('/entities',payload).then(r=>r.data),
 proposals:()=>http.get<OntologyProposal[]>('/agent/proposals').then(r=>r.data),
 discover:()=>http.post<OntologyProposal[]>('/agent/discover').then(r=>r.data),
 approve:(proposalId:string)=>http.post<OntologyMutation>(`/agent/proposals/${encodeURIComponent(proposalId)}/approve`).then(r=>r.data),
};
