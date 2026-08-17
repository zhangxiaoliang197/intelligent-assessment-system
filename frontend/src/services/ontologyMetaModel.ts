import api from './api'

/** 本体模型摘要（列表接口返回） */
export interface MetaModelSummary {
  id: string
  name: string
  description: string
  version: string
  entity_types_count: number
  relation_types_count: number
  concepts_count: number
  source_ontology_id: string | null
  is_builtin: boolean
  create_time: string
  update_time: string
}

/** 获取本体模型列表 */
export const getMetaModelList = () => {
  return api.get('/ontology/ontology-model/list')
}

/** 获取本体模型详情（含完整 concepts 与 property_schema） */
export const getMetaModel = (metaModelId: string) => {
  return api.get(`/ontology/ontology-model/${metaModelId}`)
}

/** 手动独立创建本体模型 */
export const createMetaModel = (data: FormData) => {
  return api.post('/ontology/ontology-model', data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 从已有本体另存为本体模型（抽取 schema 层，丢弃实例） */
export const saveMetaModelFromOntology = (ontologyId: string, data: FormData) => {
  return api.post(`/ontology/ontology-model/save-from-ontology/${ontologyId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 更新本体模型字段（传空字符串的字段保持原值） */
export const updateMetaModel = (metaModelId: string, data: FormData) => {
  return api.put(`/ontology/ontology-model/${metaModelId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除本体模型（不影响已基于该本体模型创建的本体/任务） */
export const deleteMetaModel = (metaModelId: string) => {
  return api.delete(`/ontology/ontology-model/${metaModelId}`)
}
