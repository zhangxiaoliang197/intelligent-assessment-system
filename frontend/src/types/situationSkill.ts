export interface SituationSkillCategory {
  name: string
  count: number
}

export type SituationSkillParameterType = 'text' | 'number' | 'select' | 'multiselect'

export type SituationSkillParameterOperator =
  | 'equals' | 'contains' | 'numeric-threshold' | 'time-window'
  | 'limit' | 'map-radius' | 'analysis-control'

export interface SituationSkillParameterDefinition {
  key: string
  label: string
  type: SituationSkillParameterType
  required?: boolean
  default?: unknown
  placeholder?: string
  options?: string[]
  minimum?: number
  maximum?: number
  description?: string
  binding?: {
    operator: SituationSkillParameterOperator
    field?: string
  }
}

export interface SituationSkill {
  order: number
  id: string
  name: string
  description: string
  category: string
  triggers: string[]
  recommendedQuestions: string[]
  inputHints: string[]
  steps: string[]
  dataSources: string[]
  chartTypes: string[]
  mapLayerTypes: string[]
  focusMetrics: string[]
  analysisGoal: string
  featured?: boolean
  score?: number
  matchedTriggers?: string[]
  recommendationReason?: string
  parameters?: SituationSkillParameterDefinition[]
  source?: 'builtin' | 'custom'
  isBuiltIn?: boolean
  ownerId?: string
  status?: 'draft' | 'published' | 'archived'
  revision?: number
  version?: number
  createdAt?: string
  updatedAt?: string
}

export type SituationSkillSummary = Pick<
  SituationSkill,
  'id' | 'name' | 'category' | 'description' | 'parameters' | 'status' | 'isBuiltIn'
>

export interface SituationSkillCatalog {
  items: SituationSkill[]
  total: number
  catalogTotal: number
  version: string
  categories: SituationSkillCategory[]
}

export interface SituationSkillMarkdownDocument {
  skillId: string
  skillName: string
  source: 'builtin' | 'custom'
  content: string
  contentHash: string
  editable: boolean
  storage: 'catalog' | 'override' | 'custom'
  overridden: boolean
  relativePath: string
  revision: number
  lastModified?: string
}

export interface SituationSkillExecutionPlan {
  skillId: string
  skillName: string
  category: string
  query: string
  parameters: Record<string, unknown>
  instruction: string
  executionPlan: Array<{ sequence: number; name: string }>
  dataSources: string[]
  chartTypes: string[]
  mapLayerTypes: string[]
  focusMetrics: string[]
  analysisGoal: string
}

export type SituationSkillCheckStatus = 'passed' | 'warning' | 'error'

export interface SituationSkillPreflightCheck {
  key: string
  label: string
  status: SituationSkillCheckStatus
  message: string
}

export interface SituationSkillPreflight {
  skillId: string
  ready: boolean
  complete: boolean
  checks: SituationSkillPreflightCheck[]
  errors: string[]
  warnings: string[]
  parameters: Record<string, unknown>
  parameterDefinitions: SituationSkillParameterDefinition[]
  executionPlan: Array<{ sequence: number; name: string }>
  dataSources: Array<{ name: string; status: SituationSkillCheckStatus; message: string }>
}

export interface SituationSkillVersion {
  skillId: string
  version: number
  status: 'draft' | 'published'
  changeNote: string
  createdAt: string
  createdBy: string
}

export interface SituationSkillUsageItem {
  reportId: string
  skillId: string
  query: string
  status: 'running' | 'ready' | 'failed'
  durationMs: number
  startedAt: string
  finishedAt: string
}

export interface SituationSkillUsageResponse {
  items: SituationSkillUsageItem[]
  total: number
  stats: Record<string, { uses: number; successes: number }>
}
