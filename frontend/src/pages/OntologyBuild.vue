<template>
  <Layout>
    <div class="ontology-build">
      <!-- 顶部 Header -->
      <div class="build-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回</el-button>
          <h2>AI 构建：{{ job?.name || '加载中...' }}</h2>
          <el-tag v-if="job" :type="getStatusType(job.status)" size="small">
            {{ getStatusText(job.status) }}
          </el-tag>
          <el-tag v-if="job?.ontology_id" type="success" size="small">已生成本体</el-tag>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
          <el-button type="primary" v-if="currentState.step3_confirmed && !currentState.ontology_id"
            @click="completeBuild" :loading="completing">
            确认完成
          </el-button>
        </div>
      </div>

      <!-- 主体：左聊天 + 右状态 -->
      <div class="workspace" v-if="job">
        <!-- 左侧：聊天窗口 -->
        <div class="chat-panel">
          <!-- 当前状态下拉面板 -->
          <CurrentStatePanel :jobId="jobId" :state="currentState" @stateChanged="onStatePanelChanged" />
          <div class="chat-messages" ref="chatMessagesRef">
            <div v-if="chatMessages.length === 0" class="chat-empty">
              <el-icon :size="48"><ChatDotRound /></el-icon>
              <p>{{ isReopen ? '欢迎回来，继续编辑你的本体。' : '你好！我已准备好帮你构建本体。请先上传文档或告诉我你想构建什么领域的本体。' }}</p>
            </div>
            <div v-for="(msg, idx) in chatMessages" :key="idx" class="chat-msg"
              :class="msg.role === 'user' ? 'chat-msg--user' : 'chat-msg--ai'">
              <div class="msg-avatar">
                <el-avatar :size="32" v-if="msg.role === 'user'">我</el-avatar>
                <el-avatar :size="32" v-else style="background: var(--primary-500)">AI</el-avatar>
              </div>
              <div class="msg-body">
                <div class="msg-content" v-html="renderMsgContent(msg)"></div>
                <!-- 消息级后台任务状态标签：随消息常显，running 实时刷新，完成后保持终态 -->
                <div v-if="msg.task" class="task-tag" :class="'task-tag--' + msg.task.status">
                  <template v-if="msg.task.status === 'running'">
                    <el-icon class="task-tag-icon is-running"><Loading /></el-icon>
                    <span class="task-tag-stage">{{ taskStageLabel(msg.task.stage) }}</span>
                    <span v-if="taskProgressText(msg.task) != null" class="task-tag-percent">{{ taskProgressText(msg.task) }}</span>
                    <span class="task-tag-message">{{ taskLiveMessage(msg.task) }}</span>
                  </template>
                  <template v-else-if="msg.task.status === 'done'">
                    <el-icon class="task-tag-icon is-done"><CircleCheckFilled /></el-icon>
                    <span class="task-tag-stage">{{ taskStageLabel(msg.task.stage) }} 完成</span>
                    <span v-if="msg.task.result_summary" class="task-tag-message">{{ msg.task.result_summary }}</span>
                  </template>
                  <template v-else>
                    <el-icon class="task-tag-icon is-failed"><CircleCloseFilled /></el-icon>
                    <span class="task-tag-stage">{{ taskStageLabel(msg.task.stage) }} 失败</span>
                    <span v-if="msg.task.result_summary" class="task-tag-message">{{ msg.task.result_summary }}</span>
                  </template>
                </div>
                <div class="msg-time">{{ msg.created_at ? formatTime(msg.created_at) : '' }}</div>
              </div>
            </div>
            <!-- 输入中指示器 -->
            <div v-if="replying" class="chat-msg chat-msg--ai">
              <div class="msg-avatar">
                <el-avatar :size="32" style="background: var(--primary-500)">AI</el-avatar>
              </div>
              <div class="msg-body">
                <div class="typing-indicator"><span></span><span></span><span></span></div>
              </div>
            </div>
          </div>
          <div class="chat-input">
            <div class="input-wrapper">
              <el-input v-model="chatInput" type="textarea" :rows="2" placeholder="输入消息...（支持上传文档、编辑本体、确认步骤等）"
                @keydown.enter.exact="sendMessage" :disabled="replying" />
              <div class="input-actions">
                <input
                  ref="fileInputRef"
                  type="file"
                  accept=".pdf,.doc,.docx,.txt,.md"
                  style="display: none"
                  @change="onFileChange"
                />
                <el-tooltip content="上传文档 (PDF/Word/TXT/Markdown)" placement="top">
                  <el-button
                    circle
                    :icon="Upload"
                    :disabled="replying"
                    @click="triggerFileUpload"
                  />
                </el-tooltip>
                <el-tooltip :content="isListening ? '停止录音' : '语音输入'" placement="top">
                  <el-button
                    circle
                    :type="isListening ? 'danger' : 'default'"
                    :icon="Microphone"
                    @click="toggleSpeech"
                  />
                </el-tooltip>
                <el-button type="primary" :loading="replying" @click="sendMessage" :disabled="!chatInput.trim()">
                  <el-icon><Promotion /></el-icon> 发送
                </el-button>
              </div>
            </div>
            <!-- 附件标签 -->
            <div v-if="attachments.length > 0" class="attachment-chips">
              <el-tag
                v-for="(att, idx) in attachments"
                :key="idx"
                :type="att.status === 'success' ? 'success' : att.status === 'uploading' ? 'warning' : 'danger'"
                closable
                size="small"
                @close="removeAttachment(idx)"
              >
                <el-icon v-if="att.status === 'uploading'"><Loading /></el-icon>
                {{ att.filename }}
              </el-tag>
            </div>
          </div>
        </div>

        <!-- 右侧：上阶段 + 下图谱 -->
        <div class="right-panel">
          <!-- 上方：构建阶段 -->
          <div class="stage-panel">
            <h4>构建阶段</h4>
            <el-steps :active="stageActive" finish-status="process" align-center class="build-steps">
              <el-step title="文档解析" :status="getStageStatus(0)" />
              <el-step title="类型提取" :status="getStageStatus(1)" />
              <el-step title="实体提取" :status="getStageStatus(2)" />
              <el-step title="分析验证" :status="getStageStatus(3)" />
            </el-steps>
            <div class="stage-summary">
              <p v-if="currentState.progress_message">{{ currentState.progress_message }}</p>
              <div class="summary-stats">
                <span>实体类型: {{ (currentState.entity_types || []).length }}</span>
                <span>实体: {{ (currentState.entities || []).length }}</span>
                <span>关系: {{ (currentState.relations || []).length }}</span>
              </div>
            </div>
          </div>

          <!-- 下方：知识图谱 -->
          <div class="graph-panel">
            <div class="graph-toolbar">
              <h4>知识图谱</h4>
              <div class="graph-controls">
                <el-button size="small" @click="graphZoomIn"><el-icon><ZoomIn /></el-icon></el-button>
                <el-button size="small" @click="graphZoomOut"><el-icon><ZoomOut /></el-icon></el-button>
                <el-button size="small" @click="graphResetZoom">重置</el-button>
                <el-button size="small" type="primary" @click="graphExpandAll">
                  <el-icon><Expand /></el-icon> 一键展开
                </el-button>
                <el-button size="small" type="warning" :disabled="!expandedTypeIds.size" @click="graphResetExpand">
                  <el-icon><Fold /></el-icon> 收起全部（{{ expandedTypeIds.size }}）
                </el-button>
                <el-tooltip content="进入图谱全屏页面（展示当前构建图谱）" placement="top">
                  <el-button size="small" @click="gotoGraphDetail">
                    <el-icon><FullScreen /></el-icon> 图谱详情页
                  </el-button>
                </el-tooltip>
              </div>
            </div>
            <div class="graph-hint">左键父类型→分解为子类型，左键叶子类型→分解为实体；右键任意节点→收起上一层</div>
            <div class="graph-wrapper">
              <div ref="graphRef" class="graph-container"></div>
              <div class="graph-legend-overlay">
                <div v-for="t in graphLegend" :key="t.name" class="legend-item">
                  <span class="legend-dot" :style="{ background: t.color }"></span>
                  <span>{{ t.name }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 加载中 -->
      <div v-else class="loading-state">
        <el-icon class="is-loading" :size="48"><Loading /></el-icon>
        <p>加载任务中...</p>
      </div>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ArrowLeft, Refresh, ChatDotRound, Loading, Upload, Microphone, Promotion, ZoomIn, ZoomOut, Fold, CircleCheckFilled, CircleCloseFilled, Expand, FullScreen } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import CurrentStatePanel from '@/components/CurrentStatePanel.vue'
