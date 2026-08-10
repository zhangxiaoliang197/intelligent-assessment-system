<template>
  <div class="situation-toolbar">
    <div class="toolbar-left">
      <span class="toolbar-title">{{ title || '态势图' }}</span>
      <el-tag v-if="sourceTag" size="small" :type="sourceTagType">{{ sourceTag }}</el-tag>
      <el-tag v-if="statusTag" size="small" :type="statusTagType">{{ statusText }}</el-tag>
    </div>
    <div class="toolbar-right">
      <el-button :icon="Refresh" size="small" :disabled="!canRefresh" @click="$emit('refresh')">
        刷新
      </el-button>
      <el-button :icon="Share" size="small" :disabled="!canExport" @click="$emit('share')">
        分享
      </el-button>
      <el-dropdown trigger="click" @command="onExport">
        <el-button :icon="Download" size="small" :disabled="!canExport">导出</el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item command="pdf">导出 PDF</el-dropdown-item>
            <el-dropdown-item command="image">导出图片</el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
      <el-button :icon="Clock" size="small" @click="goList">历史</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Refresh, Share, Download, Clock } from '@element-plus/icons-vue'

const props = defineProps<{
  title?: string
  source?: string
  status?: string
  canRefresh?: boolean
  canExport?: boolean
}>()

const emit = defineEmits<{
  (e: 'refresh'): void
  (e: 'share'): void
  (e: 'export', format: 'pdf' | 'image'): void
}>()

const router = useRouter()

const SOURCE_LABELS: Record<string, string> = {
  manual: '直接提问',
  qa: '来自知识问答',
  indicator: '来自指标分析',
  evaluation: '来自评估分析',
}

const sourceTag = computed(() => (props.source ? SOURCE_LABELS[props.source] || props.source : ''))
const sourceTagType = computed(() => (props.source && props.source !== 'manual' ? 'warning' : 'info'))

const statusTag = computed(() => !!props.status && props.status !== 'idle')
const statusTagType = computed(() => {
  switch (props.status) {
    case 'generating': return 'warning'
    case 'ready': return 'success'
    case 'partial': return 'warning'
    case 'failed': return 'danger'
    default: return 'info'
  }
})
const statusText = computed(() => {
  switch (props.status) {
    case 'generating': return '生成中'
    case 'ready': return '已就绪'
    case 'partial': return '部分完成'
    case 'failed': return '生成失败'
    default: return ''
  }
})

function onExport(cmd: string) {
  emit('export', cmd as 'pdf' | 'image')
}

function goList() {
  router.push('/situation/list')
}
</script>

<style scoped>
.situation-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #ebeef5;
  gap: 12px;
  flex-wrap: wrap;
}
.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.toolbar-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
}
</style>
