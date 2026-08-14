<template>
  <el-drawer
    :model-value="modelValue"
    size="min(920px, 92vw)"
    class="situation-skill-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="drawer-title-wrap">
        <div>
          <h2>态势 Skill</h2>
          <p>选择专业分析流程，自动组织数据、图表和地图图层</p>
        </div>
        <div class="header-actions">
          <el-button size="small" @click="emit('show-usage')">使用记录</el-button>
          <el-tag type="primary" effect="plain">{{ skills.length }} 项</el-tag>
        </div>
      </div>
    </template>

    <div class="drawer-controls">
      <el-input v-model="search" :prefix-icon="Search" clearable placeholder="搜索名称、场景、指标或触发词" />
      <div class="drawer-control-actions">
        <el-button class="create-skill-button" type="primary" :icon="Plus" @click="openEditor('create')">
          新建 Skill
        </el-button>
        <button class="favorite-filter" :class="{ active: favoritesOnly }" @click="favoritesOnly = !favoritesOnly">
          <el-icon><StarFilled v-if="favoritesOnly" /><Star v-else /></el-icon>
          我的收藏
        </button>
      </div>
    </div>

    <div class="category-list">
      <button :class="{ active: !category }" @click="category = ''">全部 {{ skills.length }}</button>
      <button
        v-for="item in categories"
        :key="item.name"
        :class="{ active: category === item.name }"
        @click="category = item.name"
      >
        {{ item.name }} {{ item.count }}
      </button>
    </div>

    <div v-loading="loading" class="catalog-layout">
      <div class="skill-list">
        <div class="list-summary">
          <span>找到 {{ filteredSkills.length }} 个 Skill</span>
          <span v-if="query" class="query-context">当前问题：{{ query }}</span>
        </div>

        <div
          v-for="skill in filteredSkills"
          :key="skill.id"
          role="button"
          tabindex="0"
          class="skill-card"
          :class="{ selected: previewSkill?.id === skill.id, applied: selectedSkillId === skill.id }"
          @click="previewSkill = skill"
          @keydown.enter.prevent="previewSkill = skill"
        >
          <span class="skill-icon">{{ categoryIcon(skill.category) }}</span>
          <span class="skill-card-content">
            <span class="skill-card-heading">
              <strong>{{ skill.name }}</strong>
              <el-tag v-if="selectedSkillId === skill.id" size="small" type="success">使用中</el-tag>
              <el-tag v-else-if="skill.status === 'draft'" size="small" type="info">草稿</el-tag>
              <el-tag v-else-if="skill.status === 'archived'" size="small" type="danger">已归档</el-tag>
              <el-tag v-else-if="skill.featured" size="small" type="warning" effect="plain">常用</el-tag>
            </span>
            <span class="skill-description">{{ skill.description }}</span>
            <span class="skill-tags">
              <el-tag size="small" effect="plain">{{ skill.category }}</el-tag>
              <el-tag size="small" type="info" effect="plain">{{ skill.chartTypes.length }} 类图表</el-tag>
              <el-tag size="small" type="info" effect="plain">{{ skill.mapLayerTypes.length }} 类图层</el-tag>
              <el-tag v-if="usageStats[skill.id]?.uses" size="small" type="success" effect="plain">
                使用 {{ usageStats[skill.id].uses }} 次
              </el-tag>
            </span>
            <span
              role="button"
              tabindex="0"
              class="mobile-use-action"
              :class="{ disabled: skill.status !== 'published' }"
              @click.stop="skill.status === 'published' && selectSkill(skill)"
              @keydown.enter.stop.prevent="skill.status === 'published' && selectSkill(skill)"
            >
              {{ selectedSkillId === skill.id ? '继续使用' : '使用此 Skill' }}
            </span>
          </span>
          <span
            class="favorite-action"
            :title="isFavorite(skill.id) ? '取消收藏' : '收藏'"
            @click.stop="toggleFavorite(skill.id)"
          >
            <el-icon><StarFilled v-if="isFavorite(skill.id)" /><Star v-else /></el-icon>
          </span>
        </div>

        <el-empty v-if="!loading && !filteredSkills.length" description="没有匹配的 Skill，试试其他关键词">
          <el-button v-if="!skills.length" type="primary" plain @click="emit('reload')">重新加载</el-button>
        </el-empty>
      </div>

      <aside v-if="previewSkill" class="skill-preview">
        <div class="preview-heading">
          <span class="preview-icon">{{ categoryIcon(previewSkill.category) }}</span>
          <div>
            <el-tag size="small" effect="plain">{{ previewSkill.category }}</el-tag>
            <el-tag
              v-if="!previewSkill.isBuiltIn"
              size="small"
              :type="previewSkill.status === 'published' ? 'success' : previewSkill.status === 'archived' ? 'danger' : 'info'"
              class="status-tag"
            >
              {{ statusLabel(previewSkill.status) }} · v{{ previewSkill.version || 1 }}
            </el-tag>
            <h3>{{ previewSkill.name }}</h3>
          </div>
        </div>
        <p class="preview-description">{{ previewSkill.description }}</p>

        <section>
          <h4>分析流程</h4>
          <ol class="step-list">
            <li v-for="step in previewSkill.steps" :key="step">{{ step }}</li>
          </ol>
        </section>

        <section>
          <h4>重点指标</h4>
          <div class="tag-cloud">
            <el-tag v-for="metric in previewSkill.focusMetrics" :key="metric" size="small">{{ metric }}</el-tag>
          </div>
        </section>

        <section>
          <h4>建议补充</h4>
          <div class="tag-cloud">
            <el-tag v-for="hint in previewSkill.inputHints" :key="hint" size="small" type="info" effect="plain">
              {{ hint }}
            </el-tag>
          </div>
        </section>

        <section>
          <h4>推荐问题</h4>
          <button
            v-for="question in previewSkill.recommendedQuestions"
            :key="question"
            class="question-example"
            @click="selectSkill(previewSkill, question)"
          >
            {{ question }}
          </button>
        </section>

        <div class="preview-actions">
          <el-button :icon="Document" @click="openMarkdown(previewSkill)">MD 文档</el-button>
          <el-button v-if="previewSkill.isBuiltIn" @click="openEditor('copy', previewSkill)">复制</el-button>
          <template v-else>
            <el-button v-if="previewSkill.status !== 'archived'" @click="openEditor('edit', previewSkill)">编辑</el-button>
            <el-button @click="openVersions(previewSkill)">版本</el-button>
            <el-button
              v-if="previewSkill.status === 'draft'"
              type="success"
              plain
              @click="publishSkill(previewSkill)"
            >发布</el-button>
            <el-button
              v-if="previewSkill.status !== 'archived'"
              type="danger"
              plain
              @click="archiveSkill(previewSkill)"
            >归档</el-button>
          </template>
          <el-button v-if="selectedSkillId === previewSkill.id" @click="emit('clear')">取消使用</el-button>
          <el-button
            type="primary"
            :disabled="previewSkill.status !== 'published'"
            :title="previewSkill.status !== 'published' ? '请先发布此 Skill' : ''"
            @click="selectSkill(previewSkill)"
          >
            {{ selectedSkillId === previewSkill.id ? '继续使用' : '使用此 Skill' }}
          </el-button>
        </div>
      </aside>
    </div>
  </el-drawer>

  <SituationSkillEditorDialog
    v-model="editorVisible"
    :skill="editorSkill"
    :mode="editorMode"
    :categories="categories.map((item) => item.name)"
    @saved="onEditorSaved"
  />

  <SituationSkillMarkdownDialog
    v-model="markdownVisible"
    :skill="markdownSkill"
    @saved="onMarkdownSaved"
  />

  <el-dialog v-model="versionsVisible" title="Skill 版本记录" width="620px">
    <el-table v-loading="versionsLoading" :data="versions" empty-text="暂无版本记录">
      <el-table-column prop="version" label="版本" width="80" />
      <el-table-column prop="status" label="状态" width="100" />
      <el-table-column prop="changeNote" label="变更说明" min-width="170" show-overflow-tooltip />
      <el-table-column prop="createdAt" label="保存时间" width="180" />
      <el-table-column label="操作" width="90">
        <template #default="scope">
          <el-button link type="primary" @click="rollbackVersion(scope.row.version)">回滚</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Document, Plus, Search, Star, StarFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SituationSkillEditorDialog from './SituationSkillEditorDialog.vue'
