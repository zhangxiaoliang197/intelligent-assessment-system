<template>
  <el-dialog
    :model-value="modelValue"
    :title="skill ? `配置「${skill.name}」` : 'Skill 参数配置'"
    width="620px"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template v-if="skill">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="参数会参与执行前检查，并随生成产物保存，便于复用和审计。"
      />

      <el-form class="parameter-form" label-position="top">
        <el-form-item
          v-for="parameter in skill.parameters || []"
          :key="parameter.key"
          :label="parameter.label"
          :required="parameter.required"
        >
          <el-input-number
            v-if="parameter.type === 'number'"
            v-model="draft[parameter.key]"
            :min="parameter.minimum"
            :max="parameter.maximum"
            controls-position="right"
            style="width: 100%"
          />
          <el-select
            v-else-if="parameter.type === 'select' || parameter.type === 'multiselect'"
            v-model="draft[parameter.key]"
            :multiple="parameter.type === 'multiselect'"
            clearable
            filterable
            :placeholder="parameter.placeholder"
            style="width: 100%"
          >
            <el-option v-for="option in parameter.options || []" :key="option" :label="option" :value="option" />
          </el-select>
          <el-input
            v-else
            v-model="draft[parameter.key]"
            clearable
            :placeholder="parameter.placeholder"
            maxlength="500"
            show-word-limit
          />
          <div v-if="parameter.description" class="parameter-help">{{ parameter.description }}</div>
        </el-form-item>
      </el-form>

      <el-empty
        v-if="!(skill.parameters || []).length"
        :image-size="70"
        description="此 Skill 无需额外参数，可直接执行前检查"
      />

      <div v-if="preflight" class="preflight-result">
        <div class="preflight-heading">
          <strong>执行前检查</strong>
          <el-tag :type="preflight.ready ? (preflight.complete ? 'success' : 'warning') : 'danger'">
            {{ preflight.ready ? (preflight.complete ? '全部通过' : '可执行，有提醒') : '检查未通过' }}
          </el-tag>
        </div>
        <div
          v-for="check in preflight.checks"
          :key="check.key"
          class="check-row"
          :class="`is-${check.status}`"
        >
          <el-icon><CircleCheck v-if="check.status === 'passed'" /><Warning v-else /></el-icon>
          <span><strong>{{ check.label }}</strong>：{{ check.message }}</span>
        </div>
      </div>
    </template>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button :loading="checking" @click="runPreflight">执行前检查</el-button>
      <el-button type="primary" @click="save">保存参数</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { CircleCheck, Warning } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { preflightSituationSkill } from '@/services/situationSkills'
import type { SituationSkill, SituationSkillPreflight } from '@/types/situationSkill'

const props = withDefaults(defineProps<{
  modelValue: boolean
  skill: SituationSkill | null
  parameters?: Record<string, unknown>
  query?: string
  dataSourceId?: string
}>(), {
  parameters: () => ({}),
  query: '',
  dataSourceId: '',
})

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'save', parameters: Record<string, unknown>, preflight?: SituationSkillPreflight): void
}>()

const draft = ref<Record<string, any>>({})
const checking = ref(false)
const preflight = ref<SituationSkillPreflight | null>(null)
const preflightFingerprint = ref('')

watch(
  () => [props.modelValue, props.skill?.id, props.parameters] as const,
  ([open]) => {
    if (!open) return
    draft.value = { ...props.parameters }
    preflight.value = null
    preflightFingerprint.value = ''
  },
  { immediate: true, deep: true },
)

watch(draft, () => {
  if (preflight.value && fingerprint() !== preflightFingerprint.value) {
    preflight.value = null
    preflightFingerprint.value = ''
  }
}, { deep: true })

function fingerprint() {
  return JSON.stringify({
    skillId: props.skill?.id || '',
    revision: props.skill?.revision || 0,
    query: props.query.trim(),
    dataSourceId: props.dataSourceId,
    parameters: normalizedParameters(),
  })
}

function normalizedParameters() {
  const allowed = new Set((props.skill?.parameters || []).map((parameter) => parameter.key))
  return Object.fromEntries(Object.entries(draft.value).filter(([key, value]) => (
    allowed.has(key) &&
    value !== undefined && value !== null && value !== '' && (!Array.isArray(value) || value.length)
  )))
}

async function runPreflight() {
  if (!props.skill) return
  checking.value = true
  try {
    preflight.value = await preflightSituationSkill(
      props.skill.id,
      props.query || props.skill.recommendedQuestions?.[0] || '',
      normalizedParameters(),
      props.dataSourceId,
    )
    preflightFingerprint.value = fingerprint()
    if (preflight.value.ready) {
      draft.value = { ...preflight.value.parameters }
      ElMessage.success(preflight.value.complete ? '执行前检查全部通过' : '检查通过，请留意数据源提醒')
    } else {
      ElMessage.error(preflight.value.errors.join('；') || '执行前检查未通过')
    }
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '执行前检查失败')
  } finally {
    checking.value = false
  }
}

function save() {
  emit('save', normalizedParameters(), preflightFingerprint.value === fingerprint() ? preflight.value || undefined : undefined)
  emit('update:modelValue', false)
}
</script>

<style scoped>
.parameter-form {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
  margin-top: 18px;
}
.parameter-help {
  margin-top: 4px;
  color: #909399;
  font-size: 12px;
}
.preflight-result {
  padding: 14px;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  background: #fafcff;
}
.preflight-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.check-row {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  padding: 5px 0;
  color: #606266;
  font-size: 12px;
  line-height: 1.45;
}
.check-row.is-passed { color: #529b2e; }
.check-row.is-warning { color: #b88230; }
.check-row.is-error { color: #c45656; }
@media (max-width: 640px) {
  .parameter-form { grid-template-columns: 1fr; }
}
</style>
