import api from '@/services/api'
import type {
  CreateSkillBatchPayload,
  EvaluationDatasetOption,
  EvaluationSkill,
  EvaluationSkillAvailability,
  EvaluationSkillCatalog,
  EvaluationSkillPermissions,
  EvaluationSkillStatus,
  EvaluationSkillUpsertPayload,
  EvaluationSkillVisibility,
  EvaluationSkillStep,
  ImportSkillsResult,
  ListEvaluationSkillsParams,
  ListSkillExecutionsParams,
  PublishSkillPayload,
  RecommendEvaluationSkillsParams,
  RollbackSkillPayload,
  ShareSkillPayload,
  SkillBatch,
  SkillAiDraftRequest,
  SkillAiDraftResult,
  SkillDatasetPlanItem,
  SkillExecution,
  SkillExecutionCatalog,
  SkillExecutionComparison,
  SkillExecutionStatus,
  SkillExecutionStep,
  SkillPreflightCheck,
  SkillPreflightResult,
  SkillQualityOverview,
  SkillQualityReport,
  SkillSchedule,
  SkillSchedulePayload,
  SkillShare,
  SkillTrialPayload,
  SkillVersion
} from '@/types/evaluationSkill'

type UnknownRecord = Record<string, any>

const asRecord = (value: unknown): UnknownRecord =>
  value && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : {}

const asString = (value: unknown): string =>
  typeof value === 'string' ? value : value == null ? '' : String(value)

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.map(asString).filter(Boolean) : []

const asBoolean = (value: unknown, fallback = false): boolean => {
  if (value == null) return fallback
  if (typeof value === 'string') return !['', '0', 'false', 'no'].includes(value.toLowerCase())
  return Boolean(value)
}

const unwrapData = (value: unknown): unknown => {
  const root = asRecord(value)
  return root.data ?? value
}

const normalizeSkillStatus = (value: unknown): EvaluationSkillStatus => {
  const status = asString(value).toLowerCase()
  return ['published', 'disabled', 'archived'].includes(status)
    ? status as EvaluationSkillStatus
    : 'draft'
}

const normalizeVisibility = (value: unknown): EvaluationSkillVisibility => {
  const visibility = asString(value).toLowerCase()
  return ['team', 'public'].includes(visibility)
    ? visibility as EvaluationSkillVisibility
    : 'private'
}

const normalizeExecutionStatus = (value: unknown): SkillExecutionStatus => {
  const status = asString(value).toLowerCase()
  const supported: SkillExecutionStatus[] = [
    'queued', 'running', 'completed', 'failed', 'error', 'cancelled',
    'partial', 'cancellation_requested', 'timed_out'
  ]
  return supported.includes(status as SkillExecutionStatus)
    ? status as SkillExecutionStatus
    : 'queued'
}

const normalizeStep = (value: unknown): EvaluationSkillStep => {
  const step = asRecord(value)
  return {
    id: asString(step.id),
    name: asString(step.name),
    description: asString(step.description),
    datasetKeywords: asStringArray(step.datasetKeywords ?? step.dataset_keywords),
    allowReuse: asBoolean(step.allowReuse ?? step.allow_reuse),
    datasetId: asString(step.datasetId ?? step.dataset_id),
    datasetName: asString(step.datasetName ?? step.dataset_name),
    dependsOn: asStringArray(step.dependsOn ?? step.depends_on),
    runIf: ['any_success', 'always'].includes(asString(step.runIf ?? step.run_if))
      ? asString(step.runIf ?? step.run_if) as 'any_success' | 'always'
      : 'all_success',
    retryCount: Number(step.retryCount ?? step.retry_count) || 0,
    timeoutSeconds: Number(step.timeoutSeconds ?? step.timeout_seconds) || 130,
    onFailure: ['stop', 'skip_dependents'].includes(asString(step.onFailure ?? step.on_failure))
      ? asString(step.onFailure ?? step.on_failure) as 'stop' | 'skip_dependents'
      : 'continue'
  }
}

const normalizeDatasetPlanItem = (value: unknown): SkillDatasetPlanItem => {
  const item = asRecord(value)
  return {
    sequence: Number(item.sequence) || 0,
    stepId: asString(item.stepId ?? item.step_id),
    stepName: asString(item.stepName ?? item.step_name),
    datasetId: asString(item.datasetId ?? item.dataset_id),
    datasetName: asString(item.datasetName ?? item.dataset_name),
    tableName: asString(item.tableName ?? item.table_name),
    matched: asBoolean(item.matched),
    message: asString(item.message)
  }
}

