<template>
  <div class="skills-page custom-scroll">
      <div class="skills-shell">
        <section class="skills-hero">
          <div class="hero-copy">
            <div class="hero-eyebrow">
              <el-icon><MagicStick /></el-icon>
              <span>EVALUATION SKILLS</span>
            </div>
            <h2>让评估按正确的数据顺序执行</h2>
            <p>
              可直接调用系统内置 Skill，也可以按自己的需求现场编排新 Skill。选择后，
              系统会严格依次核验数据、汇总证据并生成可追溯的评估结论。
            </p>
            <div class="hero-stats" aria-label="技能库统计">
              <div class="stat-item">
                <strong>{{ builtInCount }}</strong>
                <span>内置技能</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <strong>{{ customCount }}</strong>
                <span>自定义技能</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <strong>{{ categories.length }}</strong>
                <span>任务分类</span>
              </div>
              <div class="stat-divider"></div>
              <div class="stat-item">
                <strong>{{ totalSteps }}</strong>
                <span>查询步骤</span>
              </div>
            </div>
          </div>

          <div class="hero-flow" aria-hidden="true">
            <div class="flow-orbit flow-orbit-back"></div>
            <div class="flow-orbit flow-orbit-front"></div>
            <div class="flow-node flow-node-skill">
              <el-icon><MagicStick /></el-icon>
              <span>Skill</span>
            </div>
            <div class="flow-node flow-node-data">
              <el-icon><Coin /></el-icon>
              <span>数据集</span>
            </div>
            <div class="flow-node flow-node-result">
              <el-icon><DataAnalysis /></el-icon>
              <span>评估结论</span>
            </div>
          </div>
        </section>

        <section class="skills-content">
          <div class="toolbar">
            <div class="toolbar-topline">
              <div class="toolbar-copy">
                <h3>技能目录</h3>
                <span v-if="!loading">找到 {{ filteredSkills.length }} 个技能</span>
              </div>
              <div class="toolbar-actions">
                <el-button :icon="MagicStick" @click="openAiCreator">
                  智能创建
                </el-button>
                <el-button type="primary" :icon="Plus" @click="openCreateEditor">
                  新建 Skill
                </el-button>
                <el-dropdown @command="handleLibraryCommand">
                  <el-button :icon="MoreFilled">更多能力</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item command="templates" :icon="Collection">从模板创建</el-dropdown-item>
                      <el-dropdown-item command="import" :icon="Upload">导入 Skill</el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </div>
            <div class="toolbar-controls">
              <el-radio-group v-model="selectedSource" size="small" class="source-filter">
                <el-radio-button label="all">全部</el-radio-button>
                <el-radio-button label="builtin">系统内置</el-radio-button>
                <el-radio-button label="custom">自定义</el-radio-button>
              </el-radio-group>
              <el-button
                :type="favoritesOnly ? 'warning' : 'default'"
                :plain="!favoritesOnly"
                :icon="Star"
                @click="favoritesOnly = !favoritesOnly"
              >
                收藏
              </el-button>
              <el-input
                v-model="searchKeyword"
                class="skill-search"
                clearable
                placeholder="搜索技能、场景或数据集关键词"
                :prefix-icon="Search"
              />
              <el-select v-model="selectedCategory" class="category-select" aria-label="技能分类">
                <el-option label="全部分类" value="全部" />
                <el-option
                  v-for="category in categories"
                  :key="category"
                  :label="category"
                  :value="category"
                />
              </el-select>
              <el-select
                v-if="availableTags.length"
                v-model="selectedTag"
                clearable
                class="tag-select"
                placeholder="全部标签"
                aria-label="技能标签"
              >
                <el-option v-for="tag in availableTags" :key="tag" :label="tag" :value="tag" />
              </el-select>
              <el-button
                v-if="hasActiveFilter"
                class="reset-button"
                :icon="RefreshLeft"
                @click="resetFilters"
              >
                重置
              </el-button>
            </div>
            <input
              ref="importFileInput"
              class="hidden-file-input"
              type="file"
              accept="application/json,.json"
              @change="handleImportFile"
            />
          </div>

          <el-alert
            v-if="customStoreMessage && !loading"
            class="custom-store-warning"
            type="warning"
            show-icon
            :closable="false"
            title="自定义 Skill 库暂时不可用，系统内置的 15 个 Skill 仍可正常使用"
            :description="customStoreMessage"
          />

          <div v-if="loadError" class="load-error">
            <el-icon><WarningFilled /></el-icon>
            <div>
              <strong>技能目录暂时无法加载</strong>
              <p>{{ loadError }}</p>
            </div>
            <el-button type="primary" plain :icon="Refresh" @click="loadSkills">重新加载</el-button>
          </div>

          <div v-else-if="loading" class="skills-grid" aria-label="技能加载中">
            <div v-for="index in 6" :key="index" class="skill-card skeleton-card">
              <el-skeleton animated>
                <template #template>
                  <div class="skeleton-heading">
                    <el-skeleton-item variant="circle" style="width: 44px; height: 44px" />
                    <div class="skeleton-heading-copy">
                      <el-skeleton-item variant="text" style="width: 42%" />
                      <el-skeleton-item variant="h3" style="width: 70%" />
                    </div>
                  </div>
                  <el-skeleton-item variant="text" style="width: 100%; margin-top: 20px" />
                  <el-skeleton-item variant="text" style="width: 78%; margin-top: 8px" />
                  <el-skeleton-item variant="rect" style="height: 58px; margin-top: 22px" />
                </template>
              </el-skeleton>
            </div>
          </div>

          <div v-else-if="filteredSkills.length === 0" class="empty-filter">
            <div class="empty-icon"><el-icon><Search /></el-icon></div>
            <h3>没有匹配的技能</h3>
            <p>换一个关键词或清除分类筛选后再试。</p>
            <el-button type="primary" plain @click="resetFilters">查看全部技能</el-button>
          </div>

          <div v-else class="skills-grid">
            <article
              v-for="skill in filteredSkills"
              :key="skill.id"
              class="skill-card"
              :style="skillCardStyle(skill.category)"
            >
              <div class="card-main">
                <div class="card-heading">
                  <div class="skill-icon"><MagicStick /></div>
                  <div class="skill-heading-copy">
                    <div class="skill-meta">
                      <el-tag class="category-tag" size="small" effect="plain">{{ skill.category }}</el-tag>
                      <el-tag
                        class="source-tag"
                        size="small"
                        :type="skill.source === 'custom' ? 'warning' : 'info'"
                        effect="light"
                      >
                        {{ skill.source === 'custom' ? '自定义' : '系统内置' }}
                      </el-tag>
                      <el-tag
                        class="status-tag"
                        :type="skill.status === 'published' ? 'success' : 'warning'"
                        size="small"
                        effect="plain"
                      >
                        {{ skill.status === 'published' ? '已发布' : skill.status === 'archived' ? '已归档' : '草稿' }}
                      </el-tag>
                    </div>
                    <h3>{{ skill.name }}</h3>
                  </div>
                  <div class="card-heading-actions">
                    <span class="step-count" title="数据执行步骤数">
                      <el-icon><Coin /></el-icon>
                      <strong>{{ skill.stepCount }}</strong> 步
                    </span>
                    <el-button
                      circle
                      text
                      :type="skill.favorited ? 'warning' : 'default'"
                      :title="skill.favorited ? '取消收藏' : '收藏'"
                      :loading="favoritingSkillId === skill.id"
                      @click="toggleFavorite(skill)"
                    >
                      <el-icon><StarFilled v-if="skill.favorited" /><Star v-else /></el-icon>
                    </el-button>
                  </div>
                </div>

                <p class="skill-description">{{ skill.description }}</p>

                <div class="governance-line">
                  <span>{{ visibilityLabel(skill.visibility) }}</span>
                  <span v-if="skill.ownerName || skill.ownerId">
                    归属 {{ skill.ownerName || skill.ownerId }}
                  </span>
                  <span>v{{ skill.version }}</span>
                </div>

                <div v-if="skill.tags.length" class="skill-tags">
                  <el-tag v-for="tag in skill.tags.slice(0, 5)" :key="tag" size="small" effect="plain">
                    # {{ tag }}
                  </el-tag>
                </div>

                <div class="trigger-list">
                  <span class="trigger-label">适用场景</span>
                  <el-tag
                    v-for="trigger in skill.triggers.slice(0, 4)"
                    :key="trigger"
                    size="small"
                    type="info"
                    effect="plain"
                  >
                    {{ trigger }}
                  </el-tag>
                </div>

                <div v-if="skill.recommendedQuestions[0]" class="question-preview">
                  <el-icon><ChatLineRound /></el-icon>
                  <div>
                    <span>推荐提问</span>
                    <p>{{ skill.recommendedQuestions[0] }}</p>
                  </div>
                </div>

                <div v-if="skill.availability" class="availability-line">
                  <el-icon><Coin /></el-icon>
                  <span>
                    当前数据源匹配 {{ skill.availability.matchedSteps }}/{{ skill.availability.totalSteps }} 步
                  </span>
                  <el-tag
                    size="small"
                    :type="skill.availability.complete ? 'success' : skill.availability.available ? 'warning' : 'danger'"
                    effect="plain"
                  >
                    {{ skill.availability.complete ? '完整可用' : skill.availability.available ? '部分匹配' : '未匹配' }}
                  </el-tag>
                </div>
              </div>

              <el-collapse-transition>
                <div v-show="isExpanded(skill.id)" class="skill-details">
                  <div class="detail-title">
                    <span>有序数据集查询流程</span>
                    <small>严格按以下顺序执行</small>
                  </div>
                  <div class="step-list">
                    <div v-for="(step, index) in skill.steps" :key="step.id" class="step-item">
                      <div class="step-track">
                        <span class="step-number">{{ index + 1 }}</span>
                        <span v-if="index < skill.steps.length - 1" class="step-line"></span>
                      </div>
                      <div class="step-content">
                        <h4>{{ step.name }}</h4>
                        <p>{{ step.description }}</p>
                        <div v-if="step.datasetKeywords.length" class="dataset-keywords">
                          <span>匹配数据集</span>
                          <code
                            v-for="keyword in step.datasetKeywords.slice(0, 5)"
                            :key="keyword"
                          >
                            {{ keyword }}
                          </code>
                        </div>
                      </div>
                    </div>
                  </div>
                  <div class="output-rule">
                    <el-icon><DocumentChecked /></el-icon>
                    <div>
                      <strong>输出要求</strong>
                      <p>{{ skill.outputInstruction }}</p>
                    </div>
                  </div>
                </div>
              </el-collapse-transition>

              <div class="card-footer">
                <el-button text class="detail-button" @click="toggleSkill(skill.id)">
                  <el-icon>
                    <ArrowUp v-if="isExpanded(skill.id)" />
                    <ArrowDown v-else />
                  </el-icon>
                  {{ isExpanded(skill.id) ? '收起执行步骤' : '查看执行步骤' }}
                </el-button>
                <div class="card-actions">
                  <el-button v-if="skill.editable" text :icon="Edit" @click="openEditEditor(skill)">编辑</el-button>
                  <el-button
                    v-if="skill.deletable"
                    text
                    type="danger"
                    :icon="Delete"
                    :loading="deletingSkillId === skill.id"
                    @click="removeCustomSkill(skill)"
                  >
                    删除
                  </el-button>
                  <el-button text :icon="Operation" @click="openOperations(skill)">治理与运行</el-button>
                  <el-dropdown trigger="click" @command="command => handleSkillCommand(skill, command)">
                    <el-button text :icon="MoreFilled">更多</el-button>
                    <template #dropdown>
                      <el-dropdown-menu>
                        <el-dropdown-item command="share" :icon="Share" :disabled="!skill.permissions.share">分享</el-dropdown-item>
                        <el-dropdown-item command="export" :icon="Download">导出</el-dropdown-item>
                        <el-dropdown-item command="clone" :icon="CopyDocument">复制为自定义</el-dropdown-item>
                        <el-dropdown-item
                          v-if="skill.source === 'custom'"
                          command="template"
                          :icon="Collection"
                        >
                          保存为模板
                        </el-dropdown-item>
                      </el-dropdown-menu>
                    </template>
                  </el-dropdown>
                  <el-button
                    type="primary"
                    class="use-button"
                    :disabled="!skill.executable"
                    @click="useSkill(skill)"
                  >
                    {{ skill.executable ? '选择此 Skill' : '当前不可执行' }}
                    <el-icon class="el-icon--right"><Right /></el-icon>
                  </el-button>
                </div>
              </div>
            </article>
          </div>
        </section>
      </div>
      <SkillEditorDialog
        v-model="editorVisible"
        :skill="editingSkill"
        :data-source-id="dataSourceId"
        @saved="handleEditorSaved"
        @refresh="loadSkills"
      />
      <SkillOperationsDrawer
        v-model="operationsVisible"
        :skill="operationsSkill"
        :data-source-id="dataSourceId"
        :initial-tab="operationsInitialTab"
        @changed="handleOperationsChanged"
      />
      <el-dialog
        v-model="aiCreatorVisible"
        title="智能创建 Skill"
        width="min(780px, 94vw)"
        append-to-body
        destroy-on-close
      >
        <div class="ai-creator">
          <div class="ai-creator-intro">
            <el-icon><MagicStick /></el-icon>
            <div>
              <strong>描述业务目标，系统自动拆解数据步骤和运行编排</strong>
              <span>生成结果只会保存为私有草稿，确认后才能发布。</span>
            </div>
          </div>
          <el-form label-position="top">
            <el-form-item label="想解决什么问题">
              <el-input
                v-model="aiRequirement"
                type="textarea"
                :rows="4"
                maxlength="4000"
                show-word-limit
                placeholder="例如：创建一个评估任务完成质量的 Skill，先核验计划执行，再分析资源消耗，最后识别异常并给出改进建议。"
              />
            </el-form-item>
            <div class="ai-creator-options">
              <el-form-item label="最多步骤数">
                <el-input-number v-model="aiMaxSteps" :min="1" :max="12" controls-position="right" />
              </el-form-item>
              <div class="ai-data-context">
                <span>数据源上下文</span>
                <strong>{{ dataSourceId ? '使用当前数据源' : '未选择数据源' }}</strong>
                <small v-if="smartDraft">
                  已读取 {{ smartDraft.dataContext.datasetCount }} 个数据集
                </small>
              </div>
            </div>
          </el-form>

          <div v-if="smartDraft" class="ai-draft-preview">
            <div class="ai-draft-heading">
              <div>
                <el-tag size="small" effect="plain">{{ smartDraft.draft.category }}</el-tag>
                <h4>{{ smartDraft.draft.name }}</h4>
                <p>{{ smartDraft.draft.description }}</p>
              </div>
              <el-tag :type="smartDraft.dataContext.dataSourceComplete ? 'success' : 'warning'" effect="light">
                {{ smartDraft.dataContext.dataSourceComplete ? '已结合数据源' : '通用草稿' }}
              </el-tag>
            </div>
            <div class="ai-draft-steps">
              <div v-for="(step, index) in smartDraft.draft.steps" :key="step.id || index">
                <span>{{ index + 1 }}</span>
                <div>
                  <strong>{{ step.name }}</strong>
                  <small>{{ step.description }}</small>
                </div>
                <el-tag v-if="step.dependsOn?.length" size="small" effect="plain">
                  依赖 {{ step.dependsOn.length }} 步
                </el-tag>
              </div>
            </div>
          </div>
        </div>
        <template #footer>
          <el-button @click="aiCreatorVisible = false">取消</el-button>
          <el-button
            :loading="aiGenerating"
            :disabled="aiRequirement.trim().length < 5"
            @click="generateAiDraft"
          >
            {{ smartDraft ? '重新生成' : '生成草稿' }}
          </el-button>
          <el-button
            v-if="smartDraft"
            type="primary"
            :loading="aiSaving"
            @click="saveAiDraft"
          >
            创建并继续编辑
          </el-button>
        </template>
      </el-dialog>
      <el-dialog
        v-model="templatesVisible"
        title="从模板创建 Skill"
        width="min(760px, 94vw)"
        append-to-body
      >
        <div v-loading="templatesLoading" class="template-list">
          <el-empty v-if="!templatesLoading && !templates.length" description="暂无可用模板" />
          <article v-for="template in templates" :key="template.id" class="template-item">
            <div>
              <el-tag size="small" effect="plain">{{ template.category }}</el-tag>
              <h4>{{ template.name }}</h4>
              <p>{{ template.description }}</p>
              <div class="skill-tags">
                <el-tag v-for="tag in template.tags" :key="tag" size="small" effect="plain"># {{ tag }}</el-tag>
              </div>
            </div>
            <el-button
              type="primary"
              plain
              :loading="instantiatingTemplateId === template.id"
              @click="instantiateTemplate(template)"
            >
              使用模板
            </el-button>
          </article>
        </div>
      </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import {
  ArrowDown,
  ArrowUp,
  ChatLineRound,
  Collection,
  Coin,
  CopyDocument,
  DataAnalysis,
  Delete,
  DocumentChecked,
  Download,
  Edit,
  MagicStick,
  MoreFilled,
  Operation,
  Plus,
  Refresh,
  RefreshLeft,
  Right,
  Search,
  Share,
  Star,
  StarFilled,
  Upload,
  WarningFilled
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import SkillEditorDialog from '@/components/evaluation/SkillEditorDialog.vue'
import SkillOperationsDrawer from '@/components/evaluation/SkillOperationsDrawer.vue'
import {
  cloneEvaluationSkill,
  createEvaluationSkill,
  deleteEvaluationSkill,
  exportEvaluationSkill,
  importEvaluationSkills,
  generateEvaluationSkillDraft,
  instantiateEvaluationSkillTemplate,
  listEvaluationSkills,
  listEvaluationSkillTemplates,
  setEvaluationSkillFavorite,
  shareEvaluationSkill
} from '@/services/evaluationSkills'
import type {
  EvaluationSkill,
  EvaluationSkillVisibility,
  SkillAiDraftResult
} from '@/types/evaluationSkill'

const props = withDefaults(defineProps<{
  dataSourceId?: string
}>(), {
  dataSourceId: ''
})

const emit = defineEmits<{
  select: [skill: EvaluationSkill]
  loaded: [skills: EvaluationSkill[]]
  deleted: [skillId: string]
}>()
const skills = ref<EvaluationSkill[]>([])
const loading = ref(true)
const loadError = ref('')
const customStoreMessage = ref('')
const searchKeyword = ref('')
const selectedCategory = ref('全部')
const selectedTag = ref('')
const selectedSource = ref<'all' | 'builtin' | 'custom'>('all')
const favoritesOnly = ref(false)
const expandedSkillIds = ref<string[]>([])
const editorVisible = ref(false)
const editingSkill = ref<EvaluationSkill | null>(null)
const aiCreatorVisible = ref(false)
const aiRequirement = ref('')
const aiMaxSteps = ref(6)
const aiGenerating = ref(false)
const aiSaving = ref(false)
const smartDraft = ref<SkillAiDraftResult | null>(null)
const deletingSkillId = ref('')
const favoritingSkillId = ref('')
const operationsVisible = ref(false)
const operationsSkill = ref<EvaluationSkill | null>(null)
const operationsInitialTab = ref<'runtime' | 'quality' | 'versions' | 'schedules' | 'batches' | 'compare'>('runtime')
const templatesVisible = ref(false)
const templatesLoading = ref(false)
const templates = ref<EvaluationSkill[]>([])
const instantiatingTemplateId = ref('')
const importFileInput = ref<HTMLInputElement | null>(null)
let loadRequestSequence = 0

const categoryColors: Record<string, string> = {
  '综合评估': '#3b82f6',
  '空中作战': '#06b6d4',
  '火力打击': '#ef4444',
  '损伤评估': '#f59e0b',
  '保障评估': '#10b981',
  '任务评估': '#8b5cf6',
  '威胁研判': '#ec4899'
}

const categories = computed(() =>
  Array.from(new Set(skills.value.filter(skill => !skill.isTemplate).map(skill => skill.category))).filter(Boolean)
)

const availableTags = computed(() =>
  Array.from(new Set(skills.value.flatMap(skill => skill.tags))).filter(Boolean).sort()
)

const builtInCount = computed(() => skills.value.filter(skill => skill.source === 'builtin' && !skill.isTemplate).length)
const customCount = computed(() => skills.value.filter(skill => skill.source === 'custom' && !skill.isTemplate).length)

const totalSteps = computed(() =>
  skills.value.filter(skill => !skill.isTemplate).reduce((total, skill) => total + skill.stepCount, 0)
)

const hasActiveFilter = computed(() =>
  Boolean(searchKeyword.value.trim())
  || selectedCategory.value !== '全部'
  || selectedSource.value !== 'all'
  || Boolean(selectedTag.value)
  || favoritesOnly.value
)

const filteredSkills = computed(() => {
  const keyword = searchKeyword.value.trim().toLocaleLowerCase()
  return skills.value.filter(skill => {
    if (skill.isTemplate) return false
    if (selectedSource.value !== 'all' && skill.source !== selectedSource.value) {
      return false
    }
    if (selectedCategory.value !== '全部' && skill.category !== selectedCategory.value) {
      return false
    }
    if (selectedTag.value && !skill.tags.includes(selectedTag.value)) return false
    if (favoritesOnly.value && !skill.favorited) return false
    if (!keyword) return true

    const searchableText = [
      skill.name,
      skill.description,
      skill.category,
      skill.ownerName,
      skill.ownerId,
      ...skill.tags,
      ...skill.triggers,
      ...skill.recommendedQuestions,
      ...skill.steps.flatMap(step => [
        step.name,
        step.description,
        ...step.datasetKeywords
      ])
    ].join(' ').toLocaleLowerCase()
    return searchableText.includes(keyword)
  })
})

const skillCardStyle = (category: string) => ({
  '--skill-accent': categoryColors[category] || '#64748b'
})

const isExpanded = (skillId: string) => expandedSkillIds.value.includes(skillId)

const toggleSkill = (skillId: string) => {
  expandedSkillIds.value = isExpanded(skillId)
    ? expandedSkillIds.value.filter(id => id !== skillId)
    : [...expandedSkillIds.value, skillId]
}

const resetFilters = () => {
  searchKeyword.value = ''
  selectedCategory.value = '全部'
  selectedTag.value = ''
  selectedSource.value = 'all'
  favoritesOnly.value = false
}

const loadSkills = async () => {
  const requestSequence = ++loadRequestSequence
  loading.value = true
  loadError.value = ''
  customStoreMessage.value = ''
  try {
    const catalog = await listEvaluationSkills({ dataSourceId: props.dataSourceId })
    if (requestSequence !== loadRequestSequence) return
    if (catalog.skills.length === 0) {
      throw new Error('接口未返回可用技能')
    }
    skills.value = catalog.skills
    if (operationsSkill.value) {
      operationsSkill.value = catalog.skills.find(skill => skill.id === operationsSkill.value?.id)
        || operationsSkill.value
    }
    customStoreMessage.value = catalog.customStoreMessage || ''
    emit('loaded', catalog.skills)
  } catch (error: any) {
    if (requestSequence !== loadRequestSequence) return
    loadError.value = error?.serverMessage || error?.message || '请检查评估服务是否已经启动'
  } finally {
    if (requestSequence === loadRequestSequence) loading.value = false
  }
}

const useSkill = (skill: EvaluationSkill) => {
  if (!skill.executable) {
    ElMessage.warning('该 Skill 当前未发布或已归档，暂不可执行')
    return
  }
  emit('select', skill)
}

const visibilityLabel = (visibility: EvaluationSkillVisibility) => ({
  private: '仅自己可见',
  team: '团队可见',
  public: '公开'
})[visibility]

const toggleFavorite = async (skill: EvaluationSkill) => {
  if (favoritingSkillId.value) return
  const next = !skill.favorited
  favoritingSkillId.value = skill.id
  skill.favorited = next
  try {
    await setEvaluationSkillFavorite(skill.id, next)
    ElMessage.success(next ? '已收藏 Skill' : '已取消收藏')
  } catch (error: any) {
    skill.favorited = !next
    ElMessage.error(error?.serverMessage || '收藏状态更新失败')
  } finally {
    favoritingSkillId.value = ''
  }
}

const openOperations = (
  skill: EvaluationSkill,
  tab: 'runtime' | 'quality' | 'versions' | 'schedules' | 'batches' | 'compare' = 'runtime'
) => {
  operationsSkill.value = skill
  operationsInitialTab.value = tab
  operationsVisible.value = true
}

const handleOperationsChanged = async () => {
  await loadSkills()
}

const shareSkill = async (skill: EvaluationSkill) => {
  try {
    const share = await shareEvaluationSkill(skill.id)
    if (!share.url) throw new Error('服务未返回分享链接')
    const shareUrl = new URL(share.url, window.location.origin).toString()
    try {
      await navigator.clipboard.writeText(shareUrl)
      ElMessage.success('分享链接已复制')
    } catch {
      ElMessage.info('分享链接已生成，请在弹窗中复制')
    }
    await ElMessageBox.alert(shareUrl, `分享「${skill.name}」`, {
      confirmButtonText: '完成'
    })
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || error?.message || '生成分享链接失败')
  }
}

