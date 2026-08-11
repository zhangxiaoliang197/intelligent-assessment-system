<template>
  <el-dialog
    :model-value="modelValue"
    width="min(1040px, 96vw)"
    append-to-body
    destroy-on-close
    :close-on-click-modal="!saving"
    :before-close="beforeClose"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="dialog-heading">
        <div class="heading-icon"><el-icon><Document /></el-icon></div>
        <div>
          <div class="heading-title">
            <strong>{{ skill?.name || '态势 Skill' }} · SKILL.md</strong>
            <el-tag v-if="document" size="small" effect="plain" :type="document.source === 'custom' ? 'warning' : 'info'">
              {{ document.source === 'custom' ? '自定义' : '系统内置' }}
            </el-tag>
            <el-tag v-if="document?.overridden" size="small" type="warning" effect="plain">已在线修改</el-tag>
            <el-tag v-if="document && !document.editable" size="small" type="info" effect="plain">只读</el-tag>
          </div>
          <span class="heading-path">{{ document?.relativePath || '正在读取文档…' }}</span>
        </div>
      </div>
    </template>

    <div v-loading="loading" class="markdown-workbench">
      <el-alert
        v-if="loadError"
        type="error"
        show-icon
        :closable="false"
        title="SKILL.md 加载失败"
        :description="loadError"
      />

      <template v-else-if="document">
        <div class="document-toolbar">
          <el-radio-group v-model="activeMode" size="small">
            <el-radio-button label="preview">文档预览</el-radio-button>
            <el-radio-button label="source">Markdown 源码</el-radio-button>
            <el-radio-button label="edit" :disabled="!document.editable">编辑</el-radio-button>
          </el-radio-group>
          <div class="document-actions">
            <span class="document-status">
              v{{ document.revision }} · {{ storageLabel }}
              <template v-if="document.lastModified"> · {{ formatTime(document.lastModified) }}</template>
            </span>
            <el-button size="small" text :icon="CopyDocument" @click="copyMarkdown">复制</el-button>
            <el-button size="small" text :icon="Download" @click="downloadMarkdown">下载</el-button>
            <el-button size="small" text :icon="Refresh" :disabled="saving" @click="reloadDocument">刷新</el-button>
          </div>
        </div>

        <div v-if="activeMode === 'preview'" class="markdown-preview custom-scroll" v-html="previewHtml"></div>
        <div v-else class="source-panel">
          <el-input
            v-model="draftContent"
            type="textarea"
            resize="none"
            spellcheck="false"
            :readonly="activeMode !== 'edit' || !document.editable"
            :rows="25"
            class="markdown-editor"
            aria-label="态势 Skill Markdown 源码"
          />
          <div class="source-note">
            <span v-if="activeMode === 'edit' && document.editable">
              保存前会校验 YAML、Skill ID、分析步骤和文档标题；并发修改不会被静默覆盖。
            </span>
            <span v-else-if="document.editable">当前为只读源码模式，选择“编辑”后才能修改 Markdown。</span>
            <span v-else>当前账号可以查看和下载，但没有编辑权限。</span>
            <span>{{ byteLength }} / 131072 字节</span>
          </div>
        </div>
      </template>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <span v-if="dirty" class="dirty-hint">有未保存的修改</span>
        <span v-else></span>
        <div>
          <el-button @click="requestClose">关闭</el-button>
          <el-button
            v-if="document?.editable && activeMode === 'edit'"
            type="primary"
            :icon="Check"
            :loading="saving"
            :disabled="!dirty || byteLength > 131072"
            @click="saveDocument"
          >
            保存 SKILL.md
          </el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Check, CopyDocument, Document, Download, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getSituationSkillMarkdown,
  updateSituationSkillMarkdown,
} from '@/services/situationSkills'
import type { SituationSkill, SituationSkillMarkdownDocument } from '@/types/situationSkill'
import { renderMarkdown } from '@/utils/markdown'

const props = defineProps<{
  modelValue: boolean
  skill: SituationSkill | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved', skillId: string): void
}>()

const document = ref<SituationSkillMarkdownDocument | null>(null)
const draftContent = ref('')
const originalContent = ref('')
const activeMode = ref<'preview' | 'source' | 'edit'>('preview')
const loading = ref(false)
const saving = ref(false)
const loadError = ref('')
let loadSequence = 0

const dirty = computed(() => Boolean(document.value) && draftContent.value !== originalContent.value)
const byteLength = computed(() => new TextEncoder().encode(draftContent.value).length)
const storageLabel = computed(() => ({
  catalog: '内置目录',
  override: '在线覆盖层',
  custom: '自定义技能库',
})[document.value?.storage || 'catalog'])
const previewBody = computed(() => draftContent.value.replace(/^---\s*\n[\s\S]*?\n---\s*\n?/, ''))
const previewHtml = computed(() => renderMarkdown(previewBody.value))

function formatTime(value: string) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('zh-CN', { hour12: false })
}