const normalizeAvailability = (value: unknown): EvaluationSkillAvailability | undefined => {
  if (!value || typeof value !== 'object') return undefined
  const availability = asRecord(value)
  const matchedSteps = Number(availability.matchedSteps ?? availability.matched_steps) || 0
  const totalSteps = Number(availability.totalSteps ?? availability.total_steps) || 0
  return {
    matchedSteps,
    totalSteps,
    available: asBoolean(availability.available, matchedSteps > 0),
    complete: asBoolean(availability.complete, totalSteps > 0 && matchedSteps === totalSteps),
    runtimeSelectable: asBoolean(
      availability.runtimeSelectable ?? availability.runtime_selectable
    ),
    selectionMode: asString(availability.selectionMode ?? availability.selection_mode) === 'runtime'
      ? 'runtime'
      : 'configured',
    completeness: availability.completeness == null
      ? (totalSteps ? matchedSteps / totalSteps : 0)
      : Number(availability.completeness),
    datasetPlan: Array.isArray(availability.datasetPlan ?? availability.dataset_plan)
      ? (availability.datasetPlan ?? availability.dataset_plan).map(normalizeDatasetPlanItem)
      : [],
    missingSteps: asStringArray(availability.missingSteps ?? availability.missing_steps)
  }
}

const normalizePermissions = (value: unknown, isBuiltIn: boolean): EvaluationSkillPermissions => {
  const permissions = asRecord(value)
  const editable = asBoolean(permissions.edit ?? permissions.editable, !isBuiltIn)
  const deletable = asBoolean(permissions.delete ?? permissions.deletable, !isBuiltIn)
  return {
    view: asBoolean(permissions.view ?? permissions.visible, true),
    edit: editable,
    delete: deletable,
    publish: asBoolean(permissions.publish ?? permissions.publishable, !isBuiltIn),
    share: asBoolean(permissions.share ?? permissions.shareable, true),
    execute: asBoolean(permissions.execute ?? permissions.executable, true),
    manageSchedule: asBoolean(
      permissions.manageSchedule ?? permissions.manage_schedule ?? permissions.schedulable,
      !isBuiltIn
    )
  }
}

export const normalizeEvaluationSkill = (value: unknown): EvaluationSkill => {
  const raw = asRecord(unwrapData(value))
  const skill = asRecord(raw.skill ?? raw)
  const steps = Array.isArray(skill.steps) ? skill.steps.map(normalizeStep) : []
  const source = asString(skill.source ?? skill.origin) === 'custom' ? 'custom' : 'builtin'
  const isBuiltIn = source === 'builtin'
  const permissions = normalizePermissions(skill.permissions, isBuiltIn)
  return {
    id: asString(skill.id),
    name: asString(skill.name),
    description: asString(skill.description),
    category: asString(skill.category) || '其他',
    triggers: asStringArray(skill.triggers),
    recommendedQuestions: asStringArray(skill.recommendedQuestions ?? skill.recommended_questions),
    steps,
    outputInstruction: asString(skill.outputInstruction ?? skill.output_instruction),
    orchestration: {
      mode: asString(skill.orchestration?.mode) === 'dependency' ? 'dependency' : 'sequential',
      maxConcurrency: Number(skill.orchestration?.maxConcurrency ?? skill.orchestration?.max_concurrency) || 1,
      timeoutSeconds: Number(skill.orchestration?.timeoutSeconds ?? skill.orchestration?.timeout_seconds) || 600,
      failurePolicy: asString(skill.orchestration?.failurePolicy ?? skill.orchestration?.failure_policy) === 'stop'
        ? 'stop'
        : 'continue'
    },
    stepCount: Number(skill.stepCount ?? skill.step_count) || steps.length,
    availability: normalizeAvailability(skill.availability),
    score: skill.score == null && skill.recommendationScore == null
      ? undefined
      : Number(skill.score ?? skill.recommendationScore),
    matchedTriggers: asStringArray(skill.matchedTriggers ?? skill.matched_triggers),
    recommendationReason: asString(skill.recommendationReason ?? skill.recommendation_reason),
    source,
    isBuiltIn: skill.isBuiltIn == null ? isBuiltIn : asBoolean(skill.isBuiltIn),
    isTemplate: asBoolean(skill.isTemplate ?? skill.is_template),
    executable: asBoolean(skill.executable, !asBoolean(skill.isTemplate ?? skill.is_template)),
    editable: skill.editable == null ? permissions.edit : asBoolean(skill.editable),
    deletable: skill.deletable == null ? permissions.delete : asBoolean(skill.deletable),
    revision: Number(skill.revision) || 1,
    version: Number(skill.version ?? skill.currentVersion ?? skill.current_version) || 1,
    publishedVersion: skill.publishedVersion == null && skill.published_version == null
      ? undefined
      : Number(skill.publishedVersion ?? skill.published_version),
    status: normalizeSkillStatus(skill.status ?? (isBuiltIn ? 'published' : 'draft')),
    visibility: normalizeVisibility(skill.visibility ?? (isBuiltIn ? 'public' : 'private')),
    ownerId: asString(skill.ownerId ?? skill.owner_id),
    ownerName: asString(skill.ownerName ?? skill.owner_name),
    teamId: asString(skill.teamId ?? skill.team_id),
    teamName: asString(skill.teamName ?? skill.team_name),
    tags: asStringArray(skill.tags),
    favorited: asBoolean(skill.favorited ?? skill.favorite ?? skill.isFavorite ?? skill.is_favorite),
    favoriteCount: Number(skill.favoriteCount ?? skill.favorite_count) || 0,
    permissions,
    publishedAt: asString(skill.publishedAt ?? skill.published_at),
    createdAt: asString(skill.createdAt ?? skill.created_at),
    updatedAt: asString(skill.updatedAt ?? skill.updated_at)
  }
}

