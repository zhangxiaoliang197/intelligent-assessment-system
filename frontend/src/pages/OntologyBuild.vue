<template>
  <Layout>
    <div class="ontology-build">
      <!-- 顶部 Header -->
      <div class="build-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回本体首页</el-button>
          <h2>文档构建：{{ job?.name || '加载中...' }}</h2>
          <el-tag :type="getStatusType(job?.status)" size="small" v-if="job">
            {{ getStatusText(job?.status) }}
          </el-tag>
        </div>
      </div>

      <!-- 状态栏：进度 + 步骤条 合并 -->
      <div class="status-bar" v-if="job">
        <!-- 运行中进度指示 -->
        <div class="status-progress" v-if="isRunning">
          <el-icon class="is-loading" :size="16"><Loading /></el-icon>
          <span class="status-text">{{ progressMessage }}</span>
          <el-progress
            :percentage="Math.round(displayProgress)"
            :stroke-width="4"
            class="slim-progress"
            :show-text="false"
          />
          <span class="status-percent">{{ Math.round(displayProgress) }}%</span>
          <span class="status-hint">后台运行中，可随时离开</span>
        </div>
        <!-- 步骤指示 -->
        <el-steps :active="currentStep" finish-status="success" align-center class="build-steps">
          <el-step title="上传文档" :status="getStepStatus(0)" />
          <el-step title="提取概念" :status="getStepStatus(1)" />
          <el-step title="构建结构" :status="getStepStatus(2)" />
          <el-step title="生成本体" :status="getStepStatus(3)" />
        </el-steps>
      </div>

      <!-- 错误提示 -->
      <el-alert
        v-if="job?.error_message"
        :title="'构建出错：' + job.error_message"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 1rem"
      />

      <!-- 步骤内容区 -->
      <div class="step-content" v-loading="loading">
        <!-- Step 0: 上传文档 + 元模型确认 -->
        <div v-if="currentStep === 0" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>文档信息</h3>
                <el-tag type="success" v-if="job?.meta_confirmed">已确认</el-tag>
              </div>
            </template>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="本体名称">{{ job?.name }}</el-descriptions-item>
              <el-descriptions-item label="源文档">{{ job?.source_filename }}</el-descriptions-item>
              <el-descriptions-item label="字符数">{{ job?.char_count?.toLocaleString() }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatTime(job?.create_time) }}</el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ job?.description || '暂无描述' }}</el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>确认元模型</h3>
                <el-tag type="info" size="small">AI 已根据文档内容推荐以下元模型，您可以编辑确认</el-tag>
              </div>
            </template>

            <div class="meta-columns">
              <!-- 左侧：实体类型 -->
              <div class="meta-column">
                <div class="meta-column-header">
                  <h4>实体类型</h4>
                  <el-tag size="small" type="info">{{ metaForm.entityTypes.length }} 个</el-tag>
                </div>
                <div class="type-list">
                  <div v-for="(t, idx) in metaForm.entityTypes" :key="idx" class="type-item">
                    <el-input v-model="t.name" placeholder="类型名" size="small" class="type-name-input" />
                    <el-color-picker v-model="t.color" size="small" />
                    <el-button size="small" link type="danger" @click="metaForm.entityTypes.splice(idx, 1)">
                      <el-icon><Close /></el-icon>
                    </el-button>
                  </div>
                </div>
                <el-button size="small" class="add-type-btn" @click="metaForm.entityTypes.push({ name: '', color: '#5470c6' })">
                  <el-icon><Plus /></el-icon> 添加实体类型
                </el-button>
              </div>

              <!-- 右侧：关系类型 -->
              <div class="meta-column">
                <div class="meta-column-header">
                  <h4>关系类型</h4>
                  <el-tag size="small" type="info">{{ metaForm.relationTypes.length }} 个</el-tag>
                </div>
                <div class="type-list">
                  <div v-for="(t, idx) in metaForm.relationTypes" :key="idx" class="type-item">
                    <el-input v-model="t.name" placeholder="关系名" size="small" class="type-name-input" />
                    <el-button size="small" link type="danger" @click="metaForm.relationTypes.splice(idx, 1)">
                      <el-icon><Close /></el-icon>
                    </el-button>
                  </div>
                </div>
                <el-button size="small" class="add-type-btn" @click="metaForm.relationTypes.push({ name: '' })">
                  <el-icon><Plus /></el-icon> 添加关系类型
                </el-button>
              </div>
            </div>

            <div class="step-actions">
              <el-button @click="goBack">取消</el-button>
              <el-button
                type="primary"
                :loading="submitting"
                :disabled="job?.meta_confirmed"
                @click="doConfirmMeta"
              >
                {{ job?.meta_confirmed ? '已确认' : '确认元模型' }}
              </el-button>
            </div>
          </el-card>
        </div>

        <!-- Step 1: 提取概念 -->
        <div v-if="currentStep === 1" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>提取概念</h3>
                <el-tag type="info" size="small">
                  {{ isExtracting ? 'AI 正在提取，可实时编辑已提取部分' : 'AI 已提取以下概念，可编辑确认' }}
                </el-tag>
              </div>
            </template>

            <!-- 分批提取中途失败，可断点续作 -->
            <div v-if="isStep1Resumable" class="extract-section">
              <el-alert
                :title="`第 ${job.step1_failed_batch + 1}/${job.step1_batches_total} 批提取失败，已成功 ${job.step1_batches_done} 批`"
                type="warning"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>{{ job?.error_message || '部分批次提取失败' }}</p>
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续提取概念"重试，无需修改任何配置。</p>
                  <p>点击"继续提取概念"从失败批次续跑，已成功批次不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractConcepts">
                  继续提取概念
                </el-button>
              </div>
            </div>

            <!-- 未开始提取（非提取中、无概念） -->
            <div v-else-if="!isExtracting && !concepts.length" class="extract-section">
              <el-alert
                title="点击按钮开始提取概念"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将根据已确认的元模型，从文档内容中提取概念。每个概念会标注原文出处，方便您核对。</p>
                  <p>长文档会分批提取，每批完成后实时显示在下方表格中，您可边提取边编辑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractConcepts">
                  开始提取概念
                </el-button>
              </div>
            </div>

            <!-- 提取中（实时追加）或已完成审核：实时表格，始终可编辑 -->
            <div v-else class="concepts-section">
              <el-alert
                v-if="isExtracting"
                :title="batch1ProgressText"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-alert
                v-else
                title="概念提取完成，请审核确认"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-table :data="concepts" stripe style="width: 100%">
                <el-table-column prop="name" label="名称" width="140">
                  <template #default="scope">
                    <el-input v-model="scope.row.name" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="type" label="类型" width="120">
                  <template #default="scope">
                    <el-select v-model="scope.row.type" size="small">
                      <el-option
                        v-for="t in metaForm.entityTypes"
                        :key="t.name"
                        :label="t.name"
                        :value="t.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="description" label="描述" min-width="200">
                  <template #default="scope">
                    <el-input v-model="scope.row.description" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="source_snippet" label="原文出处" min-width="250">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.source_snippet"
                      size="small"
                      type="textarea"
                      :rows="2"
                      placeholder="从原文摘录"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" fixed="right">
                  <template #default="scope">
                    <el-button size="small" link type="danger" @click="concepts.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="step-actions">
                <el-button size="small" @click="concepts.push({ name: '', type: metaForm.entityTypes[0]?.name || '', description: '', source_snippet: '' })">
                  + 添加概念
                </el-button>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep1Done || job?.step1_confirmed"
                  @click="doConfirmConcepts"
                >
                  {{ job?.step1_confirmed ? '已确认' : (aiStep1Done ? '确认概念清单' : 'AI 提取中（可先编辑已提取部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 2: 构建层次结构 -->
        <div v-if="currentStep === 2" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>构建层次结构</h3>
                <el-tag type="info" size="small">
                  {{ isBuilding ? 'AI 正在构建，可实时编辑已生成部分' : 'AI 已构建以下层次结构，可编辑确认' }}
                </el-tag>
              </div>
            </template>

            <!-- 分组构建或跨组关系补充中途失败，可断点续作 -->
            <div v-if="isStep2Resumable" class="build-section">
              <el-alert
                :title="job.step2_groups_done < job.step2_groups_total
                  ? `第 ${job.step2_failed_group + 1}/${job.step2_groups_total} 组构建失败，已成功 ${job.step2_groups_done} 组`
                  : '跨组关系补充失败'"
                type="warning"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>{{ job?.error_message || '部分构建步骤失败' }}</p>
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续构建结构"重试，无需修改任何配置。</p>
                  <p>点击"继续构建结构"从断点续跑，已成功步骤不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doBuildStructure">
                  继续构建结构
                </el-button>
              </div>
            </div>

            <!-- 未开始构建（非构建中、无实体） -->
            <div v-else-if="!isBuilding && !entities.length" class="build-section">
              <el-alert
                title="点击按钮开始构建层次结构"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将根据概念清单构建实体和关系。</p>
                  <p>概念较多时分组构建，每组完成后实时显示在下方表格中，您可边构建边编辑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doBuildStructure">
                  开始构建结构
                </el-button>
              </div>
            </div>

            <!-- 构建中（实时追加）或已完成审核：实时表格，始终可编辑 -->
            <div v-else class="structure-section">
              <el-alert
                v-if="isBuilding"
                :title="batch2ProgressText"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-alert
                v-else
                title="层次结构构建完成，请审核确认"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <h4>实体列表（{{ entities.length }} 个）</h4>
              <el-table :data="entities" stripe style="width: 100%; margin-bottom: 1.5rem">
                <el-table-column prop="name" label="名称" width="140">
                  <template #default="scope">
                    <el-input v-model="scope.row.name" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="type" label="类型" width="120">
                  <template #default="scope">
                    <el-select v-model="scope.row.type" size="small">
                      <el-option
                        v-for="t in metaForm.entityTypes"
                        :key="t.name"
                        :label="t.name"
                        :value="t.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="parent" label="父实体" width="140">
                  <template #default="scope">
                    <el-select v-model="scope.row.parent" size="small" clearable placeholder="无（顶层）">
                      <el-option
                        v-for="e in entities.filter(x => x.name !== scope.row.name)"
                        :key="e.name"
                        :label="e.name"
                        :value="e.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="properties" label="属性（JSON）" min-width="200">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.propertiesStr"
                      size="small"
                      placeholder='{"key": "value"}'
                    />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" fixed="right">
                  <template #default="scope">
                    <el-button size="small" link type="danger" @click="entities.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="entities.push({ name: '', type: metaForm.entityTypes[0]?.name || '', parent: '', propertiesStr: '{}' })">
                  + 添加实体
                </el-button>
              </div>

              <h4>关系列表（{{ relations.length }} 条）</h4>
              <el-table :data="relations" stripe style="width: 100%; margin-bottom: 1.5rem">
                <el-table-column prop="source" label="源实体" width="140">
                  <template #default="scope">
                    <el-select v-model="scope.row.source" size="small">
                      <el-option
                        v-for="e in entities"
                        :key="e.name"
                        :label="e.name"
                        :value="e.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="relation_type" label="关系类型" width="120">
                  <template #default="scope">
                    <el-select v-model="scope.row.relation_type" size="small">
                      <el-option
                        v-for="t in metaForm.relationTypes"
                        :key="t.name"
                        :label="t.name"
                        :value="t.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="target" label="目标实体" width="140">
                  <template #default="scope">
                    <el-select v-model="scope.row.target" size="small">
                      <el-option
                        v-for="e in entities"
                        :key="e.name"
                        :label="e.name"
                        :value="e.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="weight" label="权重" width="110">
                  <template #default="scope">
                    <el-input-number v-model="scope.row.weight" size="small" :min="0" :max="1" :step="0.1" controls-position="right" />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" fixed="right">
                  <template #default="scope">
                    <el-button size="small" link type="danger" @click="relations.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="relations.push({ source: entities[0]?.name || '', target: '', relation_type: metaForm.relationTypes[0]?.name || '', weight: 1.0 })">
                  + 添加关系
                </el-button>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep2Done || job?.step2_confirmed"
                  @click="doConfirmStructure"
                >
                  {{ job?.step2_confirmed ? '已确认' : (aiStep2Done ? '确认层次结构' : 'AI 构建中（可先编辑已生成部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 3: 生成最终本体 -->
        <div v-if="currentStep === 3" class="step-panel">
          <el-card class="step-card">
            <!-- 等待后台生成中 -->
            <div v-if="isGenerating" class="waiting-section">
              <el-alert
                title="AI 正在做最终序列化..."
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>后台任务正在运行，请耐心等待。您可以随时离开此页面，稍后回来继续。</p>
                </template>
              </el-alert>
            </div>

            <!-- 需要点击按钮生成 -->
            <div v-else-if="job?.status !== 'completed'" class="generate-section">
              <el-alert
                title="点击按钮生成最终本体"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将对已确认的层次结构做一致性检查和属性补充，生成正式本体。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doGenerateOntology">
                  生成最终本体
                </el-button>
              </div>
            </div>

            <!-- 生成完成 -->
            <div v-else class="complete-content">
              <el-icon class="success-icon"><CircleCheck /></el-icon>
              <h3>本体构建成功！</h3>
              <el-descriptions :column="2" border style="margin: 1.5rem 0">
                <el-descriptions-item label="本体名称">{{ job?.name }}</el-descriptions-item>
                <el-descriptions-item label="状态">
                  <el-tag type="success">已完成</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="实体数量">{{ job?.step3_entities?.length || entities.length }}</el-descriptions-item>
                <el-descriptions-item label="关系数量">{{ job?.step3_relations?.length || relations.length }}</el-descriptions-item>
              </el-descriptions>
              <div class="step-actions" style="justify-content: center">
                <el-button type="primary" @click="viewOntology">查看本体详情</el-button>
                <el-button @click="goBack">返回首页</el-button>
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, CircleCheck, Loading, Close, Plus } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'
import {
  getBuildJob,
  getBuildProgress,
  confirmMeta as confirmMetaApi,
  extractConcepts as extractConceptsApi,
  confirmConcepts as confirmConceptsApi,
  buildStructure as buildStructureApi,
  confirmStructure as confirmStructureApi,
  generateOntology,
  streamBuildJob
} from '@/services/ontologyBuild'

const route = useRoute()
const router = useRouter()
const jobId = route.params.jobId as string

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)

const job = ref<any>(null)
const concepts = ref<any[]>([])
const entities = ref<any[]>([])
const relations = ref<any[]>([])

const metaForm = ref({
  entityTypes: [] as any[],
  relationTypes: [] as any[]
})

// AI 提取/构建完成标记（收到 SSE step_done 后置 true，启用"确认"按钮）
// 提取/构建进行中按钮禁用，但用户可先编辑已到达的行
const aiStep1Done = ref(false)
const aiStep2Done = ref(false)

// 轮询定时器（SSE 不可用时的降级方案）
let pollTimer: ReturnType<typeof setInterval> | null = null
// SSE 订阅 abort 函数 + 断线重试计数
let sseAbort: (() => void) | null = null
let streamRetryCount = 0
const STREAM_MAX_RETRY = 3

// ── 前端动画进度 ──
// 后端仅在 10%/30%/100% 设离散值，LLM 调用期间进度卡死。
// 前端用渐近逼近上限的方式接管显示，让进度条平滑增长。
const displayProgress = ref(0)
let progressTimer: ReturnType<typeof setInterval> | null = null
const PROGRESS_CEILING = 92  // 任务未完成时的渐近上限

const startProgressAnimation = () => {
  stopProgressAnimation()
  displayProgress.value = 8
  progressTimer = setInterval(() => {
    const remaining = PROGRESS_CEILING - displayProgress.value
    // 越接近上限增速越慢，永远不会超过上限
    if (remaining > 0.3) {
      displayProgress.value += remaining * 0.1
    }
  }, 500)
}

const stopProgressAnimation = (final?: number) => {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
  if (final !== undefined) {
    displayProgress.value = final
  }
}

// ── 计算属性 ──
const currentStep = computed(() => {
  if (!job.value) return 0
  if (job.value.status === 'completed') return 3
  if (job.value.step >= 3) return 3   // step2 已确认，等待生成
  if (job.value.step >= 2) return 2
  if (job.value.step >= 1) return 1
  return 0
})

const isRunning = computed(() => {
  return job.value?.running_step !== undefined && job.value.running_step >= 0
})

const isExtracting = computed(() => job.value?.running_step === 0)
const isBuilding = computed(() => job.value?.running_step === 1)
const isGenerating = computed(() => job.value?.running_step === 2)

// 空响应错误：LLM 服务端偶发无响应（非配置/代码问题），提示用户重试即可
const isEmptyResponseError = computed(() =>
  !!job.value?.error_message && job.value.error_message.includes('空响应')
)

// Step 1 断点续作：分批提取中途失败，可从失败批次续跑（未确认时才允许）
const isStep1Resumable = computed(() =>
  !!job.value
  && job.value.step1_batches_total > 0
  && job.value.step1_batches_done < job.value.step1_batches_total
  && job.value.step1_failed_batch >= 0
  && !job.value.step1_confirmed
)
// Step 2 断点续作：分组构建或跨组关系补充中途失败，可从断点续跑
const isStep2Resumable = computed(() =>
  !!job.value
  && !job.value.step2_confirmed
  && job.value.step2_groups_total > 0
  && (
    // 分组阶段失败
    (job.value.step2_groups_done < job.value.step2_groups_total && job.value.step2_failed_group >= 0)
    // 跨组关系补充阶段失败
    || (job.value.step2_groups_done === job.value.step2_groups_total
        && !job.value.step2_cross_group_done && job.value.step2_cross_group_failed)
  )
)

const progressMessage = computed(() => {
  if (!job.value) return ''
  const msgs: Record<number, string> = {
    0: job.value.progress_message || '正在提取概念...',
    1: job.value.progress_message || '正在构建结构...',
    2: job.value.progress_message || '正在生成最终本体...'
  }
  return msgs[job.value.running_step] || ''
})

// ── Step1/Step2 实时进度文案（提取/构建进行中显示在表格顶部）──
const batch1ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在提取概念...'
  const done = concepts.value.length
  if (j.step1_batches_total > 1) {
    return `AI 正在提取概念（第 ${j.step1_batches_done + 1}/${j.step1_batches_total} 批），已提取 ${done} 个`
  }
  return `AI 正在提取概念，已提取 ${done} 个`
})

const batch2ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在构建层次结构...'
  if (j.step2_groups_total > 1) {
    return `AI 正在构建层次结构（第 ${j.step2_groups_done + 1}/${j.step2_groups_total} 组），已生成 ${entities.value.length} 实体、${relations.value.length} 关系`
  }
  return `AI 正在构建层次结构，已生成 ${entities.value.length} 实体、${relations.value.length} 关系`
})