const exportSkill = async (skill: EvaluationSkill) => {
  try {
    const document = await exportEvaluationSkill(skill.id)
    const blob = new Blob([JSON.stringify(document, null, 2)], { type: 'application/json;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = window.document.createElement('a')
    anchor.href = url
    anchor.download = `${skill.name.replace(/[\\/:*?"<>|]/g, '_') || 'skill'}.json`
    anchor.click()
    URL.revokeObjectURL(url)
    ElMessage.success('Skill 已导出')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || 'Skill 导出失败')
  }
}

const cloneSkill = async (skill: EvaluationSkill, asTemplate = false) => {
  try {
    const cloned = await cloneEvaluationSkill(skill.id, {
      name: asTemplate ? `${skill.name}模板` : `${skill.name}副本`,
      asTemplate
    })
    ElMessage.success(asTemplate ? '已保存为模板' : '已复制为自定义 Skill')
    await loadSkills()
    if (!asTemplate) {
      selectedSource.value = 'custom'
      expandedSkillIds.value = Array.from(new Set([...expandedSkillIds.value, cloned.id]))
    }
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || (asTemplate ? '模板保存失败' : 'Skill 复制失败'))
  }
}

const handleSkillCommand = (skill: EvaluationSkill, command: string) => {
  if (command === 'share') shareSkill(skill)
  if (command === 'export') exportSkill(skill)
  if (command === 'clone') cloneSkill(skill)
  if (command === 'template') cloneSkill(skill, true)
  if (command === 'versions') openOperations(skill, 'versions')
}