const extractSkills = (response: unknown): EvaluationSkill[] => {
  if (Array.isArray(response)) return response.map(normalizeEvaluationSkill)
  const root = asRecord(response)
  const nestedData = asRecord(root.data)
  const rawSkills = root.skills ?? root.items ?? nestedData.skills ?? nestedData.items
  return Array.isArray(rawSkills) ? rawSkills.map(normalizeEvaluationSkill) : []
}

export const listEvaluationSkills = async (
  params: ListEvaluationSkillsParams = {}
): Promise<EvaluationSkillCatalog> => {
  const response = await api.get<unknown>('/evaluation/skills', { params })
  const root = asRecord(response)
  const nestedData = asRecord(root.data)
  const skills = extractSkills(response)
  return {
    version: asString(root.version ?? nestedData.version),
    total: Number(root.total ?? nestedData.total) || skills.length,
    builtInTotal: Number(root.builtInTotal ?? nestedData.builtInTotal)
      || skills.filter(skill => skill.source === 'builtin').length,
    customTotal: Number(root.customTotal ?? nestedData.customTotal)
      || skills.filter(skill => skill.source === 'custom').length,
    customStoreStatus: asString(root.customStoreStatus ?? nestedData.customStoreStatus) === 'warning'
      ? 'warning'
      : 'ready',
    customStoreMessage: asString(root.customStoreMessage ?? nestedData.customStoreMessage),
    tags: asStringArray(root.tags ?? nestedData.tags),
    skills
  }
}

export const getEvaluationSkill = async (skillId: string): Promise<EvaluationSkill> =>
  normalizeEvaluationSkill(await api.get<unknown>(`/evaluation/skills/${encodeURIComponent(skillId)}`))

export const recommendEvaluationSkills = async (
  params: RecommendEvaluationSkillsParams
): Promise<EvaluationSkill[]> => {
  const response = await api.post<unknown>('/evaluation/skills/recommend', {
    query: params.query,
    limit: params.limit ?? 3,
    ...(params.dataSourceId ? { dataSourceId: params.dataSourceId } : {})
  })
  return extractSkills(response)
}

export const createEvaluationSkill = async (
  payload: EvaluationSkillUpsertPayload
): Promise<EvaluationSkill> =>
  normalizeEvaluationSkill(await api.post<unknown>('/evaluation/skills', payload))

export const updateEvaluationSkill = async (
  skillId: string,
  payload: EvaluationSkillUpsertPayload,
  expectedRevision: number
): Promise<EvaluationSkill> => normalizeEvaluationSkill(await api.put<unknown>(
  `/evaluation/skills/${encodeURIComponent(skillId)}`,
  { ...payload, expectedRevision }
))

export const deleteEvaluationSkill = async (
  skillId: string,
  expectedRevision: number
): Promise<void> => {
  await api.delete(`/evaluation/skills/${encodeURIComponent(skillId)}`, {
    params: { expectedRevision }
  })
}

export const setEvaluationSkillFavorite = async (
  skillId: string,
  favorite: boolean
): Promise<void> => {
  const url = `/evaluation/skills/${encodeURIComponent(skillId)}/favorite`
  if (favorite) await api.put(url)
  else await api.delete(url)
}

export const publishEvaluationSkill = async (
  skillId: string,
  payload: PublishSkillPayload = {}
): Promise<EvaluationSkill> => normalizeEvaluationSkill(await api.post<unknown>(
  `/evaluation/skills/${encodeURIComponent(skillId)}/publish`,
  payload
))

