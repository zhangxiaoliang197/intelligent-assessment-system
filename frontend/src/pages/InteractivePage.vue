<template>
  <div class="ipage-workbench">
    <!-- ── 左栏：当前会话对话（可折叠，仅修订当前页面）── -->
    <aside v-show="!leftCollapsed" class="ipage-side">
      <div class="side-head">
        <div class="side-left">
          <el-tooltip content="返回态势页面主对话框" placement="bottom">
            <el-button text :icon="Back" @click="goBack" />
          </el-tooltip>
          <div class="side-title">
            <el-icon color="#0ea5e9"><MagicStick /></el-icon>
            <span>态势页面</span>
          </div>
        </div>
        <el-tooltip content="收起对话栏，页面铺满" placement="bottom">
          <el-button text :icon="Fold" @click="leftCollapsed = true" />
        </el-tooltip>
      </div>

      <div class="chat-scroll custom-scroll" ref="chatScrollRef">
        <!-- 空态引导 -->
        <div v-if="!store.messages.length" class="welcome">
          <p class="welcome-title">当前页面会话</p>
          <template v-if="store.pageId">
            <p class="welcome-sub">在下方输入修改要求（例如调整图表、增加筛选），页面将在右侧更新。</p>
          </template>
          <template v-else>
            <p class="welcome-sub">尚未选择页面。请回到主对话框提问生成，或在会话卡片中打开历史页面。</p>
            <el-button type="primary" plain @click="goBack">去主对话框提问</el-button>
          </template>
        </div>

        <!-- 会话消息（只读展示，与主对话框同步） -->
        <template v-for="m in store.messages" :key="m.id">
          <div v-if="m.role === 'user'" class="msg msg-user">
            <div class="bubble bubble-user">{{ m.content }}</div>
          </div>
          <div v-else class="msg msg-ai">
            <div class="ai-avatar"><el-icon><MagicStick /></el-icon></div>
            <div class="bubble bubble-ai">
              <!-- 直答回答 -->
              <template v-if="m.kind === 'direct'">
                <div class="direct-text">
                  <p v-for="(line, i) in splitLines(m.content)" :key="i">{{ line }}</p>
                </div>
              </template>
              <!-- 页面卡片：点击可切换查看该页面 -->
              <template v-else-if="m.kind === 'page_card'">
                <div class="ready-text">
                  <el-icon color="#059669"><CircleCheck /></el-icon>
                  <span>态势页面：{{ m.title || '未命名页面' }}</span>
                </div>
                <el-tag v-if="m.usedTemplate" size="small" type="warning" effect="plain" class="tpl-tag">
                  标准模板渲染
                </el-tag>
                <el-button
                  size="small" text type="primary" class="card-open"
                  @click="openCard(m.pageId)"
                >打开此页面</el-button>
              </template>
              <!-- 错误消息 -->
              <template v-else-if="m.kind === 'error'">
                <div class="error-text">
                  <el-icon color="#dc2626"><WarningFilled /></el-icon>
                  <span>{{ m.content || '生成失败' }}</span>
                </div>
              </template>
              <template v-else>
                <div class="plain-text">{{ m.content }}</div>
              </template>
            </div>
          </div>
        </template>
      </div>

      <!-- 输入区：仅作为"修改当前页面"入口 -->
      <div class="composer">
        <!-- 技能策略：会话级生效，作用于本会话后续每一轮修订（默认"关闭技能"） -->
        <div class="composer-skill">
          <SkillSelector
            :model-value="store.effectiveSkillChoice"
            :skills="store.skills"
            :disabled="!store.skillsEnabled"
            disabled-hint="服务端已禁用技能匹配（IPAGE_SKILL_MATCH_ENABLED=false），本轮一律不套用技能"
            @update:model-value="store.setSkillChoice"
          />
        </div>
        <el-input
          v-model="input"
          type="textarea"
          :rows="2"
          resize="none"
          :disabled="!canRevise"
          :placeholder="canRevise ? '对当前页面提出修改，例如：只看蓝方、增加时间趋势图…' : '生成页面后可在此输入修改要求'"
          @keydown.enter.exact.prevent="onSend"
        />
        <div class="composer-foot">
          <span class="composer-tip">Enter 发送 · 修改结果在右侧页面更新</span>
          <el-button
            type="primary"
            :icon="Promotion"
            :loading="store.status === 'generating'"
            :disabled="!canRevise"
            @click="onSend"
          >修改页面</el-button>
        </div>
      </div>
    </aside>

    <!-- 折叠后的悬浮展开按钮 -->
    <div v-if="leftCollapsed" class="expand-fab" @click="leftCollapsed = false">
      <el-icon><Expand /></el-icon>
      <span>对话</span>
    </div>

    <!-- ── 右侧：页面渲染区（折叠时铺满）── -->
    <main class="ipage-main">
      <!-- 修订进行中的顶部进度条 -->
      <div v-if="store.status === 'generating'" class="revising-bar">
        <el-icon class="rotating"><Loading /></el-icon>
        <span>{{ activeStepLabel || '正在修改页面…' }}</span>
        <el-button size="small" text type="danger" @click="store.cancel()">取消</el-button>
      </div>
      <!-- 本轮套用的技能（生成剧本）：可解释命中方式与匹配度 -->
      <div v-if="appliedSkillBar" class="skill-bar">
        <el-tag size="small" :type="appliedSkillBar.type" effect="plain">{{ appliedSkillBar.text }}</el-tag>
        <span class="skill-reason">{{ appliedSkillBar.reason }}</span>
      </div>
      <div v-if="store.status === 'ready' && store.intent === 'data_page' && store.html" class="canvas-wrap">
        <PageSandbox :html="store.html" :bundle="store.dataBundle" />
      </div>
      <!-- 直答（general 意图）：无需取数与页面，直接展示文字结论 -->
      <div v-else-if="store.status === 'ready' && store.intent === 'general' && store.directAnswer" class="canvas-wrap">
        <article class="direct-card">
          <div class="direct-card-q">{{ store.query }}</div>
          <div class="direct-card-body">
            <p v-for="(line, i) in splitLines(store.directAnswer)" :key="i">{{ line }}</p>
          </div>
        </article>
      </div>
      <div v-else-if="store.status === 'failed'" class="canvas-placeholder">
        <el-icon :size="42" color="#dc2626"><WarningFilled /></el-icon>
        <p>{{ store.errorMsg || '生成失败，请重试' }}</p>
        <el-button type="primary" plain @click="goBack">返回主对话框</el-button>
      </div>
      <div v-else class="canvas-placeholder">
        <el-icon :size="42" color="#94a3b8"><DataAnalysis /></el-icon>
        <p>图表 · 地图 · 文字结论，一问生成一页</p>
        <el-button type="primary" plain @click="goBack">去主对话框提问</el-button>
      </div>
    </main>
  </div>
