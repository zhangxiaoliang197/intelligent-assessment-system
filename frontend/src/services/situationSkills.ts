import api from '@/services/api'
import type {
  SituationSkill,
  SituationSkillCatalog,
  SituationSkillExecutionPlan,
  SituationSkillMarkdownDocument,
  SituationSkillPreflight,
  SituationSkillUsageResponse,
  SituationSkillVersion,
} from '@/types/situationSkill'

const unwrap = <T>(response: any): T => (response?.data ?? response) as T

export async function listSituationSkills(params: {
  query?: string
  category?: string
  featured?: boolean
  limit?: number
  includeArchived?: boolean
} = {}): Promise<SituationSkillCatalog> {
  const response = await api.get('/situation/skills', { params })
  return unwrap<SituationSkillCatalog>(response)
}

export async function getSituationSkill(skillId: string): Promise<SituationSkill> {
  const response = await api.get(`/situation/skills/${encodeURIComponent(skillId)}`)
  return unwrap<SituationSkill>(response)
}

export async function getSituationSkillMarkdown(
  skillId: string,
): Promise<SituationSkillMarkdownDocument> {
  const response = await api.get(`/situation/skills/${encodeURIComponent(skillId)}/markdown`)
  return unwrap<SituationSkillMarkdownDocument>(response)
}

export async function updateSituationSkillMarkdown(
  skillId: string,
  content: string,
  expectedHash: string,
): Promise<SituationSkillMarkdownDocument> {
  const response = await api.put(`/situation/skills/${encodeURIComponent(skillId)}/markdown`, {
    content,
    expectedHash,
  })
  return unwrap<SituationSkillMarkdownDocument>(response)
}

export async function recommendSituationSkills(
  query: string,
  limit = 3,
  context: Record<string, unknown> = {},
): Promise<SituationSkill[]> {
  const response = await api.post('/situation/skills/recommend', { query, limit, context })
  const data = unwrap<{ items: SituationSkill[] }>(response)
  return Array.isArray(data?.items) ? data.items : []
}

export async function preflightSituationSkill(
  skillId: string,
  query: string,
  parameters: Record<string, unknown> = {},
  dataSourceId = '',
): Promise<SituationSkillPreflight> {
  const response = await api.post(`/situation/skills/${encodeURIComponent(skillId)}/preflight`, {
    query,
    parameters,
    dataSourceId,
  })
  return unwrap<SituationSkillPreflight>(response)
}

export async function listSituationSkillFavorites(): Promise<string[]> {
  const response = await api.get('/situation/skills/favorites')
  return unwrap<{ skillIds: string[] }>(response).skillIds || []
}

export async function setSituationSkillFavorite(skillId: string, favorite: boolean): Promise<boolean> {
  const response = await api.put(`/situation/skills/${encodeURIComponent(skillId)}/favorite`, { favorite })
  return unwrap<{ favorite: boolean }>(response).favorite
}

export async function listSituationSkillUsage(limit = 20): Promise<SituationSkillUsageResponse> {
  const response = await api.get('/situation/skills/usage', { params: { limit } })
  return unwrap<SituationSkillUsageResponse>(response)
}

export async function createSituationSkill(definition: Record<string, unknown>): Promise<SituationSkill> {
  const response = await api.post('/situation/skills', { definition })
  return unwrap<SituationSkill>(response)
}

export async function updateSituationSkill(
  skillId: string,
  definition: Record<string, unknown>,
  expectedRevision?: number,
): Promise<SituationSkill> {
  const response = await api.put(`/situation/skills/${encodeURIComponent(skillId)}`, {
    definition,
    expectedRevision,
  })
  return unwrap<SituationSkill>(response)
}

export async function publishSituationSkill(skillId: string, changeNote = ''): Promise<SituationSkill> {
  const response = await api.post(`/situation/skills/${encodeURIComponent(skillId)}/publish`, { changeNote })
  return unwrap<SituationSkill>(response)
}

export async function archiveSituationSkill(skillId: string): Promise<SituationSkill> {
  const response = await api.delete(`/situation/skills/${encodeURIComponent(skillId)}`)
  return unwrap<SituationSkill>(response)
}

export async function listSituationSkillVersions(skillId: string): Promise<SituationSkillVersion[]> {
  const response = await api.get(`/situation/skills/${encodeURIComponent(skillId)}/versions`)
  return unwrap<{ items: SituationSkillVersion[] }>(response).items || []
}

export async function rollbackSituationSkill(skillId: string, version: number): Promise<SituationSkill> {
  const response = await api.post(`/situation/skills/${encodeURIComponent(skillId)}/rollback`, { version })
  return unwrap<SituationSkill>(response)
}

export async function applySituationSkill(
  skillId: string,
  query: string,
  parameters: Record<string, unknown> = {},
): Promise<SituationSkillExecutionPlan> {
  const response = await api.post(`/situation/skills/${encodeURIComponent(skillId)}/apply`, {
    query,
    parameters,
  })
  return unwrap<SituationSkillExecutionPlan>(response)
}
