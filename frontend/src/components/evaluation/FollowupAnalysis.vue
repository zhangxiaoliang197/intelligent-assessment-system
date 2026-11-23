<template>
  <div v-if="ontologyId" class="followup-analysis">
    <div class="fa-head">
      <div class="fa-title">接下来可以继续</div>
      <div v-if="metricOptions.length > 1" class="fa-metric-pick">
        <span>溯源指标</span>
        <el-select v-model="traceMetricKey" size="small" style="width: 160px">
          <el-option v-for="m in metricOptions" :key="m.key" :label="m.name" :value="m.key" />
        </el-select>
      </div>
    </div>
    <div class="fa-cards">
      <button class="fa-card" :class="{ active: activeMode === 'trace' }" :disabled="loading" @click="askTrace">
        <span class="fa-card-name">数据溯源</span>
        <span class="fa-card-desc">查看该结果的本体口径、计算公式与数据来源</span>
      </button>
      <button class="fa-card" :class="{ active: activeMode === 'attribution' }" :disabled="loading" @click="askAttribution">
        <span class="fa-card-name">归因分析</span>
        <span class="fa-card-desc">基于动态本体推理，分析结果背后的具体原因</span>
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import api from '@/services/api'

const props = withDefaults(defineProps<{
  question: string
  ontologyId: string
  side?: string
  profile?: string
  metricKeys?: string[]
  metricOptions?: Array<{ key: string; name: string }>
  dimensions?: Record<string, string>
}>(), {
  side: 'red',
  profile: 'v1.2',
  metricKeys: () => [],
  metricOptions: () => [],
  dimensions: () => ({})
})

// 结果不在原消息里展开，而是交给父组件追加一条对话式回答
const emit = defineEmits<{ (e: 'answer', payload: any): void }>()

const activeMode = ref<'trace' | 'attribution' | ''>('')
const loading = ref(false)
const traceMetricKey = ref(props.metricKeys[0] || props.metricOptions[0]?.key || '')

// ── 请求溯源 / 归因，成功后把结果交给父组件以对话形式展示 ──
const request = async (mode: 'trace' | 'attribution') => {
  if (!props.ontologyId || loading.value) return
  activeMode.value = mode
  loading.value = true
  try {
    const res: any = await api.post(`/evaluation/${mode}`, {
      ontologyId: props.ontologyId,
      question: props.question,
      metricKey: mode === 'trace'
        ? (traceMetricKey.value || props.metricKeys[0] || '')
        : (props.metricKeys[0] || 'index'),
      side: props.side,
      profile: props.profile,
      dimensions: props.dimensions
    })
    emit('answer', { mode, detail: res.data })
  } catch (e: any) {
    ElMessage.error(e?.serverMessage || (mode === 'trace' ? '数据溯源失败' : '归因分析失败'))
  } finally {
    loading.value = false
  }
}

const askTrace = () => request('trace')
const askAttribution = () => request('attribution')
</script>

<style scoped>
.followup-analysis {
  min-width: 0;
  max-width: 100%;
  margin: 16px 0;
}

.fa-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.fa-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.fa-metric-pick {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #6b7280;
}

.fa-cards {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.fa-card {
  flex: 1 1 200px;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 10px 12px;
  text-align: left;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.fa-card:hover,
.fa-card.active {
  border-color: #3b82f6;
  box-shadow: 0 2px 8px rgba(59, 130, 246, 0.15);
}

.fa-card:disabled {
  cursor: progress;
  opacity: 0.7;
}

.fa-card-name {
  font-size: 13px;
  font-weight: 600;
  color: #1d4ed8;
}

.fa-card-desc {
  font-size: 12px;
  color: #6b7280;
}
</style>