import SituationSkillMarkdownDialog from './SituationSkillMarkdownDialog.vue'
import {
  archiveSituationSkill,
  getSituationSkill,
  listSituationSkillVersions,
  publishSituationSkill,
  rollbackSituationSkill,
} from '@/services/situationSkills'
import type { SituationSkill, SituationSkillCategory, SituationSkillVersion } from '@/types/situationSkill'

const props = withDefaults(defineProps<{
  modelValue: boolean
  skills: SituationSkill[]
  categories: SituationSkillCategory[]
  selectedSkillId?: string
  query?: string
  loading?: boolean
  favoriteIds?: string[]
  usageStats?: Record<string, { uses: number; successes: number }>
}>(), {
  selectedSkillId: '',
  query: '',
  loading: false,
  favoriteIds: () => [],
  usageStats: () => ({}),
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'select', skill: SituationSkill, question?: string): void
  (e: 'clear'): void
  (e: 'reload'): void
  (e: 'favorite', skillId: string, favorite: boolean): void
  (e: 'show-usage'): void
}>()

const search = ref('')
const category = ref('')
const favoritesOnly = ref(false)
const previewSkill = ref<SituationSkill | null>(null)
const editorVisible = ref(false)
const editorMode = ref<'create' | 'edit' | 'copy'>('create')
const editorSkill = ref<SituationSkill | null>(null)
const markdownVisible = ref(false)
const markdownSkill = ref<SituationSkill | null>(null)
const versionsVisible = ref(false)
const versionsLoading = ref(false)
const versions = ref<SituationSkillVersion[]>([])
const versionSkill = ref<SituationSkill | null>(null)