</template>

<script setup lang="ts">
// ── 态势页工作台（/interactive?pageId=xxx，从主对话框"打开态势页面"进入）──
// 左栏 = 当前会话消息（只读）+ 修改当前页面入口，可折叠铺满；
// 右侧 = PageSandbox 离线渲染的交互页面。
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Back, Fold, Expand, MagicStick, Promotion, Loading,
  CircleCheck, WarningFilled, DataAnalysis,
} from '@element-plus/icons-vue'
import PageSandbox from '@/components/interactive/PageSandbox.vue'
import SkillSelector from '@/components/interactive/SkillSelector.vue'
import { useInteractiveStore } from '@/stores/interactive'

defineOptions({ name: 'InteractivePage' })

const route = useRoute()
const router = useRouter()
const store = useInteractiveStore()

const input = ref('')
const leftCollapsed = ref(false)
const chatScrollRef = ref<HTMLElement | null>(null)
// 发起修订时的会话快照：完成回写消息前若已切换页面/会话，则不本地追加
let generatingSession = ''

const canRevise = computed(
  () => store.status === 'ready' && store.intent === 'data_page' && !!store.pageId,
)

const activeStepLabel = computed(() => {
  const active = store.steps.find((s) => s.state === 'active')
  return active ? `${active.label}${active.detail ? '：' + active.detail : ''}` : ''
})

// 本轮套用技能的展示条（未套用或未生效时不显示 / 示警）
const appliedSkillBar = computed(() => {
  const applied = store.matchedSkill
  if (!applied || !applied.id || store.status !== 'ready') return null
  if (!applied.applied) {
    return { text: `技能未生效：${applied.name}`, type: 'warning' as const, reason: applied.reason }
  }
  const label: Record<string, string> = { auto: '自动匹配', manual: '手动指定', inherited: '继承上一版' }
  const score = typeof applied.score === 'number' ? `｜匹配度 ${applied.score.toFixed(2)}` : ''
  return {
    text: `已套用技能：${applied.name}`,
    type: 'success' as const,
    reason: `${label[applied.matchedBy] || '已套用'}${score}`,
  }
})

