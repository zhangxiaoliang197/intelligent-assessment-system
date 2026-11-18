import api from './api'

export interface OntologyDocument {
  ontology: Record<string, any>
  entity_types: Record<string, any>[]
  entity_type_relations: Record<string, any>[]
  entities: Record<string, any>[]
  relations: Record<string, any>[]
}

const unwrap = (response: any) => response?.data ?? response
const path = (id: string) => `/ontology/${encodeURIComponent(id)}/workbench`
export const getWorkbench = async (id: string) => unwrap(await api.get(path(id)))
export const saveWorkbench = async (id: string, document: OntologyDocument, revision: string, note: string) => (
  unwrap(await api.put(path(id), { document, expected_revision: revision, note }))
)
export const validateWorkbench = async (id: string, document: OntologyDocument, shapes = '') => (
  unwrap(await api.post(`${path(id)}/validate`, { document, shapes }, { timeout: 120000 }))
)
export const reasonWorkbench = async (id: string, document: OntologyDocument) => (
  unwrap(await api.post(`${path(id)}/reason`, { document }, { timeout: 120000 }))
)
export const queryWorkbench = async (id: string, document: OntologyDocument, query: string) => (
  unwrap(await api.post(`${path(id)}/query`, { document, query }, { timeout: 60000 }))
)
export const importWorkbenchRdf = async (id: string, content: string, format: string) => (
  unwrap(await api.post(`${path(id)}/import-rdf`, { content, format }, { timeout: 60000 }))
)
export const workbenchHistory = async (id: string) => (await api.get(`${path(id)}/history`)).items || []
export const exportWorkbenchRdf = (id: string, format: string) => api.get(`${path(id)}/export-rdf`, {
  params: { format }, responseType: 'blob',
})
