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

// ── SSE 实时订阅（fetch + ReadableStream，复用 Authorization header）──
// 不用 EventSource：其无法加自定义 header，会丢失 token。
// 后端端点：GET /ontology/build/{jobId}/stream，返回 text/event-stream。

/** SSE 事件回调集合 */
export interface BuildStreamHandlers {
  /** Step1 每批概念完成 */
  onBatchDone?: (d: any) => void
  /** Step2 每组实体关系完成 */
  onGroupDone?: (d: any) => void
  /** Step2 跨组关系补充完成 */
  onCrossGroupDone?: (d: any) => void
  /** 整个步骤完成（AI 全部提取/构建完毕，可确认） */
  onStepDone?: (d: any) => void
  /** 失败（含断点续作提示） */
  onError?: (d: any) => void
  /** 进度变化（可选） */
  onProgress?: (d: any) => void
  /** 连接状态变化（open/close，用于前端 UI 提示） */
  onState?: (s: 'open' | 'closed') => void
}

/**
 * 订阅构建任务的实时增量（SSE）。
 * @param jobId 任务 ID
 * @param handlers 事件回调
 * @returns abort 函数：调用以断开连接（离开页面/取消时务必调用）
 */
export const streamBuildJob = (jobId: string, handlers: BuildStreamHandlers): (() => void) => {
  const controller = new AbortController()
  const token = localStorage.getItem('token')

  ;(async () => {
    try {
      console.log('[SSE] 建立 fetch 连接, jobId=', jobId)
      const resp = await fetch(`/api/ontology/build/${jobId}/stream`, {
        method: 'GET',
        headers: {
          'Accept': 'text/event-stream',
          // 复用 api.ts 的 token 注入逻辑，保持鉴权一致
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        signal: controller.signal
      })
      console.log('[SSE] fetch 返回, status=', resp.status, 'ok=', resp.ok, 'hasBody=', !!resp.body)
      if (!resp.ok || !resp.body) {
        handlers.onError?.({ message: `SSE 连接失败 (HTTP ${resp.status})`, reconnect: true })
        return
      }
      handlers.onState?.('open')

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) { console.log('[SSE] reader done（流结束）'); break }
        buffer += decoder.decode(value, { stream: true })
        // SSE 事件帧以空行（\n\n）分隔；保留最后一个不完整帧在 buffer
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          const event = _parseSseFrame(frame)
          if (!event) continue
          console.log('[SSE] 收到事件:', event.type, event.data?.replayed ? '(回放)' : '', 
            event.type === 'group_done' ? `+${event.data.entities?.length || 0}实体` : '',
            event.type === 'batch_done' ? `+${event.data.concepts?.length || 0}概念` : '')
          switch (event.type) {
            case 'batch_done': handlers.onBatchDone?.(event.data); break
            case 'group_done': handlers.onGroupDone?.(event.data); break
            case 'cross_group_done': handlers.onCrossGroupDone?.(event.data); break
            case 'step_done': handlers.onStepDone?.(event.data); break
            case 'error': handlers.onError?.(event.data); break
            case 'progress': handlers.onProgress?.(event.data); break
          }
        }
      }
      // 连接正常关闭：若非终态（step_done/error）则视为异常断开，触发重连
      handlers.onState?.('closed')
      console.log('[SSE] 流正常结束，触发重连判断')
      handlers.onError?.({ message: '连接已断开', reconnect: true })
    } catch (e: any) {
      // 用户主动 abort 不触发重连
      if (e?.name === 'AbortError') {
        console.log('[SSE] 用户主动 abort')
        handlers.onState?.('closed')
        return
      }
      console.error('[SSE] fetch 异常:', e)
      handlers.onError?.({ message: 'SSE 连接失败', reconnect: true })
    }
  })()

  // 返回 abort 函数：调用方在离开页面/取消订阅时调用
  return () => controller.abort()
}

/**
 * 解析单个 SSE 事件帧（event: xxx \n data: xxx）。
 * 心跳行（以 : 开头）被忽略。
 */
function _parseSseFrame(frame: string): { type: string; data: any } | null {
  let type = 'message'
  let dataStr = ''
  for (const line of frame.split('\n')) {
    if (line.startsWith(':')) continue            // 心跳注释行
    if (line.startsWith('event:')) type = line.slice(6).trim()
    else if (line.startsWith('data:')) dataStr += line.slice(5).trim()
  }
  if (!dataStr) return null
  try {
    return { type, data: JSON.parse(dataStr) }
  } catch {
    return null
  }
}
