<template>
  <Layout>
    <div class="sp-container">
      <!-- ── 左栏：历史会话（与态势图一致）── -->
      <div class="sidebar">
        <div class="sidebar-section">
          <div class="sidebar-section-header">
            <h3 class="sidebar-title">会话记录</h3>
            <el-button class="new-session-btn" type="primary" @click="onNewSession">
              <el-icon><Plus /></el-icon> 新会话
            </el-button>
          </div>
          <div class="session-list custom-scroll">
            <div
              v-for="s in store.sessions"
              :key="s.sessionId"
              :class="['session-item', { active: s.sessionId === store.sessionId }]"
              @click="onPickSession(s.sessionId)"
            >
              <el-icon><ChatDotRound /></el-icon>
              <div class="session-item-content">
                <span class="session-item-title">{{ s.title || '未命名会话' }}</span>
                <span class="session-item-time">{{ formatTime(s.updatedAt) }}</span>
              </div>
              <el-button class="session-delete-btn" size="small" text type="danger" @click.stop="onDeleteSession(s.sessionId)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
            <el-empty v-if="!store.sessions.length" description="暂无会话" :image-size="56" />
          </div>
        </div>
      </div>

      <!-- ── 主内容 ── -->
      <div class="main-content">
        <!-- 顶部工具栏：技能选择（生成剧本）+ 数据源选择 -->
        <div class="top-toolbar">
          <div class="toolbar-left">
            <el-icon :size="18" color="#0ea5e9"><MagicStick /></el-icon>
            <span class="toolbar-title">态势页面</span>
          </div>
          <div class="toolbar-right">
            <!-- 技能：默认"关闭技能"（由服务端默认策略下发），可手动切自动匹配或指定技能；
                 选择写在 store 里，与页面工作台（/interactive）共用同一份会话级策略 -->
            <SkillSelector
              :model-value="store.effectiveSkillChoice"
              :skills="store.skills"
              :applied="store.matchedSkill"
              :disabled="store.status === 'generating' || !store.skillsEnabled"
              disabled-hint="服务端已禁用技能匹配（IPAGE_SKILL_MATCH_ENABLED=false），本轮一律不套用技能"
              @update:model-value="store.setSkillChoice"
            />
            <span class="label">数据源：</span>
            <el-select
              v-model="dataSourceId"
              class="data-source-select"
              placeholder="选择数据源"
              size="small"
            >
              <el-option
                v-for="ds in dataSources"
                :key="ds.id"
                :label="ds.status === 'available' ? ds.name : `${ds.name}（不可用）`"
                :value="ds.id"
                :disabled="ds.status !== 'available'"
              />
            </el-select>
            <el-button size="small" type="primary" @click="dsDialogVisible = true">
              <el-icon><Setting /></el-icon> 配置
            </el-button>
          </div>
        </div>

        <div class="content-area">
          <!-- 中栏：对话记录 -->
          <div class="chat-panel">
            <div class="chat-area custom-scroll" ref="chatAreaRef">
              <!-- 空状态 -->
              <div v-if="!store.messages.length" class="empty-state">
                <p>态势页面</p>
                <span class="empty-sub">提出态势问题，系统在后台自动取数并生成含图表、地图与文字结论的可交互页面</span>
                <div class="suggest-list">
                  <button
                    v-for="s in suggestions"
                    :key="s"
                    class="suggest-item"
                    @click="onSend(s)"
                  >{{ s }}</button>
                </div>
              </div>

              <!-- 消息列表 -->
              <div v-else class="message-list">
                <template v-for="m in store.messages" :key="m.id">
                  <!-- 用户消息 -->
                  <div v-if="m.role === 'user'" class="message user">
                    <div class="message-text user-text">{{ m.content }}</div>
                  </div>
                  <!-- AI 消息 -->
                  <div v-else class="message assistant">
                    <div class="ai-avatar"><el-icon><MagicStick /></el-icon></div>
                    <div class="assistant-body">
                      <!-- 直答回答 -->
                      <div v-if="m.kind === 'direct'" class="direct-text">
                        <p v-for="(line, i) in splitLines(m.content)" :key="i">{{ line }}</p>
                      </div>
                      <!-- 页面完成卡片：持久化、可重复点击 -->
                      <div v-else-if="m.kind === 'page_card'" class="page-card">
                        <div class="page-card-head">
                          <el-icon color="#059669"><CircleCheck /></el-icon>
                          <span>态势页面已生成：{{ m.title || '未命名页面' }}</span>
                        </div>
                        <el-tag v-if="m.usedTemplate" size="small" type="warning" effect="plain">标准模板渲染</el-tag>
                        <el-button type="primary" @click="openPage(m.pageId)">
                          <el-icon><FullScreen /></el-icon> 打开态势页面
                        </el-button>
                      </div>
                      <!-- 错误消息 -->
                      <div v-else-if="m.kind === 'error'" class="error-text">
                        <el-icon color="#dc2626"><WarningFilled /></el-icon>
                        <span>{{ m.content || '生成失败' }}</span>
                      </div>
                      <!-- 普通文本 -->
                      <div v-else class="plain-text">{{ m.content }}</div>
                    </div>
                  </div>
                </template>
              </div>
            </div>

            <!-- 输入区 -->
            <div class="input-area">
              <div class="input-wrapper">
                <el-input
                  v-model="input"
                  type="textarea"
                  :rows="3"
                  resize="none"
                  placeholder="输入态势问题，如：红蓝双方空中力量对比…"
                  @keydown.enter.exact.prevent="onSend()"
                />
                <div class="input-actions">
                  <el-button v-if="store.status === 'generating'" type="danger" plain @click="onCancel">
                    <el-icon><CircleClose /></el-icon> 取消
                  </el-button>
                  <el-button v-else type="primary" @click="onSend()">
                    <el-icon><Promotion /></el-icon> 发送
                  </el-button>
                </div>
              </div>
              <div class="input-tip">发送后自动在后台生成，过程在右侧面板展示，完成后可打开态势页面</div>
            </div>
          </div>

          <!-- 右栏：执行过程面板（可折叠 + 拖拽缩放，样式对齐态势图） -->
          <div v-if="showExecPanel" class="execution-panel" :style="{ width: execPanelWidth + 'px' }">
            <div class="resize-handle" @mousedown="startResize"></div>
            <div class="panel-header">
              <div class="panel-title-wrap"><span>执行过程</span></div>
              <el-icon class="panel-close" @click="showExecPanel = false"><Close /></el-icon>
            </div>
            <div class="execution-progress">
              <div class="execution-progress-meta">
                <span>{{ activeStepLabel || '生成进度' }}</span>
                <span v-if="execProgress.total">{{ execProgress.done }} / {{ execProgress.total }}</span>
              </div>
              <el-progress
                :percentage="execProgress.percent"
                :status="store.status === 'failed' ? 'exception' : store.status === 'ready' ? 'success' : undefined"
              />
            </div>
            <div class="execution-content custom-scroll">
              <div class="panel-section">
                <div class="section-header"><h5>生成步骤</h5></div>
                <div class="steps-list">
                  <div
                    v-for="s in store.steps"
                    :key="s.id"
                    :class="['inline-step', stepStatusClass(s.state)]"
                  >
                    <div class="inline-step-header">
                      <div class="inline-step-icon">
                        <el-icon v-if="s.state === 'completed'"><CircleCheck /></el-icon>
                        <el-icon v-else-if="s.state === 'error'"><CircleClose /></el-icon>
                        <el-icon v-else-if="s.state === 'active'" class="rotating"><Loading /></el-icon>
                        <span v-else class="step-dot-pending" />
                      </div>
                      <div class="inline-step-title">{{ s.label }}</div>
                    </div>
                    <div v-if="s.detail" class="inline-step-detail">{{ s.detail }}</div>
                  </div>
                </div>
                <el-empty v-if="!store.steps.length" description="发送问题后展示执行步骤" :image-size="56" />
              </div>
              <div v-if="store.datasetLogs.length" class="panel-section">
                <div class="section-header"><h5>取数明细</h5></div>
                <div class="dataset-list">
                  <div v-for="(d, idx) in store.datasetLogs" :key="idx" class="dataset-item">
                    <el-icon><Coin /></el-icon>
                    <span class="dataset-name">{{ d.name || d.datasetId || '数据集' }}</span>
                    <span class="dataset-meta">
                      {{ d.mode === 'aggregate' ? '聚合' : '明细' }} · {{ d.totalRows ?? '-' }} 行{{ d.truncated ? '（已抽稀）' : '' }}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="execution-panel-toggle" @click="showExecPanel = true">
            <el-icon><ArrowRight /></el-icon>
            <span class="toggle-text">执行过程</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 数据源配置对话框（对齐态势图） -->
    <el-dialog v-model="dsDialogVisible" title="数据源配置" width="600px">
      <div class="data-source-list">
        <div
          v-for="ds in dataSources"
          :key="ds.id"
          :class="['ds-item', { active: ds.id === dataSourceId }]"
          @click="selectDataSource(ds.id)"
        >
          <div class="ds-item-name">{{ ds.name }}</div>
          <div class="ds-item-meta">
            <el-tag v-if="ds.type" size="small">{{ ds.type }}</el-tag>
            <el-tag :type="ds.status === 'available' ? 'success' : 'info'" size="small">
              {{ ds.status === 'available' ? '可用' : '不可用' }}
            </el-tag>
            <el-icon v-if="ds.id === dataSourceId" class="ds-item-check"><CircleCheck /></el-icon>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="dsDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmDataSource">确定</el-button>
      </template>
    </el-dialog>
  </Layout>