const filteredSkills = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  return props.skills
    .filter((skill) => !category.value || skill.category === category.value)
    .filter((skill) => !favoritesOnly.value || props.favoriteIds.includes(skill.id))
    .filter((skill) => {
      if (!keyword) return true
      const fields = [
        skill.name,
        skill.description,
        skill.category,
        ...skill.triggers,
        ...skill.focusMetrics,
        ...skill.recommendedQuestions,
      ]
      return fields.some((field) => field.toLowerCase().includes(keyword))
    })
    .sort((a, b) => {
      const favoriteDiff = Number(isFavorite(b.id)) - Number(isFavorite(a.id))
      return favoriteDiff || a.order - b.order
    })
})

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    previewSkill.value = props.skills.find((skill) => skill.id === props.selectedSkillId)
      || filteredSkills.value[0]
      || null
  },
  { immediate: true },
)

watch(filteredSkills, (items) => {
  if (!items.some((item) => item.id === previewSkill.value?.id)) {
    previewSkill.value = items[0] || null
  }
})

function isFavorite(skillId: string) {
  return props.favoriteIds.includes(skillId)
}

function toggleFavorite(skillId: string) {
  emit('favorite', skillId, !isFavorite(skillId))
}

function statusLabel(status?: SituationSkill['status']) {
  return ({ draft: '草稿', published: '已发布', archived: '已归档' } as const)[status || 'published']
}

function openEditor(mode: 'create' | 'edit' | 'copy', skill: SituationSkill | null = null) {
  editorMode.value = mode
  editorSkill.value = skill
  editorVisible.value = true
}

function onEditorSaved(skill: SituationSkill) {
  previewSkill.value = skill
  emit('reload')
}

function openMarkdown(skill: SituationSkill) {
  markdownSkill.value = skill
  markdownVisible.value = true
}

