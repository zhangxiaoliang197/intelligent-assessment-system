<template>
  <el-dialog
    :model-value="modelValue"
    :title="editing ? '编辑自定义 Skill' : '按步骤新建 Skill'"
    width="min(900px, 94vw)"
    append-to-body
    destroy-on-close
    class="skill-editor-dialog"
    :close-on-click-modal="false"
    :before-close="handleBeforeClose"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="editor-shell">
      <el-steps :active="wizardStage" finish-status="success" align-center>
        <el-step title="定义用途" description="名称、场景与目标" />
        <el-step title="编排步骤" description="按顺序选择数据集" />
        <el-step title="输出规则" description="预览并保存" />
      </el-steps>

      <div v-if="wizardStage === 0" class="stage-panel">
        <div class="stage-heading">
          <h3>这个 Skill 要解决什么问题？</h3>
          <p>清晰描述目标和触发场景，方便以后搜索、推荐和复用。</p>
        </div>
        <el-form label-position="top">
          <div class="two-column-grid">
            <el-form-item label="Skill 名称" required>
              <el-input
                v-model="form.name"
                maxlength="80"
                show-word-limit
                placeholder="例如：重点目标威胁评估"
              />
            </el-form-item>
            <el-form-item label="分类" required>
              <el-select
                v-model="form.category"
                filterable
                allow-create
                default-first-option
                placeholder="选择或输入分类"
              >
                <el-option v-for="category in categoryOptions" :key="category" :label="category" :value="category" />
              </el-select>
            </el-form-item>
          </div>
          <el-form-item label="用途说明" required>
            <el-input
              v-model="form.description"
              type="textarea"
              :rows="3"
              maxlength="500"
              show-word-limit
              placeholder="说明这个 Skill 会按什么思路完成哪类评估"
            />
          </el-form-item>
          <div class="governance-panel">
            <div class="governance-owner">
              <span>Skill 归属</span>
              <strong>{{ skillOwnerLabel }}</strong>
              <small>归属由当前登录身份确定，仅所有者或有权限的管理员可修改。</small>
            </div>
            <el-form-item label="可见范围" required>
              <el-radio-group v-model="form.visibility">
                <el-radio-button label="private">仅自己</el-radio-button>
                <el-radio-button label="team">团队</el-radio-button>
                <el-radio-button label="public">公开</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="form.visibility === 'team'" label="团队标识" required>
              <el-input
                v-model="form.teamId"
                maxlength="80"
                placeholder="请输入当前用户所属的团队标识"
              />
            </el-form-item>
          </div>
          <el-form-item label="标签">
            <el-select
              v-model="form.tags"
              multiple
              filterable
              allow-create
              default-first-option
              :multiple-limit="12"
              placeholder="输入标签后按回车，便于检索和运营管理"
            />
          </el-form-item>
          <el-form-item label="适用场景 / 触发词">
            <el-select
              v-model="form.triggers"
              multiple
              filterable
              allow-create
              default-first-option
              :multiple-limit="12"
              placeholder="输入后按回车添加，最多 12 个"
            />
          </el-form-item>
          <el-form-item label="推荐提问">
            <el-select
              v-model="form.recommendedQuestions"
              multiple
              filterable
              allow-create
              default-first-option
              :multiple-limit="5"
              placeholder="输入用户可直接使用的问题，最多 5 个"
            />
          </el-form-item>
        </el-form>
      </div>

      <div v-else-if="wizardStage === 1" class="stage-panel step-stage">
        <div class="stage-heading step-stage-heading">
          <div>
            <h3>按实际查询顺序编排数据步骤</h3>
            <p>执行时会严格从第 1 步开始；可从当前数据源精确选择数据集，也可填写跨数据源匹配关键词。</p>
          </div>
          <el-button type="primary" plain :disabled="form.steps.length >= 12" @click="addStep">
            <el-icon><Plus /></el-icon>
            新增步骤
          </el-button>
        </div>

        <el-alert
          v-if="!dataSourceId"
          type="info"
          :closable="false"
          show-icon
          title="当前未选择数据源，可先用数据集名称、表名或业务词填写匹配关键词。"
        />
        <el-alert
          v-else-if="datasetLoadError"
          type="warning"
          :closable="false"
          show-icon
          :title="datasetLoadError"
        />

        <div class="orchestration-panel">
          <div class="orchestration-copy">
            <strong>运行编排</strong>
            <span>配置步骤依赖、失败策略与整体执行时限。</span>
          </div>
          <el-form label-position="top" class="orchestration-form">
            <el-form-item label="编排模式">
              <el-select v-model="form.orchestration.mode">
                <el-option label="顺序执行" value="sequential" />
                <el-option label="按依赖执行" value="dependency" />
              </el-select>
            </el-form-item>
            <el-form-item label="整体超时">
              <el-input-number
                v-model="form.orchestration.timeoutSeconds"
                :min="30"
                :max="1800"
                :step="30"
                controls-position="right"
              />
              <span class="field-suffix">秒</span>
            </el-form-item>
            <el-form-item label="失败策略">
              <el-select v-model="form.orchestration.failurePolicy">
                <el-option label="继续可运行步骤" value="continue" />
                <el-option label="停止后续步骤" value="stop" />
              </el-select>
            </el-form-item>
          </el-form>
        </div>

        <div class="editable-steps">
          <section v-for="(step, index) in form.steps" :key="step._key" class="editable-step-card">
            <div class="step-index-column">
              <span>{{ index + 1 }}</span>
              <div v-if="index < form.steps.length - 1" class="step-connector"></div>
            </div>
            <div class="step-form">
              <div class="step-card-header">
                <strong>第 {{ index + 1 }} 步</strong>
                <div class="step-actions">
                  <el-button text :disabled="index === 0" title="上移" @click="moveStep(index, -1)">
                    <el-icon><ArrowUp /></el-icon>
                  </el-button>
                  <el-button text :disabled="index === form.steps.length - 1" title="下移" @click="moveStep(index, 1)">
                    <el-icon><ArrowDown /></el-icon>
                  </el-button>
                  <el-button
                    text
                    type="danger"
                    :disabled="form.steps.length === 1"
                    title="删除"
                    @click="removeStep(index)"
                  >
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <div class="two-column-grid">
                <el-form-item label="步骤名称" required>
                  <el-input v-model="step.name" maxlength="80" placeholder="例如：核验威胁目标" />
                </el-form-item>
                <el-form-item label="精确数据集（可选）">
                  <el-select
                    v-model="step.datasetId"
                    clearable
                    filterable
                    :loading="datasetsLoading"
                    placeholder="从当前数据源选择"
                    @change="onDatasetChange(step)"
                  >
                    <el-option
                      v-for="dataset in datasetOptions"
                      :key="dataset.id"
                      :label="`${dataset.name} · ${dataset.tableName}`"
                      :value="dataset.id"
                    />
                  </el-select>
                </el-form-item>
              </div>
              <div v-if="hasInvalidDatasetBinding(step)" class="dataset-binding-warning">
                <span>原精确绑定不属于当前数据源，本步骤执行时将被跳过。</span>
                <el-button text type="warning" @click="clearDatasetBinding(step)">
                  解除精确绑定，改用关键词匹配
                </el-button>
              </div>
              <el-form-item label="本步骤要分析什么" required>
                <el-input
                  v-model="step.description"
                  type="textarea"
                  :rows="2"
                  maxlength="500"
                  show-word-limit
                  placeholder="只描述分析目标，不需要编写 SQL"
                />
              </el-form-item>
              <el-form-item label="数据集匹配关键词" required>
                <el-select
                  v-model="step.datasetKeywords"
                  multiple
                  filterable
                  allow-create
                  default-first-option
                  :multiple-limit="12"
                  placeholder="输入数据集名称、物理表名或业务关键词"
                >
                  <el-option
                    v-for="keyword in datasetKeywordOptions"
                    :key="keyword"
                    :label="keyword"
                    :value="keyword"
                  />
                </el-select>
              </el-form-item>
              <el-checkbox v-model="step.allowReuse">
                允许复用前面步骤已使用的数据集
              </el-checkbox>
              <el-collapse class="advanced-step-config">
                <el-collapse-item title="高级运行配置">
                  <div class="advanced-grid">
                    <el-form-item label="依赖步骤">
                      <el-select
                        v-model="step.dependsOn"
                        multiple
                        clearable
                        placeholder="无依赖"
                        :disabled="form.orchestration.mode !== 'dependency'"
                      >
                        <el-option
                          v-for="candidate in form.steps.filter(item => item.id !== step.id)"
                          :key="candidate.id"
                          :label="candidate.name || candidate.id"
                          :value="candidate.id"
                        />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="依赖满足条件">
                      <el-select v-model="step.runIf">
                        <el-option label="全部成功" value="all_success" />
                        <el-option label="任一成功" value="any_success" />
                        <el-option label="始终执行" value="always" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="失败后">
                      <el-select v-model="step.onFailure">
                        <el-option label="继续" value="continue" />
                        <el-option label="停止全部" value="stop" />
                        <el-option label="跳过依赖节点" value="skip_dependents" />
                      </el-select>
                    </el-form-item>
                    <el-form-item label="失败重试">
                      <el-input-number v-model="step.retryCount" :min="0" :max="3" controls-position="right" />
                      <span class="field-suffix">次</span>
                    </el-form-item>
                    <el-form-item label="单步超时">
                      <el-input-number
                        v-model="step.timeoutSeconds"
                        :min="5"
                        :max="300"
                        :step="5"
                        controls-position="right"
                      />
                      <span class="field-suffix">秒</span>
                    </el-form-item>
                  </div>
                </el-collapse-item>
              </el-collapse>
            </div>
          </section>
        </div>
      </div>

      <div v-else class="stage-panel">
        <div class="stage-heading">
          <h3>定义结论应该怎样输出</h3>
          <p>输出要求只控制结论的结构和侧重点，系统仍会坚持只读查询和证据约束。</p>
        </div>
        <el-form label-position="top">
          <el-form-item label="输出要求" required>
            <el-input
              v-model="form.outputInstruction"
              type="textarea"
              :rows="4"
              maxlength="1200"
              show-word-limit
              placeholder="例如：按风险等级、关键证据、影响判断和处置建议四部分输出，并明确数据缺口。"
            />
          </el-form-item>
        </el-form>

        <div class="skill-preview">
          <div class="preview-header">
            <div class="preview-icon"><el-icon><MagicStick /></el-icon></div>
            <div>
              <span>{{ form.category || '自定义' }} · {{ visibilityLabel }} · 自定义 Skill</span>
              <h4>{{ form.name || '未命名 Skill' }}</h4>
              <p>{{ form.description || '尚未填写用途说明' }}</p>
            </div>
          </div>
          <div class="preview-orchestration">
            {{ form.orchestration.mode === 'dependency' ? '依赖编排' : '顺序编排' }}
            · 整体超时 {{ form.orchestration.timeoutSeconds }} 秒
            · {{ form.orchestration.failurePolicy === 'stop' ? '失败即停止' : '失败后继续' }}
          </div>
          <div class="preview-flow">
            <template v-for="(step, index) in form.steps" :key="step._key">
              <div class="preview-step">
                <span>{{ index + 1 }}</span>
                <div>
                  <strong>{{ step.name || `步骤 ${index + 1}` }}</strong>
                  <small>{{ step.datasetName || step.datasetKeywords[0] || '待匹配数据集' }}</small>
                </div>
              </div>
              <el-icon v-if="index < form.steps.length - 1" class="preview-arrow"><Right /></el-icon>
            </template>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="editor-footer">
        <el-button :disabled="saving" @click="requestClose">取消</el-button>
        <div>
          <el-button v-if="wizardStage > 0" :disabled="saving" @click="wizardStage--">上一步</el-button>
          <el-button v-if="wizardStage < 2" type="primary" @click="goNext">下一步</el-button>
          <template v-else>
            <el-button :loading="saving" @click="saveSkill(false)">保存 Skill</el-button>
            <el-button type="primary" :loading="saving" @click="saveSkill(true)">保存并选择</el-button>
          </template>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ArrowDown, ArrowUp, Delete, MagicStick, Plus, Right } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createEvaluationSkill,
  listEvaluationDatasets,
  updateEvaluationSkill
} from '@/services/evaluationSkills'
import type {
  EvaluationDatasetOption,
  EvaluationSkill,
  EvaluationSkillStepInput,
  EvaluationSkillUpsertPayload,
  EvaluationSkillVisibility,
  SkillOrchestration
} from '@/types/evaluationSkill'