import { buildRawGraphDataFromState } from '@/utils/ontologyGraph'
import { getBuildJob, getBuildProgress, chatStream as chatStreamApi, getChatHistory, completeBuildJob, streamBuildJob, uploadBuildFile } from '@/services/ontologyBuild'

const router = useRouter()
const route = useRoute()
const jobId = route.params.jobId as string

// ── 任务数据 ──
const job = ref<any>(null)
const currentState = ref<any>({})
const isReopen = computed(() => job.value?.build_type === 'ai_build_reopen')

// ── 聊天数据 ──
const chatMessages = ref<any[]>([])
const chatInput = ref('')
const replying = ref(false)
const completing = ref(false)
const chatMessagesRef = ref<HTMLElement>()

// ── 图谱 ──
const graphRef = ref<HTMLElement>()
let chartInstance: echarts.ECharts | null = null
let buildStreamAbort: (() => void) | null = null
let graphResizeObserver: ResizeObserver | null = null

// ── 文件上传 ──
const fileInputRef = ref<HTMLInputElement>()
const attachments = ref<Array<{ filename: string; status: string; error?: string }>>([])

const triggerFileUpload = () => {
  fileInputRef.value?.click()
}

const onFileChange = async (e: Event) => {
  const input = e.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const att: { filename: string; status: string; error?: string } = { filename: file.name, status: 'uploading' }
  attachments.value.push(att)
  try {
    const res: any = await uploadBuildFile(jobId, file)
    att.status = 'success'
    ElMessage.success(`文档「${file.name}」上传成功，${res.message || ''}`)
  } catch (e: any) {
    att.status = 'error'
    console.error('文件上传失败:', e)
    const msg = e?.serverMessage || e?.message || e?.response?.data?.detail || '上传失败'
    att.error = msg
    ElMessage.error(`文档「${file.name}」${msg}`)
  }
  input.value = ''
}

const removeAttachment = (idx: number) => {
  attachments.value.splice(idx, 1)
}

// ── 语音输入 ──
const isListening = ref(false)

const toggleSpeech = () => {
  if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
    ElMessage.warning('当前浏览器不支持语音识别')
    return
  }
  if (isListening.value) {
    stopSpeech()
  } else {
    startSpeech()
  }
}

let speechRecognition: any = null

const startSpeech = () => {
  const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
  speechRecognition = new SpeechRecognition()
  speechRecognition.lang = 'zh-CN'
  speechRecognition.continuous = false
  speechRecognition.interimResults = false
  speechRecognition.onresult = (event: any) => {
    const transcript = event.results[0][0].transcript
    chatInput.value = chatInput.value ? chatInput.value + ' ' + transcript : transcript
    isListening.value = false
  }
  speechRecognition.onerror = () => {
    isListening.value = false
    ElMessage.warning('语音识别失败，请重试')
  }
  speechRecognition.onend = () => {
    isListening.value = false
  }
  speechRecognition.start()
  isListening.value = true
}

const stopSpeech = () => {
  if (speechRecognition) {
    speechRecognition.stop()
  }
  isListening.value = false
}

// ── 阶段状态 ──
const stageActive = computed(() => {
  const st = currentState.value
  if (!st || st.running_step === -1) return 4
  return st.running_step
})

const getStageStatus = (step: number) => {
  const st = currentState.value
  if (!st) return 'wait'
  const confirmed = [st.meta_confirmed, st.step1_confirmed, st.step2_confirmed, st.step3_confirmed]
  if (confirmed[step]) return 'success'
  if (step < stageActive.value) return 'process'
  if (step === stageActive.value && st.running_step === step) return 'process'
  return 'wait'
}

// ── 初始化 ──
onMounted(async () => {
  await loadJob()
  await loadHistory()
  // 订阅后台构建进度（非聊天场景，如 extract_type 后台任务）
  subscribeBuildStream()
})

onUnmounted(() => {
  // 停止 SSE 订阅与重连计划
  buildStreamStopped = true
  if (buildStreamRetryTimer != null) {
    window.clearTimeout(buildStreamRetryTimer)
    buildStreamRetryTimer = null
  }
  buildStreamAbort?.()
  // 清理后台任务状态轮询定时器
  if (taskPollTimer != null) {
    window.clearInterval(taskPollTimer)
    taskPollTimer = null
  }
  stopSpeech()
  if (graphResizeObserver) {
    graphResizeObserver.disconnect()
    graphResizeObserver = null
  }
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
})

// 页面卸载时通过浏览器 beforeunload 清理
window.addEventListener('beforeunload', () => {
  buildStreamAbort?.()
})

