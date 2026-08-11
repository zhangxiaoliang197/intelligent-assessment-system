<template>
  <el-dialog
    :model-value="modelValue"
    :title="dialogTitle"
    width="760px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="info"
      :closable="false"
      title="保存后进入草稿态；确认分析流程和数据源后，再从 Skill 详情中发布。"
    />
    <el-form class="skill-editor" label-position="top">
      <el-form-item label="名称" required>
        <el-input v-model="form.name" maxlength="80" show-word-limit />
      </el-form-item>
      <el-form-item label="分类" required>
        <el-select v-model="form.category" allow-create filterable style="width: 100%">
          <el-option v-for="category in categories" :key="category" :label="category" :value="category" />
        </el-select>
      </el-form-item>
      <el-form-item class="full-row" label="用途说明" required>
        <el-input v-model="form.description" type="textarea" :rows="2" maxlength="300" show-word-limit />
      </el-form-item>
      <el-form-item class="full-row" label="分析目标" required>
        <el-input v-model="form.analysisGoal" type="textarea" :rows="2" maxlength="500" show-word-limit />
      </el-form-item>
      <el-form-item label="触发词（逗号分隔）" required>
        <el-input v-model="form.triggers" placeholder="例如：战备状态, 装备完好" />
      </el-form-item>
      <el-form-item label="输入参数提示（逗号分隔）" required>
        <el-input v-model="form.inputHints" placeholder="例如：时间范围, 区域, 单位" />
      </el-form-item>
      <el-form-item class="full-row" label="推荐问题（每行一个）" required>
        <el-input v-model="form.recommendedQuestions" type="textarea" :rows="2" />
      </el-form-item>
      <el-form-item class="full-row" label="执行步骤（每行一个，至少 2 步）" required>
        <el-input v-model="form.steps" type="textarea" :rows="3" />
      </el-form-item>
      <el-form-item label="数据源（逗号分隔）" required>
        <el-input v-model="form.dataSources" placeholder="例如：t_equipment, indicator" />
      </el-form-item>
      <el-form-item label="重点指标（逗号分隔）" required>
        <el-input v-model="form.focusMetrics" />
      </el-form-item>
      <el-form-item label="图表类型" required>
        <el-select v-model="form.chartTypes" multiple style="width: 100%">
          <el-option v-for="type in chartOptions" :key="type" :label="type" :value="type" />
        </el-select>
      </el-form-item>
      <el-form-item label="地图图层" required>
        <el-select v-model="form.mapLayerTypes" multiple style="width: 100%">
          <el-option v-for="type in mapOptions" :key="type" :label="type" :value="type" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存草稿</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createSituationSkill, updateSituationSkill } from '@/services/situationSkills'
import type { SituationSkill } from '@/types/situationSkill'

const props = withDefaults(defineProps<{
  modelValue: boolean
  skill?: SituationSkill | null
  mode?: 'create' | 'edit' | 'copy'
  categories?: string[]
}>(), {
  skill: null,
  mode: 'create',
  categories: () => [],
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved', skill: SituationSkill): void
}>()

const chartOptions = ['bar', 'line', 'pie', 'radar', 'gauge', 'scatter', 'heatmap', 'relation', 'sankey', 'map']
const mapOptions = ['points', 'routes', 'areas', 'heatmap', 'coverage', 'clusters', 'flow']
const saving = ref(false)
const form = reactive({
  name: '', category: '综合态势', description: '', analysisGoal: '',
  triggers: '', recommendedQuestions: '', inputHints: '', steps: '',
  dataSources: '', focusMetrics: '', chartTypes: ['bar'] as string[], mapLayerTypes: ['points'] as string[],
})

const dialogTitle = computed(() => ({
  create: '新建自定义 Skill',
  edit: '编辑 Skill 草稿',
  copy: '复制为自定义 Skill',
}[props.mode]))

watch(
  () => [props.modelValue, props.skill?.id, props.mode] as const,
  ([open]) => {
    if (!open) return
    const skill = props.skill
    Object.assign(form, skill ? {
      name: props.mode === 'copy' ? `${skill.name}（副本）` : skill.name,
      category: skill.category,
      description: skill.description,
      analysisGoal: skill.analysisGoal,
      triggers: skill.triggers.join(', '),
      recommendedQuestions: skill.recommendedQuestions.join('\n'),
      inputHints: skill.inputHints.join(', '),
      steps: skill.steps.join('\n'),
      dataSources: skill.dataSources.join(', '),
      focusMetrics: skill.focusMetrics.join(', '),
      chartTypes: [...skill.chartTypes],
      mapLayerTypes: [...skill.mapLayerTypes],
    } : {
      name: '', category: '综合态势', description: '', analysisGoal: '',
      triggers: '', recommendedQuestions: '', inputHints: '',
      steps: '汇聚并校验相关数据\n计算关键指标并识别异常\n生成图表、地图和态势说明',
      dataSources: 'admin', focusMetrics: '', chartTypes: ['bar'], mapLayerTypes: ['points'],
    })
  },
  { immediate: true },
)

const splitComma = (value: string) => value.split(/[,，]/).map((item) => item.trim()).filter(Boolean)
const splitLines = (value: string) => value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean)

function definition() {
  return {
    name: form.name.trim(),
    category: form.category.trim(),
    description: form.description.trim(),
    analysisGoal: form.analysisGoal.trim(),
    triggers: splitComma(form.triggers),
    recommendedQuestions: splitLines(form.recommendedQuestions),
    inputHints: splitComma(form.inputHints),
    steps: splitLines(form.steps),
    dataSources: splitComma(form.dataSources),
    focusMetrics: splitComma(form.focusMetrics),
    chartTypes: [...form.chartTypes],
    mapLayerTypes: [...form.mapLayerTypes],
    featured: false,
  }
}

async function save() {
  const payload = definition()
  if (!payload.name || !payload.category || !payload.description || !payload.analysisGoal) {
    ElMessage.warning('请填写名称、分类、用途说明和分析目标')
    return
  }
  if (!payload.triggers.length || !payload.recommendedQuestions.length || !payload.inputHints.length
    || payload.steps.length < 2 || !payload.dataSources.length || !payload.focusMetrics.length
    || !payload.chartTypes.length || !payload.mapLayerTypes.length) {
    ElMessage.warning('请完整填写触发词、问题、参数、步骤、数据源、指标和输出类型')
    return
  }
  saving.value = true
  try {
    const skill = props.mode === 'edit' && props.skill
      ? await updateSituationSkill(props.skill.id, payload, props.skill.revision)
      : await createSituationSkill(payload)
    ElMessage.success('Skill 草稿已保存')
    emit('saved', skill)
    emit('update:modelValue', false)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || 'Skill 保存失败')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.skill-editor {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
  margin-top: 18px;
}
.full-row { grid-column: 1 / -1; }
@media (max-width: 640px) {
  .skill-editor { grid-template-columns: 1fr; }
  .full-row { grid-column: auto; }
}
</style>