const loadTemplates = async () => {
  templatesLoading.value = true
  try {
    templates.value = await listEvaluationSkillTemplates()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '模板加载失败')
  } finally {
    templatesLoading.value = false
  }
}

const handleLibraryCommand = (command: string) => {
  if (command === 'import') importFileInput.value?.click()
  if (command === 'templates') {
    templatesVisible.value = true
    loadTemplates()
  }
}

const handleImportFile = async (event: Event) => {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  try {
    if (file.size > 2 * 1024 * 1024) {
      throw new Error('导入文件不能超过 2 MB')
    }
    const document = JSON.parse(await file.text())
    const result = await importEvaluationSkills(document, 'rename')
    ElMessage.success(`成功导入 ${result.imported} 个 Skill${result.skipped ? `，跳过 ${result.skipped} 个` : ''}`)
    await loadSkills()
    selectedSource.value = 'custom'
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || error?.message || 'Skill 导入失败，请检查 JSON 文件格式')
  } finally {
    input.value = ''
  }
}

const instantiateTemplate = async (template: EvaluationSkill) => {
  if (instantiatingTemplateId.value) return
  instantiatingTemplateId.value = template.id
  try {
    const created = await instantiateEvaluationSkillTemplate(template.id, `${template.name}副本`)
    templatesVisible.value = false
    await loadSkills()
    selectedSource.value = 'custom'
    expandedSkillIds.value = Array.from(new Set([...expandedSkillIds.value, created.id]))
    ElMessage.success('已从模板创建 Skill')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '从模板创建失败')
  } finally {
    instantiatingTemplateId.value = ''
  }
}