</template>

<script setup lang="ts">
// ── 态势页面主对话框（三栏布局）──
// 左=历史会话，中=对话记录，右=执行过程面板；顶部技能选择 + 数据源选择。
// 发送后不跳转：生成全部在后台进行，完成后对话内插入"打开态势页面"卡片。
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Delete, ChatDotRound, MagicStick, Setting, Promotion, Loading,
  CircleClose, CircleCheck, Close, ArrowRight, FullScreen, WarningFilled, Coin,
} from '@element-plus/icons-vue'
import Layout from '@/components/Layout.vue'
import SkillSelector from '@/components/interactive/SkillSelector.vue'
import { useInteractiveStore } from '@/stores/interactive'
import api from '@/services/api'

defineOptions({ name: 'SituationPageDialog' })

const router = useRouter()
const store = useInteractiveStore()

// ── 页面状态 ──
const input = ref('')
const chatAreaRef = ref<HTMLElement | null>(null)
const showExecPanel = ref(false)
const execPanelWidth = ref(460)
const isResizing = ref(false)
const dsDialogVisible = ref(false)
const dataSources = ref<Array<{ id: string; name: string; type?: string; status?: string }>>([])
const dataSourceId = ref('')
// 技能选择由 store 统一持有（会话级）：此处不再维护本地默认值，避免与工作台入口漂移
// 发起生成时的会话快照：完成回写消息前若用户已切换会话，则不本地追加（后端已落库）
const generatingSession = ref('')

