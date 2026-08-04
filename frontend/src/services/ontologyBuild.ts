import api from './api'

/** 获取构建任务列表 */
export const getBuildJobList = () => {
  return api.get('/ontology/build/list')
}

/** 获取构建任务详情 */
export const getBuildJob = (jobId: string) => {
  return api.get(`/ontology/build/${jobId}`)
}

/** 查询构建进度（轻量级，供轮询） */
export const getBuildProgress = (jobId: string) => {
  return api.get(`/ontology/build/${jobId}/progress`)
}

/** 上传文档创建任务 */
export const createBuildJob = (data: FormData) => {
  return api.post('/ontology/build/upload', data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 确认元模型 */
export const confirmMeta = (jobId: string, data: FormData) => {
  return api.put(`/ontology/build/${jobId}/meta`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 提取概念（Step 1） */
export const extractConcepts = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step1`)
}

/** 确认概念清单 */
export const confirmConcepts = (jobId: string, concepts: any[]) => {
  const fd = new FormData()
  fd.append('concepts', JSON.stringify(concepts))
  return api.put(`/ontology/build/${jobId}/step1`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 构建层次结构（Step 2） */
export const buildStructure = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step2`)
}

/** 确认层次结构 */
export const confirmStructure = (jobId: string, entities: any[], relations: any[]) => {
  const fd = new FormData()
  fd.append('entities', JSON.stringify(entities))
  fd.append('relations', JSON.stringify(relations))
  return api.put(`/ontology/build/${jobId}/step2`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 生成最终本体（Step 3） */
export const generateOntology = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step3`)
}

/** 删除构建任务 */
export const deleteBuildJob = (jobId: string) => {
  return api.delete(`/ontology/build/${jobId}`)
}
