/**
 * 态势页面（ipage）Pinia store。
 *
 * 与 situation store 完全独立：SSE 事件 plan/dataset/progress/page/direct/done/error
 * 落到本 store，PageSandbox 用 html + dataBundle 渲染沙箱页面。
 * 会话模型：主对话框页（SituationPageDialog）与态势页（InteractivePage）
 * 共享同一会话，消息由后端落库，本地仅做即时回显。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import api from '@/services/api'

export interface IpageStep {
  id: string
  label: string
  state: 'pending' | 'active' | 'completed' | 'error'
  detail?: string
}

export interface IpageHistoryItem {
  pageId: string
  title: string
  query: string
  status: string
  intent: string
  parentId: string
  hasHtml: boolean
  createdAt: string
  updatedAt: string
}

export interface IpageSession {
  sessionId: string
  title: string
  userId?: string
  messageCount?: number
  pageCount?: number
  createdAt: string
  updatedAt: string
}

export interface IpageChatMessage {
  id: string
  role: 'user' | 'ai'
  kind: 'text' | 'direct' | 'page_card' | 'error'
  content: string
  pageId?: string
  title?: string
  usedTemplate?: boolean
  createdAt: string
}

export interface IpageGenerateOptions {
  sessionId?: string
  dataSourceId?: string
  parentPageId?: string
  source?: string
}

export const useInteractiveStore = defineStore('interactive', () => {
  // ── 本轮生成状态 ──
  const pageId = ref('')
  const parentPageId = ref('')
  const status = ref<'idle' | 'generating' | 'ready' | 'failed'>('idle')
  const intent = ref('')
  const title = ref('')
  const query = ref('')
  const html = ref('')
  const dataBundle = ref<any>(null)
  const plan = ref<any>(null)
  const directAnswer = ref('')
  const usedTemplate = ref(false)
  const guardIssues = ref<string[]>([])
  // 本次是否为「修改未生效、已保留上一版」（仅修订场景有意义）
  const revised = ref(false)
  const errorMsg = ref('')
  const steps = ref<IpageStep[]>([])
  const datasetLogs = ref<Array<Record<string, any>>>([])

  // ── 历史 ──
  const history = ref<IpageHistoryItem[]>([])
  const historyTotal = ref(0)
  const historyPage = ref(1)

  // ── 会话（对话式交互，主对话框页与态势页共享）──
  const sessionId = ref('')
  const sessions = ref<IpageSession[]>([])
  const messages = ref<IpageChatMessage[]>([])

  let eventSource: EventSource | null = null
  let generationEpoch = 0
  let messageSeq = 0

  function resetRound() {
    closeStream()
    pageId.value = ''
    parentPageId.value = ''
    status.value = 'idle'
    intent.value = ''
    title.value = ''
    html.value = ''
    dataBundle.value = null
    plan.value = null
    directAnswer.value = ''
    usedTemplate.value = false
    guardIssues.value = []
    revised.value = false
    errorMsg.value = ''
    datasetLogs.value = []
    steps.value = [
      { id: 'plan', label: '分析问题与规划页面', state: 'pending' },
      { id: 'research', label: '查询数据集', state: 'pending' },
      { id: 'write', label: '生成交互页面', state: 'pending' },
    ]
  }

  function setStep(id: string, state: IpageStep['state'], detail?: string) {
    const step = steps.value.find((s) => s.id === id)
    if (step) {
      step.state = state
      if (detail !== undefined) step.detail = detail
    }
  }

  // ── SSE 事件落库 ──
  function applyEvent(type: string, data: any) {
    switch (type) {
      case 'plan':
        plan.value = data.plan || null
        if (data.title) title.value = data.title
        setStep('plan', 'completed')
        setStep('research', 'active')
        break
      case 'progress':
        if (data.stage) {
          const stageMap: Record<string, string> = { plan: 'plan', research: 'research', write: 'write' }
          const stepId = stageMap[data.stage]
          if (stepId) setStep(stepId, 'active', data.message)
        }
        break
      case 'dataset':
        datasetLogs.value.push(data)
        setStep('research', 'active',
          `已获取 ${datasetLogs.value.length} 个数据集：${datasetLogs.value.map((d) => d.name).join('、')}`)
        break
      case 'direct':
        intent.value = 'general'
        directAnswer.value = data.directAnswer || ''
        if (data.title) title.value = data.title
        steps.value = []
        break
      case 'page':
        intent.value = 'data_page'
        html.value = data.html || ''
        dataBundle.value = data.bundle || null
        plan.value = data.plan || plan.value
        if (data.title) title.value = data.title
        usedTemplate.value = !!data.usedTemplate
        guardIssues.value = data.guardIssues || []
        revised.value = data.revised === undefined ? true : !!data.revised
        setStep('write', 'completed')
        setStep('research', 'completed')
        break
      case 'error':
        errorMsg.value = data.message || '生成失败'
        if (data.fatal) {
          status.value = 'failed'
          steps.value.forEach((s) => { if (s.state === 'active') s.state = 'error' })
        }
        break
      case 'done':
        if (data.status === 'ready') {
          status.value = 'ready'
          steps.value.forEach((s) => { if (s.state !== 'error') s.state = 'completed' })
        } else if (data.status === 'failed') {
          status.value = 'failed'
        }
        closeStream()
        break
    }
  }

  function subscribeSSE(pid: string, epoch: number) {
    closeStream()
    const es = new EventSource(`/api/ipage/stream/${pid}`)
    eventSource = es
    const types = ['plan', 'progress', 'dataset', 'page', 'direct']
    types.forEach((t) => {
      es.addEventListener(t, (e: MessageEvent) => {
        if (epoch !== generationEpoch) return
        try { applyEvent(t, JSON.parse(e.data)) } catch (err) { console.error('ipage SSE 解析失败', t, err) }
      })
    })
    es.addEventListener('done', (e: MessageEvent) => {
      if (epoch !== generationEpoch) return
      try { applyEvent('done', JSON.parse(e.data)) } catch (err) { console.error('ipage done 解析失败', err) }
      void fetchHistory(1)
    })
    es.addEventListener('error', (event: Event) => {
      if (epoch !== generationEpoch || status.value !== 'generating') return
      if (event instanceof MessageEvent && event.data) {
        try { applyEvent('error', JSON.parse(event.data)) } catch { /* 忽略无法解析的业务错误帧 */ }
        return
      }
      // 网络错误：EventSource 会自动重连；兜底轮询持久化页面
      scheduleRecovery(pid, epoch)
    })
  }

  let recoveryTimer: ReturnType<typeof setTimeout> | null = null
  let recoveryAttempts = 0
  function scheduleRecovery(pid: string, epoch: number) {
    if (recoveryTimer || epoch !== generationEpoch) return
    recoveryTimer = setTimeout(async () => {
      recoveryTimer = null
      if (epoch !== generationEpoch || status.value !== 'generating') return
      try {
        const resp: any = await api.get(`/ipage/pages/${encodeURIComponent(pid)}`)
        const item = resp?.data || resp
        if (item && item.status && item.status !== 'generating') {
          loadFromRecord(item)
          closeStream()
          return
        }
      } catch { /* 继续退避重试 */ }
      recoveryAttempts += 1
      if (recoveryAttempts >= 6) {
        errorMsg.value = '生成连接中断且后台状态暂不可确认，请稍后从历史记录重新打开'
        status.value = 'failed'
        closeStream()
      } else {
        scheduleRecovery(pid, epoch)
      }
    }, 4000)
  }

  function closeStream() {
    if (recoveryTimer) { clearTimeout(recoveryTimer); recoveryTimer = null }
    recoveryAttempts = 0
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  // ── 发起生成（parentPageId 非空时为对话式修订；sessionId 为空时后端自动建会话）──
  async function generate(q: string, opts: IpageGenerateOptions = {}) {
    const q2 = q.trim()
    if (!q2 || status.value === 'generating') return
    const epoch = ++generationEpoch
    resetRound()
    generationEpoch = epoch
    query.value = q2
    parentPageId.value = opts.parentPageId || ''
    status.value = 'generating'
    setStep('plan', 'active')
    try {
      const resp: any = await api.post('/ipage/generate', {
        query: q2,
        source: opts.source || 'manual',
        dataSourceId: opts.dataSourceId || '',
        parentPageId: opts.parentPageId || '',
        sessionId: opts.sessionId || '',
        context: {},
      })
      if (epoch !== generationEpoch) return
      if (!resp || resp.success === false) throw new Error(resp?.message || '生成请求失败')
      const data = resp.data || resp
      pageId.value = data.pageId
      if (data.sessionId && !sessionId.value) sessionId.value = data.sessionId
      subscribeSSE(data.pageId, epoch)
    } catch (error: any) {
      errorMsg.value = error?.serverMessage || error?.message || '生成请求失败'
      status.value = 'failed'
      setStep('plan', 'error', errorMsg.value)
    }
  }

  async function cancel() {
    const pid = pageId.value
    closeStream()
    if (pid) {
      try { await api.delete(`/ipage/generate/${encodeURIComponent(pid)}`) } catch { /* 任务可能已结束 */ }
    }
    status.value = 'idle'
  }

  // ── 历史 / 详情 ──
  function loadFromRecord(item: any) {
    closeStream()
    generationEpoch += 1
    pageId.value = item.pageId || ''
    parentPageId.value = item.parentId || ''
    if (item.sessionId) sessionId.value = item.sessionId
    title.value = item.title || ''
    query.value = item.query || ''
    status.value = item.status === 'ready' ? 'ready' : item.status === 'failed' ? 'failed' : 'idle'
    intent.value = item.intent || ''
    html.value = item.html || ''
    dataBundle.value = item.dataBundle || null
    plan.value = item.plan || null
    directAnswer.value = item.directAnswer || ''
    usedTemplate.value = item.error === 'template_fallback'
    guardIssues.value = []
    revised.value = true
    steps.value = []
  }

  async function loadPage(pid: string) {
    const resp: any = await api.get(`/ipage/pages/${encodeURIComponent(pid)}`)
    const item = resp?.data || resp
    if (!item) throw new Error('页面不存在')
    loadFromRecord(item)
    return item
  }

  async function fetchHistory(pageNo = 1) {
    try {
      const resp: any = await api.get(`/ipage/pages?pageNo=${pageNo}&size=20`)
      const data = resp?.data || resp
      history.value = data.items || []
      historyTotal.value = data.total || 0
      historyPage.value = data.page || 1
    } catch (error: any) {
      console.error('ipage 历史加载失败', error?.message)
    }
  }

  async function removePage(pid: string) {
    await api.delete(`/ipage/pages/${encodeURIComponent(pid)}`)
    if (pageId.value === pid) resetRound()
    await fetchHistory(historyPage.value || 1)
  }

  // ── 会话（对话式交互）──
  /** 后端消息 → 本地消息对象（page_card content 为 JSON 字符串需解包） */
  function normalizeMessage(raw: any): IpageChatMessage {
    const kind = (raw.kind || 'text') as IpageChatMessage['kind']
    let content = raw.content || ''
    let pageId2 = raw.pageId || ''
    let title2 = ''
    let usedTemplate = false
    if (kind === 'page_card') {
      try {
        const parsed = JSON.parse(content)
        pageId2 = parsed.pageId || pageId2
        title2 = parsed.title || ''
        usedTemplate = !!parsed.usedTemplate
        content = ''
      } catch {
        title2 = content
        content = ''
      }
    }
    messageSeq += 1
    return {
      id: raw.messageId || raw.id || `local-${messageSeq}`,
      role: raw.role === 'user' ? 'user' : 'ai',
      kind,
      content,
      pageId: pageId2,
      title: title2,
      usedTemplate,
      createdAt: raw.createdAt || '',
    }
  }

  /** 即时回显一条本地消息（后端已落库，重载会话时会被服务端消息替换） */
  function appendLocalMessage(msg: { role: 'user' | 'ai'; kind: IpageChatMessage['kind']; content: string; pageId?: string; title?: string; usedTemplate?: boolean }) {
    messageSeq += 1
    messages.value.push({
      id: `local-${messageSeq}`,
      role: msg.role,
      kind: msg.kind,
      content: msg.content || '',
      pageId: msg.pageId || '',
      title: msg.title || '',
      usedTemplate: !!msg.usedTemplate,
      createdAt: '',
    })
  }

  async function loadSessions() {
    try {
      const resp: any = await api.get('/ipage/sessions?pageNo=1&size=50')
      const data = resp?.data || resp
      sessions.value = data.items || []
    } catch (error: any) {
      console.error('态势页面会话列表加载失败', error?.message)
    }
  }

  /** 新建空会话并切换为当前会话 */
  async function createSession(title = '') {
    const resp: any = await api.post('/ipage/sessions', { title })
    const data = resp?.data || resp
    if (data?.sessionId) {
      sessions.value.unshift({
        sessionId: data.sessionId,
        title: data.title || '',
        userId: data.userId || '',
        messageCount: 0,
        pageCount: 0,
        createdAt: data.createdAt || '',
        updatedAt: data.updatedAt || '',
      })
      sessionId.value = data.sessionId
      messages.value = []
    }
    return data
  }

  /** 加载会话详情：恢复整段对话消息 */
  async function loadSession(sid: string) {
    const resp: any = await api.get(`/ipage/sessions/${encodeURIComponent(sid)}`)
    const data = resp?.data || resp
    if (!data) throw new Error('会话不存在')
    sessionId.value = data.sessionId || sid
    messages.value = (data.messages || []).map(normalizeMessage)
    return data
  }

  async function deleteSession(sid: string) {
    await api.delete(`/ipage/sessions/${encodeURIComponent(sid)}`)
    sessions.value = sessions.value.filter((s) => s.sessionId !== sid)
    if (sessionId.value === sid) {
      sessionId.value = ''
      messages.value = []
    }
  }

  return {
    pageId, parentPageId, status, intent, title, query,
    html, dataBundle, plan, directAnswer, usedTemplate, guardIssues, revised,
    errorMsg, steps, datasetLogs,
    history, historyTotal, historyPage,
    sessionId, sessions, messages,
    generate, cancel, loadPage, loadFromRecord, fetchHistory, removePage,
    resetRound, closeStream,
    appendLocalMessage, loadSessions, createSession, loadSession, deleteSession,
  }
})