const suggestions = [
  '红蓝双方空中力量对比，用图表展示并标注地图分布',
  '当前航线受到哪些打击范围圈威胁？',
  '各基地保障的飞机数量统计与地理分布',
  '介绍一下态势分析的基本流程',
]

// ── 执行面板进度（三阶段步骤收敛为百分比）──
const execProgress = computed(() => {
  const steps = store.steps
  if (!steps.length) return { done: 0, total: 0, percent: 0 }
  const done = steps.filter((s) => s.state === 'completed' || s.state === 'error').length
  return { done, total: steps.length, percent: Math.round((done / steps.length) * 100) }
})

const activeStepLabel = computed(() => {
  const active = store.steps.find((s) => s.state === 'active')
  return active ? `${active.label}${active.detail ? '：' + active.detail : ''}` : ''
})

function stepStatusClass(state: string) {
  if (state === 'completed') return 'completed'
  if (state === 'error') return 'error'
  if (state === 'active') return 'in-progress'
  return 'pending'
}

// ── 执行面板拖拽缩放（与态势图一致）──
function startResize(e: MouseEvent) {
  isResizing.value = true
  const startX = e.clientX
  const startWidth = execPanelWidth.value
  const onMouseMove = (ev: MouseEvent) => {
    if (!isResizing.value) return
    const delta = startX - ev.clientX
    execPanelWidth.value = Math.min(700, Math.max(300, startWidth + delta))
  }
  const onMouseUp = () => {
    isResizing.value = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// ── 数据源 ──
async function fetchDataSources() {
  try {
    const resp: any = await api.get('/evaluation/data-sources')
    const list = resp?.dataSources || resp?.data?.dataSources || []
    if (Array.isArray(list) && list.length) {
      dataSources.value = list
      if (!dataSourceId.value && list[0]?.id) dataSourceId.value = list[0].id
    }
  } catch (e) {
    console.warn('态势页面数据源列表加载失败', e)
  }
}

function selectDataSource(id: string) {
  const found = dataSources.value.find((d) => d.id === id)
  if (found && found.status !== 'available') return
  dataSourceId.value = id
}

function confirmDataSource() {
  dsDialogVisible.value = false
  if (dataSourceId.value) ElMessage.success('数据源已更新')
}

// ── 会话 ──
async function onNewSession() {
  try {
    await store.createSession()
    showExecPanel.value = false
  } catch (e: any) {
    ElMessage.error(e?.serverMessage || '新建会话失败')
  }
}

async function onPickSession(sid: string) {
  if (sid === store.sessionId) return
  try {
    await store.loadSession(sid)
    await scrollToBottom()
  } catch (e: any) {
    ElMessage.error(e?.serverMessage || '会话加载失败')
  }
}

async function onDeleteSession(sid: string) {
  try {
    await ElMessageBox.confirm('确定删除该会话吗？会话内的消息将被删除。', '删除确认', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  try {
    await store.deleteSession(sid)
    ElMessage.success('已删除')
  } catch (e: any) {
    ElMessage.error(e?.serverMessage || '删除失败')
  }
}

// ── 发送（不跳转，后台生成）──
async function onSend(text?: string) {
  const q = (typeof text === 'string' ? text : input.value).trim()
  if (!q || store.status === 'generating') return
  input.value = ''
  // 无当前会话时先自动建会话（标题由后端取问题前 25 字）
  if (!store.sessionId) {
    try {
      await store.createSession()
    } catch (e: any) {
      ElMessage.error(e?.serverMessage || '创建会话失败')
      return
    }
  }
  generatingSession.value = store.sessionId
  store.appendLocalMessage({ role: 'user', kind: 'text', content: q })
  showExecPanel.value = true
  await scrollToBottom()
  // 技能策略由 store 从会话级选择推导（不在此传参），两个入口因此共用同一份策略
  await store.generate(q, {
    sessionId: store.sessionId,
    dataSourceId: dataSourceId.value,
  })
}

async function onCancel() {
  await store.cancel()
  ElMessage.info('已取消本次生成')
}

// 生成结束 → 对话内插入结果消息（本地即时回显；后端同步落库）
watch(() => store.status, async (val) => {
  if (val === 'generating') return
  if (store.sessionId !== generatingSession.value) return
  if (val === 'ready') {
    if (store.intent === 'general') {
      store.appendLocalMessage({ role: 'ai', kind: 'direct', content: store.directAnswer })
    } else {
      store.appendLocalMessage({
        role: 'ai', kind: 'page_card', content: '',
        pageId: store.pageId, title: store.title, usedTemplate: store.usedTemplate,
      })
    }
  } else if (val === 'failed') {
    store.appendLocalMessage({ role: 'ai', kind: 'error', content: store.errorMsg || '生成失败' })
  }
  void store.loadSessions()
  await scrollToBottom()
})

// ── 打开态势页面（卡片可重复点击）──
function openPage(pid?: string) {
  if (!pid) return
  router.push({ path: '/interactive', query: { pageId: pid } })
}

// ── 辅助 ──
function splitLines(text: string) {
  return String(text || '').split(/\n+/).map((l) => l.trim()).filter(Boolean)
}

function formatTime(t?: string): string {
  if (!t) return ''
  const d = new Date(t.replace('-', '/').replace('-', '/'))
  if (isNaN(d.getTime())) return t
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
}

async function scrollToBottom() {
  await nextTick()
  const el = chatAreaRef.value
  if (el) el.scrollTop = el.scrollHeight
}

onMounted(async () => {
  store.resetRound()
  void store.loadSessions()
  void store.loadSkills()
  void fetchDataSources()
  // 恢复当前会话的对话内容（从态势页返回 / 组件重挂载时不丢上下文）
  if (store.sessionId) {
    try {
      await store.loadSession(store.sessionId)
      await scrollToBottom()
    } catch { /* 会话可能已删除，静默忽略 */ }
  }
})
</script>

<style scoped>
.sp-container {
  display: flex;
  height: 100%;
  background: transparent;
}

/* ── 左栏会话列表 ── */
.sidebar {
  width: 260px;
  flex-shrink: 0;
  padding: 16px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.sidebar-section { display: flex; flex-direction: column; gap: 8px; }
.sidebar-section-header { display: flex; align-items: center; justify-content: space-between; padding: 0 8px; }
.sidebar-title { font-size: 12px; font-weight: 600; color: var(--text-muted); letter-spacing: 0.5px; margin: 0; }
.new-session-btn { height: 32px !important; font-size: 13px !important; font-weight: 500 !important; padding: 0 12px !important; border-radius: 8px !important; }
.session-list { flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 2px; }
.session-item {
  display: flex; align-items: center; gap: 8px;
  padding: 10px 12px; border-radius: 8px; cursor: pointer;
  transition: all 0.2s; color: var(--text-secondary);
}
.session-item:hover { background: rgba(0, 0, 0, 0.04); color: var(--text-primary); }
.session-item.active { background: rgba(14, 165, 233, 0.09); color: #0369a1; }
.session-item .el-icon { font-size: 16px; flex-shrink: 0; color: var(--text-muted); }
.session-item.active .el-icon { color: #0ea5e9; }
.session-delete-btn { opacity: 0; transition: opacity 0.2s; flex-shrink: 0; }
.session-item:hover .session-delete-btn { opacity: 1; }
.session-item-content { flex: 1; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.session-item-title { font-size: 13px; font-weight: 500; color: inherit; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.session-item-time { font-size: 11px; color: var(--text-muted); }

/* ── 主内容区 ── */
.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--bg-card);
  border-left: 1px solid var(--border-light);
}

/* ── 顶部工具栏 ── */
.top-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 24px;
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
  background: var(--bg-card);
}
.toolbar-left { display: flex; align-items: center; gap: 8px; }
.toolbar-title { font-size: 15px; font-weight: 600; color: var(--text-primary); }
.toolbar-right { display: flex; align-items: center; gap: 10px; }
.label { font-size: 13px; color: var(--text-secondary); font-weight: 500; white-space: nowrap; }
.data-source-select { width: 180px; }

/* ── 内容区（中栏对话 + 右栏执行面板）── */
.content-area {
  flex: 1;
  display: flex;
  flex-direction: row;
  overflow: hidden;
  min-height: 0;
}
.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
}
.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 30px 0 20px;
}

/* ── 空状态 ── */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 70px;
  height: 100%;
  color: var(--text-muted);
}
.empty-state p { margin: 0; font-size: 18px; font-weight: 600; color: var(--text-primary); }
.empty-sub { margin-top: 10px; font-size: 13px; max-width: 520px; text-align: center; line-height: 1.7; }
.suggest-list { margin-top: 26px; display: flex; flex-direction: column; gap: 8px; width: 100%; max-width: 520px; padding: 0 24px; }
.suggest-item {
  text-align: left;
  border: 1px solid var(--border-light);
  background: var(--gray-50);
  border-radius: 9px;
  padding: 10px 14px;
  font-size: 13px;
  color: var(--text-secondary);
  cursor: pointer;
  transition: all .15s;
  line-height: 1.5;
}
.suggest-item:hover { border-color: #0ea5e9; color: #0369a1; background: #f0f9ff; }

/* ── 消息列表 ── */
.message-list { display: flex; flex-direction: column; gap: 22px; max-width: 860px; margin: 0 auto; padding: 0 40px; }
.message { display: flex; }
.message.user { justify-content: flex-end; }
.message-text { padding: 12px 16px; border-radius: 14px; line-height: 1.7; font-size: 14px; white-space: pre-wrap; word-wrap: break-word; }
.user-text { background: linear-gradient(135deg, #4f8cff 0%, #3b82f6 100%); color: #fff; border-bottom-right-radius: 4px; max-width: 80%; }
.message.assistant { gap: 10px; align-items: flex-start; }
.ai-avatar {
  width: 30px; height: 30px; flex-shrink: 0;
  border-radius: 9px;
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.assistant-body {
  background: var(--gray-50);
  border: 1px solid var(--border-light);
  border-bottom-left-radius: 4px;
  border-radius: 14px;
  padding: 12px 16px;
  max-width: 82%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.direct-text { font-size: 14px; line-height: 1.9; color: var(--text-primary); }
.direct-text p { margin: 0 0 6px; }
.direct-text p:last-child { margin-bottom: 0; }
.plain-text { font-size: 14px; line-height: 1.7; color: var(--text-primary); white-space: pre-wrap; }

/* 页面完成卡片 */
.page-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 10px;
}
.page-card-head { display: flex; align-items: center; gap: 6px; font-weight: 600; color: #047857; font-size: 14px; }
.error-text { display: flex; align-items: center; gap: 6px; color: #dc2626; font-size: 13.5px; font-weight: 500; }

/* ── 输入区 ── */
.input-area {
  flex-shrink: 0;
  padding: 12px 40px 18px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.input-wrapper { position: relative; max-width: 860px; margin: 0 auto; width: 100%; }
.input-wrapper :deep(.el-textarea__inner) { border-radius: 14px !important; padding: 14px 100px 14px 18px !important; font-size: 14px !important; line-height: 1.6 !important; resize: none; }
.input-actions { position: absolute; bottom: 12px; right: 14px; display: flex; gap: 8px; }
.input-actions .el-button { height: 36px; padding: 0 20px; border-radius: 9px; font-weight: 500; font-size: 13.5px; }
.input-tip { max-width: 860px; margin: 0 auto; width: 100%; font-size: 11.5px; color: var(--text-muted); text-align: center; }

/* ── 执行面板（右栏）── */
.execution-panel {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
  background: #fafbfc;
  position: relative;
  overflow: hidden;
}
.resize-handle {
  position: absolute;
  top: 0; left: -4px;
  width: 8px; height: 100%;
  cursor: col-resize;
  z-index: 10;
  background: transparent;
  transition: background 0.15s;
}
.resize-handle:hover, .resize-handle:active { background: rgba(14, 165, 233, 0.35); }
.panel-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 12px 16px; border-bottom: 1px solid #e2e8f0; background: white;
  font-size: 14px; font-weight: 600; color: #374151; flex-shrink: 0;
}
.panel-close { cursor: pointer; color: #9ca3af; font-size: 16px; }
.panel-close:hover { color: #374151; }
.execution-progress { padding: 10px 14px; background: #fff; border-bottom: 1px solid #eef2f7; }
.execution-progress-meta {
  display: flex; justify-content: space-between; gap: 8px;
  margin-bottom: 6px; color: #64748b; font-size: 11px;
  overflow: hidden;
}
.execution-progress-meta span:first-child { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.execution-content { flex: 1; overflow-y: auto; padding: 8px; }
.panel-section { background: white; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; margin-bottom: 8px; }
.section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 14px; background: #f8fafc;
}
.section-header h5 { margin: 0; font-size: 13px; font-weight: 600; color: #475569; }
.steps-list { display: flex; flex-direction: column; padding: 6px 8px; }
.inline-step { padding: 8px 10px; font-size: 13px; display: flex; flex-direction: column; gap: 4px; word-break: break-word; }
.inline-step-header { display: flex; align-items: flex-start; gap: 8px; }
.inline-step-icon { display: flex; align-items: center; flex-shrink: 0; margin-top: 1px; }
.inline-step-title { font-weight: 500; color: #1f2937; flex: 1; min-width: 0; }
.inline-step-detail { color: #6b7280; font-size: 12px; padding-left: 24px; }
.inline-step.in-progress .inline-step-icon { color: #0ea5e9; }
.inline-step.completed .inline-step-icon { color: #67c23a; }
.inline-step.error .inline-step-icon { color: #f56c6c; }
.step-dot-pending { width: 8px; height: 8px; border-radius: 50%; background: #e2e8f0; display: inline-block; }
.dataset-list { display: flex; flex-direction: column; padding: 6px 10px; }
.dataset-item {
  display: flex; align-items: center; gap: 6px;
  padding: 6px 2px; font-size: 12px; color: #475569;
  border-bottom: 1px solid #f1f5f9;
}
.dataset-item:last-child { border-bottom: none; }
.dataset-name { font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dataset-meta { margin-left: auto; flex-shrink: 0; color: #94a3b8; font-size: 11px; }

/* ── 折叠切换按钮 ── */
.execution-panel-toggle {
  flex-shrink: 0;
  width: 32px;
  background: #fafafa;
  border-left: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  transition: background 0.2s, color 0.2s;
  color: #9ca3af;
}
.execution-panel-toggle .el-icon { font-size: 16px; }
.execution-panel-toggle .toggle-text { writing-mode: vertical-rl; font-size: 13px; letter-spacing: 2px; user-select: none; }
.execution-panel-toggle:hover { background: #f0f9ff; color: #0ea5e9; }

/* ── 数据源配置对话框 ── */
.data-source-list { display: flex; flex-direction: column; gap: 8px; max-height: 360px; overflow-y: auto; }
.ds-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 12px;
  border: 1px solid var(--border-light);
  border-radius: 6px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s;
}
.ds-item:hover { border-color: #38bdf8; background: #f0f9ff; }
.ds-item.active { border-color: #0ea5e9; background: #f0f9ff; }
.ds-item-name { font-size: 14px; font-weight: 500; color: var(--text-primary); }
.ds-item-meta { display: flex; align-items: center; gap: 6px; }
.ds-item-check { color: #0ea5e9; }

/* ── 通用 ── */
.rotating { animation: sp-rotating 1.2s linear infinite; }
@keyframes sp-rotating { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.custom-scroll::-webkit-scrollbar { width: 6px; }
.custom-scroll::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.15); border-radius: 3px; }
.custom-scroll::-webkit-scrollbar-track { background: transparent; }
</style>
