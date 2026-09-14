<template>
  <section class="topic-explorer" aria-labelledby="topic-explorer-title">
    <div class="topic-header">
      <div class="topic-heading">
        <span class="topic-heading-icon"><el-icon><Compass /></el-icon></span>
        <div>
          <div class="topic-title-row">
            <h3 id="topic-explorer-title">继续探索</h3>
            <el-tag size="small" effect="plain" type="primary">自动推荐专题态势</el-tag>
          </div>
          <p>{{ question ? '已结合你的追问与当前态势，推荐以下专题' : '基于当前态势的区域、时段和分析结果，推荐下一步专题' }}</p>
        </div>
      </div>
      <el-button text :loading="loading" aria-label="刷新专题推荐" @click="$emit('refresh')">
        <el-icon><RefreshRight /></el-icon>
      </el-button>
    </div>

    <div v-if="contextTags.length" class="context-strip">
      <span class="context-label"><el-icon><Link /></el-icon> 当前上下文</span>
      <span v-for="tag in contextTags" :key="tag" class="context-chip">{{ tag }}</span>
    </div>

    <div v-if="loading && !topics.length" class="topic-grid" aria-live="polite">
      <div v-for="index in 4" :key="index" class="topic-card topic-skeleton">
        <el-skeleton :rows="3" animated />
      </div>
    </div>

    <div v-else-if="topics.length" class="topic-grid">
      <article
        v-for="topic in topics"
        :key="topic.id"
        class="topic-card"
        tabindex="0"
        @click="$emit('select', topic)"
        @keydown.enter.prevent="$emit('select', topic)"
      >
        <div class="topic-card-top">
          <span class="dimension-label">{{ topic.dimension }}</span>
          <span v-if="topic.skillName" class="skill-label">
            <el-icon><MagicStick /></el-icon>{{ topic.skillName }}
          </span>
        </div>
        <h4>{{ topic.title }}</h4>
        <p class="topic-description">{{ topic.description }}</p>
        <p class="topic-reason">{{ topic.reason }}</p>
        <div class="topic-actions">
          <button type="button" class="fill-action" @click.stop="$emit('select', topic)">
            填入追问
          </button>
          <el-button type="primary" size="small" @click.stop="$emit('generate', topic)">
            <el-icon><Promotion /></el-icon>一键生成
          </el-button>
        </div>
      </article>
    </div>

    <el-empty v-else description="暂未生成专题推荐，可输入追问后重试" :image-size="54" />
  </section>
</template>

<script setup lang="ts">
import { Compass, Link, MagicStick, Promotion, RefreshRight } from '@element-plus/icons-vue'
import type { SituationTopicRecommendation } from '@/types/situationTopic'

withDefaults(defineProps<{
  topics: SituationTopicRecommendation[]
  loading?: boolean
  question?: string
  contextTags?: string[]
}>(), {
  loading: false,
  question: '',
  contextTags: () => [],
})

defineEmits<{
  select: [topic: SituationTopicRecommendation]
  generate: [topic: SituationTopicRecommendation]
  refresh: []
}>()
</script>

<style scoped>
.topic-explorer {
  padding: 18px;
  border: 1px solid rgba(124, 58, 237, 0.18);
  border-radius: 14px;
  background:
    radial-gradient(circle at 100% 0, rgba(139, 92, 246, 0.10), transparent 34%),
    linear-gradient(145deg, #ffffff, #fbfaff);
}

.topic-header,
.topic-heading,
.topic-title-row,
.context-strip,
.topic-card-top,
.topic-actions,
.skill-label,
.context-label {
  display: flex;
  align-items: center;
}

.topic-header { justify-content: space-between; gap: 14px; }
.topic-heading { align-items: flex-start; gap: 11px; min-width: 0; }
.topic-heading-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  flex: 0 0 auto;
  color: #6d28d9;
  border-radius: 10px;
  background: rgba(139, 92, 246, 0.12);
}
.topic-title-row { gap: 8px; flex-wrap: wrap; }
.topic-title-row h3 { margin: 0; color: #312e81; font-size: 16px; }
.topic-heading p { margin: 4px 0 0; color: #64748b; font-size: 12px; line-height: 1.5; }

.context-strip { gap: 6px; margin-top: 13px; flex-wrap: wrap; }
.context-label { gap: 4px; margin-right: 2px; color: #6b7280; font-size: 11px; }
.context-chip {
  padding: 4px 8px;
  color: #5b21b6;
  font-size: 11px;
  border: 1px solid rgba(139, 92, 246, 0.16);
  border-radius: 999px;
  background: rgba(139, 92, 246, 0.06);
}

.topic-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.topic-card {
  min-width: 0;
  padding: 13px;
  cursor: pointer;
  border: 1px solid #e8e5f2;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.88);
  transition: transform 0.18s ease, border-color 0.18s ease, box-shadow 0.18s ease;
}
.topic-card:hover,
.topic-card:focus-visible {
  outline: none;
  transform: translateY(-2px);
  border-color: rgba(124, 58, 237, 0.38);
  box-shadow: 0 8px 22px rgba(76, 29, 149, 0.09);
}
.topic-card-top { justify-content: space-between; gap: 8px; }
.dimension-label {
  color: #7c3aed;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.03em;
}
.skill-label {
  gap: 3px;
  min-width: 0;
  max-width: 62%;
  color: #64748b;
  font-size: 10px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.topic-card h4 { margin: 8px 0 4px; color: #1f2937; font-size: 14px; line-height: 1.45; }
.topic-description { margin: 0; color: #64748b; font-size: 12px; line-height: 1.55; }
.topic-reason { margin: 8px 0 0; color: #8b5cf6; font-size: 10px; }
.topic-actions { justify-content: space-between; gap: 8px; margin-top: 11px; }
.fill-action {
  padding: 0;
  color: #6b7280;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
  border: 0;
  background: transparent;
}
.fill-action:hover { color: #6d28d9; }
.topic-skeleton { cursor: default; }

@media (max-width: 760px) {
  .topic-grid { grid-template-columns: 1fr; }
}
</style>
