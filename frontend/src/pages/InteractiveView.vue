<template>
  <div class="ipage-view">
    <header class="view-head">
      <div class="head-left">
        <el-button text :icon="Back" @click="goHome">返回门户</el-button>
        <el-divider direction="vertical" />
        <h2 class="view-title">{{ store.title || '态势页面' }}</h2>
        <el-tag v-if="store.usedTemplate" size="small" type="warning" effect="plain">标准模板渲染</el-tag>
      </div>
      <div class="head-right">
        <span class="head-question">{{ store.query }}</span>
        <el-button text type="primary" @click="openWorkbench">在工作台打开</el-button>
      </div>
    </header>

    <div class="view-body">
      <div v-if="loading" class="view-state">
        <el-icon class="is-loading" :size="36"><Loading /></el-icon>
        <p>正在加载页面…</p>
      </div>
      <div v-else-if="loadError" class="view-state">
        <el-icon :size="36" color="#dc2626"><WarningFilled /></el-icon>
        <p>{{ loadError }}</p>
        <el-button type="primary" plain @click="load">重试</el-button>
      </div>
      <div v-else-if="store.intent === 'general'" class="direct-panel">
        <div class="direct-meta">{{ store.query }}</div>
        <div class="direct-content" v-html="renderedDirect"></div>
      </div>
      <PageSandbox v-else :html="store.html" :bundle="store.dataBundle" />
    </div>
  </div>
</template>

<script setup lang="ts">
// ── 智能交互页面独立查看页（/interactive/view/:pageId）──
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Back, Loading, WarningFilled } from '@element-plus/icons-vue'
import PageSandbox from '@/components/interactive/PageSandbox.vue'
import { useInteractiveStore } from '@/stores/interactive'

const route = useRoute()
const router = useRouter()
const store = useInteractiveStore()

const loading = ref(true)
const loadError = ref('')

const renderedDirect = computed(() =>
  String(store.directAnswer || '').split(/\n+/).map((l) => l.trim()).filter(Boolean)
    .map((l) => `<p>${l.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c] as string)}</p>`)
    .join(''),
)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    await store.loadPage(String(route.params.pageId || ''))
    if (store.status !== 'ready') loadError.value = '该页面尚未生成完成或生成失败'
  } catch (e: any) {
    loadError.value = e?.serverMessage || e?.message || '页面不存在或加载失败'
  } finally {
    loading.value = false
  }
}

function goHome() {
  router.push('/')
}
function openWorkbench() {
  router.push('/situation-page')
}

onMounted(load)
</script>

<style scoped>
.ipage-view {
  height: calc(100vh - 60px);
  display: flex;
  flex-direction: column;
  background: #eef2f7;
}
.view-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 18px;
  background: #fff;
  border-bottom: 1px solid #e2e8f0;
}
.head-left { display: flex; align-items: center; gap: 6px; min-width: 0; }
.view-title { font-size: 16px; font-weight: 600; color: #0f172a; margin: 0; }
.head-right { display: flex; align-items: center; gap: 10px; flex-shrink: 0; }
.head-question {
  max-width: 420px;
  font-size: 12.5px;
  color: #64748b;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.view-body { flex: 1; min-height: 0; overflow: auto; padding: 18px; }
.view-state {
  height: 100%; min-height: 360px;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 12px; color: #64748b; font-size: 14px;
}
.is-loading { animation: ipage-spin 1s linear infinite; color: #1d4ed8; }
@keyframes ipage-spin { to { transform: rotate(360deg); } }
.direct-panel {
  max-width: 860px; margin: 0 auto;
  background: #fff; border-radius: 12px; padding: 28px 32px;
  box-shadow: 0 1px 4px rgba(15,23,42,.08);
}
.direct-meta {
  font-size: 13px; color: #1d4ed8; font-weight: 600;
  padding-bottom: 14px; margin-bottom: 14px; border-bottom: 1px solid #eef2f7;
}
.direct-content { font-size: 15px; line-height: 2; color: #1f2937; }
.direct-content p { margin-bottom: 8px; }
</style>
