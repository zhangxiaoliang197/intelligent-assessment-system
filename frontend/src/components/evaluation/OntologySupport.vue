<template>
  <div v-if="ontologyId" class="ontology-support">
    <div class="os-head">
      <div class="os-head-left">
        <span class="os-badge">动态本体理解</span>
        <span class="os-ontology">{{ mapping?.ontology?.name || '评估本体' }}</span>
        <el-tag v-if="mapping?.battle" size="small" type="danger" effect="plain">
          {{ mapping.battle.name }}
        </el-tag>
      </div>
      <div class="os-head-right">
        <span v-if="mapping?.profile" class="os-profile">{{ mapping.profile.name }}</span>
        <el-button link size="small" :icon="Refresh" :loading="loading" @click="loadAll">重新识别</el-button>
      </div>
    </div>

    <el-skeleton v-if="loading" :rows="2" animated />

    <template v-else>
      <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />

      <div v-if="metrics.length" class="os-sentence">
        按
        <template v-for="(item, idx) in dimSummary" :key="item.name">
          <span class="os-chip">{{ item.name }}：{{ item.value }}</span>
          <span v-if="idx < dimSummary.length - 1" class="os-sep">·</span>
        </template>
        口径，计算
        <span class="os-metrics-text">{{ metricsText }}</span>
      </div>
      <div v-else class="os-empty">未识别到评估指标，将直接按数据库问答处理。</div>

      <div class="os-actions">
        <el-button type="primary" size="small" :icon="Check" @click="confirmAndStart">
          按此口径开始评估
        </el-button>
        <el-button v-if="metrics.length" link size="small" @click="showAdjust = !showAdjust">
          {{ showAdjust ? '收起调整' : '调整口径' }}
        </el-button>
      </div>

      <div v-if="showAdjust" class="os-adjust">
        <div class="os-adjust-row">
          <span class="os-adjust-label">指标</span>
          <el-select
            v-model="selectedMetricKeys"
            multiple
            collapse-tags
            size="small"
            class="os-adjust-control"
            placeholder="选择评估指标"
          >
            <el-option v-for="c in catalog" :key="c.key" :label="c.name" :value="c.key" />
          </el-select>
        </div>
        <div v-for="item in adjustableDims" :key="item.name" class="os-adjust-row">
          <span class="os-adjust-label">{{ item.name }}</span>
          <el-select v-model="dimValues[item.name]" size="small" class="os-adjust-control">
            <el-option v-for="value in dimensionOptions(item)" :key="value" :label="value" :value="value" />
          </el-select>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { Check, Refresh } from '@element-plus/icons-vue'
import api from '@/services/api'

const props = withDefaults(defineProps<{
  question: string
  ontologyId: string
  side?: string
  profile?: string
}>(), { side: 'red', profile: 'v1.2' })

const emit = defineEmits<{
  (event: 'confirm', payload: any): void
}>()

const loading = ref(false)
const error = ref('')
const mapping = ref<any>(null)
const catalog = ref<any[]>([])
const metrics = ref<any[]>([])
const clarify = ref<any>(null)
const dimValues = reactive<Record<string, string>>({})
const selectedMetricKeys = ref<string[]>([])
const showAdjust = ref(false)
let autoConfirmed = false

const metricsText = computed(() =>
  metrics.value.map(item => item.name || item.matchedTerm || item.key).join('、')
)

const adjustableDims = computed(() => [
  ...(clarify.value?.required || []),
  ...(clarify.value?.optional || [])
])

const dimSummary = computed(() => {
  const items: Array<{ name: string; value: string }> = []
  for (const item of adjustableDims.value) {
    const value = dimValues[item.name] || item.detected || item.default || ''
    if (value) items.push({ name: item.name, value })
  }
  return items
})

const dimensionOptions = (item: any) => {
  return Array.from(new Set(
    [item.detected, item.default, ...(item.values || [])].filter(Boolean)
  ))
}