export const listEvaluationSkillVersions = async (skillId: string): Promise<SkillVersion[]> => {
  const response = await api.get<unknown>(
    `/evaluation/skills/${encodeURIComponent(skillId)}/versions`
  )
  const root = asRecord(unwrapData(response))
  const values = Array.isArray(response) ? response : root.versions ?? root.items
  if (!Array.isArray(values)) return []
  return values.map(value => {
    const version = asRecord(value)
    return {
      id: asString(version.id),
      skillId: asString(version.skillId ?? version.skill_id) || skillId,
      version: Number(version.version) || 1,
      revision: version.revision == null ? undefined : Number(version.revision),
      status: normalizeSkillStatus(version.status ?? (version.published ? 'published' : 'draft')),
      changeNote: asString(version.changeNote ?? version.change_note ?? version.action),
      createdBy: asString(version.createdBy ?? version.created_by ?? version.actorId),
      createdByName: asString(version.createdByName ?? version.created_by_name),
      createdAt: asString(version.createdAt ?? version.created_at),
      publishedAt: asString(version.publishedAt ?? version.published_at),
      snapshot: asRecord(version.snapshot) as Partial<EvaluationSkill>
    }
  })
}

export const rollbackEvaluationSkill = async (
  skillId: string,
  payload: RollbackSkillPayload
): Promise<EvaluationSkill> => normalizeEvaluationSkill(await api.post<unknown>(
  `/evaluation/skills/${encodeURIComponent(skillId)}/rollback`,
  payload
))

export const cloneEvaluationSkill = async (
  skillId: string,
  options: { name?: string; asTemplate?: boolean } = {}
): Promise<EvaluationSkill> => normalizeEvaluationSkill(await api.post<unknown>(
  `/evaluation/skills/${encodeURIComponent(skillId)}/clone`,
  options
))

export const shareEvaluationSkill = async (
  skillId: string,
  payload: ShareSkillPayload = {}
): Promise<SkillShare> => {
  const response = asRecord(unwrapData(await api.post<unknown>(
    `/evaluation/skills/${encodeURIComponent(skillId)}/share`,
    payload
  )))
  const token = asString(response.token)
  const rawUrl = asString(response.url ?? response.shareUrl ?? response.share_url)
  const fallbackUrl = token && typeof window !== 'undefined'
    ? `${window.location.origin}/api/evaluation/shared-skills/${encodeURIComponent(token)}`
    : ''
  const resolvedUrl = rawUrl.startsWith('/') && typeof window !== 'undefined'
    ? `${window.location.origin}${rawUrl.startsWith('/api/') ? '' : '/api'}${rawUrl}`
    : rawUrl
  return {
    id: asString(response.id ?? response.token),
    skillId: asString(response.skillId ?? response.skill_id) || skillId,
    token,
    url: resolvedUrl || fallbackUrl,
    visibility: normalizeVisibility(response.visibility),
    expiresAt: asString(response.expiresAt ?? response.expires_at),
    createdAt: asString(response.createdAt ?? response.created_at)
  }
}

export const exportEvaluationSkill = async (skillId: string): Promise<unknown> => {
  const response = await api.get<unknown>(`/evaluation/skills/${encodeURIComponent(skillId)}/export`)
  const root = asRecord(response)
  return root.document ?? response
}

export const importEvaluationSkills = async (
  document: unknown,
  conflictPolicy: 'rename' | 'skip' | 'error' = 'rename'
): Promise<ImportSkillsResult> => {
  const response = asRecord(unwrapData(await api.post<unknown>('/evaluation/skills/import', {
    document,
    conflictPolicy
  })))
  const rawSkills = Array.isArray(response.skills)
    ? response.skills
    : Array.isArray(response.created) ? response.created : []
  const skippedItems = Array.isArray(response.skipped) ? response.skipped : []
  return {
    imported: Number(response.imported) || rawSkills.length,
    skipped: typeof response.skipped === 'number' ? response.skipped : skippedItems.length,
    skills: rawSkills.map(normalizeEvaluationSkill),
    warnings: asStringArray(response.warnings).length
      ? asStringArray(response.warnings)
      : skippedItems.map(item => {
        const skipped = asRecord(item)
        return [asString(skipped.name), asString(skipped.reason)].filter(Boolean).join(': ')
      }).filter(Boolean)
  }
}

export const listEvaluationSkillTemplates = async (): Promise<EvaluationSkill[]> => {
  const response = await api.get<unknown>('/evaluation/skills', { params: { template: true } })
  return extractSkills(response)
}

export const instantiateEvaluationSkillTemplate = async (
  templateId: string,
  name?: string
): Promise<EvaluationSkill> => normalizeEvaluationSkill(await api.post<unknown>(
  `/evaluation/skills/${encodeURIComponent(templateId)}/clone`,
  { name, asTemplate: false }
))