// ── 步骤条状态 ──
const getStepStatus = (step: number): 'wait' | 'process' | 'finish' | 'error' => {
  if (!job.value) return 'wait'
  const j = job.value
  if (j.running_step === step) return 'process'
  if (step === 0 && j.meta_confirmed) return 'finish'
  if (step === 1 && j.step1_confirmed) return 'finish'
  if (step === 2 && j.step2_confirmed) return 'finish'
  if (step === 3 && j.status === 'completed') return 'finish'
  if (j.step > step) return 'finish'
  return 'wait'
}

// ── 数据加载 ──
const loadJob = async () => {
  try {
    const res: any = await getBuildJob(jobId)
    job.value = res.data

    // 恢复元模型
    if (job.value.meta_entity_types?.length) {
      metaForm.value.entityTypes = JSON.parse(JSON.stringify(job.value.meta_entity_types))
    }
    if (job.value.meta_relation_types?.length) {
      metaForm.value.relationTypes = JSON.parse(JSON.stringify(job.value.meta_relation_types))
    }

    // 恢复概念清单
    if (job.value.step1_concepts?.length) {
      concepts.value = JSON.parse(JSON.stringify(job.value.step1_concepts))
    }

    // 恢复实体和关系
    if (job.value.step2_entities?.length) {
      entities.value = job.value.step2_entities.map((e: any) => ({
        ...e,
        propertiesStr: JSON.stringify(e.properties || {})
      }))
    }
    if (job.value.step2_relations?.length) {
      relations.value = JSON.parse(JSON.stringify(job.value.step2_relations))
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载任务失败')
  }
}

// ── 轮询进度 ──
const startPolling = () => {
  stopPolling()
  startProgressAnimation()
  pollTimer = setInterval(async () => {
    try {
      const res: any = await getBuildProgress(jobId)
      const p = res.data
      if (job.value) {
        // 更新进度相关字段
        job.value.running_step = p.running_step
        job.value.progress = p.progress
        job.value.progress_message = p.progress_message
        job.value.error_message = p.error_message
        job.value.step = p.step
        job.value.status = p.status
        job.value.meta_confirmed = p.meta_confirmed
        job.value.step1_confirmed = p.step1_confirmed
        job.value.step2_confirmed = p.step2_confirmed
        job.value.ontology_id = p.ontology_id
        // Step 1/2 分批与断点续作状态（前端用于切换"继续提取/构建"按钮文案）
        job.value.step1_batches_total = p.step1_batches_total
        job.value.step1_batches_done = p.step1_batches_done
        job.value.step1_failed_batch = p.step1_failed_batch
        job.value.step2_groups_total = p.step2_groups_total
        job.value.step2_groups_done = p.step2_groups_done
        job.value.step2_failed_group = p.step2_failed_group
        job.value.step2_cross_group_done = p.step2_cross_group_done
        job.value.step2_cross_group_failed = p.step2_cross_group_failed

        // 后台任务完成（running_step 回到 -1）或出错时，推进到 100%、重新加载并停止轮询
        if (p.running_step === -1) {
          stopProgressAnimation(100)
          await loadJob()
          stopPolling()
        }
      }
    } catch {
      // 静默失败，继续轮询
    }
  }, 2000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  stopProgressAnimation()
}

// ── SSE 实时订阅（Step1/Step2 批次级增量推送，替代轮询）──
// 每批概念/每组实体关系完成后即时推送到前端，用户可边看边改
// 断线自动重连（最多 3 次），仍失败回退轮询

/** 名称归一化（与后端 _normalize_name 一致）：用于按名称去重，避免全角/空格差异导致重复 */
const _normName = (name: string) =>
  (name || '').trim().replace(/（/g, '(').replace(/）/g, ')').replace(/\u3000/g, ' ')

/** 关系三元组去重 key */
const _relKey = (r: any) => `${_normName(r.source)}|${r.relation_type}|${_normName(r.target)}`

/** 启动 SSE 订阅：接收 Step1/Step2 的实时增量 */
const startStream = () => {
  console.log('[Stream] startStream 调用, jobId=', jobId, '当前 entities=', entities.value.length, 'concepts=', concepts.value.length)
  stopStream()
  stopPolling()  // 确保轮询已停，避免 SSE 与轮询双重更新
  streamRetryCount = 0
  sseAbort = streamBuildJob(jobId, {
    onBatchDone: (d) => {
      // 只追加不覆盖：按归一化名称去重，已存在于前端的跳过（保留用户编辑/手动添加）
      const existing = new Set(concepts.value.map(c => _normName(c.name)).filter(Boolean))
      const fresh = (d.concepts || []).filter((c: any) => {
        const n = _normName(c.name)
        if (!n || existing.has(n)) return false
        existing.add(n)
        return true
      })
      concepts.value.push(...fresh)
      if (job.value) {
        job.value.step1_batches_done = d.batches_done
        job.value.step1_batches_total = d.batches_total
      }
    },
    onGroupDone: (d) => {
      // 实体按名称去重追加（补充 propertiesStr 供表格编辑）
      const existEnt = new Set(entities.value.map(e => _normName(e.name)).filter(Boolean))
      const freshEnt = (d.entities || []).filter((e: any) => {
        const n = _normName(e.name)
        if (!n || existEnt.has(n)) return false
        existEnt.add(n)
        return true
      }).map((e: any) => ({ ...e, propertiesStr: JSON.stringify(e.properties || {}) }))
      console.log('[Stream] onGroupDone: +' + freshEnt.length + ' 实体, 总计=' + (entities.value.length + freshEnt.length))
      entities.value.push(...freshEnt)
      // 关系按三元组去重追加
      const existRel = new Set(relations.value.map(_relKey))
      const freshRel = (d.relations || []).filter((r: any) => {
        const k = _relKey(r)
        if (existRel.has(k)) return false
        existRel.add(k)
        return true
      })
      relations.value.push(...freshRel)
      if (job.value) {
        job.value.step2_groups_done = d.groups_done
        job.value.step2_groups_total = d.groups_total
      }
    },
    onCrossGroupDone: (d) => {
      // 跨组关系补充：按三元组去重追加
      const existRel = new Set(relations.value.map(_relKey))
      const freshRel = (d.relations || []).filter((r: any) => {
        const k = _relKey(r)
        if (existRel.has(k)) return false
        existRel.add(k)
        return true
      })
      relations.value.push(...freshRel)
    },
    onStepDone: (d) => {
      // AI 全部完成，启用"确认"按钮
      if (d.step === 1) {
        aiStep1Done.value = true
        if (job.value) job.value.running_step = -1
        ElMessage.success(`概念提取完成，共 ${d.total ?? concepts.value.length} 个`)
      } else if (d.step === 2) {
        aiStep2Done.value = true
        if (job.value) job.value.running_step = -1
        ElMessage.success(`层次结构构建完成，共 ${entities.value.length} 实体、${relations.value.length} 关系`)
      }
      stopProgressAnimation(100)
    },
    onError: (d) => {
      if (d.reconnect) {
        // 连接异常断开：尝试重连
        console.log('[Stream] onError reconnect, retryCount=', streamRetryCount)
        retryStream()
      } else {
        // 真实业务错误：展示错误，回退轮询拉取完整状态（断点续作等）
        if (d.message) ElMessage.error(d.message)
        if (job.value) {
          job.value.error_message = d.message
          job.value.running_step = -1
        }
        startPolling()
      }
    },
    onState: (s) => {
      // 连接成功打开后重置重试计数
      if (s === 'open') streamRetryCount = 0
    }
  })
}

/** 停止 SSE 订阅（离开页面/确认提交时调用） */
const stopStream = () => {
  if (sseAbort) {
    sseAbort()
    sseAbort = null
  }
}

/** 断线重连：最多 3 次，仍失败回退轮询 */
const retryStream = () => {
  if (streamRetryCount >= STREAM_MAX_RETRY) {
    ElMessage.warning('实时连接不稳定，已切换到轮询模式')
    startPolling()
    return
  }
  streamRetryCount++
  setTimeout(() => {
    startStream()  // startStream 内部会先 stopStream；已有数据保留，靠后端回放 + 前端去重补全
  }, 3000)
}

// ── 步骤操作 ──
const doConfirmMeta = async () => {
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('entity_types', JSON.stringify(metaForm.value.entityTypes.filter((t: any) => t.name)))
    fd.append('relation_types', JSON.stringify(metaForm.value.relationTypes.filter((t: any) => t.name)))

    await confirmMetaApi(jobId, fd)
    ElMessage.success('元模型已确认，可执行概念提取')
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doExtractConcepts = async () => {
  try {
    await extractConceptsApi(jobId)
    // 乐观标记运行中，让进度区立即显示，无需等首次 SSE 事件
    if (job.value) {
      job.value.running_step = 0
      job.value.progress_message = '正在准备文档...'
    }
    aiStep1Done.value = false
    ElMessage.info('概念提取已在后台开始，可实时查看提取结果')
    startProgressAnimation()
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

const doConfirmConcepts = async () => {
  submitting.value = true
  try {
    await confirmConceptsApi(jobId, concepts.value)
    ElMessage.success('概念清单已确认，可执行层次结构构建')
    stopStream()
    stopProgressAnimation(100)
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doBuildStructure = async () => {
  try {
    await buildStructureApi(jobId)
    // 乐观标记运行中，让进度区立即显示，无需等首次 SSE 事件
    if (job.value) {
      job.value.running_step = 1
      job.value.progress_message = '正在准备概念清单...'
    }
    aiStep2Done.value = false
    ElMessage.info('层次结构构建已在后台开始，可实时查看构建结果')
    startProgressAnimation()
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动构建失败')
  }
}

const doConfirmStructure = async () => {
  submitting.value = true
  try {
    // 解析 propertiesStr
    const parsedEntities = entities.value.map(e => {
      let props = {}
      try {
        props = JSON.parse(e.propertiesStr || '{}')
      } catch {
        props = {}
      }
      const { propertiesStr, ...rest } = e
      return { ...rest, properties: props }
    })

    await confirmStructureApi(jobId, parsedEntities, relations.value)
    ElMessage.success('层次结构已确认，可生成最终本体')
    stopStream()
    stopProgressAnimation(100)
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doGenerateOntology = async () => {
  try {
    await generateOntology(jobId)
    // 乐观标记运行中，让进度区立即显示
    if (job.value) {
      job.value.running_step = 2
      job.value.progress_message = '正在准备数据...'
    }
    ElMessage.info('最终序列化已在后台开始，您可以离开页面')
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动生成失败')
  }
}

// ── 导航 ──
const viewOntology = () => {
  if (job.value?.ontology_id) {
    router.push(`/ontology/${job.value.ontology_id}`)
  } else {
    goBack()
  }
}

const goBack = () => {
  stopPolling()
  router.push('/ontology')
}

// ── 辅助函数 ──
const getStatusType = (status: string) => {
  const typeMap: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
    'completed': 'success',
    'draft': 'warning',
    'abandoned': 'info'
  }
  return typeMap[status] || 'info'
}

const getStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    'completed': '已完成',
    'draft': '草稿',
    'abandoned': '已废弃'
  }
  return textMap[status] || status
}

const formatTime = (time: string) => {
  if (!time) return ''
  try {
    return new Date(time).toLocaleString('zh-CN')
  } catch {
    return time
  }
}

// ── 生命周期 ──
onMounted(async () => {
  loading.value = true
  await loadJob()
  loading.value = false

  // 恢复 AI 完成标记（断线重连/刷新页面恢复场景：step1/step2 已完成但未确认）
  if (job.value?.step1_concepts?.length && !job.value?.step1_confirmed) {
    aiStep1Done.value = true
  }
  if (job.value?.step2_entities?.length && !job.value?.step2_confirmed) {
    aiStep2Done.value = true
  }

  // 若有后台任务在运行：Step1/Step2 用 SSE 实时推送，Step3（序列化）用轮询
  const rs = job.value?.running_step
  if (rs === 0 || rs === 1) {
    startProgressAnimation()
    startStream()
  } else if (rs === 2) {
    startPolling()
  }
})

onUnmounted(() => {
  stopStream()
  stopPolling()
})
</script>

<style scoped>
.ontology-build {
  height: 100%;
  padding: 1.5rem;
  overflow-y: auto;
}

.build-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.header-left h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.35rem;
  font-weight: 600;
}

.status-bar {
  background: white;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 1.25rem;
}

.status-progress {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.status-text {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-primary);
}

.slim-progress {
  flex: 1;
  margin: 0;
}

.status-percent {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--primary-500);
  min-width: 32px;
  text-align: right;
}

.status-hint {
  font-size: 0.8rem;
  color: var(--text-secondary);
  white-space: nowrap;
}

.build-steps {
  margin: 0;
}

.step-content {
  min-height: 300px;
}

.step-panel {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.step-card {
  border-radius: 10px;
}

.step-card :deep(.el-card__body) {
  padding: 1.5rem;
}

.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.step-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-bottom: 1.25rem;
}

@media (max-width: 768px) {
  .meta-columns {
    grid-template-columns: 1fr;
  }
}

.meta-column {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  padding: 1.25rem;
  border: 1px solid var(--border-color, #e4e7ed);
}

.meta-column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 2px solid var(--primary-500, #409eff);
}

.meta-column-header h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.type-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
  min-height: 80px;
}

.type-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: white;
  padding: 0.625rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border-color, #e4e7ed);
  transition: all 0.2s;
}

.type-item:hover {
  border-color: var(--primary-500, #409eff);
  box-shadow: 0 2px 4px rgba(64, 158, 255, 0.1);
}

.type-name-input {
  flex: 1;
}

.add-type-btn {
  width: 100%;
  border-style: dashed;
}

.waiting-section,
.extract-section,
.build-section,
.generate-section {
  padding: 0.5rem 0;
}

.concepts-section,
.structure-section {
  padding: 0.5rem 0;
}

.concepts-section h4,
.structure-section h4 {
  margin: 1.5rem 0 0.75rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

/* LLM 服务端偶发无响应的专属提示：突出强调，便于用户识别为外部抖动而非配置错误 */
.llm-hint {
  margin: 0.25rem 0;
  color: var(--el-color-warning);
  font-weight: 600;
}

.complete-content {
  text-align: center;
  padding: 2rem 1.5rem;
}

.success-icon {
  font-size: 3.5rem;
  color: var(--success-500);
  margin-bottom: 1rem;
}

.complete-content h3 {
  margin: 0 0 0.75rem 0;
  font-size: 1.35rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
