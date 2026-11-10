/**
 * 态势页面（ipage）Pinia store。
 *
 * SSE 事件 plan/dataset/progress/page/direct/done/error 落到本 store，
 * PageSandbox 用 html + dataBundle 渲染沙箱页面。
 * 会话模型：主对话框页（SituationPageDialog）与态势页（InteractivePage）
 * 共享同一会话，消息由后端落库，本地仅做即时回显。
 */
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import api from '@/services/api'
import type { EvaluationArtifactPayload } from '@/utils/evaluationArtifacts'

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
  /** 显式指定的技能 id（非空即手动指定） */
  skillId?: string
  /** 技能套用方式：auto=按问题语义自动匹配；off=关闭技能走自由规划 */
  skillMode?: 'auto' | 'off'
  /** 评估分析产物：非空时后端跳过规划与取数，直接用产物生成页面 */
  artifacts?: EvaluationArtifactPayload
}

/**
 * 评估分析 → 态势页面生成任务。
 *
 * 评估页可能在生成过程中被导航离开并销毁，任务状态放在全局 store 中，
 * 返回评估页后仍能恢复「正在生成 / 已生成」回执。
 */
export interface EvaluationSituationTask {
  id: string
  /** 发起任务的评估会话 id，用于只在对应会话中展示回执 */
  evaluationSessionId: string
  title: string
  pageId: string
  status: 'generating' | 'ready' | 'failed'
  error: string
  createdAt: string
}

/** 技能（生成剧本）元数据：列表接口下发，不含正文 */
export interface IpageSkill {
  id: string
  name: string
  description: string
  category: string
  order: number
  triggerCount: number
  requiredEntityKinds: string[]
  mapModes: string[]
  playback: boolean
  focusMetrics: string[]
  version: string
}

/** 本轮生成实际套用的技能（后端写在 plan.skill 中） */
export interface IpageMatchedSkill {
  id: string
  name: string
  version: string
  applied: boolean
  matchedBy: '' | 'auto' | 'manual' | 'inherited'
  score: number | null
  reason: string
  candidates: Array<{ id: string; name: string; score: number }>
  unresolvedNeeds: string[]
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

  // ── 评估分析 → 态势页面生成任务（跨路由保留，避免返回后回执消失）──
  const situationTask = ref<EvaluationSituationTask | null>(null)

  // ── 技能（生成剧本）──
  const skills = ref<IpageSkill[]>([])
  const skillsEnabled = ref(true)
  /** 服务端下发的默认策略：off=默认不套用；auto=默认自动匹配（回退值 off） */
  const skillDefaultMode = ref<'off' | 'auto'>('off')
  /**
   * 会话级技能选择（三态：__off__ 关闭 / __auto__ 自动匹配 / 技能 id 手动指定）。
   *
   * 空串表示"用户尚未显式选择"，显示与请求参数都以 effectiveSkillChoice 为准 ——
   * 这样"选择器看到的值"与"实际发出的策略"永远一致，且两个入口（主对话框 / 工作台）
   * 共用同一份状态，不再各自硬编码默认值。
   */
  const skillChoice = ref('')
  /** 本轮实际套用的技能（含匹配方式、匹配度与未生效需求），驱动页面标签展示 */
  const matchedSkill = computed<IpageMatchedSkill | null>(
    () => (plan.value?.skill as IpageMatchedSkill) || null,
  )
  /** 生效的技能选择：已显式选择用选择值，否则用服务端默认策略 */
  const effectiveSkillChoice = computed(
    () => skillChoice.value || (skillDefaultMode.value === 'auto' ? '__auto__' : '__off__'),
  )

  /** 设置会话级技能选择（'' 表示恢复默认策略） */
  function setSkillChoice(value: string) {
    skillChoice.value = value || ''
  }

  /** 会话级选择 → 请求参数（三态映射；显式技能时后端按手动指定处理，忽略 skillMode） */
  function resolveSkillChoice(): { skillId: string; skillMode: 'auto' | 'off' } {
    const choice = effectiveSkillChoice.value
    if (choice === '__off__') return { skillId: '', skillMode: 'off' }
    if (choice === '__auto__') return { skillId: '', skillMode: 'auto' }
    return { skillId: choice, skillMode: 'auto' }
  }

