import api from './api'

/** 获取本体列表 */
export const getOntologyList = () => {
  return api.get('/ontology/list')
}

/** 获取本体统计 */
export const getOntologyStats = () => {
  return api.get('/ontology/stats')
}

/** 获取默认本体 */
export const getDefaultOntology = () => {
  return api.get('/ontology/default')
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

/** 设为默认 */
export const setDefaultOntology = (id: string) => {
  return api.post(`/ontology/${id}/set-default`)
}

/** 导入本体 */
export const importOntology = (file: File) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post('/ontology/import', fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 导出本体 */
export const exportOntology = (id: string) => {
  return api.get(`/ontology/export/${id}`)
}

/** 获取本体详情 */
export const getOntology = (id: string) => {
  return api.get(`/ontology/${id}`)
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
