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

/** 创建构建任务（上传文档） */
export const createBuildJob = (data: FormData) => {
  return api.post('/ontology/build/upload', data, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

/** 无文件创建 AI 构建任务 */
export const createBuildJobSimple = (name: string, description: string = '') => {
  return api.post('/ontology/build/create', { name, description })
}

/** 上传文件到已有构建任务（聊天中追加） */
export const uploadBuildFile = (jobId: string, file: File) => {
  const form = new FormData()
  form.append('file', file)
  return api.post(`/ontology/build/${jobId}/upload-file`, form)
}

/** 阶段 0「文档解析」：解析上传的文档 + 推荐本体模型（后台异步，SSE 订阅 parse_done/error） */
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

/** 确认本体模型（Step 0：本体模型 + 粒度 + 阶段提示词） */
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

// ── AI 构建聊天接口 ──

/** 从已完成本体开启 AI 构建对话 */
export const buildFromOntology = (ontologyId: string) => {
  return api.post('/ontology/build/from-ontology', { ontology_id: ontologyId })
}

/** 获取聊天历史与当前状态（刷新恢复） */
export const getChatHistory = (jobId: string) => {
  return api.get(`/ontology/build/${jobId}/history`)
}

/** 增量编辑当前状态（即时写回，step3 确认时才真正落库） */
export const editBuildState = (jobId: string, operation: object) => {
  return api.post(`/ontology/build/${jobId}/edit`, { operation })
}

// ── AI 构建聊天 SSE 接口 ──

/** 聊天 SSE 事件回调集合 */
export interface ChatStreamHandlers {
  onChatStatus?: (d: { status: string; message: string }) => void
  onChatReply?: (d: { reply: string; intent: string; task?: any }) => void
  onStateUpdate?: (d: any) => void
  onGraphUpdate?: (d: any) => void
  onChatError?: (d: { error: string }) => void
  onChatDone?: (d: any) => void
  onState?: (s: 'open' | 'closed') => void
}

/**
 * 订阅 AI 构建聊天（SSE）。
 * @param jobId 任务 ID
 * @param message 用户输入消息
 * @param handlers 事件回调
 * @returns abort 函数
 */
export const chatStream = (jobId: string, message: string, handlers: ChatStreamHandlers): (() => void) => {
  const controller = new AbortController()
  const token = localStorage.getItem('token')

  ;(async () => {
    try {
      const resp = await fetch(`/api/ontology/build/${jobId}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'text/event-stream',
          ...(token ? { Authorization: `Bearer ${token}` } : {})
        },
        body: JSON.stringify({ message }),
        signal: controller.signal
      })
      if (!resp.ok || !resp.body) {
        handlers.onChatError?.({ error: `请求失败 (HTTP ${resp.status})` })
        return
      }
      handlers.onState?.('open')

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        for (const frame of frames) {
          const event = _parseSseFrame(frame)
          if (!event) continue
          switch (event.type) {
            case 'chat_status': handlers.onChatStatus?.(event.data); break
            case 'chat_reply': handlers.onChatReply?.(event.data); break
            case 'state_update': handlers.onStateUpdate?.(event.data); break
            case 'graph_update': handlers.onGraphUpdate?.(event.data); break
            case 'chat_error': handlers.onChatError?.(event.data); break
            case 'chat_done': handlers.onChatDone?.(event.data); break
          }
        }
      }
      handlers.onState?.('closed')
    } catch (e: any) {
      if (e?.name === 'AbortError') {
        handlers.onState?.('closed')
        return
      }
      handlers.onChatError?.({ error: 'SSE 连接失败' })
    }
  })()

  return () => controller.abort()
}

// ── SSE 实时订阅（fetch + ReadableStream，复用 Authorization header）──
// 不用 EventSource：其无法加自定义 header，会丢失 token。
// 后端端点：GET /ontology/build/{jobId}/stream，返回 text/event-stream。

/** SSE 事件回调集合 */
export interface BuildStreamHandlers {
  /** 阶段 0 文档解析完成（含 char_count / 推荐的本体模型） */
  onParseDone?: (d: any) => void
  /** 后台任务推送的聊天消息（如解析完成后的文档摘要+构建建议） */
  onChatMessage?: (d: any) => void
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
  const token = localStorage.getItem('token')
  // 是否已收到终态事件（step_done/error）：收到后正常关闭流不应再触发重连，
  // 否则会无限重连并反复回放 step_done，导致「实体类型提取完成」等提示重复弹出（含在其他页面）。
  let terminated = false
  // 用户主动取消（调用返回的 abort 函数）：与看门狗 abort 区分，不触发重连
  let stopped = false
  // 每次连接独立的 AbortController：AbortController 一次性，abort 后 signal 永久为 aborted；
  // 若全程复用一个实例，看门狗触发一次 abort 后所有后续 fetch 立即失败且无法重连（永久失聪）
  let controller: AbortController | null = null
  // 断线自动重连：未到终态的流结束/异常由本函数内部自动重连（指数退避），
  // 之前只抛 onError({reconnect:true}) 无人处理，服务重启/代理超时后前端永久失聪，
  // 增量事件（batch_done/step_done）全部丢失，表现为顶部下拉不更新、无法进入下一步。
  // 重连后靠后端回放机制补全断线期间的事件。
  let retryCount = 0
  const MAX_RETRY = 10
  let retryTimer: ReturnType<typeof setTimeout> | null = null
  // 看门狗：fetch+ReadableStream 无内建断线检测，系统休眠/代理静默掐断后
  // reader.read() 可能永久挂起（连接「假活」），终态事件（step_done/chat_message）
  // 全部丢失，表现为任务标签卡 running。后端每 15s 发一次心跳注释行，
  // 超过 35s（漏 2 次心跳）未收到任何字节即强制 abort 并走重连（回放可补全事件）
  let staleTimer: ReturnType<typeof setTimeout> | null = null
  let watchdogFired = false
  const clearWatchdog = () => {
    if (staleTimer != null) { clearTimeout(staleTimer); staleTimer = null }
  }
  const armWatchdog = () => {
    clearWatchdog()
    staleTimer = setTimeout(() => {
      watchdogFired = true
      console.warn('[SSE] 看门狗超时（35s 无数据，连接假死），强制断开重连')
      controller?.abort()
    }, 35000)
  }

  const scheduleReconnect = () => {
    if (terminated || stopped) return
    if (retryCount >= MAX_RETRY) {
      console.warn('[SSE] 连续重连失败次数达上限，停止重连')
      handlers.onError?.({ message: 'SSE 连接中断且重连失败，请刷新页面重试', reconnect: false })
      handlers.onState?.('closed')
      return
    }
    const delay = Math.min(3000 * Math.pow(2, retryCount), 30000)
    retryCount++
    console.log(`[SSE] ${delay}ms 后第 ${retryCount} 次重连...`)
    retryTimer = setTimeout(() => { retryTimer = null; connect() }, delay)
  }

  const connect = async () => {
    // 每次连接（含重连）新建 controller，避免复用已 aborted 的实例
    controller = new AbortController()
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
        scheduleReconnect()
        return
      }
      // 连接成功：重置退避计数，恢复 open 状态；启动看门狗监测连接假死
      retryCount = 0
      handlers.onState?.('open')
      armWatchdog()

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) { console.log('[SSE] reader done（流结束）'); break }
        // 收到任何字节（含心跳注释行）都说明连接活着，重置看门狗
        armWatchdog()
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
            case 'chat_message': handlers.onChatMessage?.(event.data); break
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
      clearWatchdog()
      if (terminated) {
        console.log('[SSE] 已收到终态事件，正常结束，不触发重连')
        handlers.onState?.('closed')
      } else {
        // 未到终态流被关闭（服务重启/代理掐断）：自动重连，重连回放可补全丢失事件
        scheduleReconnect()
      }
    } catch (e: any) {
      clearWatchdog()
      // 看门狗触发的 abort：视为连接假死，强制走重连（不能当作用户主动断开）
      if (watchdogFired) {
        watchdogFired = false
        scheduleReconnect()
        return
      }
      // 用户主动 abort 不触发重连
      if (e?.name === 'AbortError') {
        console.log('[SSE] 用户主动 abort')
        handlers.onState?.('closed')
        return
      }
      console.error('[SSE] fetch 异常:', e)
      // 已收到终态事件后，即使连接异常结束也不再重连（避免回放 step_done 重复弹提示）
      if (!terminated) {
        scheduleReconnect()
      } else {
        handlers.onState?.('closed')
      }
    }
  }

  connect()

  // 返回 abort 函数：调用方在离开页面/取消订阅时调用（同时清理待执行的重连定时器与看门狗）
  return () => {
    stopped = true
    if (retryTimer != null) {
      clearTimeout(retryTimer)
      retryTimer = null
    }
    clearWatchdog()
    controller?.abort()
  }
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
