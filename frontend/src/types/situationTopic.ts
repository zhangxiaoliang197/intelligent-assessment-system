export interface SituationTopicRecommendation {
  id: string
  dimension: '追问专题' | '空间聚焦' | '时间演化' | '对比研判' | '风险预警' | string
  title: string
  description: string
  query: string
  reason: string
  contextTags: string[]
  rank: number
  skillId?: string
  skillName?: string
  skillReason?: string
}

export interface SituationTopicRecommendationResponse {
  items: SituationTopicRecommendation[]
  total: number
  currentQuery: string
  question: string
  reportId: string
  contextTags: string[]
}

export interface SituationTopicRecommendationRequest {
  currentQuery: string
  question?: string
  reportId?: string
  currentSkillId?: string
  limit?: number
  context?: Record<string, unknown>
}