export const listEvaluationDatasets = async (
  dataSourceId: string
): Promise<EvaluationDatasetOption[]> => {
  if (!dataSourceId) return []
  const response = await api.get<unknown>(
    `/evaluation/data-sources/${encodeURIComponent(dataSourceId)}/datasets`
  )
  const root = asRecord(response)
  const nestedData = asRecord(root.data)
  const rawDatasets = root.datasets ?? nestedData.datasets
  if (!Array.isArray(rawDatasets)) return []
  return rawDatasets.map(value => {
    const dataset = asRecord(value)
    return {
      id: asString(dataset.id),
      name: asString(dataset.name),
      tableName: asString(dataset.tableName ?? dataset.table_name),
      description: asString(dataset.description)
    }
  }).filter(dataset => dataset.id && dataset.tableName)
}

const normalizeCheck = (value: unknown, index: number): SkillPreflightCheck => {
  if (typeof value === 'string') {
    return { code: `check-${index + 1}`, name: `检查 ${index + 1}`, status: 'passed', message: value }
  }
  const check = asRecord(value)
  const rawStatus = asString(check.status).toLowerCase()
  return {
    code: asString(check.code) || `check-${index + 1}`,
    name: asString(check.name ?? check.title) || `检查 ${index + 1}`,
    status: rawStatus === 'failed' || rawStatus === 'error'
      ? 'failed'
      : rawStatus === 'warning' || rawStatus === 'incomplete'
        ? 'warning'
        : 'passed',
    message: asString(check.message ?? check.detail),
    stepId: asString(check.stepId ?? check.step_id),
    datasetId: asString(check.datasetId ?? check.dataset_id)
  }
}

export const preflightEvaluationSkill = async (
  skillId: string,
  dataSourceId: string
): Promise<SkillPreflightResult> => {
  const response = asRecord(unwrapData(await api.post<unknown>(
    `/evaluation/skills/${encodeURIComponent(skillId)}/preflight`,
    { dataSourceId }
  )))
  const availability = normalizeAvailability(response.availability ?? {
    matchedSteps: response.matchedSteps ?? response.matched_steps,
    totalSteps: response.totalSteps ?? response.total_steps,
    completeness: response.completeness,
    complete: response.ready,
    available: Number(response.matchedSteps ?? response.matched_steps) > 0
      || asBoolean(response.runtimeSelectable ?? response.runtime_selectable),
    runtimeSelectable: response.runtimeSelectable ?? response.runtime_selectable,
    selectionMode: (response.runtimeSelectable ?? response.runtime_selectable) ? 'runtime' : 'configured',
    datasetPlan: response.datasetPlan ?? response.dataset_plan
  })
  return {
    skillId: asString(response.skillId ?? response.skill_id) || skillId,
    dataSourceId: asString(response.dataSourceId ?? response.databaseId ?? response.database_id) || dataSourceId,
    runnable: asBoolean(response.runnable ?? response.ready),
    checkedAt: asString(response.checkedAt ?? response.checked_at),
    availability,
    checks: Array.isArray(response.checks)
      ? response.checks.map(normalizeCheck)
      : []
  }
}

const normalizeExecutionStep = (value: unknown, index: number): SkillExecutionStep => {
  const step = asRecord(value)
  return {
    id: asString(step.id) || asString(step.stepId ?? step.step_id) || `step-${index + 1}`,
    stepId: asString(step.stepId ?? step.step_id ?? step.id),
    stepName: asString(step.stepName ?? step.step_name ?? step.name) || `步骤 ${index + 1}`,
    sequence: Number(step.sequence ?? step.index) || index + 1,
    status: normalizeExecutionStatus(step.status),
    progress: step.progress == null ? undefined : Number(step.progress),
    datasetId: asString(step.datasetId ?? step.dataset_id),
    datasetName: asString(step.datasetName ?? step.dataset_name),
    summary: asString(step.summary ?? step.resultSummary ?? step.result_summary),
    error: asString(step.error ?? step.message),
    startedAt: asString(step.startedAt ?? step.started_at),
    finishedAt: asString(step.finishedAt ?? step.finished_at),
    durationMs: step.durationMs == null && step.duration_ms == null
      ? undefined
      : Number(step.durationMs ?? step.duration_ms)
  }
}