const openCreateEditor = () => {
  editingSkill.value = null
  editorVisible.value = true
}

const openAiCreator = () => {
  aiRequirement.value = ''
  aiMaxSteps.value = 6
  smartDraft.value = null
  aiCreatorVisible.value = true
}

const generateAiDraft = async () => {
  if (aiGenerating.value || aiRequirement.value.trim().length < 5) return
  aiGenerating.value = true
  try {
    smartDraft.value = await generateEvaluationSkillDraft({
      requirement: aiRequirement.value.trim(),
      dataSourceId: props.dataSourceId || undefined,
      maxSteps: aiMaxSteps.value
    })
    ElMessage.success('Skill 草稿已生成，可确认步骤后创建')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '智能创建失败，请稍后重试')
  } finally {
    aiGenerating.value = false
  }
}

const saveAiDraft = async () => {
  if (!smartDraft.value || aiSaving.value) return
  aiSaving.value = true
  try {
    const created = await createEvaluationSkill(smartDraft.value.draft)
    await loadSkills()
    selectedSource.value = 'custom'
    aiCreatorVisible.value = false
    editingSkill.value = skills.value.find(skill => skill.id === created.id) || created
    editorVisible.value = true
    ElMessage.success('已创建私有草稿，请检查并完善后再发布')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || 'Skill 草稿保存失败')
  } finally {
    aiSaving.value = false
  }
}