const loadJob = async () => {
  try {
    const res = await getBuildJob(jobId)
    job.value = res.data
    // 从 job 初始化当前状态
    if (job.value) {
      currentState.value = {
        running_step: job.value.running_step,
        progress: job.value.progress,
        progress_message: job.value.progress_message,
        // 阶段时间线（权威状态）：供 reconcileTaskTags 对账翻转卡死的任务标签
        progress_stages: job.value.progress_stages,
        meta_confirmed: job.value.meta_confirmed,
        step1_confirmed: job.value.step1_confirmed,
        step2_confirmed: job.value.step2_confirmed,
        step3_confirmed: job.value.step3_confirmed,
        // 各阶段批次进度（任务标签显示「X/Y 批」用）
        step1_batches_done: job.value.step1_batches_done,
        step1_batches_total: job.value.step1_batches_total,
        step2_batches_done: job.value.step2_batches_done,
        step2_batches_total: job.value.step2_batches_total,
        step3_groups_done: job.value.step3_groups_done,
        step3_groups_total: job.value.step3_groups_total,
        entity_types: job.value.step1_entity_types || job.value.step1_concepts || [],
        entity_type_relations: job.value.step1_entity_type_relations || [],
        entities: job.value.step2_entities || [],
        relations: job.value.step3_relations || job.value.step2_relations || [],
        verification: job.value.step3_verification || job.value.step4_verification,
        ontology_id: job.value.ontology_id,
        error_message: job.value.error_message,
        status: job.value.status,
      }
      // 全量加载后对账：翻掉历史卡 running 的任务标签
      reconcileTaskTags()
      nextTick(() => rebuildAndRenderGraph())
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载任务失败')
  }
}

const loadHistory = async () => {
  try {
    const res = await getChatHistory(jobId)
    const data = res.data
    if (data?.chat_history) {
      chatMessages.value = data.chat_history
        .filter((m: any) => m.role === 'user' || m.role === 'assistant')
        .map((m: any) => ({
          role: m.role,
          content: m.content,
          intent: m.intent,
          // 消息级任务标签（running/done/failed），随消息持久化，刷新后照常渲染
          task: m.task || null,
          created_at: m.created_at,
        }))
    }
    if (data?.state) {
      currentState.value = { ...currentState.value, ...data.state }
    }
    // 历史加载后若任务在跑但无标签（非聊天入口启动），补兜底标签
    ensureRunningTaskTag()
    await nextTick()
    scrollToBottom()
    rebuildAndRenderGraph()
  } catch (e: any) {
    console.error('加载聊天历史失败:', e)
  }
}

// ── 发送消息 ──
const sendMessage = async () => {
  const msg = chatInput.value.trim()
  if (!msg || replying.value) return

  // 添加用户消息
  chatMessages.value.push({ role: 'user', content: msg, created_at: new Date().toISOString() })
  chatInput.value = ''
  replying.value = true
  await nextTick()
  scrollToBottom()

  chatStreamApi(jobId, msg, {
    onChatStatus: (d) => {
      console.log('[Chat]', d.status, d.message)
    },
    onChatReply: (d) => {
      // 真实回复自带任务标签：先移除同阶段的本地兜底消息（intent=task_start，不入库），
      // 避免兜底「已开始XX...」与真实回复并存被当成重复回答；再做内容级去重追加
      if (d.task?.stage !== undefined) {
        chatMessages.value = chatMessages.value.filter(
          (m: any) => !(m.intent === 'task_start' && m.task?.stage === d.task.stage)
        )
      }
      pushAssistantMessage({
        role: 'assistant',
        content: d.reply,
        intent: d.intent,
        // 后端本轮启动了后台任务时携带任务标记，前端在该消息下渲染常显状态标签
        task: d.task || null,
        created_at: new Date().toISOString(),
      })
      replying.value = false
      // 回复已落地：若本轮启动了后台任务但回复未携带标签（异常场景），补兜底标签；
      // 正常情况下回复自带标签，此调用为幂等空操作
      ensureRunningTaskTag()
      nextTick(() => {
        scrollToBottom()
        rebuildAndRenderGraph()
      })
    },
    onStateUpdate: (d) => {
      if (!d) return
      const patch = { ...d }
      // 后台任务刚启动时 state_update 携带空实体数组，避免清空已显示内容：
      // 运行中（当前或本事件显示 running_step>=0）跳过空数组覆盖
      const incomingRunning = patch.running_step !== undefined && patch.running_step !== -1
      if (taskRunning.value || incomingRunning) {
        for (const k of ['entity_types', 'entity_type_relations', 'entities', 'relations']) {
          if (Array.isArray(patch[k]) && patch[k].length === 0) delete patch[k]
        }
      }
      currentState.value = { ...currentState.value, ...patch }
      nextTick(() => rebuildAndRenderGraph())
      // chat 触发了后台任务（running_step>=0）：确保 SSE 订阅在线，增量事件不丢
      if (incomingRunning) {
        ensureBuildStreamConnected?.()
      }
    },
    onGraphUpdate: () => {
      // 统一从 currentState 重建图谱，保证与面板/LLM 同源。
      // 后端 graph_update 的节点字段（entity_type/instance_of）与前端
      // buildRawGraphData（type/concept_id）不一致，直接使用会导致 category
      // 映射失败、全部节点落到灰色 fallback。
      nextTick(() => rebuildAndRenderGraph())
    },
    onChatError: (d) => {
      ElMessage.error(d.error || '对话失败')
      replying.value = false
      // 回复失败也要补查兜底标签：本轮可能已启动后台任务（state_update 先于错误到达），
      // 不补查会导致任务在跑但聊天无标签
      ensureRunningTaskTag()
    },
    onChatDone: () => {
      replying.value = false
      // AI 回复后可能触发后台任务，立即刷新一次进度以点亮状态卡片
      loadJobSnapshot()
    },
  })
}

// ── 渲染消息内容 ──
const renderMsgContent = (msg: any) => {
  if (!msg.content) return ''
  // 轻量 markdown：**加粗**、段落分隔线（摘要消息使用），其余按换行渲染
  return msg.content
    .replace(/\n---\n/g, '<hr class="msg-hr">')
    .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
    .replace(/\n/g, '<br>')
}

// 统一追加 assistant 气泡（内容级幂等去重）：
// SSE 双订阅/事件重放/兜底与真实回复并存等场景可能把同一内容推两次，
// 与最后一条 assistant 消息内容完全相同时跳过（刷新后 /history 也会去重，保持一致）
const pushAssistantMessage = (msg: any) => {
  const last = chatMessages.value[chatMessages.value.length - 1]
  if (last && last.role === 'assistant' && last.content === msg.content) {
    return false
  }
  chatMessages.value.push(msg)
  return true
}

// ── 后台构建进度订阅 ──
// 支持断线自动重连：后端 /stream 在补发终态后会关闭连接，服务重启/网络抖动也会断开；
// 不重连会导致后续任务的 batch_done/step_done 事件全部丢失，任务状态卡片进度停滞
let buildStreamStopped = false
let buildStreamRetryTimer: number | null = null
let buildStreamRetryDelay = 2000 // 重连退避：2s → 4s → 8s（上限 10s），连接成功后归位
let buildStreamConnected = false
// 任务启动时若 SSE 已断开（后端推完终态会关连接）则立即重建订阅，供外部调用
let ensureBuildStreamConnected: (() => void) | null = null
const subscribeBuildStream = () => {
  const scheduleReconnect = (immediate = false) => {
    if (buildStreamStopped || buildStreamRetryTimer != null) return
    const delay = immediate ? 0 : buildStreamRetryDelay
    buildStreamRetryTimer = window.setTimeout(() => {
      buildStreamRetryTimer = null
      if (!buildStreamStopped) connectBuildStream()
    }, delay)
    if (!immediate) buildStreamRetryDelay = Math.min(buildStreamRetryDelay * 2, 10000)
  }
  const connectBuildStream = () => {
    buildStreamAbort = streamBuildJob(jobId, {
      onState: (s) => {
        if (s === 'open') {
          buildStreamConnected = true
          buildStreamRetryDelay = 2000 // 连接成功，重置退避
        } else {
          buildStreamConnected = false
        }
      },
      onParseDone: () => {
        // 阶段 0 文档解析完成：刷新状态（meta 候选 + running_step 归位）；
        // 兜底翻转 stage0 标签（断线回放时 chat_message 可能已错过，幂等）
        flipTaskTag(0, 'done', '文档解析完成')
        loadJobSnapshot()
      },
      onChatMessage: (d) => {
        // 后台任务推送的聊天消息：先应用任务标签状态更新（翻 done/failed），
        // 再追加消息气泡（message 为空时仅翻标签，如阶段 0 解析收尾）
        const upd = d?.task_update
        if (upd) {
          flipTaskTag(upd.stage, upd.status === 'failed' ? 'failed' : 'done', upd.result_summary || '')
        }
        const msg = d?.message
        if (msg?.content) {
          // 内容级去重：SSE 双订阅/重连回放可能把同一 chat_message 投递两次
          pushAssistantMessage({ role: 'assistant', content: msg.content, intent: msg.intent })
        }
        nextTick(() => scrollToBottom())
      },
      onBatchDone: (d) => {
      // 后台任务每批完成：SSE 事件数据累积合并进 currentState
      // （并行批次到达顺序不定，按名称/三元组去重累积，避免逐批覆盖导致闪烁或空白）
      if (d) {
        // 批次进度即时更新（不等 2.5s 轮询），供任务标签「X/Y 批」显示
        if (d.batches_total > 1 && typeof d.batches_done === 'number') {
          const patch: any = {}
          if (d.entity_types || d.concepts) {
            patch.step1_batches_done = d.batches_done
            patch.step1_batches_total = d.batches_total
          } else if (d.entities) {
            patch.step2_batches_done = d.batches_done
            patch.step2_batches_total = d.batches_total
          }
          if (Object.keys(patch).length) {
            currentState.value = { ...currentState.value, ...patch }
          }
        }
        if (d.concepts || d.entity_types) {
          const batchTypes = d.concepts || d.entity_types || []
          const typeByName = new Map(
            (currentState.value.entity_types || []).map((t: any) => [t.name, t])
          )
          batchTypes.forEach((t: any) => typeByName.set(t.name, t))
          currentState.value = {
            ...currentState.value,
            entity_types: [...typeByName.values()],
          }
        }
        if (d.entity_type_relations) {
          const relByKey = new Map(
            (currentState.value.entity_type_relations || []).map((r: any) => [
              `${r.source_entity_type_name}|${r.target_entity_type_name}|${r.relation_type}`,
              r,
            ])
          )
          d.entity_type_relations.forEach((r: any) => {
            relByKey.set(`${r.source_entity_type_name}|${r.target_entity_type_name}|${r.relation_type}`, r)
          })
          currentState.value = {
            ...currentState.value,
            entity_type_relations: [...relByKey.values()],
          }
        }
        if (d.entities) {
          const entByName = new Map(
            (currentState.value.entities || []).map((e: any) => [e.name, e])
          )
          d.entities.forEach((e: any) => entByName.set(e.name, e))
          currentState.value = {
            ...currentState.value,
            entities: [...entByName.values()],
          }
        }
        if (d.relations) {
          const relByKey = new Map(
            (currentState.value.relations || []).map((r: any) => [
              `${r.source}|${r.target}|${r.relation_type}`,
              r,
            ])
          )
          d.relations.forEach((r: any) => {
            relByKey.set(`${r.source}|${r.target}|${r.relation_type}`, r)
          })
          currentState.value = {
            ...currentState.value,
            relations: [...relByKey.values()],
          }
        }
        nextTick(() => rebuildAndRenderGraph())
      }
      // 同时刷新进度字段
      loadJobSnapshot()
    },
    onStepDone: (d) => {
      // 后台任务全部完成：step_done 携带合并后的权威全量结果，直接整体替换
      if (d) {
        const patch: any = {}
        if (d.concepts || d.entity_types) patch.entity_types = d.concepts || d.entity_types
        if (d.entity_type_relations) patch.entity_type_relations = d.entity_type_relations
        if (d.entities) patch.entities = d.entities
        if (d.relations) patch.relations = d.relations
        if (Object.keys(patch).length) {
          currentState.value = { ...currentState.value, ...patch }
        }
        nextTick(() => rebuildAndRenderGraph())
        // 兜底翻转对应阶段标签（断线回放时 chat_message 可能已错过，幂等）
        const stage = d.step
        if (typeof stage === 'number' && stage >= 1 && stage <= 3) {
          const summary = stage === 1
            ? `共 ${d.entity_types?.length ?? d.total ?? 0} 个类型`
            : stage === 2
              ? `共 ${d.entities?.length ?? d.total ?? 0} 个实体、${d.relations?.length ?? 0} 条关系`
              : (d.verification
                ? `通过 ${d.verification.verified_count ?? '?'} 项，存疑 ${d.verification.suspect_count ?? '?'} 项`
                : '')
          flipTaskTag(stage, 'done', summary)
        }
      }
      // 同时刷新进度字段
      loadJobSnapshot()
    },
    onError: (d) => {
      if (d?.reconnect) {
        // 连接断开/异常：静默重连，不打扰用户
        scheduleReconnect()
        return
      }
      // 任务失败：翻对应阶段标签为 failed（后端 chat_message 未达或断线时的兜底，幂等）
      if (typeof d?.step === 'number' && d.step >= 0 && d.step <= 3) {
        flipTaskTag(d.step, 'failed', d.message || '任务失败')
      }
      if (d?.message) {
        ElMessage.warning(d.message)
      }
    },
    })
  }
  ensureBuildStreamConnected = () => {
    // 新任务已启动（running_step>=0）但 SSE 断开：立即重连订阅增量事件
    if (!buildStreamConnected) scheduleReconnect(true)
  }
  connectBuildStream()
}

const loadJobSnapshot = async () => {
  try {
    const res = await getBuildProgress(jobId)
    const j = res.data
    if (j) {
      job.value = { ...job.value, ...j }
      // 只更新进度字段，保留已有的实体数据（/progress 接口不返回实体数据）
      currentState.value = {
        ...currentState.value,
        running_step: j.running_step,
        progress: j.progress,
        progress_message: j.progress_message,
        // 阶段时间线（权威状态）：供 reconcileTaskTags 对账翻转卡死的任务标签
        progress_stages: j.progress_stages,
        meta_confirmed: j.meta_confirmed,
        step1_confirmed: j.step1_confirmed,
        step2_confirmed: j.step2_confirmed,
        step3_confirmed: j.step3_confirmed,
        // 各阶段批次进度（任务标签显示「X/Y 批」用）
        step1_batches_done: j.step1_batches_done,
        step1_batches_total: j.step1_batches_total,
        step2_batches_done: j.step2_batches_done,
        step2_batches_total: j.step2_batches_total,
        step3_groups_done: j.step3_groups_done,
        step3_groups_total: j.step3_groups_total,
        // 只有 /progress 明确返回了实体数据时才更新，否则保留现有数据
        ...(j.step1_entity_types != null || j.step1_concepts != null ? { entity_types: j.step1_entity_types || j.step1_concepts } : {}),
        ...(j.step1_entity_type_relations != null ? { entity_type_relations: j.step1_entity_type_relations } : {}),
        ...(j.step2_entities != null ? { entities: j.step2_entities } : {}),
        ...(j.step2_relations != null || j.step3_relations != null ? { relations: j.step3_relations || j.step2_relations } : {}),
        verification: j.step3_verification || j.step4_verification,
        ontology_id: j.ontology_id,
        error_message: j.error_message,
        status: j.status,
      }
      // 对账：阶段已终结但标签还卡 running（SSE 终态事件丢失）时兜底翻转
      reconcileTaskTags()
      nextTick(() => rebuildAndRenderGraph())
      // 任务启动但 SSE 已断开（上一任务终态后后端关闭了连接）：立即重连订阅增量事件
      if (j.running_step !== undefined && j.running_step !== -1) {
        ensureBuildStreamConnected?.()
      }
    }
  } catch (e) {
    // 静默忽略轮询失败
  }
}

// ── 后台任务状态（消息级常显标签 + 轮询驱动实时进度）──
const STAGE_NAMES = ['文档解析', '类型提取', '实体提取', '分析验证']
// running_step: -1=空闲, 0=文档解析, 1=类型提取, 2=实体提取, 3=分析验证
const taskRunning = computed(() =>
  currentState.value?.running_step !== undefined && currentState.value?.running_step !== -1
)
// 消息标签：阶段名
const taskStageLabel = (stage: number) => STAGE_NAMES[stage] || '后台处理'
// 任务标签进度文本：有批次/分组的阶段显示「X/Y 批」「X/Y 组」（直观、与实际提取一致），
// 无批次概念的阶段（文档解析、验证内部步骤）回退百分比
const taskProgressText = (task: any) => {
  if (task.status !== 'running' || currentState.value?.running_step !== task.stage) return null
  const st = currentState.value as any
  if (task.stage === 1 && st.step1_batches_total > 1) {
    return `${st.step1_batches_done ?? 0}/${st.step1_batches_total} 批`
  }
  if (task.stage === 2 && st.step2_batches_total > 1) {
    return `${st.step2_batches_done ?? 0}/${st.step2_batches_total} 批`
  }
  if (task.stage === 3 && st.step3_groups_total > 1) {
    return `${st.step3_groups_done ?? 0}/${st.step3_groups_total} 组`
  }
  return `${Math.min(100, Math.max(0, st.progress || 0))}%`
}
const taskLiveMessage = (task: any) =>
  task.status === 'running' && currentState.value?.running_step === task.stage
    ? (currentState.value?.progress_message || 'AI 正在处理...')
    : ''

// 翻转任务标签终态：把该 stage 所有 running 标签消息翻成 done/failed（幂等）。
// 翻全部而非仅最后一条：历史 bug/重复消息可能留下多条同 stage 的 running 标签
const flipTaskTag = (stage: number, status: 'done' | 'failed', resultSummary = '') => {
  let flipped = false
  for (let i = chatMessages.value.length - 1; i >= 0; i--) {
    const m = chatMessages.value[i]
    if (m?.task?.stage === stage && m.task.status === 'running') {
      m.task = { ...m.task, status, result_summary: resultSummary }
      flipped = true
    }
  }
  return flipped
}

// 轮询对账：SSE 静默断连时终态事件（chat_message 翻标签/step_done）会丢，
// 任务标签卡 running。用 /progress 返回的 progress_stages 权威状态兜底翻转：
// 阶段状态已 done/failed 且不是当前运行阶段 → 幂等翻转对应标签（不依赖 SSE）
const reconcileTaskTags = () => {
  const stages = currentState.value?.progress_stages
  if (!Array.isArray(stages)) return
  const runningStep = currentState.value?.running_step
  for (const st of stages) {
    if (!st || st.stage === runningStep) continue
    if (st.status === 'done') flipTaskTag(st.stage, 'done', '')
    else if (st.status === 'failed') flipTaskTag(st.stage, 'failed', '')
  }
}

// 兜底标签：任务在跑但聊天中无对应 running 标签时补一条本地消息
// （覆盖「新建任务上传文档」直接启动解析、不经聊天的入口；本地消息不入库，
// 完成时仍靠 chat_message 的 task_update 翻转终态）
const ensureRunningTaskTag = () => {
  // 聊天回复进行中跳过：后端 chat 流先推 state_update(running_step>=0) 再推 chat_reply，
  // 此刻真回复（自带任务标签）尚未落地，兜底消息会与回复重复出现（两条「已开始XX」）；
  // 回复落地/失败后由 onChatReply/onChatError 再补查
  if (replying.value) return
  const stage = currentState.value?.running_step
  if (stage === undefined || stage === -1) return
  const exists = chatMessages.value.some(
    (m: any) => m?.task?.stage === stage && m.task.status === 'running'
  )
  if (!exists) {
    chatMessages.value.push({
      role: 'assistant',
      content: `已开始${taskStageLabel(stage)}，正在后台处理...`,
      intent: 'task_start',
      task: { stage, status: 'running' },
      created_at: new Date().toISOString(),
    })
    nextTick(() => scrollToBottom())
  }
}

// 任务运行期间轮询 /progress（后端 SSE 只推批完成事件，批内进度靠轮询补齐）
let taskPollTimer: number | null = null
watch(taskRunning, (running) => {
  if (running) {
    if (taskPollTimer == null) {
      taskPollTimer = window.setInterval(loadJobSnapshot, 2500)
    }
    // 任务在跑但聊天无对应标签（非聊天入口启动/历史未带）时补兜底标签
    ensureRunningTaskTag()
    nextTick(() => scrollToBottom())
  } else if (taskPollTimer != null) {
    window.clearInterval(taskPollTimer)
    taskPollTimer = null
    // 任务结束：全量刷新任务（/progress 不含实体数据，须拉全量保证
    // 顶部下拉/图谱与后端最终结果一致，覆盖 SSE 事件丢失的场景）
    loadJob()
  }
}, { immediate: true })

// ── 完成构建 ──
const completeBuild = async () => {
  try {
    completing.value = true
    await completeBuildJob(jobId)
    ElMessage.success('本体构建完成！')
    // 重新加载
    await loadJob()
    await loadHistory()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '完成构建失败')
  } finally {
    completing.value = false
  }
}

