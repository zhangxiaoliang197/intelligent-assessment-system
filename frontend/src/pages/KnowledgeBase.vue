<template>
  <Layout>
    <div class="knowledge-container">
      <div class="page-header">
        <h2>知识库管理</h2>
        <div class="header-actions">
          <el-button @click="refreshData">刷新</el-button>
          <el-button type="primary" @click="showUploadDialog = true">上传知识</el-button>
        </div>
      </div>

      <div class="stats-cards">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon blue">
              <el-icon :size="40"><Document /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_documents || 0 }}</h3>
              <p>文档总数</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon green">
              <el-icon :size="40"><SuccessFilled /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.parsed_documents || 0 }}</h3>
              <p>已解析</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon orange">
              <el-icon :size="40"><Clock /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.pending_documents || 0 }}</h3>
              <p>待解析</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon purple">
              <el-icon :size="40"><Folder /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.categories || 0 }}</h3>
              <p>知识分类</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon cyan">
              <el-icon :size="40"><Files /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_chunks || 0 }}</h3>
              <p>知识分片</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon pink">
              <el-icon :size="40"><DataAnalysis /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_size_formatted || '0 MB' }}</h3>
              <p>总大小</p>
            </div>
          </div>
        </el-card>
      </div>

      <div class="content-section">
        <div class="toolbar">
          <el-input
            v-model="searchQuery"
            placeholder="搜索知识..."
            prefix-icon="Search"
            clearable
            style="width: 300px"
          />
          <el-select v-model="filterCategory" placeholder="选择分类" clearable style="width: 200px">
            <el-option
              v-for="cat in categories"
              :key="cat"
              :label="cat"
              :value="cat"
            />
          </el-select>
          <el-select v-model="filterStatus" placeholder="选择状态" clearable style="width: 150px">
            <el-option label="待解析" value="待解析" />
            <el-option label="解析中" value="解析中" />
            <el-option label="已完成" value="已完成" />
          </el-select>
          <el-button type="primary" @click="parseAll">批量解析</el-button>
        </div>

        <el-table :data="filteredKnowledge" style="width: 100%" stripe>
          <el-table-column prop="title" label="文档名称" min-width="200" />
          <el-table-column prop="file_type" label="类型" width="120" />
          <el-table-column prop="category" label="分类" width="150" />
          <el-table-column prop="status" label="状态" width="120">
            <template #default="scope">
              <el-tag :type="getStatusType(scope.row.status)">
                {{ scope.row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="upload_time" label="上传时间" width="180">
            <template #default="scope">
              {{ formatTime(scope.row.upload_time) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="300" fixed="right">
            <template #default="scope">
              <el-button size="small" @click="viewKnowledge(scope.row)">查看</el-button>
              <el-button size="small" type="warning" @click="parseKnowledge(scope.row)" :disabled="scope.row.status === '已完成'">
                解析
              </el-button>
              <el-button size="small" @click="editKnowledge(scope.row)">编辑</el-button>
              <el-button size="small" type="danger" @click="deleteKnowledge(scope.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <el-dialog v-model="showUploadDialog" title="上传知识文档" width="700px">
        <el-form :model="uploadForm" label-width="100px">
          <el-form-item label="选择文件">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="10"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.md,.csv"
              :file-list="uploadFileList"
              @change="handleFileChange"
              @remove="handleFileRemove"
            >
              <el-button type="primary">选择文件</el-button>
              <template #tip>
                <div class="el-upload__tip">支持PDF、Word、Excel、TXT、Markdown格式，单个文件不超过100MB</div>
              </template>
            </el-upload>
          </el-form-item>
          <el-form-item label="已选文件">
            <div class="selected-files">
              <div v-for="(file, index) in uploadFileList" :key="index" class="file-item">
                <el-icon><Document /></el-icon>
                <span>{{ file.name }}</span>
                <span class="file-size">{{ formatFileSize(file.size) }}</span>
              </div>
              <div v-if="uploadFileList.length === 0" class="no-files">未选择文件</div>
            </div>
          </el-form-item>
          <el-form-item label="知识分类">
            <el-select v-model="uploadForm.category" placeholder="选择分类" style="width: 100%">
              <el-option
                v-for="cat in ['评估标准', '方法论', '案例库', '技术文档', '作战数据', '未分类']"
                :key="cat"
                :label="cat"
                :value="cat"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="知识标签">
            <el-input v-model="uploadForm.tags" placeholder="多个标签用逗号分隔" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showUploadDialog = false">取消</el-button>
          <el-button type="primary" @click="uploadKnowledge" :loading="uploading">上传 ({{ uploadFileList.length }}个文件)</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showEditDialog" title="编辑知识" width="500px">
        <el-form :model="editForm" label-width="100px">
          <el-form-item label="知识名称">
            <el-input v-model="editForm.title" placeholder="请输入知识名称" />
          </el-form-item>
          <el-form-item label="知识分类">
            <el-select v-model="editForm.category" placeholder="选择分类" style="width: 100%">
              <el-option
                v-for="cat in ['评估标准', '方法论', '案例库', '技术文档', '作战数据', '未分类']"
                :key="cat"
                :label="cat"
                :value="cat"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="知识标签">
            <el-input v-model="editForm.tags" placeholder="多个标签用逗号分隔" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showEditDialog = false">取消</el-button>
          <el-button type="primary" @click="saveEdit">保存</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showViewDialog" title="知识详情" width="700px">
        <el-descriptions :column="2" border v-if="viewData">
          <el-descriptions-item label="文档名称" :span="2">{{ viewData.title }}</el-descriptions-item>
          <el-descriptions-item label="文件名">{{ viewData.filename }}</el-descriptions-item>
          <el-descriptions-item label="文件类型">{{ viewData.file_type }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ viewData.category }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusType(viewData.status)">{{ viewData.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="上传时间">{{ formatTime(viewData.upload_time) }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatFileSize(viewData.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="内容长度">{{ viewData.content_length || 0 }} 字符</el-descriptions-item>
          <el-descriptions-item label="解析时间" :span="2">{{ viewData.parse_time || '未解析' }}</el-descriptions-item>
          <el-descriptions-item label="标签" :span="2">
            <el-tag v-for="tag in viewData.tags" :key="tag" size="small" style="margin-right: 0.5rem">{{ tag }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="内容预览" :span="2">
            <div class="content-preview">{{ viewData.content || '暂无内容，请先解析文档' }}</div>
          </el-descriptions-item>
        </el-descriptions>
        <template #footer>
          <el-button @click="showViewDialog = false">关闭</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Document, SuccessFilled, Clock, Folder, Files, DataAnalysis } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const searchQuery = ref('')
const filterCategory = ref('')
const filterStatus = ref('')
const showUploadDialog = ref(false)
const showEditDialog = ref(false)
const showViewDialog = ref(false)
const uploadFileList = ref<any[]>([])
const uploadRef = ref()
const uploading = ref(false)

const uploadForm = ref({
  category: '未分类',
  tags: ''
})

const editForm = ref({
  id: '',
  title: '',
  category: '',
  tags: ''
})

const viewData = ref<any>(null)

const knowledgeList = ref<any[]>([])

const categories = ref(['评估标准', '方法论', '案例库', '技术文档', '作战数据', '未分类'])

const stats = ref({
  total_documents: 0,
  parsed_documents: 0,
  pending_documents: 0,
  categories: 0,
  total_chunks: 0,
  total_size: 0,
  total_size_formatted: '0 MB'
})

const filteredKnowledge = computed(() => {
  return knowledgeList.value.filter(item => {
    const matchSearch = !searchQuery.value || item.title.toLowerCase().includes(searchQuery.value.toLowerCase())
    const matchCategory = !filterCategory.value || item.category === filterCategory.value
    const matchStatus = !filterStatus.value || item.status === filterStatus.value
    return matchSearch && matchCategory && matchStatus
  })
})

const getStatusType = (status: string) => {
  const typeMap: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
    '已完成': 'success',
    '解析中': 'warning',
    '待解析': 'info',
    '解析失败': 'danger'
  }
  return typeMap[status] || 'info'
}

const formatTime = (time: string) => {
  if (!time) return ''
  try {
    const date = new Date(time)
    return date.toLocaleString('zh-CN')
  } catch {
    return time
  }
}

const formatFileSize = (bytes: number) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let size = bytes
  let unitIndex = 0
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024
    unitIndex++
  }
  return `${size.toFixed(2)} ${units[unitIndex]}`
}

const loadStats = async () => {
  try {
    const res = await api.get('/knowledge/stats')
    if (res.success && res.data) {
      stats.value = {
        total_documents: res.data.total_documents || 0,
        parsed_documents: res.data.parsed_documents || 0,
        pending_documents: res.data.pending_documents || 0,
        categories: res.data.categories || 0,
        total_chunks: res.data.total_chunks || 0,
        total_size: res.data.total_size || 0,
        total_size_formatted: res.data.total_size_formatted || '0 MB'
      }
    }
  } catch (e) {
    console.error('加载统计数据失败:', e)
  }
}

const loadData = async () => {
  try {
    const res = await api.get('/knowledge/list?page_size=100')
    if (res.items) {
      knowledgeList.value = res.items
    }
    await loadStats()
  } catch (e) {
    ElMessage.error('加载知识列表失败')
  }
}

const handleFileChange = (_file: any, files: any[]) => {
  uploadFileList.value = files
}

const handleFileRemove = (_file: any, files: any[]) => {
  uploadFileList.value = files
}

const uploadKnowledge = async () => {
  if (uploadFileList.value.length === 0) {
    ElMessage.warning('请选择要上传的文件')
    return
  }

  uploading.value = true
  let successCount = 0
  let failCount = 0

  for (const file of uploadFileList.value) {
    try {
      const formData = new FormData()
      const rawFile = file.raw || file
      formData.append('file', rawFile)
      formData.append('category', uploadForm.value.category)
      formData.append('tags', uploadForm.value.tags)

      await api.post('/knowledge/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      successCount++
    } catch (e) {
      failCount++
      console.error(`文件 ${file.name} 上传失败:`, e)
    }
  }

  uploading.value = false
  
  if (failCount === 0) {
    ElMessage.success(`成功上传 ${successCount} 个文件`)
  } else {
    ElMessage.warning(`上传完成：${successCount} 个成功，${failCount} 个失败`)
  }
  
  showUploadDialog.value = false
  uploadFileList.value = []
  uploadForm.value = { category: '未分类', tags: '' }
  await loadData()
}

const viewKnowledge = async (row: any) => {
  try {
    const res = await api.get(`/knowledge/${row.id}`)
    if (res.success && res.data) {
      viewData.value = res.data
    } else {
      viewData.value = row
    }
    showViewDialog.value = true
  } catch (e) {
    viewData.value = row
    showViewDialog.value = true
  }
}

const parseKnowledge = async (row: any) => {
  row.status = '解析中'
  try {
    const res = await api.post(`/knowledge/parse/${row.id}`)
    if (res.success) {
      ElMessage.success(res.message || '解析完成')
      await loadData()
    }
  } catch (e) {
    row.status = '解析失败'
    ElMessage.error('解析失败')
  }
}

const parseAll = async () => {
  try {
    ElMessage.info('开始批量解析...')
    const res = await api.post('/knowledge/parse/all')
    if (res.success) {
      ElMessage.success(res.message || '批量解析完成')
      await loadData()
    }
  } catch (e) {
    ElMessage.error('批量解析失败')
  }
}

const editKnowledge = (row: any) => {
  editForm.value = {
    id: row.id,
    title: row.title,
    category: row.category,
    tags: Array.isArray(row.tags) ? row.tags.join(',') : row.tags
  }
  showEditDialog.value = true
}

const saveEdit = async () => {
  try {
    const res = await api.put(`/knowledge/${editForm.value.id}`, {
      category: editForm.value.category,
      tags: editForm.value.tags
    })
    if (res.success) {
      ElMessage.success('修改成功')
      showEditDialog.value = false
      await loadData()
    }
  } catch (e) {
    ElMessage.error('修改失败')
  }
}

const deleteKnowledge = async (row: any) => {
  ElMessageBox.confirm(`确定删除知识文档"${row.title}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(async () => {
    try {
      await api.delete(`/knowledge/${row.id}`)
      ElMessage.success('删除成功')
      await loadData()
    } catch (e) {
      ElMessage.error('删除失败')
    }
  }).catch(() => {})
}

const refreshData = () => {
  loadData()
  ElMessage.success('数据已刷新')
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.knowledge-container {
  height: 100%;
  padding: 2rem;
  overflow-y: auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2rem;
}

.page-header h2 {
  margin: 0;
  color: #303133;
  font-size: 1.5rem;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 1rem;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
  margin-bottom: 2rem;
}

.stat-card {
  border-radius: 12px;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.stat-icon {
  width: 60px;
  height: 60px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon.blue {
  background: rgba(64, 158, 255, 0.1);
  color: #409eff;
}

.stat-icon.green {
  background: rgba(103, 194, 58, 0.1);
  color: #67c23a;
}

.stat-icon.orange {
  background: rgba(230, 162, 60, 0.1);
  color: #e6a23c;
}

.stat-icon.purple {
  background: rgba(144, 147, 153, 0.1);
  color: #909399;
}

.stat-icon.cyan {
  background: rgba(64, 211, 255, 0.1);
  color: #00d5ff;
}

.stat-icon.pink {
  background: rgba(255, 0, 135, 0.1);
  color: #ff0087;
}

.stat-info h3 {
  margin: 0;
  font-size: 1.8rem;
  font-weight: 700;
  color: #303133;
}

.stat-info p {
  margin: 0.25rem 0 0 0;
  font-size: 0.9rem;
  color: #909399;
}

.content-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.toolbar {
  display: flex;
  gap: 1rem;
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
}

.content-preview {
  max-height: 200px;
  overflow-y: auto;
  padding: 1rem;
  background: #f5f7fa;
  border-radius: 4px;
  font-size: 0.9rem;
  color: #606266;
  white-space: pre-wrap;
}

.selected-files {
  max-height: 200px;
  overflow-y: auto;
  padding: 1rem;
  background: #f5f7fa;
  border-radius: 4px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0;
  border-bottom: 1px solid #ebeef5;
  font-size: 0.9rem;
}

.file-item:last-child {
  border-bottom: none;
}

.file-item .file-size {
  margin-left: auto;
  color: #909399;
  font-size: 0.85rem;
}

.no-files {
  color: #909399;
  text-align: center;
  padding: 2rem;
}
</style>