const openEditEditor = (skill: EvaluationSkill) => {
  if (!skill.editable) return
  editingSkill.value = skill
  editorVisible.value = true
}

const handleEditorSaved = async (saved: EvaluationSkill, selectAfterSave: boolean) => {
  await loadSkills()
  const refreshed = skills.value.find(skill => skill.id === saved.id) || saved
  expandedSkillIds.value = Array.from(new Set([...expandedSkillIds.value, saved.id]))
  if (selectAfterSave) {
    emit('select', refreshed)
  } else {
    selectedSource.value = 'custom'
    selectedCategory.value = '全部'
    searchKeyword.value = ''
  }
}

const removeCustomSkill = async (skill: EvaluationSkill) => {
  if (!skill.deletable || deletingSkillId.value) return
  try {
    await ElMessageBox.confirm(
      `删除「${skill.name}」后不能恢复，已有评估历史仍会保留当时的执行快照。`,
      '删除自定义 Skill',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }

  deletingSkillId.value = skill.id
  try {
    await deleteEvaluationSkill(skill.id, skill.revision)
    emit('deleted', skill.id)
    ElMessage.success('自定义 Skill 已删除')
    await loadSkills()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || 'Skill 删除失败')
    if ([404, 409].includes(error?.response?.status)) await loadSkills()
  } finally {
    deletingSkillId.value = ''
  }
}