// 修订未生效的中文原因（来自后端 Guard 校验问题列表）
const revisionFailureText = computed(() => {
  const issues = (store.guardIssues || []).filter((i) => String(i || '').trim())
  return '本次修改未生效，已保留上一版：'
    + (issues.length ? issues.slice(0, 3).join('；') : '重新设计未通过校验')
})

function splitLines(text: string) {
  return String(text || '').split(/\n+/).map((l) => l.trim()).filter(Boolean)
}

async function scrollToBottom() {
  await nextTick()
  const el = chatScrollRef.value
  if (el) el.scrollTop = el.scrollHeight
}

// ── 页面加载（详情 + 所属会话消息）──
async function loadTargetPage(pid: string) {
  const item = await store.loadPage(pid)
  if (item?.sessionId) {
    try {
      await store.loadSession(item.sessionId)
    } catch { /* 会话可能已删除，静默忽略 */ }
  } else {
    store.messages.splice(0)
  }
  await scrollToBottom()
}

// ── 卡片点击：总是按 pid 从服务端重载 ──
// 不能用 `pid === store.pageId` 直接 return：修订完成后 store.pageId 已指向新页面，
// 修改后的卡片会被静默吞掉（点了没反应）。pid 与当前页相同时即幂等刷新，
// 同时可自愈 store 与库内不一致的情况。
async function openCard(pid?: string) {
  if (!pid) return
  if (pid !== store.pageId) {
    router.replace({ path: '/interactive', query: { pageId: pid } })
  }
  try {
    await loadTargetPage(pid)
  } catch (e: any) {
    store.appendLocalMessage({ role: 'ai', kind: 'error', content: e?.serverMessage || '页面加载失败' })
  }
}

function goBack() {
  router.push('/situation-page')
}

// ── 修改当前页面（parentPageId 修订，不提供新页面生成入口）──
async function onSend() {
  const q = input.value.trim()
  if (!q || store.status === 'generating' || !canRevise.value) return
  input.value = ''
  generatingSession = store.sessionId
  store.appendLocalMessage({ role: 'user', kind: 'text', content: q })
  await scrollToBottom()
  await store.generate(q, { sessionId: store.sessionId, parentPageId: store.pageId })
}

// 修订结束 → 同步消息 + 修正 URL 指向新页面
watch(() => store.status, async (val) => {
  if (val === 'generating') return
  if (store.sessionId !== generatingSession) return
  if (val === 'ready') {
    if (store.intent === 'general') {
      store.appendLocalMessage({ role: 'ai', kind: 'direct', content: store.directAnswer })
    } else {
      store.appendLocalMessage({
        role: 'ai', kind: 'page_card', content: '',
        pageId: store.pageId, title: store.title, usedTemplate: store.usedTemplate,
      })
      // 修订失败：页面保留上一版，必须显式说明原因，否则用户以为修改已生效
      if (store.parentPageId && !store.revised) {
        store.appendLocalMessage({ role: 'ai', kind: 'text', content: revisionFailureText.value })
      }
      if (store.pageId && route.query.pageId !== store.pageId) {
        router.replace({ path: '/interactive', query: { pageId: store.pageId } })
      }
    }
  } else if (val === 'failed') {
    store.appendLocalMessage({ role: 'ai', kind: 'error', content: store.errorMsg || '生成失败' })
  }
  await scrollToBottom()
})

onMounted(async () => {
  store.resetRound()
  // 技能目录与服务端默认策略（默认 off=不套用）：供选择器展示与请求参数推导
  void store.loadSkills()
  const pid = String(route.query.pageId || '')
  if (pid) {
    try {
      await loadTargetPage(pid)
    } catch (e: any) {
      store.appendLocalMessage({ role: 'ai', kind: 'error', content: e?.serverMessage || '页面加载失败' })
    }
  }
})
</script>

<style scoped>
.ipage-workbench {
  display: flex;
  height: calc(100vh - 60px);
  min-height: 0;
  background: #eef2f7;
}

