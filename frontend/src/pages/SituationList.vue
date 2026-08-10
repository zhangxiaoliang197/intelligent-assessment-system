<template>
  <div class="situation-list-page">
    <div class="list-header">
      <h3>态势图历史</h3>
      <el-button type="primary" @click="goNew">新建态势图</el-button>
    </div>
    <el-table :data="items" v-loading="loading" border stripe style="width: 100%">
      <el-table-column prop="title" label="标题" min-width="180" />
      <el-table-column prop="query" label="问题" min-width="220" show-overflow-tooltip />
      <el-table-column prop="source" label="来源" width="110">
        <template #default="{ row }">
          <el-tag size="small" :type="sourceTagType(row.source)">{{ sourceLabel(row.source) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100">
        <template #default="{ row }">
          <el-tag size="small" :type="statusTagType(row.status)">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="createdAt" label="创建时间" width="180" />
      <el-table-column label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="open(row.reportId)">查看</el-button>
          <el-button size="small" type="danger" @click="remove(row.reportId)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
    <div class="pager">
      <el-pagination
        v-model:current-page="page"
        v-model:page-size="size"
        :total="total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next"
        @current-change="load"
        @size-change="load"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/services/api'

const router = useRouter()
const items = ref<any[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const resp: any = await api.get('/situation/reports', { params: { page: page.value, size: size.value } })
    if (resp?.success !== false) {
      const data = resp.data || resp
      items.value = data.items || []
      total.value = data.total || 0
    }
  } catch (e: any) {
    ElMessage.error('列表加载失败：' + (e?.serverMessage || ''))
  } finally {
    loading.value = false
  }
}

function open(reportId: string) {
  router.push(`/situation?reportId=${reportId}`)
}

async function remove(reportId: string) {
  await ElMessageBox.confirm('确认删除该态势图？', '提示', { type: 'warning' })
  try {
    const resp: any = await api.delete(`/situation/reports/${reportId}`)
    if (resp?.success !== false) {
      ElMessage.success('已删除')
      load()
    }
  } catch (e: any) {
    ElMessage.error('删除失败：' + (e?.serverMessage || ''))
  }
}

function goNew() {
  router.push('/situation')
}

function sourceLabel(s: string) {
  return ({ manual: '直接', qa: '问答', indicator: '指标', evaluation: '评估' } as any)[s] || s
}
function sourceTagType(s: string) {
  return s === 'manual' ? 'info' : 'warning'
}
function statusLabel(s: string) {
  return ({ generating: '生成中', ready: '就绪', partial: '部分', failed: '失败' } as any)[s] || s
}
function statusTagType(s: string) {
  return ({ ready: 'success', generating: 'warning', partial: 'warning', failed: 'danger' } as any)[s] || 'info'
}

onMounted(load)
</script>

<style scoped>
.situation-list-page {
  padding: 16px;
  height: 100vh;
  overflow-y: auto;
  background: #f5f7fa;
}
.list-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.list-header h3 {
  margin: 0;
  font-size: 18px;
  color: #303133;
}
.pager {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}
</style>
