<template>
  <!-- 评估分析 → 态势页面：多轮对话产物选择弹窗（从顶部入口打开，非强制、可关闭） -->
  <el-dialog
    v-model="visible"
    title="生成态势页面"
    width="min(920px, 94vw)"
    class="situation-artifact-dialog"
    :close-on-click-modal="false"
    append-to-body
  >
    <div class="dialog-intro">
      <span>可跨多轮评估对话挑选产物，确认后统一生成一张态势页面。</span>
      <span v-if="crossSource" class="intro-warn">当前选中轮次来自不同数据源，页面仅记录首个轮次的数据源用于溯源。</span>
    </div>

    <div class="round-list">
      <section
        v-for="entry in normalizedRounds"
        :key="entry.round.roundIndex"
        class="round-card"
        :class="{ empty: !entry.items.length }"
      >
        <header class="round-head">
          <div class="round-title">
            <span class="round-tag">第 {{ entry.round.roundIndex }} 轮</span>
            <span class="round-question" :title="entry.round.question">
              {{ entry.round.question || '未记录问题' }}
            </span>
            <el-tag v-if="entry.round.context.skillName" size="small" effect="plain">
              {{ entry.round.context.skillName }}
            </el-tag>
          </div>
          <el-checkbox
            v-if="entry.items.length"
            :model-value="isRoundAllSelected(entry)"
            :indeterminate="isRoundIndeterminate(entry)"
            :disabled="loading"
            @change="toggleRound(entry, $event)"
          >整轮勾选</el-checkbox>
        </header>

        <template v-if="entry.items.length">
          <el-checkbox-group
            v-model="selectedIds[entry.round.roundIndex]"
            class="artifact-list"
            :disabled="loading"
          >
            <el-checkbox
              v-for="item in entry.items"
              :key="item.artifactId"
              :value="item.artifactId"
              class="artifact-item"
            >
              <div class="artifact-main">
                <div class="artifact-name">{{ item.name }}</div>
                <div class="artifact-meta">
                  <span>{{ item.totalRows }} 行</span>
                  <el-tag v-if="capabilities(item).chart" size="small" type="success" effect="plain">图表可用</el-tag>
                  <el-tag v-if="capabilities(item).map" size="small" type="warning" effect="plain">地图可用</el-tag>
                  <el-tag v-if="item.truncated" size="small" type="info" effect="plain">已截断</el-tag>
                </div>
                <div v-if="item.purpose" class="artifact-purpose" :title="item.purpose">{{ item.purpose }}</div>
              </div>
            </el-checkbox>
          </el-checkbox-group>

          <div v-if="entry.conclusion" class="conclusion-row">
            <el-checkbox
              v-model="conclusionSelected[entry.round.roundIndex]"
              :disabled="loading"
            >带入本轮综合结论</el-checkbox>
            <el-button text size="small" @click="toggleConclusionPreview(entry.round.roundIndex)">
              {{ previewRounds.includes(entry.round.roundIndex) ? '收起' : '预览' }}
            </el-button>
          </div>
          <p v-if="previewRounds.includes(entry.round.roundIndex)" class="conclusion-text">
            {{ entry.conclusion }}
          </p>
        </template>

        <p v-else class="round-empty">该轮没有可用于态势页面的数据产物：{{ entry.reason }}</p>
      </section>
    </div>

    <div class="dialog-config">
      <div class="config-row">
        <span class="config-label">呈现区块</span>
        <div class="config-options">
          <el-checkbox v-model="presentation.kpi" :disabled="loading">KPI 指标</el-checkbox>
          <el-checkbox v-model="presentation.chart" :disabled="loading">图表</el-checkbox>
          <el-checkbox
            v-model="presentation.map"
            :disabled="loading || !mapAvailable"
            :title="mapAvailable ? '' : '当前勾选的产物没有坐标数据，地图不可用'"
          >地图</el-checkbox>
          <el-checkbox v-model="presentation.table" :disabled="loading">明细表</el-checkbox>
        </div>
      </div>
      <div class="config-row">
        <span class="config-label">页面标题</span>
        <el-input
          v-model="title"
          size="small"
          maxlength="60"
          placeholder="评估态势综合分析"
          :disabled="loading"
          @input="titleTouched = true"
        />
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <span class="footer-tip">
          已选 {{ selectedRoundCount }} 轮 / {{ selectedItemCount }} 项产物
        </span>
        <div class="footer-actions">
          <el-button :disabled="loading" @click="visible = false">暂时不用</el-button>
          <el-button
            type="primary"
            :loading="loading"
            :disabled="!canSubmit"
            @click="onConfirm"
          >生成态势页面</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// ── 评估分析 → 态势页面：多轮产物选择弹窗 ──