// ── 图谱渲染（复用 OntologyDetail 分解/合并交互逻辑）──
// rawGraphData 缓存当前状态的原始图谱数据，expandedTypeIds 记录已分解的类型 ID
const rawGraphData = ref<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] })
const expandedTypeIds = ref<Set<string>>(new Set())
// 图例（右上角浮层，与图谱详情页样式统一）
const graphLegend = ref<{ name: string; color: string }[]>([])

/** 从 currentState 构建原始图谱数据（公共转换逻辑见 utils/ontologyGraph.ts） */
const buildRawGraphData = () => buildRawGraphDataFromState(currentState.value)

/** 渲染图谱（父→子→实体 逐层下钻，父子/类型实例两两互斥） */
const renderGraph = () => {
  if (!graphRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(graphRef.value)
    // 阻止默认右键菜单，让 ECharts contextmenu 事件生效
    graphRef.value.addEventListener('contextmenu', (e) => e.preventDefault())
    // 注册图谱交互事件
    chartInstance.on('contextmenu', handleGraphContextMenu)
    chartInstance.on('click', handleGraphClick)
    // 监听容器尺寸变化自动 resize
    if (!graphResizeObserver) {
      graphResizeObserver = new ResizeObserver(() => chartInstance?.resize())
      graphResizeObserver.observe(graphRef.value)
    }
  }
  chartInstance.resize()

  const raw = rawGraphData.value
  if (!raw.nodes.length) {
    chartInstance.clear()
    return
  }

  const expanded = expandedTypeIds.value
  const isExpanded = (typeId?: string) => !!typeId && expanded.has(typeId)

  // 预索引
  const typeNodes = raw.nodes.filter((n: any) => n.node_type === 'concept')
  const entityNodes = raw.nodes.filter((n: any) => n.node_type === 'entity')
  const typeNodeById: Record<string, any> = {}
  for (const n of typeNodes) typeNodeById[n.id] = n
  const entityById: Record<string, any> = {}
  for (const e of entityNodes) entityById[e.id] = e

  // 顶层类型 id 列表（parentId 为空）
  const topLevelTypeIds = typeNodes.filter((n: any) => !n.parentId).map((n: any) => n.id)

  // 类别映射（按 entity_type 名称着色）
  const cats: any[] = []
  const catIndex: Record<string, number> = {}
  const typeNames = [...new Set(typeNodes.map((n: any) => n.type).filter(Boolean))]
  typeNames.forEach((name: string, i: number) => {
    catIndex[name] = i
    const tn = typeNodes.find((n: any) => n.type === name)
    cats.push({ name: name as string, itemStyle: { color: tn?.color || '#409eff' } })
  })
  const fallbackCatIndex = cats.length
  cats.push({ name: '[未分类]', itemStyle: { color: '#909399' } })
  // 图例数据（右上角浮层，与图谱详情页样式统一）
  graphLegend.value = typeNames.map((name: string) => ({
    name,
    color: typeNodes.find((n: any) => n.type === name)?.color || '#409eff',
  }))

  // 全量 id→name 映射
  const idToName: Record<string, string> = {}
  for (const n of raw.nodes) idToName[n.id] = n.name

  // 每个类型拥有的实例数
  const instanceCount: Record<string, number> = {}
  for (const e of entityNodes) {
    if (e.concept_id) instanceCount[e.concept_id] = (instanceCount[e.concept_id] || 0) + 1
  }

  // 类型节点当前是否作为节点可见（父链上均已展开、且自身未展开）
  const isTypeVisible = (typeId: string): boolean => {
    const tn = typeNodeById[typeId]
    if (!tn) return false
    if (isExpanded(typeId)) return false
    if (!tn.parentId) return true
    return isExpanded(tn.parentId)
  }

  // 实体的可见代表：实体显示则返回实体 id，否则返回最近可见的类型祖先节点 id
  const visibleRepOfEntity = (e: any): string | null => {
    const typeId = e.concept_id
    if (!typeId) return e.id
    // 叶子类型已展开 → 实体显示；若该类型有子类型（实体挂在中间类型）则实体被折叠
    if (isExpanded(typeId)) {
      return (typeNodeById[typeId]?.children?.length) ? null : e.id
    }
    // 未展开 → 递归向上找可见类型祖先
    let cur = typeId
    while (cur && typeNodeById[cur]) {
      if (isTypeVisible(cur)) return cur
      cur = typeNodeById[cur].parentId
    }
    return cur || null
  }

  // ── 节点：从顶层类型递归下钻，父/子/实例互斥 ──
  const displayNodes: any[] = []
  const walkType = (typeId: string) => {
    const tn = typeNodeById[typeId]
    if (!tn) return
    if (!isExpanded(typeId)) {
      // 收起态：显示类型节点
      displayNodes.push({
        name: tn.name,
        id: tn.id,
        category: catIndex[tn.type] ?? fallbackCatIndex,
        symbolSize: 50,
        draggable: true,
        nodeType: 'entityType',
        conceptId: tn.id,
        parentId: tn.parentId,
        childCount: (tn.children || []).length,
        itemStyle: { borderColor: '#333', borderWidth: 2 },
        label: { fontWeight: 'bold' },
      })
      return
    }
    const children = tn.children || []
    if (children.length) {
      // 有子类型 → 分解为子类型
      children.forEach(walkType)
    } else {
      // 叶子类型 → 分解为实体
      for (const e of entityNodes) {
        if (e.concept_id === typeId) {
          displayNodes.push({
            name: e.name,
            id: e.id,
            category: catIndex[e.type] ?? fallbackCatIndex,
            symbolSize: 32,
            draggable: true,
            nodeType: 'entity',
            conceptId: e.concept_id,
            itemStyle: { borderColor: '#fff', borderWidth: 1.5 },
          })
        }
      }
    }
  }
  topLevelTypeIds.forEach(walkType)

  // 可见节点集合
  const visibleNodeIds = new Set(displayNodes.map(n => n.id))

  // ── 边：连接两端各自的可见代表，去重去自环 ──
  const displayLinks: any[] = []
  const seenEdges = new Set<string>()
  const pushEdge = (srcId: string | null, tgtId: string | null, relation: string, dashed = false) => {
    if (!srcId || !tgtId || srcId === tgtId) return
    if (!visibleNodeIds.has(srcId) || !visibleNodeIds.has(tgtId)) return
    const edgeKey = `${srcId}-${tgtId}-${relation}`
    if (seenEdges.has(edgeKey)) return
    seenEdges.add(edgeKey)
    displayLinks.push({
      source: srcId,
      target: tgtId,
      value: relation,
      sourceName: idToName[srcId] || srcId,
      targetName: idToName[tgtId] || tgtId,
      lineStyle: dashed ? { type: 'dashed', width: 1, opacity: 0.45 } : { type: 'solid' },
    })
  }

  for (const l of raw.links) {
    const relation = l.relation
    // 类型级边：两端类型节点均可见时才渲染
    if (typeNodeById[l.source] && typeNodeById[l.target]) {
      pushEdge(l.source, l.target, relation)
      continue
    }
    // 实例归属边（instance_of）：不渲染，靠位置/同色表达
    if (relation === 'instance_of') continue
    // 实体-实体关系边：提升/降级到两端可见代表
    const srcEntity = entityById[l.source]
    const tgtEntity = entityById[l.target]
    if (srcEntity && tgtEntity) {
      const srcRep = visibleRepOfEntity(srcEntity)
      const tgtRep = visibleRepOfEntity(tgtEntity)
      pushEdge(srcRep, tgtRep, relation)
    }
  }

  const option: any = {
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        if (params.dataType === 'edge' || !params.data?.name) {
          const s = params.data?.sourceName || params.data?.source || ''
          const t = params.data?.targetName || params.data?.target || ''
          const v = params.data?.value || params.value || ''
          return `${s} → ${t}${v ? ` (${v})` : ''}`
        }
        const d = params.data
        if (d.nodeType === 'entityType') {
          const tn = typeNodeById[d.conceptId]
          const childCount = (tn?.children || []).length
          const cnt = instanceCount[d.conceptId] || 0
          const parentName = tn?.parent ? `父类型：${tn.parent}<br/>` : ''
          const state = childCount
            ? (isExpanded(d.conceptId) ? '左键收起子类型' : `左键分解为子类型（${childCount} 个）`)
            : (isExpanded(d.conceptId) ? '左键收起实例' : `左键分解为实例（${cnt} 个）`)
          const head = childCount ? `${d.name}（${childCount} 个子类型）` : `${d.name}（${cnt} 个实例）`
          return `${head}<br/>${parentName}<small>${state}</small>`
        }
        return d.name
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      roam: true,
      draggable: true,
      // 样式与图谱详情页（OntologyDetail）统一：标签底部、箭头边、直线边
      label: { show: true, position: 'bottom', fontSize: 12 },
      edgeSymbol: ['circle', 'arrow'],
      edgeSymbolSize: [4, 10],
      data: displayNodes,
      links: displayLinks,
      categories: cats,
      lineStyle: { opacity: 0.6, width: 2, curveness: 0 },
      force: { repulsion: 200, edgeLength: 150 },
      emphasis: { focus: 'adjacency' },
    }],
  }
  chartInstance.setOption(option, true)
}