/* ── 左栏 ── */
.ipage-side {
  width: 380px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border-right: 1px solid #e2e8f0;
}
.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  border-bottom: 1px solid #eef2f7;
}
.side-left { display: flex; align-items: center; gap: 4px; min-width: 0; }
.side-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}
.chat-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.welcome-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 6px;
}
.welcome-sub {
  font-size: 13px;
  color: #64748b;
  line-height: 1.7;
  margin-bottom: 14px;
}

.msg { display: flex; }
.msg-user { justify-content: flex-end; }
.bubble {
  max-width: 88%;
  border-radius: 12px;
  padding: 10px 13px;
  font-size: 13.5px;
  line-height: 1.7;
}
.bubble-user {
  background: #1d4ed8;
  color: #fff;
  border-bottom-right-radius: 3px;
  white-space: pre-wrap;
  word-wrap: break-word;
}
.msg-ai { gap: 8px; align-items: flex-start; }
.ai-avatar {
  width: 28px; height: 28px; flex-shrink: 0;
  border-radius: 8px;
  background: linear-gradient(135deg, #38bdf8, #0ea5e9);
  color: #fff;
  display: flex; align-items: center; justify-content: center;
}
.bubble-ai {
  background: #f8fafc;
  border: 1px solid #eef2f7;
  color: #1f2937;
  border-bottom-left-radius: 3px;
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.direct-text { font-size: 13.5px; line-height: 1.9; }
.direct-text p { margin: 0 0 6px; }
.direct-text p:last-child { margin-bottom: 0; }
.plain-text { white-space: pre-wrap; }
.ready-text, .error-text { display: flex; align-items: center; gap: 6px; font-weight: 600; }
.ready-text { color: #047857; }
.error-text { color: #dc2626; font-weight: 500; }
.tpl-tag { margin: 0; align-self: flex-start; }
.card-open { align-self: flex-start; padding-left: 0; }

.composer {
  border-top: 1px solid #eef2f7;
  padding: 12px 14px;
}
.composer-skill {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
}
.composer-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.composer-tip { font-size: 11.5px; color: #94a3b8; }

/* ── 折叠后的悬浮展开按钮 ── */
.expand-fab {
  position: fixed;
  top: 76px;
  left: 12px;
  z-index: 30;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 7px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 999px;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.1);
  cursor: pointer;
  font-size: 13px;
  color: #0369a1;
  transition: all .15s;
}
.expand-fab:hover { border-color: #0ea5e9; background: #f0f9ff; }

/* ── 右侧 ── */
.ipage-main {
  flex: 1;
  min-width: 0;
  overflow: auto;
  padding: 18px;
  display: flex;
  flex-direction: column;
}
.revising-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 14px;
  margin-bottom: 12px;
  background: #f0f9ff;
  border: 1px solid #bae6fd;
  border-radius: 9px;
  color: #0369a1;
  font-size: 13px;
  flex-shrink: 0;
}
.revising-bar span { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.skill-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 4px;
  margin-bottom: 8px;
  font-size: 12.5px;
  color: var(--text-muted);
  flex-shrink: 0;
}
.skill-reason { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.canvas-wrap { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.canvas-wrap > * { flex: 1; }
.direct-card {
  max-width: 860px;
  width: 100%;
  margin: 24px auto;
  background: #fff;
  border-radius: 12px;
  padding: 28px 32px;
  box-shadow: 0 1px 4px rgba(15, 23, 42, .08);
  align-self: flex-start;
  flex: 0 0 auto;
}
.direct-card-q {
  font-size: 13px;
  color: #1d4ed8;
  font-weight: 600;
  padding-bottom: 14px;
  margin-bottom: 14px;
  border-bottom: 1px solid #eef2f7;
}
.direct-card-body { font-size: 15px; line-height: 2; color: #1f2937; }
.direct-card-body p { margin: 0 0 8px; }
.canvas-placeholder {
  flex: 1;
  min-height: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: #64748b;
  font-size: 14px;
}
.rotating { animation: ipage-spin 1s linear infinite; color: #0ea5e9; }
@keyframes ipage-spin { to { transform: rotate(360deg); } }

.custom-scroll::-webkit-scrollbar { width: 6px; }
.custom-scroll::-webkit-scrollbar-thumb { background: rgba(0, 0, 0, 0.15); border-radius: 3px; }
.custom-scroll::-webkit-scrollbar-track { background: transparent; }
</style>