watch(() => props.dataSourceId, (next, previous) => {
  if (next !== previous) loadSkills()
})

onMounted(loadSkills)
</script>

<style scoped>
.skills-page {
  height: 100%;
  overflow-y: auto;
  background:
    radial-gradient(circle at 88% 8%, rgba(139, 92, 246, 0.08), transparent 26%),
    radial-gradient(circle at 8% 34%, rgba(59, 130, 246, 0.06), transparent 24%),
    var(--bg-page);
}

.skills-shell {
  width: min(1520px, 100%);
  margin: 0 auto;
  padding: 28px 32px 56px;
}

.skills-hero {
  position: relative;
  min-height: 260px;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 48px;
  padding: 40px 48px;
  color: white;
  border-radius: var(--radius-2xl);
  background:
    linear-gradient(118deg, rgba(15, 23, 42, 0.98), rgba(30, 64, 175, 0.94)),
    #0f172a;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.18);
}

.skills-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  opacity: 0.18;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.16) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.16) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: linear-gradient(90deg, transparent, black 62%);
  -webkit-mask-image: linear-gradient(90deg, transparent, black 62%);
}

.hero-copy {
  position: relative;
  z-index: 1;
  max-width: 760px;
}

.hero-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 18px;
  border: 1px solid rgba(191, 219, 254, 0.3);
  border-radius: var(--radius-full);
  background: rgba(255, 255, 255, 0.08);
  color: #bfdbfe;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
}

.skills-hero h2 {
  margin: 0;
  font-size: clamp(26px, 3vw, 38px);
  line-height: 1.22;
  letter-spacing: -0.5px;
}

.skills-hero p {
  max-width: 720px;
  margin: 16px 0 0;
  color: rgba(226, 232, 240, 0.88);
  font-size: 15px;
  line-height: 1.8;
}

.hero-stats {
  display: flex;
  align-items: center;
  gap: 20px;
  margin-top: 28px;
}

.stat-item {
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.stat-item strong {
  font-size: 24px;
  line-height: 1;
}

.stat-item span {
  color: #cbd5e1;
  font-size: 12px;
}

.stat-divider {
  width: 1px;
  height: 24px;
  background: rgba(203, 213, 225, 0.28);
}

.hero-flow {
  position: relative;
  z-index: 1;
  width: 360px;
  height: 180px;
  flex-shrink: 0;
}

.flow-orbit {
  position: absolute;
  height: 2px;
  background: linear-gradient(90deg, transparent, rgba(147, 197, 253, 0.8), transparent);
  transform-origin: center;
}

.flow-orbit::after {
  content: '';
  position: absolute;
  right: 18%;
  top: -3px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #60a5fa;
  box-shadow: 0 0 16px #60a5fa;
}

.flow-orbit-back { width: 190px; left: 44px; top: 98px; transform: rotate(-17deg); }
.flow-orbit-front { width: 174px; right: 20px; top: 82px; transform: rotate(20deg); }

.flow-node {
  position: absolute;
  width: 82px;
  height: 82px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  border: 1px solid rgba(191, 219, 254, 0.32);
  border-radius: 22px;
  background: rgba(255, 255, 255, 0.1);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.16), 0 14px 30px rgba(2, 6, 23, 0.22);
  backdrop-filter: blur(10px);
  color: #dbeafe;
  font-size: 12px;
}

.flow-node .el-icon { font-size: 24px; color: white; }
.flow-node-skill { left: 0; top: 64px; }
.flow-node-data { left: 138px; top: 8px; }
.flow-node-result { right: 0; bottom: 4px; }

.skills-content {
  margin-top: 28px;
}

.toolbar {
  margin-bottom: 24px;
}

.toolbar-topline {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 14px;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  gap: 10px;
}

.toolbar-copy h3 {
  margin: 0;
  color: var(--text-primary);
  font-size: var(--text-2xl);
}

.toolbar-copy span {
  display: block;
  margin-top: 4px;
  color: var(--text-muted);
  font-size: var(--text-sm);
}

.toolbar-controls {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--bg-card) 92%, #eff6ff);
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.035);
}