// 只负责展示与选择，不发请求；确认后把合并后的 payload 交给评估页发起生成。
import { computed, ref, watch } from 'vue'
import {
  buildMultiRoundPayload,
  defaultSelectedIds,
  describeNoArtifacts,
  itemCapabilities,
  normalizeEvaluationResult,
  type EvaluationArtifactItem,
  type EvaluationArtifactPayload,
  type EvaluationArtifactRound,
  type RoundSelection,
} from '@/utils/evaluationArtifacts'

const props = withDefaults(defineProps<{
  /** 控制弹窗显示（v-model） */
  modelValue: boolean
  /** 当前会话的多轮评估（按出现顺序编号） */
  rounds: EvaluationArtifactRound[]
  /** 生成请求进行中 */
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  'update:modelValue': [boolean]
  confirm: [EvaluationArtifactPayload]
}>()

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

/** 单轮归一化结果：可用产物、结论、无产物原因 */
interface NormalizedRound {
  round: EvaluationArtifactRound
  items: EvaluationArtifactItem[]
  conclusion: string
  reason: string
}

const normalizedRounds = computed<NormalizedRound[]>(() => props.rounds.map((round) => {
  const { items, conclusion } = normalizeEvaluationResult(round.result, round.context)
  const usable = items.filter((item) => item.rows.length > 0)
  return {
    round,
    items: usable,
    conclusion: conclusion.trim(),
    reason: usable.length ? '' : describeNoArtifacts(round.result),
  }
}))

/** 每轮勾选的产物 id（键为轮次序号） */
const selectedIds = ref<Record<number, string[]>>({})
/** 每轮结论是否带入（键为轮次序号） */
const conclusionSelected = ref<Record<number, boolean>>({})
/** 已展开结论预览的轮次 */
const previewRounds = ref<number[]>([])
const presentation = ref({ kpi: true, chart: true, map: true, table: false })
const title = ref('')
/** 用户是否手动改过标题（改过就不再被默认标题覆盖） */
const titleTouched = ref(false)

/** 勾选了产物的轮次 */
const selectedRounds = computed(() => normalizedRounds.value.filter(
  (entry) => (selectedIds.value[entry.round.roundIndex] || []).length > 0,
))

const selectedItemCount = computed(() => selectedRounds.value.reduce(
  (total, entry) => total + (selectedIds.value[entry.round.roundIndex] || []).length, 0,
))

const selectedRoundCount = computed(() => selectedRounds.value.length)

/** 已选产物中是否存在坐标产物，决定「地图」是否可选 */
const mapAvailable = computed(() => selectedRounds.value.some((entry) => (
  (selectedIds.value[entry.round.roundIndex] || []).some((id) => (
    entry.items.some((item) => item.artifactId === id && itemCapabilities(item).map)
  ))
)))

/** 选中轮次是否跨数据源（仅用于提示，不阻止生成） */
const crossSource = computed(() => {
  const ids = new Set(selectedRounds.value
    .map((entry) => entry.round.context.dataSourceId)
    .filter(Boolean))
  return ids.size > 1
})

/** 默认标题：选中轮次技能一致时带上技能名 */
const autoTitle = computed(() => {
  const names = new Set(selectedRounds.value
    .map((entry) => entry.round.context.skillName)
    .filter(Boolean))
  return names.size === 1 ? `${[...names][0]} · 态势综合分析` : '评估态势综合分析'
})

const canSubmit = computed(() => !props.loading && selectedItemCount.value > 0)

/** 产物能力（图表/地图/明细） */
function capabilities(item: EvaluationArtifactItem) {
  return itemCapabilities(item)
}

/** 某轮是否全部可用产物都已勾选 */
function isRoundAllSelected(entry: NormalizedRound): boolean {
  const selected = selectedIds.value[entry.round.roundIndex] || []
  return entry.items.length > 0 && selected.length === entry.items.length
}

/** 某轮是否部分勾选（用于半选态） */
function isRoundIndeterminate(entry: NormalizedRound): boolean {
  const selected = selectedIds.value[entry.round.roundIndex] || []
  return selected.length > 0 && selected.length < entry.items.length
}

/** 整轮勾选/取消：同时联动本轮结论 */
function toggleRound(entry: NormalizedRound, checked: unknown) {
  const index = entry.round.roundIndex
  const next = !!checked
  selectedIds.value[index] = next ? entry.items.map((item) => item.artifactId) : []
  conclusionSelected.value[index] = next && !!entry.conclusion
}

/** 展开/收起某轮结论预览 */
function toggleConclusionPreview(index: number) {
  previewRounds.value = previewRounds.value.includes(index)
    ? previewRounds.value.filter((item) => item !== index)
    : [...previewRounds.value, index]
}

/** 打开弹窗时重置为默认选择：可用轮次全选，结论默认勾选，地图按坐标可用性默认开启 */
function initSelection() {
  const ids: Record<number, string[]> = {}
  const conclusions: Record<number, boolean> = {}
  normalizedRounds.value.forEach((entry) => {
    ids[entry.round.roundIndex] = defaultSelectedIds(entry.items)
    conclusions[entry.round.roundIndex] = !!entry.conclusion
  })
  selectedIds.value = ids
  conclusionSelected.value = conclusions
  previewRounds.value = []
  presentation.value = {
    kpi: true,
    chart: true,
    map: normalizedRounds.value.some((entry) => entry.items.some(
      (item) => itemCapabilities(item).map,
    )),
    table: false,
  }
  titleTouched.value = false
  title.value = autoTitle.value
}

function onConfirm() {
  if (!canSubmit.value) return
  const selections: RoundSelection[] = selectedRounds.value.map((entry) => ({
    round: entry.round,
    itemIds: selectedIds.value[entry.round.roundIndex] || [],
    includeConclusion: !!conclusionSelected.value[entry.round.roundIndex],
  }))
  emit('confirm', buildMultiRoundPayload(selections, {
    title: title.value,
    presentation: { ...presentation.value, map: presentation.value.map && mapAvailable.value },
  }))
}

// 取消勾选最后一个坐标产物后，自动关闭地图区块
watch(mapAvailable, (available) => {
  if (!available && presentation.value.map) presentation.value.map = false
})

// 默认标题随选中轮次变化，用户手动改过则保持用户输入
watch(autoTitle, (value) => {
  if (!titleTouched.value) title.value = value
})

// 每次打开弹窗重新初始化，避免沿用上一次的勾选
watch(() => props.modelValue, (value) => {
  if (value) initSelection()
})

// 轮次数据变化（如新一轮评估完成）时同步重建默认选择，保证弹窗内容与勾选状态一致
watch(normalizedRounds, () => initSelection(), { immediate: true })
</script>

<style scoped>
/* ── 弹窗说明 ── */
.dialog-intro {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 10px;
  font-size: 12px;
  color: var(--text-muted);
}
.intro-warn { color: #b45309; }

/* ── 轮次列表 ── */
.round-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 52vh;
  overflow-y: auto;
  padding-right: 4px;
}
.round-card {
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: #fff;
  padding: 10px 12px;
}
.round-card.empty { background: var(--gray-50); }
.round-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.round-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
.round-tag {
  flex: none;
  padding: 1px 8px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4338ca;
  font-size: 11.5px;
  font-weight: 600;
}
.round-question {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
  font-weight: 600;
  color: var(--text-primary);
}
.round-empty { margin: 6px 0 0; font-size: 12px; color: var(--text-muted); }

/* ── 产物列表 ── */
.artifact-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 2px 16px;
  margin-top: 6px;
}
.artifact-item { width: 100%; height: auto; margin-right: 0; padding: 4px 0; align-items: flex-start; }
.artifact-item :deep(.el-checkbox__label) { width: 100%; min-width: 0; }
.artifact-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.artifact-name { font-size: 12.5px; font-weight: 500; color: var(--text-primary); }
.artifact-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; font-size: 11px; color: var(--text-muted); }
.artifact-purpose {
  font-size: 11px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 结论 ── */
.conclusion-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--border-light);
}
.conclusion-text {
  margin: 6px 0 0;
  max-height: 140px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

/* ── 全局配置 ── */
.dialog-config {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
  padding: 10px 12px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: var(--gray-50);
}
.config-row { display: flex; align-items: center; gap: 12px; }
.config-label { flex: none; font-size: 12px; color: var(--text-secondary); }
.config-options { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 18px; }
.config-row :deep(.el-input) { max-width: 320px; }

/* ── 底部操作 ── */
.dialog-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.footer-tip { font-size: 12px; color: var(--text-muted); }
.footer-actions { display: flex; gap: 8px; }
</style>
