export type EvaluationSkillSource = 'builtin' | 'custom'
export type EvaluationSkillVisibility = 'private' | 'team' | 'public'
export type EvaluationSkillStatus = 'draft' | 'published' | 'disabled' | 'archived'
export type SkillExecutionStatus =
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'error'
  | 'cancelled'
  | 'timed_out'
  | 'partial'
  | 'cancellation_requested'

export interface EvaluationSkillStep {
  id: string
  name: string
  description: string
  datasetKeywords: string[]
  allowReuse?: boolean
  datasetId?: string
  datasetName?: string
  dependsOn: string[]
  runIf: 'all_success' | 'any_success' | 'always'
  retryCount: number
  timeoutSeconds: number
  onFailure: 'continue' | 'stop' | 'skip_dependents'
}

export interface SkillOrchestration {
  mode: 'sequential' | 'dependency'
  maxConcurrency: number
  timeoutSeconds: number
  failurePolicy: 'continue' | 'stop'
}

export interface SkillDatasetPlanItem {
  sequence: number
  stepId: string
  stepName: string
  datasetId: string
  datasetName: string
  tableName: string
  matched: boolean
  message?: string
}

export interface EvaluationSkillAvailability {
  matchedSteps: number
  totalSteps: number
  available: boolean
  complete: boolean
  completeness?: number
  datasetPlan: SkillDatasetPlanItem[]
  missingSteps?: string[]
}

export interface EvaluationSkillPermissions {
  view: boolean
  edit: boolean
  delete: boolean
  publish: boolean
  share: boolean
  execute: boolean
  manageSchedule: boolean
}

export interface EvaluationSkill {
  id: string
  name: string
  description: string
  category: string
  triggers: string[]
  recommendedQuestions: string[]
  steps: EvaluationSkillStep[]
  outputInstruction: string
  orchestration: SkillOrchestration
  stepCount: number
  availability?: EvaluationSkillAvailability
  score?: number
  matchedTriggers?: string[]
  recommendationReason?: string
  source: EvaluationSkillSource
  isBuiltIn: boolean
  isTemplate: boolean
  executable: boolean
  editable: boolean
  deletable: boolean
  revision: number
  version: number
  publishedVersion?: number
  status: EvaluationSkillStatus
  visibility: EvaluationSkillVisibility
  ownerId?: string
  ownerName?: string
  teamId?: string
  teamName?: string
  tags: string[]
  favorited: boolean
  favoriteCount: number
  permissions: EvaluationSkillPermissions
  publishedAt?: string
  createdAt?: string
  updatedAt?: string
}

export interface EvaluationSkillCatalog {
  version: string
  total: number
  builtInTotal: number
  customTotal: number
  customStoreStatus?: 'ready' | 'warning'
  customStoreMessage?: string
  tags?: string[]
  skills: EvaluationSkill[]
}

export interface ListEvaluationSkillsParams {
  dataSourceId?: string
  status?: EvaluationSkillStatus
  visibility?: EvaluationSkillVisibility
  favorite?: boolean
  tag?: string
}

export interface RecommendEvaluationSkillsParams {
  query: string
  limit?: number
  dataSourceId?: string
}

export interface EvaluationSkillStepInput {
  id?: string
  name: string
  description: string
  datasetKeywords: string[]
  allowReuse?: boolean
  datasetId?: string
  datasetName?: string
  dependsOn?: string[]
  runIf?: 'all_success' | 'any_success' | 'always'
  retryCount?: number
  timeoutSeconds?: number
  onFailure?: 'continue' | 'stop' | 'skip_dependents'
}

export interface EvaluationSkillUpsertPayload {
  name: string
  description: string
  category: string
  triggers: string[]
  recommendedQuestions: string[]
  steps: EvaluationSkillStepInput[]
  outputInstruction: string
  orchestration?: SkillOrchestration
  visibility?: EvaluationSkillVisibility
  teamId?: string
  tags?: string[]
}

export interface EvaluationDatasetOption {
  id: string
  name: string
  tableName: string
  description: string
}

export interface SkillPreflightCheck {
  code: string
  name: string
  status: 'passed' | 'warning' | 'failed'
  message: string
  stepId?: string
  datasetId?: string
}

export interface SkillPreflightResult {
  skillId: string
  dataSourceId: string
  runnable: boolean
  checkedAt?: string
  availability?: EvaluationSkillAvailability
  checks: SkillPreflightCheck[]
}

export interface SkillTrialPayload {
  dataSourceId: string
  query: string
  stepId: string
  variables?: Record<string, unknown>
}

