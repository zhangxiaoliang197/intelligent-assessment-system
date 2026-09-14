import api from '@/services/api'
import type {
  SituationTopicRecommendationRequest,
  SituationTopicRecommendationResponse,
} from '@/types/situationTopic'

const unwrap = <T>(response: any): T => (response?.data ?? response) as T

export async function recommendSituationTopics(
  request: SituationTopicRecommendationRequest,
): Promise<SituationTopicRecommendationResponse> {
  const response = await api.post('/situation/topics/recommend', {
    currentQuery: request.currentQuery,
    question: request.question || '',
    reportId: request.reportId || '',
    currentSkillId: request.currentSkillId || '',
    limit: request.limit || 4,
    context: request.context || {},
  })
  return unwrap<SituationTopicRecommendationResponse>(response)
}