async function loadDocument() {
  if (!props.skill) return
  const sequence = ++loadSequence
  loading.value = true
  loadError.value = ''
  try {
    const result = await getSituationSkillMarkdown(props.skill.id)
    if (sequence !== loadSequence) return
    document.value = result
    draftContent.value = result.content
    originalContent.value = result.content
    activeMode.value = 'preview'
  } catch (error: any) {
    if (sequence !== loadSequence) return
    document.value = null
    loadError.value = error?.serverMessage || error?.message || '请检查态势图服务是否可用'
  } finally {
    if (sequence === loadSequence) loading.value = false
  }
}

async function confirmDiscard() {
  if (!dirty.value) return true
  try {
    await ElMessageBox.confirm('当前 SKILL.md 有未保存的修改，确定放弃吗？', '放弃修改', {
      type: 'warning',
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
    })
    return true
  } catch {
    return false
  }
}

async function reloadDocument() {
  if (await confirmDiscard()) await loadDocument()
}

async function saveDocument() {
  if (!document.value?.editable || activeMode.value !== 'edit' || !dirty.value || saving.value) return
  saving.value = true
  try {
    const result = await updateSituationSkillMarkdown(
      document.value.skillId,
      draftContent.value,
      document.value.contentHash,
    )
    document.value = result
    draftContent.value = result.content
    originalContent.value = result.content
    emit('saved', result.skillId)
    ElMessage.success('态势 Skill 的 SKILL.md 已保存并通过完整性校验')
  } catch (error: any) {
    if (error?.response?.status === 409) {
      ElMessage.error('文档已经更新，请刷新后重新编辑')
    } else {
      ElMessage.error(error?.serverMessage || error?.message || 'SKILL.md 保存失败')
    }
  } finally {
    saving.value = false
  }
}

async function copyMarkdown() {
  try {
    await navigator.clipboard.writeText(draftContent.value)
    ElMessage.success('Markdown 已复制')
  } catch {
    ElMessage.warning('浏览器未允许访问剪贴板，请在源码模式中手动复制')
  }
}

function downloadMarkdown() {
  const blob = new Blob([draftContent.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = window.document.createElement('a')
  anchor.href = url
  anchor.download = `${props.skill?.id || 'situation-skill'}-SKILL.md`
  anchor.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 0)
}

async function requestClose() {
  if (await confirmDiscard()) emit('update:modelValue', false)
}

async function beforeClose(done: () => void) {
  if (await confirmDiscard()) done()
}

watch(
  () => [props.modelValue, props.skill?.id] as const,
  ([open, skillId], previous) => {
    if (open && skillId && (!previous?.[0] || skillId !== previous?.[1])) loadDocument()
    if (!open) {
      loadSequence += 1
      document.value = null
      draftContent.value = ''
      originalContent.value = ''
      loadError.value = ''
    }
  },
  { immediate: true },
)
</script>

<style scoped>
.dialog-heading,
.heading-title,
.document-toolbar,
.document-actions,
.dialog-footer { display: flex; align-items: center; }
.dialog-heading { gap: 12px; }
.heading-icon {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 10px;
  background: #eff6ff;
  color: #2563eb;
  font-size: 19px;
}
.heading-title { gap: 8px; }
.heading-title strong { color: #172033; font-size: 16px; }
.heading-path { display: block; margin-top: 4px; color: #8490a3; font: 12px Consolas, monospace; }
.markdown-workbench { min-height: 420px; }
.document-toolbar { justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.document-actions { gap: 3px; }
.document-status { margin-right: 8px; color: #7b8798; font-size: 12px; }
.markdown-preview {
  min-height: 420px;
  max-height: 62vh;
  overflow: auto;
  padding: 22px 28px;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  color: #273244;
  line-height: 1.75;
}
.markdown-preview :deep(h1) { margin: 0 0 20px; color: #172033; font-size: 25px; }
.markdown-preview :deep(h2) { margin: 26px 0 12px; border-bottom: 1px solid #edf0f5; padding-bottom: 7px; font-size: 19px; }
.markdown-preview :deep(code) { border-radius: 4px; background: #f3f6fa; padding: 2px 5px; color: #b42362; }
.markdown-editor :deep(textarea) {
  min-height: 420px !important;
  max-height: 62vh;
  padding: 16px 18px;
  background: #111827;
  color: #e5edf8;
  font-family: Consolas, 'SFMono-Regular', monospace;
  font-size: 13px;
  line-height: 1.65;
  tab-size: 2;
}
.markdown-editor :deep(textarea[readonly]) { background: #202938; color: #ced6e2; }
.source-note { display: flex; justify-content: space-between; gap: 20px; margin-top: 8px; color: #8490a3; font-size: 12px; }
.dialog-footer { justify-content: space-between; }
.dirty-hint { color: #d97706; font-size: 13px; }
@media (max-width: 720px) {
  .document-toolbar { align-items: flex-start; flex-direction: column; }
  .document-actions { flex-wrap: wrap; }
  .document-status { width: 100%; }
  .source-note { flex-direction: column; gap: 3px; }
}
</style>
