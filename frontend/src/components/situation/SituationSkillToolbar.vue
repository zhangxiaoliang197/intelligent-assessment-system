<template>
  <div class="situation-skill-toolbar">
    <div class="toolbar-primary-row">
      <div class="skill-selector-zone">
        <div class="skill-toolbar-title">
          <span class="title-icon"><el-icon><MagicStick /></el-icon></span>
          <span>Skill</span>
          <span class="skill-total">{{ skillTotal }}</span>
        </div>

        <el-select
          v-model="selectedCategory"
          class="category-select"
          clearable
          placeholder="全部分类"
          :disabled="loading || !usableSkills.length"
        >
          <el-option
            v-for="item in categories"
            :key="item.name"
            :label="`${item.name} (${item.count})`"
            :value="item.name"
          />
        </el-select>

        <el-select
          :model-value="activeSkill?.id || ''"
          class="skill-select"
          filterable
          clearable
          :loading="loading"
          :disabled="loading || !usableSkills.length"
          placeholder="搜索并选择一个 Skill"
          no-match-text="没有匹配的 Skill"
          @change="onSkillChange"
          @clear="emit('clear')"
        >
          <el-option
            v-for="skill in selectableSkills"
            :key="skill.id"
            :label="skill.name"
            :value="skill.id"
          >
            <span class="option-name">{{ skill.name }}</span>
            <span class="option-category">{{ skill.category }}</span>
          </el-option>
        </el-select>

        <el-button :icon="Collection" :loading="loading" @click="emit('open-library')">
          技能库
        </el-button>
      </div>

      <!-- 数据源选择固定在第一行右侧，不再挤压当前 Skill 信息。 -->
      <div v-if="$slots.append" class="append-zone">
        <slot name="append" />
      </div>
    </div>

    <div class="toolbar-secondary-row">
      <div v-if="activeSkill" class="active-skill-zone">
        <div class="active-skill-summary">
          <span class="active-status"><span class="status-dot" />已启用</span>
          <strong :title="activeSkill.name">{{ activeSkill.name }}</strong>
          <el-tag size="small" effect="plain">{{ activeSkill.category }}</el-tag>
          <span class="active-description" :title="activeSkill.description">{{ activeSkill.description }}</span>
        </div>
        <div class="active-skill-actions">
          <el-button
            v-if="selectedSkill?.recommendedQuestions?.length"
            text
            type="primary"
            @click="useRecommendedQuestion"
          >
            填入示例问题
          </el-button>
          <el-button :icon="Document" plain size="small" @click="emit('open-markdown')">
            SKILL.md
          </el-button>
          <el-button :icon="Setting" plain size="small" @click="emit('configure')">
            参数配置
            <span v-if="configuredCount" class="configured-count">{{ configuredCount }}</span>
          </el-button>
          <el-button text :icon="Close" title="取消使用当前 Skill" @click="emit('clear')" />
        </div>
      </div>

      <div v-else class="recommend-zone">
        <span class="recommend-label">智能推荐</span>
        <button
          v-for="skill in recommendations"
          :key="skill.id"
          type="button"
          class="recommend-chip"
          :title="skill.description"
          @click="emit('select', skill)"
        >
          {{ skill.name }}
        </button>
        <span v-if="!recommendations.length" class="empty-recommendation">
          输入问题后会自动推荐，也可以直接从上方选择
        </span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { Close, Collection, Document, MagicStick, Setting } from '@element-plus/icons-vue'
import type {
  SituationSkill,
  SituationSkillCategory,
  SituationSkillSummary,
} from '@/types/situationSkill'

const props = withDefaults(defineProps<{
  skills: SituationSkill[]
  categories: SituationSkillCategory[]
  activeSkill?: SituationSkillSummary | null
  recommendations?: SituationSkill[]
  skillTotal?: number
  loading?: boolean
  parameters?: Record<string, unknown>
}>(), {
  activeSkill: null,
  recommendations: () => [],
  skillTotal: 0,
  loading: false,
  parameters: () => ({}),
})

const emit = defineEmits<{
  (e: 'select', skill: SituationSkill, question?: string): void
  (e: 'clear'): void
  (e: 'open-library'): void
  (e: 'open-markdown'): void
  (e: 'configure'): void
}>()

const selectedCategory = ref('')

const selectedSkill = computed(() =>
  props.skills.find((skill) => skill.id === props.activeSkill?.id) || null
)
const usableSkills = computed(() => props.skills.filter((skill) => skill.status === 'published'))

const configuredCount = computed(() => Object.values(props.parameters).filter(
  (value) => value !== undefined && value !== null && value !== '' && (!Array.isArray(value) || value.length),
).length)

const selectableSkills = computed(() => {
  if (!selectedCategory.value) return usableSkills.value
  const items = usableSkills.value.filter((skill) => skill.category === selectedCategory.value)
  if (selectedSkill.value && !items.some((skill) => skill.id === selectedSkill.value?.id)) {
    return [selectedSkill.value, ...items]
  }
  return items
})

