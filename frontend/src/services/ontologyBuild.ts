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

/** 阶段 0「文档解析」：解析上传的文档 + 推荐元模型（后台异步，SSE 订阅 parse_done/error） */
export const parseBuildJob = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/parse`)
}

/** 创建手动构建任务（无文档，纳入「进行中的构建任务」，支持退出后继续） */
export const createManualBuildJob = (data: FormData) => {
  return api.post('/ontology/build/manual', data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 标记构建任务完成（手动构建「完成构建」时调用） */
export const completeBuildJob = (jobId: string) => {
  return api.put(`/ontology/build/${jobId}/complete`)
}

/** 确认元模型（Step 0：元模型 + 粒度 + 阶段提示词） */
export const confirmMeta = (jobId: string, data: FormData) => {
  return api.put(`/ontology/build/${jobId}/meta`, data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ── Step 1：实体类型提取（类型层）──
/** 启动实体类型提取（Step 1） */
export const extractConcepts = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step1`)
}

/** 确认实体类型清单（Step 1） */
export const confirmConcepts = (jobId: string, concepts: any[]) => {
  const fd = new FormData()
  fd.append('concepts', JSON.stringify(concepts))
  return api.put(`/ontology/build/${jobId}/step1`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ── Step 2：实体+属性提取（实例层）──
/** 启动实体+属性提取（Step 2） */
export const extractEntities = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step2`)
}

/** 确认实体清单（Step 2），可选传主要实体勾选结果 */
export const confirmEntities = (jobId: string, entities: any[], primaryEntitySelected: string[] = []) => {
  const fd = new FormData()
  fd.append('entities', JSON.stringify(entities))
  fd.append('primary_entity_selected', JSON.stringify(primaryEntitySelected))
  return api.put(`/ontology/build/${jobId}/step2`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ── Step 3：关系建模 ──
/** 启动关系建模（Step 3） */
export const buildRelations = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step3`)
}

/** 确认关系清单（Step 3） */
export const confirmRelations = (jobId: string, relations: any[]) => {
  const fd = new FormData()
  fd.append('relations', JSON.stringify(relations))
  return api.put(`/ontology/build/${jobId}/step3`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ── Step 4：验证 + 报告 ──
/** 启动 LLM 自检验证（Step 4） */
export const verifyOntology = (jobId: string) => {
  return api.post(`/ontology/build/${jobId}/step4`)
}

/** 确认验证结果，触发生成正式本体（Step 4） */
export const confirmVerification = (jobId: string) => {
  return api.put(`/ontology/build/${jobId}/step4`)
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
  /** 阶段 0 文档解析完成（含 char_count / 推荐的元模型） */
  onParseDone?: (d: any) => void
  /** Step1 每批实体类型完成 / Step2 每批实体完成（同事件名，按 data 字段区分） */
  onBatchDone?: (d: any) => void
  /** Step3 每组关系完成 */
  onGroupDone?: (d: any) => void
  /** Step3 跨组关系补充完成 */
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
  // 是否已收到终态事件（step_done/error）：收到后正常关闭流不应再触发重连，
  // 否则会无限重连并反复回放 step_done，导致「实体类型提取完成」等提示重复弹出（含在其他页面）。
  let terminated = false

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
            event.type === 'group_done' ? `+${event.data.relations?.length || 0}关系` : '',
            event.type === 'batch_done' ? `+${event.data.concepts?.length || 0}实体类型/+${event.data.entities?.length || 0}实体` : '')
          switch (event.type) {
            case 'parse_done': handlers.onParseDone?.(event.data); break
            case 'batch_done': handlers.onBatchDone?.(event.data); break
            case 'group_done': handlers.onGroupDone?.(event.data); break
            case 'cross_group_done': handlers.onCrossGroupDone?.(event.data); break
            case 'step_done':
              terminated = true
              handlers.onStepDone?.(event.data); break
            case 'error':
              terminated = true
              handlers.onError?.(event.data); break
            case 'progress': handlers.onProgress?.(event.data); break
          }
        }
      }
      // 连接正常关闭：若已收到终态（step_done/error）则不重连，避免无限重连反复回放提示
      handlers.onState?.('closed')
      if (terminated) {
        console.log('[SSE] 已收到终态事件，正常结束，不触发重连')
      } else {
        console.log('[SSE] 流正常结束但未到终态，触发重连判断')
        handlers.onError?.({ message: '连接已断开', reconnect: true })
      }
    } catch (e: any) {
      // 用户主动 abort 不触发重连
      if (e?.name === 'AbortError') {
        console.log('[SSE] 用户主动 abort')
        handlers.onState?.('closed')
        return
      }
      console.error('[SSE] fetch 异常:', e)
      // 已收到终态事件后，即使连接异常结束也不再重连（避免回放 step_done 重复弹提示）
      if (!terminated) {
        handlers.onError?.({ message: 'SSE 连接失败', reconnect: true })
      } else {
        handlers.onState?.('closed')
      }
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