export interface SkillExecutionStep {
  id: string
  stepId: string
  stepName: string
  sequence: number
  status: SkillExecutionStatus
  progress?: number
  datasetId?: string
  datasetName?: string
  summary?: string
  error?: string
  startedAt?: string
  finishedAt?: string
  durationMs?: number
}

export interface SkillExecution {
  id: string
  runId: string
  skillId: string
  skillName?: string
  skillVersion?: number
  type?: 'evaluation' | 'trial' | 'scheduled' | 'batch'
  status: SkillExecutionStatus
  query?: string
  dataSourceId?: string
  progress: number
  summary?: string
  result?: unknown
  error?: string
  steps: SkillExecutionStep[]
  createdBy?: string
  createdByName?: string
  createdAt?: string
  startedAt?: string
  finishedAt?: string
  durationMs?: number
}

export interface ListSkillExecutionsParams {
  skillId?: string
  status?: SkillExecutionStatus
  page?: number
  pageSize?: number
}

export interface SkillExecutionCatalog {
  total: number
  items: SkillExecution[]
}

export interface SkillVersion {
  id?: string
  skillId: string
  version: number
  revision?: number
  status?: EvaluationSkillStatus
  changeNote?: string
  createdBy?: string
  createdByName?: string
  createdAt?: string
  publishedAt?: string
  snapshot?: Partial<EvaluationSkill>
}

export interface PublishSkillPayload {
  changeNote?: string
  expectedRevision?: number
}

export interface RollbackSkillPayload {
  version: number
  expectedRevision?: number
}

export interface SkillShare {
  id: string
  skillId: string
  token?: string
  url: string
  visibility?: EvaluationSkillVisibility
  expiresAt?: string
  createdAt?: string
}

export interface ShareSkillPayload {
  visibility?: EvaluationSkillVisibility
  expiresInDays?: number
}

export interface SkillSchedule {
  id: string
  skillId: string
  name: string
  cron: string
  timezone: string
  enabled: boolean
  query: string
  dataSourceId: string
  nextRunAt?: string
  lastRunAt?: string
  createdAt?: string
  updatedAt?: string
}

export interface SkillSchedulePayload {
  name: string
  cron: string
  timezone?: string
  enabled?: boolean
  query: string
  dataSourceId: string
}

export interface SkillBatchItem {
  id?: string
  query: string
  status?: SkillExecutionStatus
  runId?: string
  result?: unknown
  error?: string
}

export interface SkillBatch {
  id: string
  skillId: string
  name: string
  dataSourceId: string
  status: SkillExecutionStatus
  total: number
  completed: number
  failed: number
  items: SkillBatchItem[]
  createdAt?: string
  finishedAt?: string
}

export interface CreateSkillBatchPayload {
  skillId: string
  name: string
  dataSourceId: string
  queries: string[]
}

export interface SkillExecutionComparisonItem {
  runId: string
  skillName?: string
  skillVersion?: number
  status?: SkillExecutionStatus
  durationMs?: number
  summary?: string
  metrics?: Record<string, number | string | null>
}

export interface SkillExecutionComparison {
  runIds: string[]
  items: SkillExecutionComparisonItem[]
  metricNames: string[]
  generatedAt?: string
}

export interface ImportSkillsResult {
  imported: number
  skipped: number
  skills: EvaluationSkill[]
  warnings: string[]
}

export interface SkillAiDraftRequest {
  requirement: string
  dataSourceId?: string
  maxSteps?: number
}

export interface SkillAiDraftResult {
  draft: EvaluationSkillUpsertPayload
  dataContext: {
    datasetCount: number
    dataSourceComplete: boolean
  }
}

export interface SkillQualityDimension {
  score: number
  maxScore: number
}

export interface SkillQualityReport {
  reportId: string
  runId: string
  skillId: string
  score: number
  grade: 'A' | 'B' | 'C' | 'D'
  dimensions: Record<string, SkillQualityDimension>
  issues: string[]
  suggestions: string[]
  expectedKeywordCoverage?: number | null
  createdAt?: string
  updatedAt?: string
}

export interface SkillQualityOverview {
  skillId: string
  days: number
  runCount: number
  successRate: number
  cancelRate: number
  timeoutRate: number
  averageDurationMs: number
  averageQualityScore: number
  evaluatedRuns: number
  statusDistribution: Record<string, number>
  triggerDistribution: Record<string, number>
  recentReports: SkillQualityReport[]
  generatedAt?: string
}