function onSkillChange(skillId: string) {
  if (!skillId) {
    emit('clear')
    return
  }
  const skill = usableSkills.value.find((item) => item.id === skillId)
  if (skill) emit('select', skill)
}

function useRecommendedQuestion() {
  const skill = selectedSkill.value
  const question = skill?.recommendedQuestions?.[0]
  if (skill && question) emit('select', skill, question)
}
</script>

<style scoped>
.situation-skill-toolbar {
  padding: 10px 16px 9px;
  border-bottom: 1px solid #e5e7eb;
  background: linear-gradient(90deg, #f8fbff 0%, #fff 45%);
}
.toolbar-primary-row,
.toolbar-secondary-row {
  display: flex;
  align-items: center;
  min-width: 0;
}
.toolbar-primary-row {
  gap: 20px;
}
.toolbar-secondary-row {
  min-height: 32px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid #edf1f7;
}
.skill-selector-zone,
.skill-toolbar-title,
.active-skill-zone,
.recommend-zone {
  display: flex;
  align-items: center;
}
.skill-selector-zone {
  min-width: 0;
  flex: 1 1 auto;
  gap: 9px;
}
.skill-toolbar-title {
  gap: 7px;
  color: #303133;
  font-size: 14px;
  font-weight: 600;
  white-space: nowrap;
}
.title-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: #2563eb;
  background: #eaf2ff;
}
.skill-total {
  min-width: 21px;
  height: 21px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
  border-radius: 11px;
  color: #fff;
  background: #409eff;
  font-size: 11px;
  font-weight: 500;
}
.category-select {
  width: 148px;
}
.skill-select {
  min-width: 240px;
  max-width: 380px;
  flex: 1 1 320px;
}
.option-name {
  float: left;
}
.option-category {
  float: right;
  margin-left: 20px;
  color: #909399;
  font-size: 12px;
}
.active-skill-zone,
.recommend-zone {
  min-width: 0;
  width: 100%;
  flex: 1 1 100%;
  gap: 8px;
}
.active-skill-zone {
  justify-content: space-between;
}
.active-skill-summary,
.active-skill-actions {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}
.active-skill-summary {
  flex: 1 1 auto;
  overflow: hidden;
}
.active-skill-actions {
  flex: 0 0 auto;
}
/* 数据源选择区（右侧，与技能同行） */
.append-zone {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 20px;
  border-left: 1px solid #e5e7eb;
  margin-left: auto;
  white-space: nowrap;
}
.append-zone :deep(.data-source-select) {
  width: 250px;
}
.append-zone :deep(.label) {
  font-size: 13px;
  color: #475569;
  font-weight: 500;
}
.active-status,
.recommend-label,
.empty-recommendation {
  flex: 0 0 auto;
  color: #909399;
  font-size: 12px;
}
.active-status {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #67c23a;
}
.status-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #67c23a;
  box-shadow: 0 0 0 3px rgba(103, 194, 58, .14);
}
.active-skill-zone strong {
  flex: 0 1 auto;
  overflow: hidden;
  max-width: 190px;
  color: #303133;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.active-description {
  min-width: 80px;
  flex: 1 1 auto;
  overflow: hidden;
  color: #909399;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
}
.configured-count {
  min-width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: 4px;
  padding: 0 5px;
  border-radius: 9px;
  color: #2563eb;
  background: #dbeafe;
  font-size: 11px;
}
.recommend-chip {
  flex: 0 1 auto;
  overflow: hidden;
  max-width: 180px;
  padding: 5px 9px;
  border: 1px solid #dbeafe;
  border-radius: 14px;
  color: #2563eb;
  background: #f8fbff;
  text-overflow: ellipsis;
  white-space: nowrap;
  cursor: pointer;
  font-size: 12px;
}
.recommend-chip:hover {
  border-color: #93c5fd;
  background: #eff6ff;
}
@media (max-width: 1180px) {
  .toolbar-primary-row {
    align-items: stretch;
    flex-direction: column;
    gap: 9px;
  }
  .append-zone {
    width: 100%;
    justify-content: flex-end;
    padding: 8px 0 0;
    border-top: 1px dashed #e5e7eb;
    border-left: 0;
    margin-left: 0;
  }
}
@media (max-width: 720px) {
  .skill-selector-zone {
    width: 100%;
    flex-wrap: wrap;
  }
  .category-select,
  .skill-select {
    width: calc(50% - 5px);
    min-width: 0;
  }
  .skill-toolbar-title {
    width: 100%;
  }
  .active-skill-zone {
    align-items: flex-start;
    flex-direction: column;
  }
  .active-description,
  .recommend-label,
  .recommend-chip:nth-of-type(n + 3) {
    display: none;
  }
  .active-skill-actions {
    width: 100%;
    flex-wrap: wrap;
  }
  .append-zone {
    justify-content: flex-start;
    flex-wrap: wrap;
  }
  .append-zone :deep(.data-source-select) {
    width: min(100%, 260px);
  }
}
</style>
