<template>
  <el-drawer
    :model-value="modelValue"
    size="min(920px, 96vw)"
    append-to-body
    destroy-on-close
    class="skill-operations-drawer"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div v-if="skill" class="drawer-heading">
        <div>
          <span>SKILL CONTROL CENTER</span>
          <h3>{{ skill.name }}</h3>
        </div>
        <div class="heading-tags">
          <el-tag :type="statusTagType(skill.status)" effect="light">{{ statusLabel(skill.status) }}</el-tag>
          <el-tag effect="plain">{{ visibilityLabel(skill.visibility) }}</el-tag>
          <el-tag v-if="skill.ownerName || skill.ownerId" type="info" effect="plain">
            {{ skill.ownerName || skill.ownerId }}
          </el-tag>
        </div>
      </div>
    </template>

    <div v-if="skill" class="drawer-body">
      <el-tabs v-model="activeTab" @tab-change="handleTabChange">
        <el-tab-pane label="运行保障" name="runtime">
          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>运行前检查</h4>
                <p>检查数据源绑定、步骤完整度和执行条件，确认后再正式运行。</p>
              </div>
              <el-button
                type="primary"
                plain
                :loading="preflightLoading"
                :disabled="!dataSourceId"
                @click="runPreflight"
              >
                开始检查
              </el-button>
            </div>
            <el-alert
              v-if="!dataSourceId"
              type="warning"
              show-icon
              :closable="false"
              title="请先在评估页面选择数据源，再进行运行前检查或单步试运行。"
            />
            <template v-if="preflightResult">
              <div class="preflight-summary">
                <el-progress
                  type="dashboard"
                  :width="92"
                  :percentage="preflightPercentage"
                  :status="preflightResult.runnable ? 'success' : 'warning'"
                />
                <div>
                  <strong>{{ preflightResult.runnable ? '可以运行' : '存在阻断项' }}</strong>
                  <span>
                    已匹配 {{ preflightResult.availability?.matchedSteps || 0 }}/{{ preflightResult.availability?.totalSteps || skill.stepCount }} 个数据步骤
                  </span>
                </div>
              </div>
              <div class="check-list">
                <div v-for="check in preflightResult.checks" :key="check.code" class="check-item">
                  <el-icon :class="`check-${check.status}`">
                    <CircleCheck v-if="check.status === 'passed'" />
                    <WarningFilled v-else />
                  </el-icon>
                  <div>
                    <strong>{{ check.name }}</strong>
                    <span>{{ check.message || '检查完成' }}</span>
                  </div>
                </div>
              </div>
            </template>
          </section>

          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>单步试运行</h4>
                <p>只运行一个指定步骤，用于验证数据、问题表达和输出是否符合预期。</p>
              </div>
            </div>
            <el-form label-position="top">
              <div class="two-column-form">
                <el-form-item label="试运行步骤">
                  <el-select v-model="trialForm.stepId" placeholder="选择一个步骤">
                    <el-option
                      v-for="(step, index) in skill.steps"
                      :key="step.id"
                      :label="`${index + 1}. ${step.name}`"
                      :value="step.id"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="当前数据源">
                  <el-input :model-value="dataSourceId || '未选择'" disabled />
                </el-form-item>
              </div>
              <el-form-item label="测试问题">
                <el-input
                  v-model="trialForm.query"
                  type="textarea"
                  :rows="3"
                  maxlength="500"
                  show-word-limit
                  placeholder="输入只针对该步骤的测试问题"
                />
              </el-form-item>
              <el-button
                type="primary"
                :loading="trialLoading"
                :disabled="!dataSourceId"
                @click="runTrial"
              >
                运行选中步骤
              </el-button>
            </el-form>
            <div v-if="trialResult" class="result-panel">
              <div class="result-title">
                <strong>试运行结果</strong>
                <el-tag :type="executionTagType(trialResult.status)" size="small">
                  {{ executionStatusLabel(trialResult.status) }}
                </el-tag>
              </div>
              <el-descriptions :column="2" border size="small">
                <el-descriptions-item label="运行编号">{{ trialResult.runId || '-' }}</el-descriptions-item>
                <el-descriptions-item label="耗时">{{ formatDuration(trialResult.durationMs) }}</el-descriptions-item>
                <el-descriptions-item label="摘要" :span="2">
                  {{ trialResult.summary || stringifyResult(trialResult.result) || trialResult.error || '已完成，暂无摘要' }}
                </el-descriptions-item>
              </el-descriptions>
            </div>
          </section>

          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>执行记录</h4>
                <p>查看运行状态、版本、耗时与异常；运行中的任务可以请求取消。</p>
              </div>
              <el-button :icon="Refresh" :loading="executionsLoading" @click="loadExecutions">刷新</el-button>
            </div>
            <el-table v-loading="executionsLoading" :data="executions" empty-text="暂无执行记录">
              <el-table-column label="运行编号" min-width="145">
                <template #default="{ row }"><code>{{ compactId(row.runId) }}</code></template>
              </el-table-column>
              <el-table-column prop="query" label="问题" min-width="190" show-overflow-tooltip />
              <el-table-column label="状态" width="110">
                <template #default="{ row }">
                  <el-tag :type="executionTagType(row.status)" size="small">
                    {{ executionStatusLabel(row.status) }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="耗时" width="90">
                <template #default="{ row }">{{ formatDuration(row.durationMs) }}</template>
              </el-table-column>
              <el-table-column label="时间" width="165">
                <template #default="{ row }">{{ formatTime(row.startedAt || row.createdAt) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="isCancellable(row.status)"
                    text
                    type="danger"
                    :loading="cancellingRunId === row.runId"
                    @click="cancelExecution(row)"
                  >
                    取消
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="质量与运营" name="quality">
          <section class="quality-metrics" v-loading="qualityLoading">
            <div>
              <span>近 30 天运行</span>
              <strong>{{ qualityOverview?.runCount || 0 }}</strong>
            </div>
            <div>
              <span>成功率</span>
              <strong>{{ qualityOverview?.successRate || 0 }}%</strong>
            </div>
            <div>
              <span>平均质量分</span>
              <strong>{{ qualityOverview?.averageQualityScore || '-' }}</strong>
            </div>
            <div>
              <span>平均耗时</span>
              <strong>{{ formatDuration(qualityOverview?.averageDurationMs) }}</strong>
            </div>
            <div>
              <span>超时率</span>
              <strong>{{ qualityOverview?.timeoutRate || 0 }}%</strong>
            </div>
          </section>

          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>执行质量评测</h4>
                <p>从真实运行记录评估完成度、可靠性、数据覆盖、结论质量和性能。</p>
              </div>
              <el-button :icon="Refresh" :loading="qualityLoading" @click="loadQualityOverview">刷新指标</el-button>
            </div>
            <el-form label-position="top">
              <div class="two-column-form">
                <el-form-item label="选择已结束运行">
                  <el-select v-model="qualityRunId" filterable placeholder="选择运行记录">
                    <el-option
                      v-for="execution in qualityEligibleExecutions"
                      :key="execution.runId"
                      :label="`${compactId(execution.runId)} · ${executionStatusLabel(execution.status)} · ${execution.query || '无问题摘要'}`"
                      :value="execution.runId"
                    />
                  </el-select>
                </el-form-item>
                <el-form-item label="期望关键词（可选）">
                  <el-select
                    v-model="qualityKeywords"
                    multiple
                    filterable
                    allow-create
                    default-first-option
                    placeholder="输入结论应覆盖的指标或业务词"
                  />
                </el-form-item>
              </div>
              <el-button
                type="primary"
                :loading="qualityEvaluating"
                :disabled="!qualityRunId"
                @click="evaluateQuality"
              >
                开始质量评测
              </el-button>
            </el-form>
            <div v-if="qualityReport" class="quality-report">
              <div class="quality-score">
                <strong>{{ qualityReport.score }}</strong>
                <span>质量分 · {{ qualityReport.grade }} 级</span>
              </div>
              <div class="quality-dimensions">
                <div v-for="(dimension, name) in qualityReport.dimensions" :key="name">
                  <span>{{ qualityDimensionLabel(name) }}</span>
                  <el-progress
                    :percentage="dimension.maxScore ? Math.round(dimension.score / dimension.maxScore * 100) : 0"
                    :format="() => `${dimension.score}/${dimension.maxScore}`"
                  />
                </div>
              </div>
              <div v-if="qualityReport.issues.length" class="quality-findings">
                <strong>发现的问题</strong>
                <ul><li v-for="issue in qualityReport.issues" :key="issue">{{ issue }}</li></ul>
              </div>
              <div class="quality-findings suggestions">
                <strong>优化建议</strong>
                <ul><li v-for="suggestion in qualityReport.suggestions" :key="suggestion">{{ suggestion }}</li></ul>
              </div>
            </div>
          </section>

          <section class="operation-section">
            <div class="section-heading">
              <div><h4>最近质量报告</h4><p>同一运行重复评测会更新原报告，方便持续校准。</p></div>
            </div>
            <el-table :data="qualityOverview?.recentReports || []" empty-text="暂无质量报告">
              <el-table-column label="运行" width="145">
                <template #default="{ row }"><code>{{ compactId(row.runId) }}</code></template>
              </el-table-column>
              <el-table-column prop="score" label="得分" width="80" />
              <el-table-column prop="grade" label="等级" width="70" />
              <el-table-column label="主要问题" min-width="220" show-overflow-tooltip>
                <template #default="{ row }">{{ row.issues?.[0] || '未发现明显问题' }}</template>
              </el-table-column>
              <el-table-column label="评测时间" width="165">
                <template #default="{ row }">{{ formatTime(row.updatedAt || row.createdAt) }}</template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="发布与版本" name="versions">
          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>发布当前草稿</h4>
                <p>发布会生成不可变版本；历史版本可回滚为新的修订版本。</p>
              </div>
              <el-button
                v-if="skill.permissions.publish"
                type="primary"
                :loading="publishing"
                @click="publishSkill"
              >
                发布为 v{{ currentVersion + 1 }}
              </el-button>
            </div>
            <el-input
              v-model="publishNote"
              maxlength="300"
              show-word-limit
              placeholder="可选：说明本次发布的变化"
            />
          </section>
          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>版本历史</h4>
                <p>回滚不会删除历史记录，会从指定版本创建一个新修订。</p>
              </div>
              <el-button :icon="Refresh" :loading="versionsLoading" @click="loadVersions">刷新</el-button>
            </div>
            <el-table v-loading="versionsLoading" :data="versions" empty-text="暂无已保存版本">
              <el-table-column label="版本" width="90">
                <template #default="{ row }"><strong>v{{ row.version }}</strong></template>
              </el-table-column>
              <el-table-column prop="changeNote" label="变更说明" min-width="220" show-overflow-tooltip />
              <el-table-column label="操作者" width="130">
                <template #default="{ row }">{{ row.createdByName || row.createdBy || '-' }}</template>
              </el-table-column>
              <el-table-column label="时间" width="170">
                <template #default="{ row }">{{ formatTime(row.publishedAt || row.createdAt) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="90" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="skill.permissions.publish && row.version !== currentVersion"
                    text
                    type="primary"
                    :loading="rollingBackVersion === row.version"
                    @click="rollbackVersion(row)"
                  >
                    回滚
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="定时运行" name="schedules">
          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>创建定时任务</h4>
                <p>Cron 使用“分 时 日 月 周”，例如每天 08:00 为 <code>0 8 * * *</code>。</p>
              </div>
            </div>
            <el-form label-position="top">
              <div class="two-column-form">
                <el-form-item label="任务名称"><el-input v-model="scheduleForm.name" /></el-form-item>
                <el-form-item label="Cron 表达式"><el-input v-model="scheduleForm.cron" /></el-form-item>
              </div>
              <el-form-item label="评估问题">
                <el-input v-model="scheduleForm.query" type="textarea" :rows="2" maxlength="500" />
              </el-form-item>
              <el-button
                type="primary"
                :loading="scheduleSaving"
                :disabled="!dataSourceId || !skill.permissions.manageSchedule"
                @click="createSchedule"
              >
                保存定时任务
              </el-button>
            </el-form>
          </section>
          <section class="operation-section">
            <div class="section-heading">
              <div><h4>任务列表</h4><p>停用任务会保留配置，但不会触发下一次运行。</p></div>
              <el-button :icon="Refresh" :loading="schedulesLoading" @click="loadSchedules">刷新</el-button>
            </div>
            <el-table v-loading="schedulesLoading" :data="schedules" empty-text="暂无定时任务">
              <el-table-column prop="name" label="名称" min-width="150" />
              <el-table-column prop="cron" label="Cron" width="130" />
              <el-table-column label="下次运行" width="165">
                <template #default="{ row }">{{ formatTime(row.nextRunAt) }}</template>
              </el-table-column>
              <el-table-column label="启用" width="80">
                <template #default="{ row }">
                  <el-switch :model-value="row.enabled" @change="toggleSchedule(row, Boolean($event))" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="{ row }">
                  <el-button text type="danger" @click="removeSchedule(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="批量评估" name="batches">
          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>创建批量任务</h4>
                <p>每行一个评估问题，使用相同 Skill 和数据源运行，便于横向复核。</p>
              </div>
            </div>
            <el-form label-position="top">
              <el-form-item label="批次名称"><el-input v-model="batchForm.name" /></el-form-item>
              <el-form-item label="评估问题">
                <el-input
                  v-model="batchForm.queries"
                  type="textarea"
                  :rows="6"
                  placeholder="问题一&#10;问题二&#10;问题三"
                />
              </el-form-item>
              <el-button type="primary" :loading="batchCreating" :disabled="!dataSourceId" @click="createBatch">
                创建批量评估
              </el-button>
            </el-form>
          </section>
          <section class="operation-section">
            <div class="section-heading">
              <div><h4>批次记录</h4><p>显示任务完成度和失败数量。</p></div>
              <el-button :icon="Refresh" :loading="batchesLoading" @click="loadBatches">刷新</el-button>
            </div>
            <el-table v-loading="batchesLoading" :data="batches" empty-text="暂无批量任务">
              <el-table-column prop="name" label="批次" min-width="180" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">
                  <el-tag :type="executionTagType(row.status)" size="small">{{ executionStatusLabel(row.status) }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="进度" min-width="180">
                <template #default="{ row }">
                  <el-progress :percentage="row.total ? Math.round(row.completed / row.total * 100) : 0" />
                </template>
              </el-table-column>
              <el-table-column prop="failed" label="失败" width="80" />
              <el-table-column label="创建时间" width="165">
                <template #default="{ row }">{{ formatTime(row.createdAt) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="80" fixed="right">
                <template #default="{ row }">
                  <el-button
                    v-if="isCancellable(row.status)"
                    text
                    type="danger"
                    :loading="cancellingBatchId === row.id"
                    @click="cancelBatch(row)"
                  >
                    取消
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>

        <el-tab-pane label="结果对比" name="compare">
          <section class="operation-section">
            <div class="section-heading">
              <div>
                <h4>选择运行结果</h4>
                <p>选择 2 至 6 条执行记录，对比状态、版本、耗时、摘要和服务端指标。</p>
              </div>
              <el-button :icon="Refresh" :loading="executionsLoading" @click="loadExecutions">刷新记录</el-button>
            </div>
            <el-select
              v-model="compareRunIds"
              multiple
              filterable
              collapse-tags
              :multiple-limit="6"
              class="run-selector"
              placeholder="选择至少两条执行记录"
            >
              <el-option
                v-for="execution in executions"
                :key="execution.runId"
                :label="`${compactId(execution.runId)} · ${executionStatusLabel(execution.status)} · ${execution.query || '无问题摘要'}`"
                :value="execution.runId"
              />
            </el-select>
            <el-button type="primary" :loading="comparing" @click="compareExecutions">开始对比</el-button>
          </section>
          <section v-if="comparison" class="operation-section comparison-section">
            <div class="section-heading"><div><h4>对比结果</h4><p>相同指标按列对齐展示。</p></div></div>
            <el-table :data="comparison.items" border>
              <el-table-column label="运行" min-width="130">
                <template #default="{ row }"><code>{{ compactId(row.runId) }}</code></template>
              </el-table-column>
              <el-table-column prop="skillVersion" label="版本" width="80" />
              <el-table-column label="状态" width="100">
                <template #default="{ row }">{{ executionStatusLabel(row.status) }}</template>
              </el-table-column>
              <el-table-column label="耗时" width="100">
                <template #default="{ row }">{{ formatDuration(row.durationMs) }}</template>
              </el-table-column>
              <el-table-column prop="summary" label="摘要" min-width="220" show-overflow-tooltip />
              <el-table-column
                v-for="metric in comparisonMetricNames"
                :key="metric"
                :label="metric"
                min-width="110"
              >
                <template #default="{ row }">{{ row.metrics?.[metric] ?? '-' }}</template>
              </el-table-column>
            </el-table>
          </section>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { CircleCheck, Refresh, WarningFilled } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cancelSkillBatch,
  cancelSkillExecution,
  compareSkillExecutions,
  createSkillBatch,
  createSkillSchedule,
  deleteSkillSchedule,
  evaluateSkillExecutionQuality,
  getSkillQualityOverview,
  listEvaluationSkillVersions,
  listSkillBatches,
  listSkillExecutions,
  listSkillSchedules,
  preflightEvaluationSkill,
  publishEvaluationSkill,
  rollbackEvaluationSkill,
  trialEvaluationSkillStep,
  updateSkillSchedule
} from '@/services/evaluationSkills'
import type {
  EvaluationSkill,
  EvaluationSkillStatus,
  EvaluationSkillVisibility,
  SkillBatch,
  SkillExecution,
  SkillExecutionComparison,
  SkillExecutionStatus,
  SkillPreflightResult,
  SkillQualityOverview,
  SkillQualityReport,
  SkillSchedule,
  SkillVersion
} from '@/types/evaluationSkill'

const props = withDefaults(defineProps<{
  modelValue: boolean
  skill?: EvaluationSkill | null
  dataSourceId?: string
  initialTab?: 'runtime' | 'quality' | 'versions' | 'schedules' | 'batches' | 'compare'
}>(), {
  skill: null,
  dataSourceId: '',
  initialTab: 'runtime'
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
  changed: []
}>()

const activeTab = ref(props.initialTab)
const preflightLoading = ref(false)
const preflightResult = ref<SkillPreflightResult | null>(null)
const trialLoading = ref(false)
const trialResult = ref<SkillExecution | null>(null)
const trialForm = reactive({ stepId: '', query: '' })
const executionsLoading = ref(false)
const executions = ref<SkillExecution[]>([])
const cancellingRunId = ref('')
const versionsLoading = ref(false)
const versions = ref<SkillVersion[]>([])
const publishNote = ref('')
const publishing = ref(false)
const rollingBackVersion = ref<number | null>(null)
const schedulesLoading = ref(false)
const scheduleSaving = ref(false)
const schedules = ref<SkillSchedule[]>([])
const scheduleForm = reactive({ name: '', cron: '0 8 * * *', query: '' })
const batchesLoading = ref(false)
const batchCreating = ref(false)
const cancellingBatchId = ref('')
const batches = ref<SkillBatch[]>([])
const batchForm = reactive({ name: '', queries: '' })
const compareRunIds = ref<string[]>([])
const comparing = ref(false)
const comparison = ref<SkillExecutionComparison | null>(null)
const qualityLoading = ref(false)
const qualityEvaluating = ref(false)
const qualityOverview = ref<SkillQualityOverview | null>(null)
const qualityReport = ref<SkillQualityReport | null>(null)
const qualityRunId = ref('')
const qualityKeywords = ref<string[]>([])

const preflightPercentage = computed(() => {
  const availability = preflightResult.value?.availability
  if (!availability?.totalSteps) return preflightResult.value?.runnable ? 100 : 0
  const raw = availability.completeness == null
    ? availability.matchedSteps / availability.totalSteps
    : availability.completeness
  return Math.round((raw <= 1 ? raw * 100 : raw))
})

const currentVersion = computed(() => Math.max(
  props.skill?.version || 1,
  ...versions.value.map(version => version.version)
))

const comparisonMetricNames = computed(() => {
  const names = comparison.value?.metricNames || []
  if (names.length) return names
  return Array.from(new Set(
    (comparison.value?.items || []).flatMap(item => Object.keys(item.metrics || {}))
  ))
})

const qualityEligibleExecutions = computed(() => executions.value.filter(
  execution => !['queued', 'running', 'cancellation_requested'].includes(execution.status)
))

const statusLabel = (status: EvaluationSkillStatus) => ({
  draft: '草稿',
  published: '已发布',
  disabled: '已停用',
  archived: '已归档'
})[status]

const statusTagType = (status: EvaluationSkillStatus) =>
  status === 'published' ? 'success' : status === 'archived' ? 'info' : 'warning'

const visibilityLabel = (visibility: EvaluationSkillVisibility) => ({
  private: '仅自己',
  team: '团队可见',
  public: '公开'
})[visibility]

const executionStatusLabel = (status?: SkillExecutionStatus) => ({
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  failed: '失败',
  error: '失败',
  cancelled: '已取消',
  timed_out: '已超时',
  partial: '部分完成',
  cancellation_requested: '取消中'
})[status || 'queued']

const executionTagType = (status: SkillExecutionStatus) => {
  if (status === 'completed') return 'success'
  if (['failed', 'error', 'cancelled', 'timed_out'].includes(status)) return 'danger'
  if (status === 'partial' || status === 'cancellation_requested') return 'warning'
  return 'info'
}

const compactId = (value: string) => value?.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value || '-'
const formatTime = (value?: string) => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const formatDuration = (value?: number) => value == null ? '-' : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(1)} s`
const stringifyResult = (value: unknown) => {
  if (value == null) return ''
  if (typeof value === 'string') return value
  try { return JSON.stringify(value).slice(0, 500) } catch { return String(value) }
}
const qualityDimensionLabel = (name: string) => ({
  completion: '完成度',
  reliability: '可靠性',
  dataCoverage: '数据覆盖',
  answerQuality: '结论质量',
  performance: '性能'
})[name] || name
const isCancellable = (status: SkillExecutionStatus) => ['queued', 'running'].includes(status)

const runPreflight = async () => {
  if (!props.skill || !props.dataSourceId || preflightLoading.value) return
  preflightLoading.value = true
  try {
    preflightResult.value = await preflightEvaluationSkill(props.skill.id, props.dataSourceId)
    ElMessage.success(preflightResult.value.runnable ? '运行前检查通过' : '检查完成，请先处理阻断项')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '运行前检查失败')
  } finally {
    preflightLoading.value = false
  }
}

const runTrial = async () => {
  if (!props.skill || !props.dataSourceId || trialLoading.value) return
  if (!trialForm.stepId || !trialForm.query.trim()) {
    ElMessage.warning('请选择步骤并填写测试问题')
    return
  }
  trialLoading.value = true
  trialResult.value = null
  try {
    trialResult.value = await trialEvaluationSkillStep(props.skill.id, {
      dataSourceId: props.dataSourceId,
      stepId: trialForm.stepId,
      query: trialForm.query.trim()
    })
    ElMessage.success('单步试运行已完成')
    await loadExecutions()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '单步试运行失败')
  } finally {
    trialLoading.value = false
  }
}

const loadExecutions = async () => {
  if (!props.skill || executionsLoading.value) return
  executionsLoading.value = true
  try {
    executions.value = (await listSkillExecutions({ skillId: props.skill.id, pageSize: 100 })).items
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '执行记录加载失败')
  } finally {
    executionsLoading.value = false
  }
}

const cancelExecution = async (execution: any) => {
  if (cancellingRunId.value) return
  cancellingRunId.value = execution.runId
  try {
    const result = await cancelSkillExecution(execution.runId)
    ElMessage.success(result.message || (result.accepted ? '已提交取消请求' : '任务当前无法取消'))
    await loadExecutions()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '取消执行失败')
  } finally {
    cancellingRunId.value = ''
  }
}

const loadVersions = async () => {
  if (!props.skill || versionsLoading.value) return
  versionsLoading.value = true
  try {
    versions.value = await listEvaluationSkillVersions(props.skill.id)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '版本历史加载失败')
  } finally {
    versionsLoading.value = false
  }
}

const publishSkill = async () => {
  if (!props.skill || publishing.value) return
  publishing.value = true
  try {
    await publishEvaluationSkill(props.skill.id, {
      expectedRevision: props.skill.revision,
      changeNote: publishNote.value.trim() || undefined
    })
    publishNote.value = ''
    ElMessage.success('Skill 已发布')
    emit('changed')
    await loadVersions()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || 'Skill 发布失败')
  } finally {
    publishing.value = false
  }
}

const rollbackVersion = async (version: any) => {
  if (!props.skill || rollingBackVersion.value != null) return
  try {
    await ElMessageBox.confirm(
      `确定从 v${version.version} 创建新的回滚版本吗？`,
      '回滚 Skill',
      { type: 'warning', confirmButtonText: '确认回滚', cancelButtonText: '取消' }
    )
  } catch { return }
  rollingBackVersion.value = version.version
  try {
    await rollbackEvaluationSkill(props.skill.id, {
      version: version.version,
      expectedRevision: props.skill.revision
    })
    ElMessage.success(`已回滚到 v${version.version}`)
    emit('changed')
    await loadVersions()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '版本回滚失败')
  } finally {
    rollingBackVersion.value = null
  }
}

const loadSchedules = async () => {
  if (!props.skill || schedulesLoading.value) return
  schedulesLoading.value = true
  try {
    schedules.value = await listSkillSchedules(props.skill.id)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '定时任务加载失败')
  } finally {
    schedulesLoading.value = false
  }
}

const createSchedule = async () => {
  if (!props.skill || !props.dataSourceId || scheduleSaving.value) return
  if (!scheduleForm.name.trim() || !scheduleForm.cron.trim() || !scheduleForm.query.trim()) {
    ElMessage.warning('请完整填写任务名称、Cron 和评估问题')
    return
  }
  scheduleSaving.value = true
  try {
    await createSkillSchedule({
      skillId: props.skill.id,
      name: scheduleForm.name.trim(),
      cron: scheduleForm.cron.trim(),
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || 'Asia/Shanghai',
      enabled: true,
      query: scheduleForm.query.trim(),
      dataSourceId: props.dataSourceId
    })
    scheduleForm.name = ''
    scheduleForm.query = ''
    ElMessage.success('定时任务已创建')
    await loadSchedules()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '定时任务创建失败')
  } finally {
    scheduleSaving.value = false
  }
}

const toggleSchedule = async (schedule: any, enabled: boolean) => {
  try {
    const updated = await updateSkillSchedule(schedule.id, { enabled })
    Object.assign(schedule, updated)
    ElMessage.success(enabled ? '定时任务已启用' : '定时任务已停用')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '定时任务更新失败')
  }
}

const removeSchedule = async (schedule: any) => {
  try {
    await ElMessageBox.confirm(`确定删除定时任务「${schedule.name}」吗？`, '删除定时任务', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await deleteSkillSchedule(schedule.id)
    ElMessage.success('定时任务已删除')
    await loadSchedules()
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.serverMessage || '定时任务删除失败')
  }
}

const loadBatches = async () => {
  if (!props.skill || batchesLoading.value) return
  batchesLoading.value = true
  try {
    batches.value = await listSkillBatches(props.skill.id)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '批量任务加载失败')
  } finally {
    batchesLoading.value = false
  }
}

const createBatch = async () => {
  if (!props.skill || !props.dataSourceId || batchCreating.value) return
  const queries = batchForm.queries.split(/\r?\n/).map(value => value.trim()).filter(Boolean)
  if (!batchForm.name.trim() || queries.length < 2) {
    ElMessage.warning('请填写批次名称，并至少输入两个评估问题')
    return
  }
  batchCreating.value = true
  try {
    await createSkillBatch({
      skillId: props.skill.id,
      name: batchForm.name.trim(),
      dataSourceId: props.dataSourceId,
      queries
    })
    batchForm.name = ''
    batchForm.queries = ''
    ElMessage.success('批量评估已创建')
    await loadBatches()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '批量评估创建失败')
  } finally {
    batchCreating.value = false
  }
}

const cancelBatch = async (batch: any) => {
  if (cancellingBatchId.value) return
  cancellingBatchId.value = batch.id
  try {
    const result = await cancelSkillBatch(batch.id)
    ElMessage.success(result.message || (result.accepted ? '已提交批量取消请求' : '批次当前无法取消'))
    await loadBatches()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '取消批量评估失败')
  } finally {
    cancellingBatchId.value = ''
  }
}

const compareExecutions = async () => {
  if (compareRunIds.value.length < 2) {
    ElMessage.warning('请选择至少两条执行记录')
    return
  }
  comparing.value = true
  try {
    comparison.value = await compareSkillExecutions(compareRunIds.value)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '结果对比失败')
  } finally {
    comparing.value = false
  }
}

const loadQualityOverview = async () => {
  if (!props.skill || qualityLoading.value) return
  qualityLoading.value = true
  try {
    const [overview] = await Promise.all([
      getSkillQualityOverview(props.skill.id, 30),
      executions.value.length ? Promise.resolve() : loadExecutions()
    ])
    qualityOverview.value = overview
    if (!qualityRunId.value && qualityEligibleExecutions.value.length) {
      qualityRunId.value = qualityEligibleExecutions.value[0].runId
    }
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '质量运营指标加载失败')
  } finally {
    qualityLoading.value = false
  }
}

const evaluateQuality = async () => {
  if (!qualityRunId.value || qualityEvaluating.value) return
  qualityEvaluating.value = true
  try {
    qualityReport.value = await evaluateSkillExecutionQuality(
      qualityRunId.value,
      qualityKeywords.value.map(value => value.trim()).filter(Boolean)
    )
    ElMessage.success(`质量评测完成：${qualityReport.value.score} 分（${qualityReport.value.grade} 级）`)
    await loadQualityOverview()
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '执行质量评测失败')
  } finally {
    qualityEvaluating.value = false
  }
}

const handleTabChange = (name: string | number) => {
  if (name === 'runtime' || name === 'compare') loadExecutions()
  if (name === 'quality') loadQualityOverview()
  if (name === 'versions') loadVersions()
  if (name === 'schedules') loadSchedules()
  if (name === 'batches') loadBatches()
}

watch(() => props.modelValue, open => {
  if (!open || !props.skill) return
  activeTab.value = props.initialTab
  preflightResult.value = null
  trialResult.value = null
  qualityReport.value = null
  qualityOverview.value = null
  qualityRunId.value = ''
  qualityKeywords.value = []
  trialForm.stepId = props.skill.steps[0]?.id || ''
  trialForm.query = props.skill.recommendedQuestions[0] || ''
  scheduleForm.query = props.skill.recommendedQuestions[0] || ''
  batchForm.name = `${props.skill.name}批量评估`
  handleTabChange(activeTab.value)
})
</script>

<style scoped>
.drawer-heading { width: 100%; display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; }
.drawer-heading span { color: var(--primary-500); font-size: 11px; font-weight: 700; letter-spacing: .12em; }
.drawer-heading h3 { margin: 4px 0 0; color: var(--text-primary); font-size: 21px; }
.heading-tags { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.drawer-body { padding: 0 4px 30px; }
.operation-section { margin: 18px 0; padding: 20px; border: 1px solid var(--border-normal); border-radius: var(--radius-xl); background: var(--bg-card); }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-heading h4 { margin: 0; color: var(--text-primary); font-size: 16px; }
.section-heading p { margin: 6px 0 0; color: var(--text-tertiary); font-size: 12px; line-height: 1.6; }
.section-heading code { padding: 2px 5px; border-radius: 4px; background: var(--bg-hover); }
.two-column-form { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.two-column-form :deep(.el-select), .run-selector { width: 100%; }
.preflight-summary { display: flex; align-items: center; gap: 18px; margin-top: 18px; padding: 14px 18px; border-radius: var(--radius-lg); background: var(--bg-hover); }
.preflight-summary > div:last-child { display: flex; flex-direction: column; gap: 5px; }
.preflight-summary strong { color: var(--text-primary); font-size: 17px; }
.preflight-summary span { color: var(--text-tertiary); font-size: 12px; }
.check-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
.check-item { display: flex; align-items: flex-start; gap: 9px; padding: 11px; border: 1px solid var(--border-light); border-radius: var(--radius-md); }
.check-item > div { display: flex; flex-direction: column; gap: 3px; }
.check-item strong { color: var(--text-secondary); font-size: 12px; }
.check-item span { color: var(--text-muted); font-size: 11px; line-height: 1.5; }
.check-passed { color: #10b981; }
.check-warning { color: #f59e0b; }
.check-failed { color: #ef4444; }
.result-panel { margin-top: 16px; padding: 14px; border: 1px solid #bfdbfe; border-radius: var(--radius-lg); background: #f8fbff; }
.result-title { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.result-title strong { color: var(--text-primary); }
.run-selector { margin-bottom: 14px; }
.comparison-section { overflow-x: auto; }
.quality-metrics { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin: 18px 0; }
.quality-metrics > div { display: flex; flex-direction: column; gap: 7px; padding: 15px; border: 1px solid #dbeafe; border-radius: var(--radius-lg); background: linear-gradient(145deg, #f8fbff, #f5f3ff); }
.quality-metrics span { color: var(--text-muted); font-size: 11px; }
.quality-metrics strong { color: var(--text-primary); font-size: 21px; }
.quality-report { display: grid; grid-template-columns: 130px 1fr; gap: 18px; margin-top: 18px; padding: 18px; border: 1px solid #c7d2fe; border-radius: var(--radius-lg); background: #f8faff; }
.quality-score { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 110px; border-radius: var(--radius-lg); color: white; background: linear-gradient(145deg, #4f46e5, #7c3aed); }
.quality-score strong { font-size: 36px; line-height: 1; }
.quality-score span { margin-top: 9px; font-size: 11px; }
.quality-dimensions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 18px; }
.quality-dimensions > div > span { display: block; margin-bottom: 5px; color: var(--text-secondary); font-size: 12px; }
.quality-findings { grid-column: 1 / -1; padding: 12px 14px; border-radius: var(--radius-md); background: #fff7ed; }
.quality-findings.suggestions { background: #ecfdf5; }
.quality-findings strong { color: var(--text-secondary); font-size: 12px; }
.quality-findings ul { margin: 7px 0 0; padding-left: 18px; color: var(--text-tertiary); font-size: 12px; line-height: 1.7; }
code { color: var(--primary-600); font-size: 11px; }

@media (max-width: 720px) {
  .drawer-heading { align-items: flex-start; flex-direction: column; gap: 10px; }
  .heading-tags { justify-content: flex-start; }
  .operation-section { padding: 15px 12px; }
  .section-heading { flex-direction: column; }
  .two-column-form, .check-list { grid-template-columns: 1fr; }
  .quality-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .quality-report, .quality-dimensions { grid-template-columns: 1fr; }
}
</style>