const normalizeExecution = (value: unknown): SkillExecution => {
  const raw = asRecord(unwrapData(value))
  const execution = asRecord(raw.execution ?? raw.skillExecution ?? raw.skill_execution ?? raw)
  const executionResult = asRecord(execution.result)
  const runId = asString(execution.runId ?? execution.run_id ?? execution.id)
  return {
    id: asString(execution.id) || runId,
    runId,
    skillId: asString(execution.skillId ?? execution.skill_id),
    skillName: asString(execution.skillName ?? execution.skill_name),
    skillVersion: execution.skillVersion == null && execution.skill_version == null
      ? undefined
      : Number(execution.skillVersion ?? execution.skill_version),
    type: execution.type,
    status: normalizeExecutionStatus(execution.status),
    query: asString(execution.query ?? execution.question),
    dataSourceId: asString(execution.dataSourceId ?? execution.data_source_id ?? execution.databaseId),
    progress: Number(execution.progress) || 0,
    summary: asString(
      execution.summary
      ?? execution.finalAnswer
      ?? execution.final_answer
      ?? executionResult.finalAnswer
      ?? executionResult.final_answer
    ),
    result: execution.result ?? execution.stepResult ?? execution.step_result,
    error: asString(execution.error ?? execution.message),
    steps: Array.isArray(execution.steps)
      ? execution.steps.map(normalizeExecutionStep)
      : [],
    createdBy: asString(execution.createdBy ?? execution.created_by),
    createdByName: asString(execution.createdByName ?? execution.created_by_name),
    createdAt: asString(execution.createdAt ?? execution.created_at),
    startedAt: asString(execution.startedAt ?? execution.started_at),
    finishedAt: asString(execution.finishedAt ?? execution.finished_at),
    durationMs: execution.durationMs == null && execution.duration_ms == null
      ? undefined
      : Number(execution.durationMs ?? execution.duration_ms)
  }
}

const parseTrialResponse = (response: unknown): unknown => {
  if (typeof response !== 'string') return response
  const events = response.split(/\r?\n/)
    .map(line => line.replace(/^data:\s*/, '').trim())
    .filter(line => line && line !== '[DONE]')
    .flatMap(line => {
      try { return [JSON.parse(line)] } catch { return [] }
    })
  return [...events].reverse().find(event => {
    const value = asRecord(event)
    return value.execution || value.skillExecution || value.runId || value.type === 'result'
  }) ?? events[events.length - 1] ?? {}
}

export const trialEvaluationSkillStep = async (
  skillId: string,
  payload: SkillTrialPayload
): Promise<SkillExecution> => {
  const response = await api.post<unknown>(
    `/evaluation/skills/${encodeURIComponent(skillId)}/trial`,
    { ...payload }
  )
  return normalizeExecution(parseTrialResponse(response))
}

export const listSkillExecutions = async (
  params: ListSkillExecutionsParams = {}
): Promise<SkillExecutionCatalog> => {
  const response = await api.get<unknown>('/evaluation/executions', { params })
  const root = asRecord(unwrapData(response))
  const values = Array.isArray(response) ? response : root.items ?? root.executions
  const items = Array.isArray(values) ? values.map(normalizeExecution) : []
  return { total: Number(root.total) || items.length, items }
}

export const getSkillExecution = async (runId: string): Promise<SkillExecution> =>
  normalizeExecution(await api.get<unknown>(`/evaluation/executions/${encodeURIComponent(runId)}`))

export const cancelSkillExecution = async (runId: string): Promise<{ accepted: boolean; status: string; message: string }> => {
  const response = asRecord(unwrapData(await api.post<unknown>(
    `/evaluation/executions/${encodeURIComponent(runId)}/cancel`
  )))
  const status = asString(response.status)
  return {
    accepted: asBoolean(response.accepted, status === 'cancellation_requested'),
    status,
    message: asString(response.message)
  }
}

const normalizeSchedule = (value: unknown): SkillSchedule => {
  const schedule = asRecord(value)
  return {
    id: asString(schedule.id ?? schedule.scheduleId ?? schedule.schedule_id),
    skillId: asString(schedule.skillId ?? schedule.skill_id),
    name: asString(schedule.name),
    cron: asString(schedule.cron ?? schedule.cronExpression ?? schedule.cron_expression),
    timezone: asString(schedule.timezone) || 'Asia/Shanghai',
    enabled: asBoolean(schedule.enabled, true),
    query: asString(schedule.query ?? schedule.question),
    dataSourceId: asString(schedule.dataSourceId ?? schedule.data_source_id ?? schedule.databaseId),
    nextRunAt: asString(schedule.nextRunAt ?? schedule.next_run_at),
    lastRunAt: asString(schedule.lastRunAt ?? schedule.last_run_at),
    createdAt: asString(schedule.createdAt ?? schedule.created_at),
    updatedAt: asString(schedule.updatedAt ?? schedule.updated_at)
  }
}

