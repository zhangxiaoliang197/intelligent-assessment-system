import api from './api'

/** 获取本体列表 */
export const getOntologyList = () => {
  return api.get('/ontology/list')
}

/** 获取本体统计 */
export const getOntologyStats = () => {
  return api.get('/ontology/stats')
}

/** 创建本体 */
export const createOntology = (data: FormData) => {
  return api.post('/ontology/create', data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 更新本体 */
export const updateOntology = (id: string, data: FormData) => {
  return api.put(`/ontology/${id}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除本体 */
export const deleteOntology = (id: string) => {
  return api.delete(`/ontology/${id}`)
}

/** 归档本体（参与下游数据联动） */
export const archiveOntology = (id: string) => {
  return api.post(`/ontology/${id}/archive`)
}

/** 恢复本体（取消归档，不再参与下游数据联动） */
export const restoreOntology = (id: string) => {
  return api.post(`/ontology/${id}/unarchive`)
}

/** 导入本体 */
export const importOntology = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/ontology/import', fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 导出本体（JSON 格式，含 entity_types + entity_type_relations + entities + relations） */
export const exportOntology = (id: string) => {
  return api.get(`/ontology/export/${id}`)
}

/** 导出本体为 OWL 2 / RDF 文件（RDF/XML 格式，Protégé 可直接打开）
 *  v3：含 EntityType 层级（subClassOf）+ 类型间关系（ObjectProperty domain/range）
 *  返回 Blob（文件下载），调用方可用 URL.createObjectURL 触发浏览器下载
 */
export const exportOntologyOwl = (id: string) => {
  return api.get(`/ontology/${id}/owl`, {
    responseType: 'blob',
    headers: { 'Accept': 'application/rdf+xml' }
  })
}

/** 获取本体详情 */
export const getOntology = (id: string) => {
  return api.get(`/ontology/${id}`)
}

/** 获取本体元信息（v3：返回 entity_types + relation_types + entity_type_relations 聚合视图） */
export const getOntologyMeta = (ontologyId: string) => {
  return api.get(`/ontology/${ontologyId}/meta`)
}

/** 获取实体列表 */
export const getEntityList = (ontologyId: string, page = 1, pageSize = 1000) => {
  return api.get(`/ontology/${ontologyId}/entity/list`, {
    params: { page, page_size: pageSize }
  })
}

/** 获取关系列表 */
export const getRelationList = (ontologyId: string, page = 1, pageSize = 1000) => {
  return api.get(`/ontology/${ontologyId}/relation/list`, {
    params: { page, page_size: pageSize }
  })
}

/** 获取图谱数据 */
export const getGraphData = (ontologyId: string) => {
  return api.get(`/ontology/${ontologyId}/graph`)
}

// ── 实体类型（类型层）CRUD ──
// v3 重构：ConceptType = EntityType，独立概念层已合并进实体类型层（历史兼容）
// 后端路由仍为 /concept/*（历史兼容），前端函数名统一为 entityType* 语义
// FormData 可包含 v3 字段：parent_entity_type_id / parent_entity_type_name（层级）

/** 获取实体类型列表（v3：实体类型列表，含 parent_entity_type_id 层级字段） */
export const getEntityTypeList = (ontologyId: string, entityType?: string) => {
  return api.get(`/ontology/${ontologyId}/concept/list`, {
    params: entityType ? { entity_type: entityType } : {}
  })
}

/** 新增实体类型（含属性骨架 property_schema + 父层级 parent_entity_type_id） */
export const createEntityType = (ontologyId: string, data: FormData) => {
  return api.post(`/ontology/${ontologyId}/concept`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 更新实体类型（仅传非空字段，支持 parent_entity_type_id 层级调整） */
export const updateEntityType = (ontologyId: string, typeId: string, data: FormData) => {
  return api.put(`/ontology/${ontologyId}/concept/${typeId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除实体类型（若有实体引用会拒绝） */
export const deleteEntityType = (ontologyId: string, typeId: string) => {
  return api.delete(`/ontology/${ontologyId}/concept/${typeId}`)
}

// ── 向后兼容别名（旧 Vue 页面引用 getConceptList 等仍可工作）──
export const getConceptList = getEntityTypeList
export const createConcept = createEntityType
export const updateConcept = updateEntityType
export const deleteConcept = deleteEntityType

// ── 实体类型间关系 CRUD（v3 新增：类型层关系）──

/** 获取实体类型间关系列表（step1 提取或手动添加的类型层关系） */
export const getEntityTypeRelationList = (ontologyId: string) => {
  return api.get(`/ontology/${ontologyId}/entity_type_relation/list`)
}

/** 新增实体类型间关系 */
export const createEntityTypeRelation = (ontologyId: string, data: FormData) => {
  return api.post(`/ontology/${ontologyId}/entity_type_relation`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除实体类型间关系 */
export const deleteEntityTypeRelation = (ontologyId: string, relationId: string) => {
  return api.delete(`/ontology/${ontologyId}/entity_type_relation/${relationId}`)
}

// ── 构建任务返工（v3 新增：每步可重新调用 LLM 重建）──

/** 返工某步骤（用户输入新提示词，重新调用 LLM 重建该步结果） */
export const reworkBuildStep = (jobId: string, step: number, data: FormData) => {
  return api.post(`/ontology/build/${jobId}/rework/${step}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ── 实体（实例层）CRUD ──
// 新 schema：instance_of 指向实体类型ID，properties 为 List[Property] 结构化数组

/** 新增实体（instance_of + 结构化 properties） */
export const createEntity = (ontologyId: string, data: FormData) => {
  return api.post(`/ontology/${ontologyId}/entity`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 更新实体 */
export const updateEntity = (ontologyId: string, entityId: string, data: FormData) => {
  return api.put(`/ontology/${ontologyId}/entity/${entityId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除实体（级联删除相关关系） */
export const deleteEntity = (ontologyId: string, entityId: string) => {
  return api.delete(`/ontology/${ontologyId}/entity/${entityId}`)
}

// ── 属性 CRUD ──

/** 新增属性 */
export const addProperty = (ontologyId: string, entityId: string, data: FormData) => {
  return api.post(`/ontology/${ontologyId}/entity/${entityId}/property`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 更新属性（指标型 value 变更时旧值自动入 history） */
export const updateProperty = (ontologyId: string, entityId: string, propertyId: string, data: FormData) => {
  return api.put(`/ontology/${ontologyId}/entity/${entityId}/property/${propertyId}`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除属性 */
export const deleteProperty = (ontologyId: string, entityId: string, propertyId: string) => {
  return api.delete(`/ontology/${ontologyId}/entity/${entityId}/property/${propertyId}`)
}

/** 为指标型属性追加历史值 */
export const addPropertyHistory = (ontologyId: string, entityId: string, propertyId: string, data: FormData) => {
  return api.post(`/ontology/${ontologyId}/entity/${entityId}/property/${propertyId}/history`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ── 关系 CRUD ──

/** 新增关系 */
export const createRelation = (ontologyId: string, data: FormData) => {
  return api.post(`/ontology/${ontologyId}/relation`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 删除关系 */
export const deleteRelation = (ontologyId: string, relationId: string) => {
  return api.delete(`/ontology/${ontologyId}/relation/${relationId}`)
}