const buildDimensions = () => {
  const dims: Record<string, string> = {}
  for (const item of clarify.value?.resolved || []) {
    if (item.detected) dims[item.name] = item.detected
  }
  for (const item of adjustableDims.value) {
    const value = dimValues[item.name]
    if (value) dims[item.name] = value
  }
  return dims
}

const sideFromDimensions = () => {
  const side = dimValues['阵营'] || ''
  if (side.includes('蓝')) return 'blue'
  return 'red'
}

const confirmAndStart = () => {
  emit('confirm', {
    question: props.question,
    ontologyId: props.ontologyId,
    metricKeys: selectedMetricKeys.value.slice(),
    metricOptions: catalog.value
      .filter(item => selectedMetricKeys.value.includes(item.key))
      .map(item => ({ key: item.key, name: item.name })),
    dimensions: buildDimensions(),
    profile: dimValues['口径版本'] || mapping.value?.profile?.key || props.profile,
    side: sideFromDimensions()
  })
}

const loadClarify = async () => {
  if (!props.ontologyId) return
  try {
    const res: any = await api.post('/evaluation/clarify', {
      ontologyId: props.ontologyId,
      question: props.question,
      metricKeys: selectedMetricKeys.value
    })
    clarify.value = res.data
    for (const key of Object.keys(dimValues)) delete dimValues[key]
    for (const item of [...(res.data?.required || []), ...(res.data?.optional || [])]) {
      dimValues[item.name] = item.detected || item.default || ''
    }
  } catch (e) {
    clarify.value = null
  }
}

const loadAll = async () => {
  if (!props.ontologyId) return
  loading.value = true
  error.value = ''
  autoConfirmed = false
  showAdjust.value = false
  try {
    const res: any = await api.post('/evaluation/semantic-map', {
      ontologyId: props.ontologyId,
      question: props.question,
      side: props.side,
      profile: props.profile
    })
    mapping.value = res.data
    catalog.value = res.data?.catalog || []
    metrics.value = (res.data?.metrics || []).map((item: any) => ({ ...item }))
    selectedMetricKeys.value = metrics.value.map(item => item.key)
    await loadClarify()
    // 没有命中任何本体指标时无需确认口径，直接进入数据库问答
    if (!metrics.value.length && !autoConfirmed) {
      autoConfirmed = true
      emit('confirm', {
        question: props.question,
        ontologyId: props.ontologyId,
        metricKeys: [],
        metricOptions: [],
        dimensions: buildDimensions(),
        profile: dimValues['口径版本'] || mapping.value?.profile?.key || props.profile,
        side: sideFromDimensions(),
        auto: true
      })
    }
  } catch (e: any) {
    error.value = e?.serverMessage || e?.message || '本体语义映射失败'
  } finally {
    loading.value = false
  }
}

watch(() => [props.question, props.ontologyId], loadAll, { immediate: true })
</script>

<style scoped>
.ontology-support {
  min-width: 0;
  max-width: 100%;
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
}

.os-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.os-head-left,
.os-head-right {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.os-badge {
  font-size: 12px;
  font-weight: 600;
  color: #1d4ed8;
}

.os-ontology {
  font-size: 13px;
  color: #111827;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.os-profile {
  font-size: 12px;
  color: #6b7280;
}

.os-sentence {
  font-size: 13px;
  line-height: 1.9;
  color: #1f2937;
}

.os-chip {
  display: inline-block;
  margin: 0 2px;
  padding: 1px 8px;
  border-radius: 999px;
  background: #e0edff;
  color: #1d4ed8;
  font-size: 12px;
}

.os-sep {
  color: #9ca3af;
}

.os-metrics-text {
  font-weight: 600;
  color: #111827;
}

.os-empty {
  font-size: 13px;
  color: #6b7280;
}

.os-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.os-adjust {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px dashed #dbeafe;
}

.os-adjust-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.os-adjust-label {
  flex: 0 0 72px;
  font-size: 12px;
  color: #6b7280;
}

.os-adjust-control {
  flex: 1;
  min-width: 0;
}
</style>