.source-filter { flex-shrink: 0; }
.skill-search { min-width: 260px; flex: 1; }
.category-select { width: 180px; flex-shrink: 0; }
.tag-select { width: 130px; }
.reset-button { flex-shrink: 0; }
.custom-store-warning { margin-bottom: 18px; }
.hidden-file-input { display: none; }
.ai-creator { display: flex; flex-direction: column; gap: 18px; }
.ai-creator-intro { display: flex; gap: 13px; padding: 15px; border: 1px solid #c7d2fe; border-radius: var(--radius-lg); background: linear-gradient(135deg, #eef2ff, #faf5ff); }
.ai-creator-intro > .el-icon { width: 38px; height: 38px; flex-shrink: 0; border-radius: 11px; color: white; background: #6366f1; font-size: 20px; }
.ai-creator-intro div { display: flex; flex-direction: column; gap: 4px; }
.ai-creator-intro strong { color: var(--text-primary); font-size: 14px; }
.ai-creator-intro span { color: var(--text-tertiary); font-size: 12px; }
.ai-creator-options { display: grid; grid-template-columns: 180px 1fr; gap: 18px; align-items: stretch; }
.ai-data-context { display: flex; flex-direction: column; justify-content: center; padding: 10px 14px; border: 1px solid var(--border-light); border-radius: var(--radius-md); background: var(--bg-secondary); }
.ai-data-context span, .ai-data-context small { color: var(--text-muted); font-size: 11px; }
.ai-data-context strong { margin: 3px 0; color: var(--text-secondary); font-size: 13px; }
.ai-draft-preview { padding: 18px; border: 1px solid #bfdbfe; border-radius: var(--radius-lg); background: #f8fbff; }
.ai-draft-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; }
.ai-draft-heading h4 { margin: 8px 0 5px; color: var(--text-primary); font-size: 18px; }
.ai-draft-heading p { margin: 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.6; }
.ai-draft-steps { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; }
.ai-draft-steps > div { display: grid; grid-template-columns: 26px 1fr auto; gap: 10px; align-items: center; padding: 10px 12px; border: 1px solid var(--border-light); border-radius: var(--radius-md); background: white; }
.ai-draft-steps > div > span { width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; border-radius: 50%; color: white; background: #6366f1; font-size: 11px; font-weight: 700; }
.ai-draft-steps strong, .ai-draft-steps small { display: block; }
.ai-draft-steps strong { color: var(--text-secondary); font-size: 13px; }
.ai-draft-steps small { margin-top: 3px; color: var(--text-muted); font-size: 11px; }

.skills-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(420px, 100%), 1fr));
  align-items: start;
  gap: 22px;
}

.skill-card {
  --skill-accent: #3b82f6;
  position: relative;
  overflow: hidden;
  border: 1px solid color-mix(in srgb, var(--skill-accent) 18%, var(--border-normal));
  border-radius: var(--radius-xl);
  background: var(--bg-card);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.055);
  transition: transform var(--transition-normal), box-shadow var(--transition-normal), border-color var(--transition-normal);
}

.skill-card::before {
  content: '';
  position: absolute;
  z-index: 1;
  inset: 0 0 auto;
  height: 4px;
  background: linear-gradient(90deg, var(--skill-accent), color-mix(in srgb, var(--skill-accent) 45%, white));
}

.skill-card:hover {
  transform: translateY(-3px);
  border-color: color-mix(in srgb, var(--skill-accent) 38%, var(--border-normal));
  box-shadow: var(--shadow-lg);
}

.card-main { padding: 24px 22px 18px; }

.card-heading {
  display: grid;
  grid-template-columns: 48px minmax(0, 1fr) auto;
  align-items: flex-start;
  gap: 14px;
}

.skill-icon {
  width: 48px;
  height: 48px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 15px;
  color: var(--skill-accent);
  background: color-mix(in srgb, var(--skill-accent) 11%, white);
  font-size: 24px;
}

.skill-icon .el-icon { font-size: 24px; }
.skill-heading-copy { min-width: 0; flex: 1; }

.skill-meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.skill-meta .el-tag { white-space: nowrap; }
.skill-meta .category-tag {
  border-color: color-mix(in srgb, var(--skill-accent) 28%, white);
  color: var(--skill-accent);
  background: color-mix(in srgb, var(--skill-accent) 7%, white);
}