export const listSkillSchedules = async (skillId?: string): Promise<SkillSchedule[]> => {
  const response = await api.get<unknown>('/evaluation/schedules', {
    params: skillId ? { skillId } : undefined
  })
  const root = asRecord(unwrapData(response))
  const values = Array.isArray(response) ? response : root.items ?? root.schedules
  return Array.isArray(values) ? values.map(normalizeSchedule) : []
}

export const createSkillSchedule = async (payload: SkillSchedulePayload & { skillId: string }): Promise<SkillSchedule> =>
  normalizeSchedule(unwrapData(await api.post<unknown>('/evaluation/schedules', payload)))

export const updateSkillSchedule = async (
  scheduleId: string,
  payload: Partial<SkillSchedulePayload>
): Promise<SkillSchedule> => normalizeSchedule(unwrapData(await api.put<unknown>(
  `/evaluation/schedules/${encodeURIComponent(scheduleId)}`,
  payload
)))

export const deleteSkillSchedule = async (scheduleId: string): Promise<void> => {
  await api.delete(`/evaluation/schedules/${encodeURIComponent(scheduleId)}`)
}

const normalizeBatch = (value: unknown): SkillBatch => {
  const batch = asRecord(unwrapData(value))
  const rawItems = Array.isArray(batch.items) ? batch.items : []
  return {
    id: asString(batch.id ?? batch.batchId ?? batch.batch_id),
    skillId: asString(batch.skillId ?? batch.skill_id),
    name: asString(batch.name),
    dataSourceId: asString(batch.dataSourceId ?? batch.data_source_id),
    status: normalizeExecutionStatus(batch.status),
    total: Number(batch.total ?? batch.totalItems) || rawItems.length,
    completed: Number(batch.completed ?? batch.completedItems) || 0,
    failed: Number(batch.failed ?? batch.failedItems) || 0,
    items: rawItems.map(value => {
      const item = asRecord(value)
      return {
        id: asString(item.id),
        query: asString(item.query ?? item.question),
        status: normalizeExecutionStatus(item.status),
        runId: asString(item.runId ?? item.run_id),
        result: item.result,
        error: asString(item.error ?? item.message)
      }
    }),
    createdAt: asString(batch.createdAt ?? batch.created_at),
    finishedAt: asString(batch.finishedAt ?? batch.finished_at)
  }
}

export const createSkillBatch = async (payload: CreateSkillBatchPayload): Promise<SkillBatch> =>
  normalizeBatch(await api.post<unknown>('/evaluation/batches', payload))

export const listSkillBatches = async (skillId?: string): Promise<SkillBatch[]> => {
  const response = await api.get<unknown>('/evaluation/batches', {
    params: skillId ? { skillId } : undefined
  })
  const root = asRecord(unwrapData(response))
  const values = Array.isArray(response) ? response : root.items ?? root.batches
  return Array.isArray(values) ? values.map(normalizeBatch) : []
}

export const cancelSkillBatch = async (
  batchId: string
): Promise<{ accepted: boolean; status: string; message: string }> => {
  const response = asRecord(unwrapData(await api.post<unknown>(
    `/evaluation/batches/${encodeURIComponent(batchId)}/cancel`
  )))
  const status = asString(response.status)
  return {
    accepted: asBoolean(response.accepted, status === 'cancellation_requested'),
    status,
    message: asString(response.message)
  }
}

export const compareSkillExecutions = async (runIds: string[]): Promise<SkillExecutionComparison> => {
  const response = asRecord(unwrapData(await api.post<unknown>('/evaluation/executions/compare', {
    runIds
  })))
  const rawItems = Array.isArray(response.items)
    ? response.items
    : Array.isArray(response.rows) ? response.rows : []
  return {
    runIds: asStringArray(response.runIds ?? response.run_ids).length
      ? asStringArray(response.runIds ?? response.run_ids)
      : runIds,
    items: rawItems.map(value => {
      const item = asRecord(value)
      return {
        runId: asString(item.runId ?? item.run_id),
        skillName: asString(item.skillName ?? item.skill_name),
        skillVersion: item.skillVersion == null && item.skill_version == null
          ? undefined
          : Number(item.skillVersion ?? item.skill_version),
        status: normalizeExecutionStatus(item.status),
        durationMs: item.durationMs == null && item.duration_ms == null
          ? undefined
          : Number(item.durationMs ?? item.duration_ms),
        summary: asString(item.summary ?? item.finalAnswer ?? item.final_answer),
        metrics: Object.keys(asRecord(item.metrics)).length
          ? asRecord(item.metrics)
          : {
            durationMs: item.durationMs ?? item.duration_ms ?? null,
            completedSteps: item.completedSteps ?? item.completed_steps ?? null,
            skippedSteps: item.skippedSteps ?? item.skipped_steps ?? null,
            errorSteps: item.errorSteps ?? item.error_steps ?? null,
            completionRate: item.completionRate ?? item.completion_rate ?? null
          }
      }
    }),
    metricNames: asStringArray(response.metricNames ?? response.metric_names ?? response.metrics),
    generatedAt: asString(response.generatedAt ?? response.generated_at)
  }
}