/** 重建图谱数据并渲染 */
const rebuildAndRenderGraph = () => {
  rawGraphData.value = buildRawGraphData()
  renderGraph()
}

// ── 图谱交互：分解 / 合并 ──

/** 从原始图谱数据查找类型节点（含 parentId/children） */
const getTypeNode = (typeId: string) =>
  rawGraphData.value.nodes.find((n: any) => n.id === typeId && n.node_type === 'concept')

/** 右键实例 → 收回其所属类型；右键子类型 → 收起其父类型（逐层向上收回） */
const handleGraphContextMenu = (params: any) => {
  if (params.dataType !== 'node' || !params.data) return
  const node = params.data
  if (node.nodeType === 'entity' && node.conceptId) {
    collapseType(node.conceptId)
  } else if (node.nodeType === 'entityType') {
    // 子类型：收起父类型；顶层类型：收起自身子树
    collapseType(node.parentId || node.conceptId)
  }
}

/** 左键类型 → 分解（父→子 / 叶子→实例）或收起 */
const handleGraphClick = (params: any) => {
  if (params.dataType !== 'node' || !params.data) return
  const node = params.data
  if (node.nodeType === 'entityType') {
    if (expandedTypeIds.value.has(node.conceptId)) {
      collapseType(node.conceptId)
    } else {
      expandType(node.conceptId)
    }
  }
}

