import api from './api'

/** 模板摘要（列表接口返回） */
export interface TemplateSummary {
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

/** 获取模板列表 */
export const getTemplateList = () => {
  return api.get('/ontology/template/list')
}

/** 获取模板详情（含完整 concepts 与 property_schema） */
export const getTemplate = (templateId: string) => {
  return api.get(`/ontology/template/${templateId}`)
}

/** 手动独立创建模板 */
export const createTemplate = (data: FormData) => {
  return api.post('/ontology/template', data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 从已有本体另存为模板（抽取 schema 层，丢弃实例） */
export const saveTemplateFromOntology = (ontologyId: string, data: FormData) => {
  return api.post(`/ontology/template/save-from-ontology/${ontologyId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 更新模板字段（传空字符串的字段保持原值） */
export const updateTemplate = (templateId: string, data: FormData) => {
  return api.put(`/ontology/template/${templateId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除模板（不影响已基于该模板创建的本体/任务） */
export const deleteTemplate = (templateId: string) => {
  return api.delete(`/ontology/template/${templateId}`)
}