interface EditableStep extends Omit<EvaluationSkillStepInput, 'id' | 'dependsOn' | 'runIf' | 'retryCount' | 'timeoutSeconds' | 'onFailure'> {
  _key: string
  _autoKeywords: string[]
  id: string
  dependsOn: string[]
  runIf: 'all_success' | 'any_success' | 'always'
  retryCount: number
  timeoutSeconds: number
  onFailure: 'continue' | 'stop' | 'skip_dependents'
}

const props = withDefaults(defineProps<{
  modelValue: boolean
  skill?: EvaluationSkill | null
  dataSourceId?: string
}>(), {
  skill: null,
  dataSourceId: ''
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  saved: [skill: EvaluationSkill, selectAfterSave: boolean]
  refresh: []
}>()

const categoryOptions = [
  '综合评估', '空中作战', '火力打击', '损伤评估',
  '保障评估', '任务评估', '威胁研判', '自定义'
]
let draftKey = 0
const newStep = (): EditableStep => {
  const sequence = ++draftKey
  return {
    _key: `draft-${Date.now()}-${sequence}`,
    _autoKeywords: [],
    id: `step-${sequence}`,
    name: '',
    description: '',
    datasetKeywords: [],
    allowReuse: false,
    datasetId: '',
    datasetName: '',
    dependsOn: [],
    runIf: 'all_success',
    retryCount: 0,
    timeoutSeconds: 130,
    onFailure: 'continue'
  }
}

const form = reactive<{
  name: string
  description: string
  category: string
  triggers: string[]
  recommendedQuestions: string[]
  visibility: EvaluationSkillVisibility
  teamId: string
  tags: string[]
  steps: EditableStep[]
  outputInstruction: string
  orchestration: SkillOrchestration
}>({
  name: '',
  description: '',
  category: '自定义',
  triggers: [],
  recommendedQuestions: [],
  visibility: 'private',
  teamId: '',
  tags: [],
  steps: [newStep()],
  outputInstruction: '',
  orchestration: {
    mode: 'sequential',
    maxConcurrency: 1,
    timeoutSeconds: 600,
    failurePolicy: 'continue'
  }
})

const wizardStage = ref(0)
const saving = ref(false)
const datasetsLoading = ref(false)
const datasetLoadError = ref('')
const datasetOptions = ref<EvaluationDatasetOption[]>([])
const datasetsLoaded = ref(false)
const originalSnapshot = ref('')
let datasetRequestSequence = 0
const editing = computed(() => props.skill?.source === 'custom')
const skillOwnerLabel = computed(() => props.skill?.ownerName || props.skill?.ownerId || '当前用户')
const visibilityLabel = computed(() => ({
  private: '仅自己可见',
  team: '团队可见',
  public: '公开'
})[form.visibility])
const datasetKeywordOptions = computed(() => Array.from(new Set(
  datasetOptions.value.flatMap(dataset => [dataset.name, dataset.tableName]).filter(Boolean)
)))

const toPayload = (): EvaluationSkillUpsertPayload => ({
  name: form.name.trim(),
  description: form.description.trim(),
  category: form.category.trim(),
  triggers: form.triggers.map(item => item.trim()).filter(Boolean),
  recommendedQuestions: form.recommendedQuestions.map(item => item.trim()).filter(Boolean),
  visibility: form.visibility,
  ...(form.visibility === 'team' && form.teamId.trim() ? { teamId: form.teamId.trim() } : {}),
  tags: form.tags.map(item => item.trim()).filter(Boolean),
  steps: form.steps.map(step => ({
    id: step.id,
    name: step.name.trim(),
    description: step.description.trim(),
    datasetKeywords: step.datasetKeywords.map(item => item.trim()).filter(Boolean),
    allowReuse: Boolean(step.allowReuse),
    dependsOn: form.orchestration.mode === 'dependency' ? [...step.dependsOn] : [],
    runIf: step.runIf,
    retryCount: step.retryCount,
    timeoutSeconds: step.timeoutSeconds,
    onFailure: step.onFailure,
    ...(step.datasetId ? { datasetId: step.datasetId } : {}),
    ...(step.datasetName ? { datasetName: step.datasetName } : {})
  })),
  outputInstruction: form.outputInstruction.trim(),
  orchestration: { ...form.orchestration }
})

const resetForm = () => {
  const skill = props.skill
  form.name = skill?.name || ''
  form.description = skill?.description || ''
  form.category = skill?.category || '自定义'
  form.triggers = [...(skill?.triggers || [])]
  form.recommendedQuestions = [...(skill?.recommendedQuestions || [])]
  form.visibility = skill?.visibility || 'private'
  form.teamId = skill?.teamId || ''
  form.tags = [...(skill?.tags || [])]
  form.steps = skill?.steps?.length
    ? skill.steps.map(step => ({
      _key: `existing-${step.id}-${++draftKey}`,
      _autoKeywords: [],
      id: step.id,
      name: step.name,
      description: step.description,
      datasetKeywords: [...step.datasetKeywords],
      allowReuse: Boolean(step.allowReuse),
      datasetId: step.datasetId || '',
      datasetName: step.datasetName || '',
      dependsOn: [...(step.dependsOn || [])],
      runIf: step.runIf || 'all_success',
      retryCount: step.retryCount ?? 0,
      timeoutSeconds: step.timeoutSeconds || 130,
      onFailure: step.onFailure || 'continue'
    }))
    : [newStep()]
  form.outputInstruction = skill?.outputInstruction || ''
  form.orchestration = skill?.orchestration
    ? { ...skill.orchestration }
    : { mode: 'sequential', maxConcurrency: 1, timeoutSeconds: 600, failurePolicy: 'continue' }
  wizardStage.value = 0
  originalSnapshot.value = JSON.stringify(toPayload())
}

const loadDatasets = async () => {
  const requestSequence = ++datasetRequestSequence
  datasetOptions.value = []
  datasetLoadError.value = ''
  datasetsLoaded.value = false
  if (!props.dataSourceId) return
  datasetsLoading.value = true
  try {
    const datasets = await listEvaluationDatasets(props.dataSourceId)
    if (requestSequence !== datasetRequestSequence) return
    datasetOptions.value = datasets
    form.steps.forEach(step => {
      const selected = datasets.find(dataset => dataset.id === step.datasetId)
      if (!selected) return
      step._autoKeywords = [selected.tableName, selected.name]
        .filter(keyword => step.datasetKeywords.includes(keyword))
    })
    datasetsLoaded.value = true
  } catch (error: any) {
    if (requestSequence !== datasetRequestSequence) return
    datasetLoadError.value = error?.serverMessage || '当前数据源的数据集暂时无法加载，可继续填写匹配关键词'
  } finally {
    if (requestSequence === datasetRequestSequence) datasetsLoading.value = false
  }
}

watch(() => props.modelValue, async open => {
  if (!open) return
  resetForm()
  await loadDatasets()
})

watch(() => props.dataSourceId, () => {
  if (props.modelValue) loadDatasets()
})

const addStep = () => {
  if (form.steps.length >= 12) return
  form.steps.push(newStep())
}

const removeStep = (index: number) => {
  if (form.steps.length <= 1) return
  const [removed] = form.steps.splice(index, 1)
  form.steps.forEach(step => {
    step.dependsOn = step.dependsOn.filter(dependency => dependency !== removed.id)
  })
}

const moveStep = (index: number, offset: number) => {
  const target = index + offset
  if (target < 0 || target >= form.steps.length) return
  const [step] = form.steps.splice(index, 1)
  form.steps.splice(target, 0, step)
}

const onDatasetChange = (step: EditableStep) => {
  const dataset = datasetOptions.value.find(item => item.id === step.datasetId)
  if (!dataset) {
    step.datasetName = ''
    step._autoKeywords = []
    return
  }
  const manuallyEntered = step.datasetKeywords.filter(
    keyword => !step._autoKeywords.includes(keyword)
  )
  const automaticKeywords = [dataset.tableName, dataset.name].filter(Boolean)
  step.datasetName = dataset.name
  step.datasetKeywords = Array.from(new Set([
    ...automaticKeywords,
    ...manuallyEntered
  ].filter(Boolean))).slice(0, 12)
  step._autoKeywords = automaticKeywords
}

const hasInvalidDatasetBinding = (step: EditableStep) => Boolean(
  props.dataSourceId
  && datasetsLoaded.value
  && step.datasetId
  && !datasetOptions.value.some(dataset => dataset.id === step.datasetId)
)

const clearDatasetBinding = (step: EditableStep) => {
  step.datasetId = ''
  step.datasetName = ''
  step._autoKeywords = []
}

const validateStage = (stage: number): boolean => {
  if (stage === 0) {
    if (!form.name.trim() || !form.category.trim() || !form.description.trim()) {
      ElMessage.warning('请完整填写 Skill 名称、分类和用途说明')
      return false
    }
    if (form.name.trim().length > 80 || form.category.trim().length > 40 || form.description.trim().length > 500) {
      ElMessage.warning('Skill 名称、分类或用途说明超过长度限制')
      return false
    }
    if (form.triggers.length > 12 || form.recommendedQuestions.length > 5) {
      ElMessage.warning('触发词或推荐问题数量超过限制')
      return false
    }
    if (form.visibility === 'team' && !form.teamId.trim()) {
      ElMessage.warning('选择团队可见时，请填写团队标识')
      return false
    }
    if (form.tags.length > 12 || form.tags.some(item => !item.trim() || item.trim().length > 40)) {
      ElMessage.warning('标签最多 12 个，每个标签最多 40 个字符')
      return false
    }
    if (form.triggers.some(item => item.trim().length > 80)) {
      ElMessage.warning('每个触发词最多 80 个字符')
      return false
    }
    if (form.recommendedQuestions.some(item => item.trim().length > 300)) {
      ElMessage.warning('每个推荐问题最多 300 个字符')
      return false
    }
  }
  if (stage === 1) {
    if (!form.steps.length || form.steps.length > 12) {
      ElMessage.warning('一个 Skill 需要 1 至 12 个执行步骤')
      return false
    }
    const invalidIndex = form.steps.findIndex(step =>
      !step.name.trim()
      || !step.description.trim()
      || !step.datasetKeywords.length
      || step.datasetKeywords.length > 12
      || step.name.trim().length > 80
      || step.description.trim().length > 500
      || step.datasetKeywords.some(keyword => !keyword.trim() || keyword.trim().length > 80)
    )
    if (invalidIndex >= 0) {
      ElMessage.warning(`请完整填写第 ${invalidIndex + 1} 步及其数据集匹配关键词`)
      return false
    }
    const runtimeInvalidIndex = form.steps.findIndex(step =>
      step.retryCount < 0 || step.retryCount > 3
      || step.timeoutSeconds < 5 || step.timeoutSeconds > 300
    )
    if (runtimeInvalidIndex >= 0) {
      ElMessage.warning(`第 ${runtimeInvalidIndex + 1} 步的重试次数或超时时间超出范围`)
      return false
    }
    if (form.orchestration.timeoutSeconds < 30 || form.orchestration.timeoutSeconds > 1800) {
      ElMessage.warning('Skill 整体超时需设置为 30 至 1800 秒')
      return false
    }
    if (form.orchestration.mode === 'dependency') {
      const stepIds = new Set(form.steps.map(step => step.id))
      const dependencyMap = new Map(form.steps.map(step => [step.id, step.dependsOn]))
      const invalidDependency = form.steps.find(step =>
        step.dependsOn.some(dependency => dependency === step.id || !stepIds.has(dependency))
      )
      if (invalidDependency) {
        ElMessage.warning(`步骤「${invalidDependency.name}」包含无效依赖`)
        return false
      }
      const visiting = new Set<string>()
      const visited = new Set<string>()
      const hasCycle = (stepId: string): boolean => {
        if (visiting.has(stepId)) return true
        if (visited.has(stepId)) return false
        visiting.add(stepId)
        const cyclic = (dependencyMap.get(stepId) || []).some(hasCycle)
        visiting.delete(stepId)
        visited.add(stepId)
        return cyclic
      }
      if (form.steps.some(step => hasCycle(step.id))) {
        ElMessage.warning('步骤依赖存在循环，请调整后再保存')
        return false
      }
    }
  }
  if (stage === 2) {
    if (!form.outputInstruction.trim()) {
      ElMessage.warning('请填写结论输出要求')
      return false
    }
    if (form.outputInstruction.trim().length > 1200) {
      ElMessage.warning('结论输出要求最多 1200 个字符')
      return false
    }
  }
  return true
}

const goNext = () => {
  if (!validateStage(wizardStage.value)) return
  wizardStage.value++
}

const validateAll = () => [0, 1, 2].every(validateStage)

const saveSkill = async (selectAfterSave: boolean) => {
  if (!validateAll() || saving.value) return
  saving.value = true
  try {
    const saved = editing.value && props.skill
      ? await updateEvaluationSkill(props.skill.id, toPayload(), props.skill.revision)
      : await createEvaluationSkill(toPayload())
    originalSnapshot.value = JSON.stringify(toPayload())
    ElMessage.success(editing.value ? '自定义 Skill 已更新' : '自定义 Skill 已创建')
    emit('saved', saved, selectAfterSave)
    emit('update:modelValue', false)
  } catch (error: any) {
    const status = error?.response?.status
    if (status === 409 || status === 404) {
      emit('refresh')
      ElMessage.error(
        status === 409
          ? '该 Skill 已被其他操作更新，目录已刷新，请重新打开后编辑'
          : '该 Skill 已被删除，目录已刷新'
      )
      emit('update:modelValue', false)
      return
    }
    ElMessage.error(error?.serverMessage || 'Skill 保存失败')
  } finally {
    saving.value = false
  }
}

const confirmDiscard = async (): Promise<boolean> => {
  if (JSON.stringify(toPayload()) === originalSnapshot.value) return true
  try {
    await ElMessageBox.confirm('尚有未保存的 Skill 内容，确定放弃吗？', '放弃修改', {
      confirmButtonText: '放弃',
      cancelButtonText: '继续编辑',
      type: 'warning'
    })
    return true
  } catch {
    return false
  }
}

const requestClose = async () => {
  if (saving.value || !(await confirmDiscard())) return
  emit('update:modelValue', false)
}

const handleBeforeClose = async (done: () => void) => {
  if (saving.value || !(await confirmDiscard())) return
  done()
}
</script>

<style scoped>
.editor-shell { min-height: 560px; padding: 4px 8px 0; }
.stage-panel { margin-top: 28px; }
.stage-heading { margin-bottom: 20px; }
.stage-heading h3 { margin: 0; color: var(--text-primary); font-size: 18px; }
.stage-heading p { margin: 7px 0 0; color: var(--text-tertiary); font-size: 13px; line-height: 1.65; }
.step-stage-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; }
.two-column-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.governance-panel { display: grid; grid-template-columns: minmax(180px, .8fr) minmax(280px, 1.2fr); gap: 14px 18px; margin-bottom: 18px; padding: 16px; border: 1px solid #dbeafe; border-radius: var(--radius-lg); background: #f8fbff; }
.governance-panel .el-form-item { margin-bottom: 0; }
.governance-owner { display: flex; flex-direction: column; gap: 4px; }
.governance-owner span { color: var(--text-secondary); font-size: 13px; }
.governance-owner strong { color: var(--text-primary); font-size: 14px; }
.governance-owner small { max-width: 280px; color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.stage-panel :deep(.el-select) { width: 100%; }
.orchestration-panel { display: grid; grid-template-columns: minmax(150px, .65fr) minmax(460px, 1.35fr); gap: 18px; margin-top: 16px; padding: 16px; border: 1px solid #c7d2fe; border-radius: var(--radius-lg); background: linear-gradient(135deg, #f8faff, #f5f3ff); }
.orchestration-copy { display: flex; flex-direction: column; gap: 5px; }
.orchestration-copy strong { color: var(--text-primary); font-size: 14px; }
.orchestration-copy span { color: var(--text-tertiary); font-size: 12px; line-height: 1.55; }
.orchestration-form { display: grid; grid-template-columns: 1fr 1fr 1.25fr; gap: 12px; }
.orchestration-form .el-form-item { margin-bottom: 0; }
.field-suffix { margin-left: 7px; color: var(--text-muted); font-size: 12px; }
.editable-steps { display: flex; flex-direction: column; gap: 14px; margin-top: 16px; }
.editable-step-card { display: flex; gap: 14px; padding: 18px; border: 1px solid var(--border-normal); border-radius: var(--radius-lg); background: var(--bg-card); }
.step-index-column { width: 30px; flex-shrink: 0; display: flex; flex-direction: column; align-items: center; }
.step-index-column > span { width: 28px; height: 28px; display: flex; align-items: center; justify-content: center; border-radius: 50%; color: white; background: var(--primary-500); font-size: 12px; font-weight: 700; }
.step-connector { width: 1px; min-height: 120px; flex: 1; margin-top: 8px; background: var(--border-normal); }
.step-form { min-width: 0; flex: 1; }
.step-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.step-card-header strong { color: var(--text-secondary); font-size: 14px; }
.step-actions { display: flex; }
.step-actions .el-button { margin-left: 0; padding: 6px; }
.dataset-binding-warning { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: -4px 0 14px; padding: 9px 12px; border: 1px solid #fde68a; border-radius: var(--radius-md); background: #fffbeb; color: #92400e; font-size: 12px; }
.dataset-binding-warning .el-button { flex-shrink: 0; padding: 0; }
.advanced-step-config { margin-top: 14px; border-top: 1px dashed var(--border-normal); }
.advanced-step-config :deep(.el-collapse-item__header) { height: 42px; color: var(--text-secondary); font-size: 12px; }
.advanced-grid { display: grid; grid-template-columns: 1.45fr 1fr 1fr; gap: 0 14px; padding-top: 8px; }
.advanced-grid .el-form-item { margin-bottom: 14px; }
.skill-preview { margin-top: 24px; padding: 20px; border: 1px solid #bfdbfe; border-radius: var(--radius-xl); background: linear-gradient(135deg, #eff6ff, #f8fafc); }
.preview-header { display: flex; gap: 14px; }
.preview-icon { width: 44px; height: 44px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 13px; color: white; background: var(--primary-500); }
.preview-header span { color: var(--primary-600); font-size: 11px; font-weight: 600; }
.preview-header h4 { margin: 3px 0 5px; color: var(--text-primary); font-size: 17px; }
.preview-header p { margin: 0; color: var(--text-tertiary); font-size: 12px; }
.preview-orchestration { display: inline-flex; margin-top: 16px; padding: 6px 10px; border-radius: 999px; color: #4338ca; background: #eef2ff; font-size: 11px; }
.preview-flow { display: flex; align-items: center; gap: 8px; overflow-x: auto; margin-top: 20px; padding-bottom: 4px; }
.preview-step { min-width: 150px; display: flex; align-items: center; gap: 9px; padding: 10px 12px; border: 1px solid var(--border-normal); border-radius: var(--radius-md); background: white; }
.preview-step > span { width: 22px; height: 22px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 50%; color: white; background: var(--primary-500); font-size: 10px; }
.preview-step div { min-width: 0; }
.preview-step strong, .preview-step small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview-step strong { color: var(--text-secondary); font-size: 12px; }
.preview-step small { margin-top: 3px; color: var(--text-muted); font-size: 10px; }
.preview-arrow { flex-shrink: 0; color: var(--text-muted); }
.editor-footer { width: 100%; display: flex; align-items: center; justify-content: space-between; }

@media (max-width: 720px) {
  .editor-shell { min-height: 0; }
  .two-column-grid { grid-template-columns: 1fr; gap: 0; }
  .governance-panel { grid-template-columns: 1fr; }
  .orchestration-panel, .orchestration-form, .advanced-grid { grid-template-columns: 1fr; }
  .step-stage-heading { flex-direction: column; }
  .editable-step-card { padding: 14px 12px; }
  .dataset-binding-warning { align-items: flex-start; flex-direction: column; }
  .editor-footer { align-items: stretch; flex-direction: column-reverse; gap: 10px; }
  .editor-footer > div { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
  .editor-footer .el-button { margin-left: 0; }
}
</style>