/** 分解类型：有子类型则分解为子类型，否则（叶子）分解为实例 */
const expandType = (typeId: string) => {
  const tn = getTypeNode(typeId)
  const children = tn?.children || []
  if (children.length) {
    const newSet = new Set(expandedTypeIds.value)
    newSet.add(typeId)
    expandedTypeIds.value = newSet
    renderGraph()
    return
  }
  const hasInstances = rawGraphData.value.nodes.some(
    (n: any) => n.node_type === 'entity' && n.concept_id === typeId
  )
  if (!hasInstances) {
    ElMessage.info('该类型暂无实体实例，无法分解')
    return
  }
  const newSet = new Set(expandedTypeIds.value)
  newSet.add(typeId)
  expandedTypeIds.value = newSet
  renderGraph()
}

/** 收回类型：删除其及所有后代的展开状态（级联清理，避免幽灵节点） */
const collapseType = (typeId: string) => {
  const newSet = new Set(expandedTypeIds.value)
  const removeSubtree = (id: string) => {
    newSet.delete(id)
    const tn = getTypeNode(id)
    for (const cid of (tn?.children || [])) removeSubtree(cid)
  }
  removeSubtree(typeId)
  expandedTypeIds.value = newSet
  renderGraph()
}

/** 收起全部实例 */
const graphResetExpand = () => {
  expandedTypeIds.value = new Set()
  renderGraph()
}