async function onMarkdownSaved(skillId: string) {
  try {
    const refreshed = await getSituationSkill(skillId)
    markdownSkill.value = refreshed
    previewSkill.value = refreshed
  } catch (error: any) {
    ElMessage.warning(error?.serverMessage || 'SKILL.md 已保存，但技能详情刷新失败')
  }
  emit('reload')
}

async function publishSkill(skill: SituationSkill) {
  try {
    const { value } = await ElMessageBox.prompt('填写本次发布说明（可选）', '发布 Skill', {
      confirmButtonText: '发布',
      cancelButtonText: '取消',
      inputPlaceholder: '例如：补充装备完好率检查',
      inputValue: '',
    })
    previewSkill.value = await publishSituationSkill(skill.id, value || '')
    ElMessage.success('Skill 已发布，可用于态势生成')
    emit('reload')
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.serverMessage || 'Skill 发布失败')
  }
}

async function archiveSkill(skill: SituationSkill) {
  try {
    await ElMessageBox.confirm('归档后将不能继续使用或编辑，版本记录仍会保留。', '归档 Skill', {
      type: 'warning',
      confirmButtonText: '确认归档',
      cancelButtonText: '取消',
    })
    await archiveSituationSkill(skill.id)
    if (props.selectedSkillId === skill.id) emit('clear')
    previewSkill.value = null
    ElMessage.success('Skill 已归档')
    emit('reload')
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.serverMessage || 'Skill 归档失败')
  }
}

async function openVersions(skill: SituationSkill) {
  versionSkill.value = skill
  versionsVisible.value = true
  versionsLoading.value = true
  try {
    versions.value = await listSituationSkillVersions(skill.id)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '版本记录加载失败')
  } finally {
    versionsLoading.value = false
  }
}

async function rollbackVersion(version: number) {
  const skill = versionSkill.value
  if (!skill) return
  try {
    await ElMessageBox.confirm(`回滚到 v${version} 后会进入草稿态，需要重新发布。`, '确认回滚', {
      type: 'warning',
    })
    previewSkill.value = await rollbackSituationSkill(skill.id, version)
    versionsVisible.value = false
    ElMessage.success(`已回滚到 v${version}`)
    emit('reload')
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.serverMessage || '版本回滚失败')
  }
}

function categoryIcon(value: string) {
  return ({
    综合态势: '◎',
    威胁预警: '△',
    作战效能: '⚡',
    任务行动: '◇',
    战备保障: '▣',
    损耗复盘: '↗',
    决策辅助: '⌘',
  } as Record<string, string>)[value] || '✦'
}

function selectSkill(skill: SituationSkill, question?: string) {
  emit('select', skill, question)
  emit('update:modelValue', false)
}
</script>

