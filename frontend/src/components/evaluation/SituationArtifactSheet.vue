<template>
  <!-- 评估产物 → 态势页面：内联在评估结果之后的选择区（非强制、不弹层） -->
  <section class="artifact-panel">
    <div class="panel-head">
      <div class="panel-title">
        <span class="panel-title-main">态势分析</span>
        <span class="panel-title-sub">按需勾选要用于生成态势页面的内容，不生成也可以直接忽略</span>
      </div>
      <el-button text size="small" :disabled="loading" @click="close">收起</el-button>
    </div>

    <div class="panel-body">
      <!-- ── 评估结论 ── -->
      <div v-if="conclusion" class="panel-card">
        <div class="card-head">
          <el-checkbox v-model="includeConclusion" :disabled="loading">综合评估结论</el-checkbox>
          <el-button text size="small" @click="showConclusion = !showConclusion">
            {{ showConclusion ? '收起' : '预览' }}
          </el-button>
        </div>
        <p v-if="!showConclusion" class="conclusion-preview">{{ conclusionPreview }}</p>
        <p v-else class="conclusion-full">{{ conclusion }}</p>
      </div>

      <!-- ── 数据产物 ── -->
      <div class="panel-card">
        <div class="card-head">
          <span class="card-title">评估产物</span>
          <span class="card-meta">已选 {{ selectedIds.length }} / {{ items.length }} 项</span>
        </div>
        <el-empty
          v-if="!items.length"
          description="本次评估没有可用于态势页面的数据产物"
          :image-size="46"
        />
        <el-checkbox-group
          v-else
          v-model="selectedIds"
          class="artifact-list"
          :disabled="loading"
        >
          <el-checkbox
            v-for="item in items"
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
              <div v-if="item.purpose" class="artifact-purpose">{{ item.purpose }}</div>
            </div>
          </el-checkbox>
        </el-checkbox-group>
        <p class="card-tip">执行失败或没有返回数据的步骤不会出现在此处。</p>
      </div>

      <!-- ── 呈现区块 + 页面标题 ── -->
      <div class="panel-card">
        <div class="card-head">
          <span class="card-title">呈现区块</span>
        </div>
        <div class="presentation-row">
          <el-checkbox v-model="presentation.kpi" :disabled="loading">KPI 指标</el-checkbox>
          <el-checkbox v-model="presentation.chart" :disabled="loading">图表</el-checkbox>
          <el-checkbox v-model="presentation.map" :disabled="loading">地图</el-checkbox>
          <el-checkbox v-model="presentation.table" :disabled="loading">明细表</el-checkbox>
        </div>
        <div class="title-row">
          <span class="title-label">页面标题</span>
          <el-input
            v-model="title"
            size="small"
            maxlength="60"
            placeholder="评估态势分析"
            :disabled="loading"
          />
        </div>
      </div>
    </div>

    <div class="panel-foot">
      <span class="foot-tip">
        {{ selectedIds.length ? `将基于 ${selectedIds.length} 项评估产物生成态势页面` : '请至少勾选一项数据产物' }}
      </span>
      <div class="foot-actions">
        <el-button size="small" :disabled="loading" @click="close">暂时不用</el-button>
        <el-button
          size="small"
          type="primary"
          :loading="loading"
          :disabled="!canSubmit"
          @click="onConfirm"
        >生成态势页面</el-button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
// ── 评估分析 → 态势页面：结果卡下方的内联产物选择区 ──
// 只负责展示与选择，不发请求；确认后把归一化后的 payload 交给评估页发起生成。
import { computed, ref, watch } from 'vue'
import {
  buildArtifactPayload,
  defaultSelectedIds,
  itemCapabilities,
  normalizeEvaluationResult,
  type ArtifactContext,
  type EvaluationArtifactItem,
  type EvaluationArtifactPayload,
} from '@/utils/evaluationArtifacts'

const props = withDefaults(defineProps<{
  /** 本轮评估的 result */
  result: any
  /** 评估上下文（问题、数据源、技能） */
  context: ArtifactContext
  /** 生成请求进行中 */
  loading?: boolean
}>(), {
  loading: false,
})