/** 一键展开：所有实体类型进入分解态（层级递归下钻到叶子），仅显示实体及实体间关系 */
const graphExpandAll = () => {
  const newSet = new Set(expandedTypeIds.value)
  for (const n of rawGraphData.value.nodes) {
    if (n.node_type === 'concept') newSet.add(n.id)
  }
  if (!newSet.size) {
    ElMessage.info('暂无实体类型可展开')
    return
  }
  expandedTypeIds.value = newSet
  renderGraph()
}

/** 进入原方案图谱全屏页面（构建预览模式，展示当前构建图谱快照） */
const gotoGraphDetail = () => {
  router.push({ path: '/ontology/preview', query: { jobId } })
}

/** 图谱缩放 */
const graphZoomIn = () => {
  if (!chartInstance) return
  const option: any = chartInstance.getOption()
  const zoom = (option.series?.[0]?.zoom || 1) * 1.2
  chartInstance.setOption({ series: [{ zoom }] })
}
const graphZoomOut = () => {
  if (!chartInstance) return
  const option: any = chartInstance.getOption()
  const zoom = (option.series?.[0]?.zoom || 1) / 1.2
  chartInstance.setOption({ series: [{ zoom }] })
}
const graphResetZoom = () => {
  chartInstance?.setOption({ series: [{ zoom: 1 }] })
}