<style scoped>
.drawer-title-wrap {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.drawer-title-wrap h2 {
  margin: 0;
  color: #1f2937;
  font-size: 20px;
}
.drawer-title-wrap p {
  margin: 5px 0 0;
  color: #909399;
  font-size: 13px;
}
.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.status-tag { margin-left: 6px; }
.drawer-controls {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
}
.drawer-control-actions {
  display: flex;
  align-items: stretch;
  gap: 10px;
}
.create-skill-button,
.favorite-filter {
  min-height: 40px;
}
.favorite-filter,
.category-list button {
  border: 1px solid #dcdfe6;
  background: #fff;
  color: #606266;
  border-radius: 8px;
  cursor: pointer;
}
.favorite-filter {
  min-width: 112px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}
.favorite-filter.active,
.category-list button.active {
  color: #2563eb;
  border-color: #93c5fd;
  background: #eff6ff;
}
.category-list {
  display: flex;
  gap: 8px;
  padding: 14px 0;
  overflow-x: auto;
}
.category-list button {
  flex: 0 0 auto;
  padding: 7px 11px;
  font-size: 12px;
}
.catalog-layout {
  min-height: 520px;
  height: calc(100vh - 190px);
  display: grid;
  grid-template-columns: minmax(360px, 1fr) 330px;
  gap: 16px;
}
.skill-list {
  overflow-y: auto;
  padding-right: 4px;
}
.list-summary {
  min-height: 28px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #909399;
  font-size: 12px;
}
.query-context {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.skill-card {
  width: 100%;
  display: grid;
  grid-template-columns: 42px minmax(0, 1fr) 28px;
  gap: 10px;
  align-items: start;
  padding: 13px;
  margin-bottom: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  color: inherit;
  text-align: left;
  background: #fff;
  cursor: pointer;
  transition: border-color .2s, box-shadow .2s, transform .2s;
}
.skill-card:hover,
.skill-card.selected {
  border-color: #93c5fd;
  box-shadow: 0 5px 16px rgba(37, 99, 235, .08);
  transform: translateY(-1px);
}
.skill-card.applied {
  border-color: #67c23a;
}
.skill-icon,
.preview-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #2563eb;
  background: #eff6ff;
  border-radius: 10px;
  font-weight: 700;
}
.skill-icon {
  width: 40px;
  height: 40px;
  font-size: 20px;
}
.skill-card-content,
.skill-card-heading,
.skill-tags {
  display: flex;
}
.skill-card-content {
  min-width: 0;
  flex-direction: column;
  gap: 7px;
}
.skill-card-heading {
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.skill-card-heading strong {
  color: #303133;
  font-size: 14px;
}
.skill-description {
  color: #606266;
  line-height: 1.55;
  font-size: 12px;
}
.skill-tags,
.tag-cloud {
  flex-wrap: wrap;
  gap: 6px;
}
.favorite-action {
  color: #e6a23c;
  padding: 4px;
}
.mobile-use-action { display: none; }
.skill-preview {
  overflow-y: auto;
  padding: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 12px;
  background: linear-gradient(180deg, #f8fbff 0, #fff 180px);
}
.preview-heading {
  display: flex;
  align-items: center;
  gap: 12px;
}
.preview-icon {
  flex: 0 0 auto;
  width: 52px;
  height: 52px;
  font-size: 24px;
}
.preview-heading h3 {
  margin: 6px 0 0;
  color: #1f2937;
}
.preview-description {
  color: #606266;
  font-size: 13px;
  line-height: 1.65;
}
.skill-preview section {
  margin-top: 18px;
}
.skill-preview h4 {
  margin: 0 0 9px;
  color: #303133;
  font-size: 13px;
}
.step-list {
  margin: 0;
  padding-left: 22px;
  color: #606266;
  font-size: 12px;
  line-height: 1.8;
}
.tag-cloud {
  display: flex;
}
.question-example {
  width: 100%;
  margin-bottom: 7px;
  padding: 8px 10px;
  border: 1px solid #dbeafe;
  border-radius: 7px;
  background: #f8fbff;
  color: #2563eb;
  text-align: left;
  line-height: 1.45;
  cursor: pointer;
}
.question-example:hover {
  background: #eff6ff;
}
.preview-actions {
  position: sticky;
  bottom: -18px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin: 18px -18px -18px;
  padding: 13px 18px;
  border-top: 1px solid #e5e7eb;
  background: rgba(255, 255, 255, .96);
}
@media (max-width: 760px) {
  .drawer-controls {
    grid-template-columns: 1fr;
  }
  .drawer-control-actions {
    display: grid;
    grid-template-columns: 1fr 1fr;
  }
  .catalog-layout {
    grid-template-columns: 1fr;
  }
  .skill-preview {
    display: none;
  }
  .mobile-use-action {
    display: inline-flex;
    align-self: flex-start;
    align-items: center;
    min-height: 30px;
    padding: 5px 12px;
    border-radius: 6px;
    color: #fff;
    background: #2563eb;
    font-size: 12px;
    font-weight: 600;
  }
  .mobile-use-action.disabled {
    color: #909399;
    background: #f2f3f5;
    cursor: not-allowed;
  }
}
</style>