export const generateEvaluationSkillDraft = async (
  payload: SkillAiDraftRequest
): Promise<SkillAiDraftResult> => {
  const response = asRecord(unwrapData(await api.post<unknown>('/evaluation/skills/ai-draft', payload)))
  const draft = asRecord(response.draft)
  const normalized = normalizeEvaluationSkill({
    ...draft,
    id: 'ai-draft',
    source: 'custom',
    status: 'draft'
  })
  return {
    draft: {
      name: normalized.name,
      description: normalized.description,
      category: normalized.category,
      triggers: normalized.triggers,
      recommendedQuestions: normalized.recommendedQuestions,
      steps: normalized.steps,
      outputInstruction: normalized.outputInstruction,
      orchestration: normalized.orchestration,
      visibility: 'private',
      tags: asStringArray(draft.tags)
    },
    dataContext: {
      datasetCount: Number(response.dataContext?.datasetCount ?? draft.dataContext?.datasetCount) || 0,
      dataSourceComplete: asBoolean(
        response.dataContext?.dataSourceComplete ?? draft.dataContext?.dataSourceComplete
      )
    }
  }
}

const normalizeQualityReport = (value: unknown): SkillQualityReport => {
  const report = asRecord(value)
  const rawDimensions = asRecord(report.dimensions)
  const dimensions: SkillQualityReport['dimensions'] = {}
  Object.entries(rawDimensions).forEach(([key, rawValue]) => {
    const dimension = asRecord(rawValue)
    dimensions[key] = {
      score: Number(dimension.score) || 0,
      maxScore: Number(dimension.maxScore ?? dimension.max_score) || 0
    }
  })
  return {
    reportId: asString(report.reportId ?? report.report_id),
    runId: asString(report.runId ?? report.run_id),
    skillId: asString(report.skillId ?? report.skill_id),
    score: Number(report.score) || 0,
    grade: ['A', 'B', 'C'].includes(asString(report.grade))
      ? asString(report.grade) as 'A' | 'B' | 'C'
      : 'D',
    dimensions,
    issues: asStringArray(report.issues),
    suggestions: asStringArray(report.suggestions),
    expectedKeywordCoverage: report.expectedKeywordCoverage == null
      ? null
      : Number(report.expectedKeywordCoverage),
    createdAt: asString(report.createdAt ?? report.created_at),
    updatedAt: asString(report.updatedAt ?? report.updated_at)
  }
}

export const evaluateSkillExecutionQuality = async (
  runId: string,
  expectedKeywords: string[] = []
): Promise<SkillQualityReport> => {
  const response = asRecord(unwrapData(await api.post<unknown>('/evaluation/quality/evaluate', {
    runId,
    expectedKeywords
  })))
  return normalizeQualityReport(response.report ?? response)
}

export const getSkillQualityOverview = async (
  skillId?: string,
  days = 30
): Promise<SkillQualityOverview> => {
  const response = asRecord(unwrapData(await api.get<unknown>('/evaluation/quality/overview', {
    params: { ...(skillId ? { skillId } : {}), days }
  })))
  const overview = asRecord(response.overview ?? response)
  return {
    skillId: asString(overview.skillId ?? overview.skill_id),
    days: Number(overview.days) || days,
    runCount: Number(overview.runCount ?? overview.run_count) || 0,
    successRate: Number(overview.successRate ?? overview.success_rate) || 0,
    cancelRate: Number(overview.cancelRate ?? overview.cancel_rate) || 0,
    timeoutRate: Number(overview.timeoutRate ?? overview.timeout_rate) || 0,
    averageDurationMs: Number(overview.averageDurationMs ?? overview.average_duration_ms) || 0,
    averageQualityScore: Number(overview.averageQualityScore ?? overview.average_quality_score) || 0,
    evaluatedRuns: Number(overview.evaluatedRuns ?? overview.evaluated_runs) || 0,
    statusDistribution: asRecord(overview.statusDistribution ?? overview.status_distribution),
    triggerDistribution: asRecord(overview.triggerDistribution ?? overview.trigger_distribution),
    recentReports: Array.isArray(overview.recentReports)
      ? overview.recentReports.map(normalizeQualityReport)
      : [],
    generatedAt: asString(overview.generatedAt ?? overview.generated_at)
  }
}