// ── 滚动到底 ──
const scrollToBottom = () => {
  nextTick(() => {
    const el = chatMessagesRef.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// ── 工具函数 ──
const goBack = () => router.push('/ontology')
const refreshAll = async () => { await loadJob(); await loadHistory() }

// 下拉面板编辑后刷新状态（获取完整数据，含实体类型/实体/关系）
const onStatePanelChanged = async () => {
  await loadJob()
}

const getStatusType = (status: string) => {
  const map: Record<string, any> = { 'completed': 'success', 'running': 'warning', 'failed': 'danger', 'paused': 'info' }
  return map[status] || ''
}
const getStatusText = (status: string) => {
  const map: Record<string, string> = { 'completed': '已完成', 'running': '进行中', 'failed': '失败', 'paused': '已暂停', 'pending': '待处理' }
  return map[status] || status
}
const formatTime = (t: string) => {
  if (!t) return ''
  const d = new Date(t)
  return d.toLocaleString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.ontology-build {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 1.25rem;
  overflow: hidden;
}

.build-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-shrink: 0;
  margin-bottom: 1rem;
}
.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}
.header-left h2 {
  font-size: 1.125rem;
  font-weight: 600;
  margin: 0;
}
.header-actions {
  display: flex;
  gap: 0.5rem;
}

/* ── 主体：左右布局 ── */
.workspace {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 1rem;
  overflow: hidden;
}

/* ── 左侧：聊天窗口 ── */
.chat-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  overflow: hidden;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.chat-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, #909399);
  gap: 0.75rem;
  padding: 2rem;
}
.chat-empty p {
  text-align: center;
  max-width: 360px;
  line-height: 1.6;
}

.chat-msg {
  display: flex;
  gap: 0.75rem;
  max-width: 85%;
}
.chat-msg--user {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.chat-msg--ai {
  align-self: flex-start;
}

.msg-avatar {
  flex-shrink: 0;
  padding-top: 2px;
}

.msg-body {
  flex: 1;
  min-width: 0;
}

.msg-content {
  background: #f5f7fa;
  border-radius: 12px;
  padding: 0.75rem 1rem;
  line-height: 1.65;
  word-break: break-word;
}
.msg-hr {
  border: none;
  border-top: 1px solid #e4e7ed;
  margin: 0.6rem 0;
}
.chat-msg--user .msg-content {
  background: var(--primary-500, #409eff);
  color: #fff;
}

.msg-time {
  font-size: 0.7rem;
  color: var(--text-secondary, #c0c4cc);
  margin-top: 0.25rem;
  padding: 0 0.25rem;
}

/* 消息级后台任务状态标签（随消息常显：running 实时刷新 → done/failed 保持终态） */
.task-tag {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.4rem;
  margin-top: 0.4rem;
  padding: 0.35rem 0.7rem;
  border-radius: 8px;
  font-size: 0.78rem;
  border: 1px solid transparent;
  max-width: 100%;
}
.task-tag--running {
  background: linear-gradient(135deg, #ecf5ff, #f5f7fa);
  border-color: #d9ecff;
}
.task-tag--done {
  background: #f0f9eb;
  border-color: #e1f3d8;
}
.task-tag--failed {
  background: #fef0f0;
  border-color: #fde2e2;
}
.task-tag-icon {
  font-size: 15px;
  flex-shrink: 0;
}
.task-tag-icon.is-running {
  color: var(--primary-500, #409eff);
  animation: task-rotate 1.2s linear infinite;
}
.task-tag-icon.is-done { color: #67c23a; }
.task-tag-icon.is-failed { color: #f56c6c; }
.task-tag-stage {
  font-weight: 600;
  color: var(--text-primary, #303133);
  flex-shrink: 0;
}
.task-tag-percent {
  color: var(--primary-500, #409eff);
  font-variant-numeric: tabular-nums;
  flex-shrink: 0;
}
.task-tag-message {
  color: var(--text-secondary, #909399);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}
@keyframes task-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 打字指示器 */
.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 0.75rem 1rem;
  background: #f5f7fa;
  border-radius: 12px;
  width: fit-content;
}
.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #c0c4cc;
  animation: typing-bounce 1.4s infinite ease-in-out both;
}
.typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
.typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
.typing-indicator span:nth-child(3) { animation-delay: 0s; }

@keyframes typing-bounce {
  0%, 80%, 100% { transform: scale(0.6); }
  40% { transform: scale(1); }
}

/* 输入区 */
.chat-input {
  padding: 0.75rem 1rem;
  border-top: 1px solid #ebeef5;
  background: #fafafa;
  flex-shrink: 0;
}
.input-wrapper {
  display: flex;
  gap: 0.5rem;
  align-items: flex-end;
}
.input-wrapper :deep(.el-textarea) {
  flex: 1;
}
.input-wrapper :deep(.el-textarea__inner) {
  resize: none;
}
.input-actions {
  display: flex;
  gap: 0.25rem;
  align-items: center;
  flex-shrink: 0;
}
.attachment-chips {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
  margin-top: 0.5rem;
}

/* ── 右侧面板 ── */
.right-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow: hidden;
}

.stage-panel {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  padding: 1rem;
  flex-shrink: 0;
}
.stage-panel h4 {
  margin: 0 0 0.75rem;
  font-size: 0.95rem;
  font-weight: 600;
}
.stage-summary {
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid #ebeef5;
}
.stage-summary p {
  margin: 0 0 0.5rem;
  font-size: 0.8rem;
  color: var(--text-secondary, #909399);
}
.summary-stats {
  display: flex;
  gap: 1rem;
  font-size: 0.8rem;
  color: var(--text-primary, #303133);
}
.summary-stats span {
  background: #f5f7fa;
  padding: 0.25rem 0.5rem;
  border-radius: 4px;
}

.graph-panel {
  flex: 1;
  min-height: 0;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  padding: 1rem;
  display: flex;
  flex-direction: column;
}
.graph-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.5rem;
  flex-shrink: 0;
}
.graph-toolbar h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
}
.graph-controls {
  display: flex;
  gap: 0.25rem;
  align-items: center;
}
.graph-hint {
  font-size: 0.72rem;
  color: #909399;
  margin-bottom: 0.5rem;
  flex-shrink: 0;
}
/* 图谱容器 + 图例浮层（与图谱详情页样式统一） */
.graph-wrapper {
  flex: 1;
  min-height: 300px;
  position: relative;
  display: flex;
  flex-direction: column;
}
.graph-container {
  flex: 1;
  min-height: 300px;
  border-radius: 8px;
  border: 1px solid #ebeef5;
}
.graph-legend-overlay {
  position: absolute;
  top: 12px;
  right: 12px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  z-index: 10;
  max-width: 200px;
}
.graph-legend-overlay .legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--text-regular, #606266);
  padding: 2px 0;
}
.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

/* 加载状态 */
.loading-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-secondary, #909399);
  gap: 1rem;
}

/* 构建步骤条 */
.build-steps :deep(.el-step__icon) { font-size: 12px; }
.build-steps :deep(.el-step__title) { font-size: 12px; }
</style>