const emit = defineEmits<{
  confirm: [EvaluationArtifactPayload]
  cancel: []
}>()

const items = ref<EvaluationArtifactItem[]>([])
const conclusion = ref('')
const selectedIds = ref<string[]>([])
const includeConclusion = ref(false)
const showConclusion = ref(false)
const title = ref('')
const presentation = ref({ kpi: true, chart: true, map: true, table: false })

const conclusionPreview = computed(() => {
  const text = conclusion.value.replace(/\s+/g, ' ').trim()
  return text.length > 120 ? `${text.slice(0, 120)}…` : text
})

const canSubmit = computed(() => selectedIds.value.length > 0)

/** 产物能力（图表/地图/明细） */
function capabilities(item: EvaluationArtifactItem) {
  return itemCapabilities(item)
}

/** 展开时初始化选择（默认全选数据项、勾选结论、图表与地图开启、明细关闭） */
function initSelection() {
  const normalized = normalizeEvaluationResult(props.result, props.context)
  items.value = normalized.items
  conclusion.value = normalized.conclusion
  selectedIds.value = defaultSelectedIds(normalized.items)
  includeConclusion.value = !!normalized.conclusion
  presentation.value = { kpi: true, chart: true, map: true, table: false }
  title.value = props.context.skillName
    ? `${props.context.skillName} · 态势分析`
    : '评估态势分析'
  showConclusion.value = false
}

function close() {
  emit('cancel')
}

function onConfirm() {
  if (!canSubmit.value) return
  emit('confirm', buildArtifactPayload(props.result, props.context, {
    itemIds: selectedIds.value,
    includeConclusion: includeConclusion.value,
    presentation: presentation.value,
    title: title.value.trim(),
  }))
}

watch(
  () => [props.result, props.context.skillName, props.context.question],
  () => initSelection(),
  { immediate: true },
)
</script>

<style scoped>
/* ── 内联选择区：跟在评估结果之后，不遮挡页面 ── */
.artifact-panel {
  margin-top: 12px;
  border: 1px solid var(--border-light);
  border-radius: 10px;
  background: #fff;
  overflow: hidden;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 14px;
  background: var(--gray-50);
  border-bottom: 1px solid var(--border-light);
}
.panel-title { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.panel-title-main { font-size: 13.5px; font-weight: 600; color: var(--text-primary); }
.panel-title-sub { font-size: 11.5px; color: var(--text-muted); }

.panel-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px 14px;
}
.panel-card {
  background: var(--gray-50);
  border: 1px solid var(--border-light);
  border-radius: 8px;
  padding: 8px 10px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 6px;
}
.card-title { font-size: 12.5px; font-weight: 600; color: var(--text-primary); }
.card-meta { font-size: 11.5px; color: var(--text-muted); }
.card-tip { margin: 6px 0 0; font-size: 11px; color: var(--text-muted); }

.conclusion-preview { margin: 0; font-size: 12px; line-height: 1.7; color: var(--text-secondary); }
.conclusion-full {
  margin: 0;
  max-height: 140px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.8;
  color: var(--text-secondary);
  white-space: pre-wrap;
}

/* ── 产物列表：多列排布，避免纵向拉太长 ── */
.artifact-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 2px 16px;
}
.artifact-item { width: 100%; height: auto; margin-right: 0; padding: 5px 0; align-items: flex-start; }
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

/* ── 呈现区块与标题 ── */
.presentation-row { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 18px; }
.title-row { display: flex; align-items: center; gap: 10px; margin-top: 8px; }
.title-label { flex: none; font-size: 12px; color: var(--text-secondary); }
.title-row :deep(.el-input) { max-width: 320px; }

/* ── 底部操作 ── */
.panel-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 8px 14px;
  border-top: 1px solid var(--border-light);
  background: #fff;
}
.foot-tip { font-size: 11.5px; color: var(--text-muted); }
.foot-actions { display: flex; gap: 8px; }
</style>