  // ── 评估分析让态势页面生成的跨页面任务 ──
  /** 开始一条评估分析发起的态势页面生成任务 */
  function startSituationTask(input: { evaluationSessionId?: string; title?: string } = {}) {
    situationTask.value = {
      id: `st-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      evaluationSessionId: input.evaluationSessionId || '',
      title: input.title || '态势页面',
      pageId: '',
      status: 'generating',
      error: '',
      createdAt: new Date().toISOString(),
    }
    return situationTask.value
  }

  /** 更新任务字段（页面 id、状态、错误等） */
  function updateSituationTask(patch: Partial<EvaluationSituationTask>) {
    if (!situationTask.value) return
    situationTask.value = { ...situationTask.value, ...patch }
  }

  /** 清除评估页的态势页面回执 */
  function clearSituationTask() {
    situationTask.value = null
  }

  /**
   * 把当前页面生成状态同步到评估页任务回执。
   *
   * 任务已有 pageId 时只接受同一页面的事件，避免被其他页面生成覆盖；
   * 任务尚未拿到 pageId 时采用当前页面 id（POST 返回后立即绑定）。
   */
  function syncSituationTask(statusOverride?: 'generating' | 'ready' | 'failed') {
    const task = situationTask.value
    if (!task || task.status !== 'generating') return
    if (task.pageId && pageId.value && task.pageId !== pageId.value) return
    const nextPageId = task.pageId || pageId.value
    const nextStatus = statusOverride || status.value
    if (nextStatus === 'ready') {
      situationTask.value = {
        ...task,
        pageId: nextPageId,
        title: title.value || task.title,
        status: 'ready',
        error: '',
      }
    } else if (nextStatus === 'failed') {
      situationTask.value = {
        ...task,
        pageId: nextPageId,
        status: 'failed',
        error: errorMsg.value || task.error || '态势页面生成失败',
      }
    } else if (nextPageId && nextPageId !== task.pageId) {
      situationTask.value = { ...task, pageId: nextPageId }
    }
  }

  let eventSource: EventSource | null = null
  let generationEpoch = 0
  let messageSeq = 0
  // 消息版本号：loadSession 请求期间若本地已追加消息（如点击推荐问题），
  // 返回的旧会话快照不能再覆盖当前对话
  let messagesRevision = 0

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
          syncSituationTask('failed')
        }
        break
      case 'done':
        if (data.status === 'ready') {
          status.value = 'ready'
          steps.value.forEach((s) => { if (s.state !== 'error') s.state = 'completed' })
          syncSituationTask('ready')
        } else if (data.status === 'failed') {
          status.value = 'failed'
          syncSituationTask('failed')
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
        syncSituationTask('failed')
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
      // 技能策略：调用方显式传参时以传参为准（并回写到会话级状态，保证两个入口同步），
      // 否则沿用会话级选择 / 服务端默认策略（默认 off = 不套用技能）
      const explicitSkill = !!opts.skillMode
      const skillOpts = explicitSkill
        ? { skillId: opts.skillId || '', skillMode: opts.skillMode as 'auto' | 'off' }
        : resolveSkillChoice()
      if (explicitSkill) {
        setSkillChoice(skillOpts.skillMode === 'off' ? '__off__'
          : (skillOpts.skillId ? skillOpts.skillId : '__auto__'))
      }
      const resp: any = await api.post('/ipage/generate', {
        query: q2,
        source: opts.source || 'manual',
        dataSourceId: opts.dataSourceId || '',
        parentPageId: opts.parentPageId || '',
        sessionId: opts.sessionId || '',
        skillId: skillOpts.skillId,
        skillMode: skillOpts.skillMode,
        context: {},
        artifacts: opts.artifacts || undefined,
      })
      if (epoch !== generationEpoch) return
      if (!resp || resp.success === false) throw new Error(resp?.message || '生成请求失败')
      const data = resp.data || resp
      pageId.value = data.pageId
      if (data.sessionId && !sessionId.value) sessionId.value = data.sessionId
      // POST 返回后立即把页面 id 绑定到评估页任务，方便返回时恢复回执
      syncSituationTask()
      subscribeSSE(data.pageId, epoch)
    } catch (error: any) {
      errorMsg.value = error?.serverMessage || error?.message || '生成请求失败'
      status.value = 'failed'
      setStep('plan', 'error', errorMsg.value)
      syncSituationTask('failed')
    }
  }

  async function cancel() {
    const pid = pageId.value
    closeStream()
    if (pid) {
      try { await api.delete(`/ipage/generate/${encodeURIComponent(pid)}`) } catch { /* 任务可能已结束 */ }
    }
    if (situationTask.value?.status === 'generating') {
      updateSituationTask({ status: 'failed', error: '态势页面生成已取消' })
    }
    status.value = 'idle'
  }

  // ── 历史 / 详情 ──
  /**
   * 页面记录 → 执行步骤。
   *
   * 页面生成完成后再次打开（历史记录、态势页返回、评估产物页）时，
   * SSE 步骤不会重放；这里根据 plan / dataBundle / sqlLog / html 还原
   * 执行过程面板，避免面板空白。
   */
  function buildStepsFromRecord(item: any): IpageStep[] {
    const plan = item?.plan || {}
    const bundle = item?.dataBundle || {}
    const datasets = Array.isArray(bundle.datasets) ? bundle.datasets : []
    const sqlLog = Array.isArray(item?.sqlLog) ? item.sqlLog : []
    const status = String(item?.status || '')
    const generating = status === 'generating'
    const failed = status === 'failed'
    const hasPlan = !!item?.plan
    const hasData = datasets.length > 0 || sqlLog.length > 0
    const hasHtml = !!item?.html
    const isEvaluation = String(plan?.origin?.type || '') === 'evaluation'

    const planState: IpageStep['state'] = hasPlan
      ? 'completed'
      : generating ? 'active' : 'pending'
    const researchState: IpageStep['state'] = hasData
      ? 'completed'
      : generating && hasPlan ? 'active' : 'pending'
    const writeState: IpageStep['state'] = hasHtml
      ? 'completed'
      : failed ? 'error' : generating && hasData ? 'active' : 'pending'

    const labels = isEvaluation
      ? { plan: '解析评估产物并规划页面', research: '整理勾选产物', write: '生成交互页面' }
      : { plan: '分析问题与规划页面', research: '查询数据集', write: '生成交互页面' }
    const pageTitle = String(plan?.title || item?.title || '')
    const researchDetail = isEvaluation
      ? `已整理 ${datasets.length} 个评估产物`
      : sqlLog.length
        ? `已执行 ${sqlLog.length} 条取数 SQL`
        : datasets.length ? `已获取 ${datasets.length} 个数据集` : ''
    const writeDetail = hasHtml
      ? '页面已生成'
      : failed ? String(item?.error || '页面生成失败') : ''

    return [
      {
        id: 'plan',
        label: labels.plan,
        state: planState,
        detail: pageTitle ? `页面标题：${pageTitle}` : undefined,
      },
      {
        id: 'research',
        label: labels.research,
        state: researchState,
        detail: researchDetail || undefined,
      },
      {
        id: 'write',
        label: labels.write,
        state: writeState,
        detail: writeDetail || undefined,
      },
    ]
  }

  /** 页面记录 → 取数明细（来自 dataBundle.datasets） */
  function buildDatasetLogsFromRecord(item: any) {
    const bundle = item?.dataBundle || {}
    const datasets = Array.isArray(bundle.datasets) ? bundle.datasets : []
    return datasets.map((dataset: any) => ({
      datasetId: dataset?.id || dataset?.datasetId || '',
      name: dataset?.name || dataset?.tableName || '数据集',
      mode: dataset?.mode === 'aggregate' ? 'aggregate' : 'detail',
      totalRows: dataset?.totalRows ?? 0,
      truncated: !!dataset?.truncated,
    }))
  }

  function loadFromRecord(item: any) {
    closeStream()
    generationEpoch += 1
    pageId.value = item.pageId || ''
    parentPageId.value = item.parentId || ''
    if (item.sessionId) sessionId.value = item.sessionId
    title.value = item.title || ''
    query.value = item.query || ''
    status.value = item.status === 'ready' ? 'ready'
      : item.status === 'failed' ? 'failed'
      : item.status === 'generating' ? 'generating'
      : 'idle'
    intent.value = item.intent || ''
    html.value = item.html || ''
    dataBundle.value = item.dataBundle || null
    plan.value = item.plan || null
    directAnswer.value = item.directAnswer || ''
    usedTemplate.value = item.error === 'template_fallback'
    guardIssues.value = []
    revised.value = true
    // 从记录还原执行过程，避免历史页面/评估产物页的执行面板空白
    steps.value = buildStepsFromRecord(item)
    datasetLogs.value = buildDatasetLogsFromRecord(item)
    // 若加载的是评估页正在等待的同一个页面，按落库状态刷新回执
    if (situationTask.value?.pageId && situationTask.value.pageId === pageId.value) {
      syncSituationTask()
    }
  }

  async function loadPage(pid: string) {
    const resp: any = await api.get(`/ipage/pages/${encodeURIComponent(pid)}`)
    const item = resp?.data || resp
    if (!item) throw new Error('页面不存在')
    loadFromRecord(item)
    return item
  }

  /**
   * 打开页面并在「生成中」时续订 SSE。
   *
   * 用于从其他入口（历史列表、评估页跳转）打开一个尚未完成的页面：
   * loadFromRecord 会关闭旧流，因此必须在它之后重新订阅，否则进度会丢失。
   */
  async function attachPage(pid: string) {
    const resp: any = await api.get(`/ipage/pages/${encodeURIComponent(pid)}`)
    const item = resp?.data || resp
    if (!item) throw new Error('页面不存在')
    loadFromRecord(item)
    if (item.status === 'generating') {
      const epoch = ++generationEpoch
      subscribeSSE(pid, epoch)
    }
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
    messagesRevision += 1
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

  /** 加载技能目录（供技能选择器；失败静默降级为空列表，不影响生成） */
  async function loadSkills() {
    try {
      const resp: any = await api.get('/ipage/skills')
      const data = resp?.data || resp
      skills.value = data?.items || []
      skillsEnabled.value = data?.enabled !== false
      // 默认策略由服务端下发（单一来源），缺失时回退 off（不套用技能）
      skillDefaultMode.value = data?.defaultMode === 'auto' ? 'auto' : 'off'
    } catch (error: any) {
      skills.value = []
      console.error('技能目录加载失败', error?.message)
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
      messagesRevision += 1
    }
    return data
  }

  /** 加载会话详情：恢复整段对话消息 */
  async function loadSession(sid: string) {
    const revisionAtStart = messagesRevision
    const resp: any = await api.get(`/ipage/sessions/${encodeURIComponent(sid)}`)
    const data = resp?.data || resp
    if (!data) throw new Error('会话不存在')
    // 请求期间用户已发起新问题/追加消息，或正在生成：保留当前对话，不用旧快照覆盖
    if (messagesRevision !== revisionAtStart || status.value === 'generating') return data
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
      messagesRevision += 1
    }
  }

  return {
    pageId, parentPageId, status, intent, title, query,
    html, dataBundle, plan, directAnswer, usedTemplate, guardIssues, revised,
    errorMsg, steps, datasetLogs,
    history, historyTotal, historyPage,
    sessionId, sessions, messages,
    situationTask,
    startSituationTask, updateSituationTask, clearSituationTask,
    skills, skillsEnabled, matchedSkill,
    skillChoice, skillDefaultMode, effectiveSkillChoice, setSkillChoice, resolveSkillChoice,
    generate, cancel, loadPage, attachPage, loadFromRecord, fetchHistory, removePage,
    resetRound, closeStream,
    appendLocalMessage, loadSessions, createSession, loadSession, deleteSession,
    loadSkills,
  }
})