.skill-meta .source-tag { --el-tag-bg-color: #f8fafc; --el-tag-border-color: #e2e8f0; --el-tag-text-color: #64748b; }
.skill-meta .status-tag { font-weight: 500; }

.skill-heading-copy h3 {
  margin: 0;
  color: var(--text-primary);
  overflow: hidden;
  font-size: 18px;
  line-height: 1.4;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-heading-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.step-count {
  height: 30px;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 0 9px;
  border: 1px solid color-mix(in srgb, var(--skill-accent) 18%, var(--border-light));
  border-radius: var(--radius-full);
  color: var(--text-tertiary);
  background: color-mix(in srgb, var(--skill-accent) 5%, white);
  font-size: 11px;
  line-height: 1;
  white-space: nowrap;
}

.step-count .el-icon { color: var(--skill-accent); }
.step-count strong { color: var(--text-secondary); font-size: 12px; }
.card-heading-actions .el-button { margin-left: 0; }

.skill-description {
  min-height: 44px;
  display: -webkit-box;
  overflow: hidden;
  margin: 16px 0 12px;
  color: var(--text-tertiary);
  font-size: 13px;
  line-height: 1.7;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.governance-line { display: flex; flex-wrap: wrap; gap: 6px 12px; margin: 0 0 13px; color: var(--text-muted); font-size: 10px; }
.governance-line span + span { position: relative; }
.governance-line span + span::before { content: '·'; position: absolute; left: -8px; }
.skill-tags { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; margin: 8px 0 12px; }
.skill-tags .el-tag { --el-tag-bg-color: #f8fafc; --el-tag-border-color: var(--border-light); --el-tag-text-color: var(--text-tertiary); }

.trigger-list {
  min-height: 48px;
  display: flex;
  align-content: flex-start;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.trigger-label {
  margin-right: 2px;
  color: var(--text-muted);
  font-size: 11px;
}

.trigger-list .el-tag {
  --el-tag-bg-color: var(--gray-50);
  --el-tag-border-color: var(--border-light);
  --el-tag-text-color: var(--text-tertiary);
  font-weight: 400;
}

.question-preview {
  min-height: 72px;
  display: flex;
  gap: 10px;
  margin-top: 14px;
  padding: 12px 13px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: linear-gradient(145deg, #f8fafc, color-mix(in srgb, var(--skill-accent) 3%, white));
}

.question-preview > .el-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--skill-accent);
}

.question-preview span { color: var(--text-muted); font-size: 10px; }
.question-preview p {
  display: -webkit-box;
  overflow: hidden;
  margin: 4px 0 0;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.availability-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  padding: 9px 11px;
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  color: var(--text-tertiary);
  background: #fbfdff;
  font-size: 11px;
}

.availability-line > span { flex: 1; }
.availability-line > .el-icon { color: var(--skill-accent); }
.availability-line .el-tag { width: auto; min-width: 72px; flex: 0 0 auto; justify-content: center; }

.skill-details {
  padding: 0 22px 20px;
  border-top: 1px dashed var(--border-normal);
  background: linear-gradient(180deg, var(--gray-50), white 38%);
}

.detail-title {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  padding: 18px 0 14px;
}

.detail-title span { color: var(--text-primary); font-size: 13px; font-weight: 600; }
.detail-title small { color: var(--text-muted); font-size: 10px; }

.step-item { display: flex; gap: 12px; }
.step-track { width: 24px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; }

.step-number {
  width: 24px;
  height: 24px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  color: white;
  background: var(--skill-accent);
  font-size: 11px;
  font-weight: 700;
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--skill-accent) 10%, white);
}

.step-line { width: 1px; min-height: 54px; flex: 1; background: var(--border-normal); }
.step-content { min-width: 0; flex: 1; padding: 2px 0 18px; }
.step-content h4 { margin: 0; color: var(--text-secondary); font-size: 13px; }
.step-content p { margin: 5px 0 8px; color: var(--text-tertiary); font-size: 11px; line-height: 1.55; }

.dataset-keywords { display: flex; align-items: center; flex-wrap: wrap; gap: 5px; }
.dataset-keywords > span { color: var(--text-muted); font-size: 10px; }
.dataset-keywords code {
  padding: 2px 5px;
  border-radius: 4px;
  color: var(--skill-accent);
  background: color-mix(in srgb, var(--skill-accent) 7%, white);
  font-family: inherit;
  font-size: 10px;
}

.output-rule {
  display: flex;
  gap: 10px;
  padding: 11px 12px;
  border: 1px solid color-mix(in srgb, var(--skill-accent) 18%, var(--border-light));
  border-radius: var(--radius-md);
  background: color-mix(in srgb, var(--skill-accent) 4%, white);
}

.output-rule > .el-icon { flex-shrink: 0; margin-top: 2px; color: var(--skill-accent); }
.output-rule strong { color: var(--text-secondary); font-size: 11px; }
.output-rule p { margin: 3px 0 0; color: var(--text-tertiary); font-size: 11px; line-height: 1.6; }

.card-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  padding: 12px 18px;
  border-top: 1px solid var(--border-light);
  background: rgba(248, 250, 252, 0.7);
}

.detail-button { margin-left: 0; color: var(--text-tertiary); }
.detail-button:hover { color: var(--skill-accent); }
.use-button { min-width: 108px; }
.card-actions { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; }
.card-actions .el-button { margin-left: 6px; }

.template-list { min-height: 180px; display: flex; flex-direction: column; gap: 12px; }
.template-item { display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 16px; border: 1px solid var(--border-normal); border-radius: var(--radius-lg); background: var(--bg-card); }
.template-item > div { min-width: 0; }
.template-item h4 { margin: 7px 0 4px; color: var(--text-primary); }
.template-item p { margin: 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.6; }
.template-item .skill-tags { margin-bottom: 0; }

.load-error {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px 22px;
  border: 1px solid #fecaca;
  border-radius: var(--radius-lg);
  background: #fef2f2;
  color: var(--danger-600);
}

.load-error > .el-icon { flex-shrink: 0; font-size: 24px; }
.load-error > div { min-width: 0; flex: 1; }
.load-error strong { color: #991b1b; }
.load-error p { margin: 4px 0 0; color: #b91c1c; font-size: 12px; }

.empty-filter {
  min-height: 320px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px;
  border: 1px dashed var(--border-normal);
  border-radius: var(--radius-xl);
  background: var(--bg-card);
  text-align: center;
}

.empty-icon {
  width: 54px;
  height: 54px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--gray-100);
  color: var(--text-muted);
}

.empty-icon .el-icon { font-size: 24px; }
.empty-filter h3 { margin: 16px 0 6px; color: var(--text-secondary); font-size: 16px; }
.empty-filter p { margin: 0 0 18px; color: var(--text-muted); font-size: 13px; }

.skeleton-card { padding: 22px; border-top-color: var(--gray-200); }
.skeleton-card:hover { transform: none; box-shadow: var(--shadow-sm); }
.skeleton-heading { display: flex; gap: 14px; }
.skeleton-heading-copy { flex: 1; display: flex; flex-direction: column; gap: 10px; }

@media (max-width: 1180px) {
  .skills-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .hero-flow { width: 300px; transform: scale(0.9); transform-origin: right center; }
  .toolbar-controls { flex-wrap: wrap; }
  .skill-search { flex: 1 1 320px; }
}

@media (max-width: 860px) {
  .skills-shell { padding: 20px 20px 40px; }
  .skills-hero { min-height: 0; padding: 32px; }
  .hero-flow { display: none; }
  .toolbar-topline { align-items: center; }
  .toolbar-controls { width: 100%; flex-wrap: wrap; }
  .skill-search { width: 100%; flex: 1; }
}

@media (max-width: 640px) {
  .skills-shell { padding: 14px 12px 32px; }
  .skills-hero { padding: 26px 22px; border-radius: var(--radius-xl); }
  .skills-hero p { font-size: 13px; }
  .hero-stats { gap: 12px; }
  .stat-item { flex-direction: column; align-items: flex-start; gap: 3px; }
  .skills-grid { grid-template-columns: 1fr; }
  .toolbar-topline { align-items: flex-start; flex-direction: column; }
  .toolbar-actions { width: 100%; }
  .toolbar-actions > .el-button,
  .toolbar-actions :deep(.el-dropdown) { flex: 1; }
  .toolbar-actions :deep(.el-dropdown .el-button) { width: 100%; }
  .toolbar-controls { flex-wrap: wrap; }
  .source-filter { width: 100%; }
  .source-filter :deep(.el-radio-button) { flex: 1; }
  .source-filter :deep(.el-radio-button__inner) { width: 100%; }
  .skill-search { flex-basis: 100%; }
  .category-select { flex: 1; }
  .card-heading { grid-template-columns: 44px minmax(0, 1fr); }
  .skill-icon { width: 44px; height: 44px; }
  .card-heading-actions { grid-column: 1 / -1; justify-content: space-between; margin-top: 2px; }
  .card-footer { align-items: stretch; flex-direction: column-reverse; }
  .card-actions { flex-wrap: wrap; }
  .use-button { width: 100%; }
}
</style>
