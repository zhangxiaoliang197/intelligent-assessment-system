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

      <!-- 后台运行进度提示 -->
      <div class="progress-section" v-if="isRunning">
        <el-card class="progress-card">
          <div class="progress-content">
            <div class="progress-icon">
              <el-icon class="is-loading" :size="24"><Loading /></el-icon>
            </div>
            <div class="progress-info">
              <div class="progress-title">{{ progressMessage }}</div>
              <el-progress
                :percentage="job?.progress || 0"
                :stroke-width="8"
                :text-inside="true"
                class="animated-progress"
              />
              <div class="progress-hint">后台任务运行中，您可以离开此页面，稍后回来查看结果</div>
            </div>
          </div>
        </el-card>
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

      <!-- 步骤条 -->
      <div class="steps-section" v-if="job">
        <el-steps :active="currentStep" finish-status="success" align-center>
          <el-step title="上传文档" :status="getStepStatus(0)" />
          <el-step title="提取概念" :status="getStepStatus(1)" />
          <el-step title="构建结构" :status="getStepStatus(2)" />
          <el-step title="生成本体" :status="getStepStatus(3)" />
        </el-steps>
      </div>

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
                <el-tag type="info" size="small">AI 已从文档中提取以下概念，您可以编辑确认</el-tag>
              </div>
            </template>

            <!-- 等待后台提取中 -->
            <div v-if="isExtracting" class="waiting-section">
              <el-alert
                title="AI 正在提取概念..."
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>后台任务正在运行，请耐心等待。您可以随时离开此页面，稍后回来继续。</p>
                </template>
              </el-alert>
            </div>

            <!-- 需要点击按钮开始提取 -->
            <div v-else-if="!job?.step1_concepts?.length" class="extract-section">
              <el-alert
                title="点击按钮开始提取概念"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将根据已确认的元模型，从文档内容中提取概念。每个概念会标注原文出处，方便您核对。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractConcepts">
                  开始提取概念
                </el-button>
              </div>
            </div>

            <!-- 概念清单已就绪，等待用户审核 -->
            <div v-else class="concepts-section">
              <el-alert
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
                  :disabled="job?.step1_confirmed"
                  @click="doConfirmConcepts"
                >
                  {{ job?.step1_confirmed ? '已确认' : '确认概念清单' }}
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
                <el-tag type="info" size="small">AI 已根据概念清单构建以下层次结构</el-tag>
              </div>
            </template>

            <!-- 等待后台构建中 -->
            <div v-if="isBuilding" class="waiting-section">
              <el-alert
                title="AI 正在构建层次结构..."
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>后台任务正在运行，请耐心等待。您可以随时离开此页面，稍后回来继续。</p>
                </template>
              </el-alert>
            </div>

            <!-- 需要点击按钮开始构建 -->
            <div v-else-if="!job?.step2_entities?.length" class="build-section">
              <el-alert
                title="点击按钮开始构建层次结构"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将根据概念清单构建实体和关系。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doBuildStructure">
                  开始构建结构
                </el-button>
              </div>
            </div>

            <!-- 结构已就绪，等待用户审核 -->
            <div v-else class="structure-section">
              <el-alert
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
                  :disabled="job?.step2_confirmed"
                  @click="doConfirmStructure"
                >
                  {{ job?.step2_confirmed ? '已确认' : '确认层次结构' }}
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
  generateOntology
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

// 轮询定时器
let pollTimer: ReturnType<typeof setInterval> | null = null

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

const progressMessage = computed(() => {
  if (!job.value) return ''
  const msgs: Record<number, string> = {
    0: job.value.progress_message || '正在提取概念...',
    1: job.value.progress_message || '正在构建结构...',
    2: job.value.progress_message || '正在生成最终本体...'
  }
  return msgs[job.value.running_step] || ''
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

        // 后台任务完成（running_step 回到 -1）或出错时，重新加载完整数据并停止轮询
        if (p.running_step === -1) {
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
    ElMessage.info('概念提取已在后台开始，您可以离开页面')
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

const doConfirmConcepts = async () => {
  submitting.value = true
  try {
    await confirmConceptsApi(jobId, concepts.value)
    ElMessage.success('概念清单已确认，可执行层次结构构建')
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
    ElMessage.info('层次结构构建已在后台开始，您可以离开页面')
    startPolling()
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

  // 若有后台任务在运行，自动开始轮询
  if (job.value?.running_step >= 0) {
    startPolling()
  }
})

onUnmounted(() => {
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
  margin-bottom: 1.25rem;
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

.progress-section {
  margin-bottom: 1rem;
}

.progress-card {
  border-radius: 10px;
  border: 1px solid var(--primary-200, #b3d8ff);
}

.progress-content {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0.25rem 0;
}

.progress-icon {
  flex-shrink: 0;
  color: var(--primary-500, #409eff);
}

.progress-info {
  flex: 1;
}

.progress-title {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-primary);
  margin-bottom: 0.5rem;
}

.progress-hint {
  font-size: 0.8rem;
  color: var(--text-secondary, #909399);
  margin-top: 0.5rem;
}

.steps-section {
  background: white;
  border-radius: 10px;
  padding: 1.25rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 1.25rem;
}

.step-content {
  min-height: 300px;
}

.step-panel {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.step-card {
  border-radius: 10px;
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
  padding: 1rem;
  border: 1px solid var(--border-color, #e4e7ed);
}

.meta-column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.875rem;
  padding-bottom: 0.625rem;
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
  gap: 0.625rem;
  margin-bottom: 0.875rem;
  min-height: 80px;
}

.type-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: white;
  padding: 0.5rem;
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
  padding: 0.75rem 0;
}

.concepts-section,
.structure-section {
  padding: 0.75rem 0;
}

.concepts-section h4,
.structure-section h4 {
  margin: 1.25rem 0 0.625rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.625rem;
  margin-top: 1.25rem;
}

.complete-content {
  text-align: center;
  padding: 1.5rem;
}

.success-icon {
  font-size: 3.5rem;
  color: var(--success-500);
  margin-bottom: 0.75rem;
}

.complete-content h3 {
  margin: 0 0 0.75rem 0;
  font-size: 1.35rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
