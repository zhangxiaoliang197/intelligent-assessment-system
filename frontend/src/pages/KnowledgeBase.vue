<template>
  <Layout>
    <div class="knowledge-container">
      <div class="page-header">
        <div class="header-left">
          <h2>知识库管理</h2>
          <el-tag type="primary" size="small" effect="dark" class="engine-badge">Qdrant + BGE 语义检索</el-tag>
        </div>
        <div class="header-actions">
          <el-button @click="refreshData" :icon="Refresh">刷新</el-button>
          <el-button type="primary" @click="showUploadDialog = true" :icon="Upload">上传知识</el-button>
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
            <div class="stat-icon green">
              <el-icon :size="40"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.qdrant_vectors || 0 }}</h3>
              <p>向量索引</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon orange">
              <el-icon :size="40"><Cpu /></el-icon>
            </div>
            <div class="stat-info">
              <h3>BGE</h3>
              <p>嵌入模型</p>
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
            <div class="stat-icon pink">
              <el-icon :size="40"><Coin /></el-icon>
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
            placeholder="搜索文档名称..."
            prefix-icon="Search"
            clearable
            style="width: 280px"
          />
          <el-select v-model="filterCategory" placeholder="选择分类" clearable style="width: 180px">
            <el-option
              v-for="cat in categoryOptions"
              :key="cat"
              :label="cat"
              :value="cat"
            />
          </el-select>
          <el-select v-model="filterStatus" placeholder="选择状态" clearable style="width: 130px">
            <el-option label="已完成" value="已完成" />
            <el-option label="待处理" value="待解析" />
          </el-select>
          <div class="toolbar-spacer" />
          <el-button @click="showCategoryDialog = true" :icon="FolderOpened">
            分类管理
          </el-button>
          <el-tooltip content="重新生成所有文档的向量索引" placement="top">
            <el-button type="warning" @click="reindexAll" :loading="reindexing" :icon="RefreshRight">
              重建向量索引
            </el-button>
          </el-tooltip>
          <el-tooltip content="打开 Qdrant 管理面板查看向量数据" placement="top">
            <el-button @click="openQdrantDashboard" :icon="Monitor">
              Qdrant 面板
            </el-button>
          </el-tooltip>
        </div>

        <el-table :data="filteredKnowledge" style="width: 100%" stripe v-loading="loading">
          <el-table-column prop="title" label="文档名称" min-width="200" />
          <el-table-column prop="file_type" label="类型" width="120" />
          <el-table-column prop="category" label="分类" width="150" />
          <el-table-column label="状态" width="110">
            <template #default="scope">
              <el-tooltip :content="scope.row.status === '已完成' ? '已向量化，可语义检索' : '等待处理'" placement="top">
                <el-tag :type="getStatusType(scope.row.status)" effect="light">
                  {{ scope.row.status }}
                </el-tag>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column label="分片" width="80">
            <template #default="scope">
              <span class="chunk-count">{{ scope.row.chunk_count || 0 }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="upload_time" label="上传时间" width="180">
            <template #default="scope">
              {{ formatTime(scope.row.upload_time) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="240" fixed="right">
            <template #default="scope">
              <el-button size="small" text type="primary" @click="viewKnowledge(scope.row)">查看</el-button>
              <el-button size="small" text type="warning" @click="editKnowledge(scope.row)">编辑</el-button>
              <el-button size="small" text type="danger" @click="deleteKnowledge(scope.row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <!-- 上传对话框 -->
      <el-dialog v-model="showUploadDialog" title="上传知识文档" width="700px">
        <el-alert
          title="上传后自动向量化"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 1rem"
        >
          <template #default>
            <p>文档上传后将自动分片并通过 <strong>BGE-small-zh-v1.5</strong> 嵌入模型生成语义向量，存入 <strong>Qdrant</strong> 向量数据库，支持高精度语义检索。</p>
          </template>
        </el-alert>
        <el-form :model="uploadForm" label-width="100px">
          <el-form-item label="选择文件">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="20"
              multiple
              accept=".pdf,.doc,.docx,.txt,.md,.csv"
              :file-list="uploadFileList"
              @change="handleFileChange"
              @remove="handleFileRemove"
              drag
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖拽文件到此处，或 <em>点击选择</em></div>
              <template #tip>
                <div class="el-upload__tip">支持 PDF / Word / TXT / Markdown / CSV，单文件不超过 100MB</div>
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
                v-for="cat in categoryOptions"
                :key="cat"
                :label="cat"
                :value="cat"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="知识标签">
            <el-input v-model="uploadForm.tags" placeholder="多个标签用逗号分隔，用于精确筛选" />
          </el-form-item>

          <el-divider />
          <el-collapse>
            <el-collapse-item title="高级分片设置">
              <div class="chunk-settings">
                <el-form-item label="分片大小">
                  <el-input-number
                    v-model="uploadForm.chunkSize"
                    :min="100"
                    :max="800"
                    :step="50"
                    style="width: 100%"
                  />
                  <div class="setting-hint">每个分片最大字符数，模型上限 512 token（约 400 中文），超出会被截断</div>
                </el-form-item>
                <el-form-item label="重叠长度">
                  <el-input-number
                    v-model="uploadForm.chunkOverlap"
                    :min="0"
                    :max="500"
                    :step="10"
                    style="width: 100%"
                  />
                  <div class="setting-hint">相邻分片重叠字符数，避免关键信息被截断</div>
                </el-form-item>
              </div>
            </el-collapse-item>
          </el-collapse>
        </el-form>
        <template #footer>
          <el-button @click="showUploadDialog = false">取消</el-button>
          <el-button type="primary" @click="uploadKnowledge" :loading="uploading">
            上传 ({{ uploadFileList.length }} 个文件)
          </el-button>
        </template>
      </el-dialog>

      <!-- 编辑对话框 -->
      <el-dialog v-model="showEditDialog" title="编辑知识" width="500px">
        <el-form :model="editForm" label-width="100px">
          <el-form-item label="文档名称">
            <el-input v-model="editForm.title" placeholder="请输入文档名称" />
          </el-form-item>
          <el-form-item label="知识分类">
            <el-select v-model="editForm.category" placeholder="选择分类" style="width: 100%">
              <el-option
                v-for="cat in categoryOptions"
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
          <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
        </template>
      </el-dialog>

      <!-- 分类管理对话框 -->
      <el-dialog v-model="showCategoryDialog" title="管理分类" width="500px">
        <div class="category-manage">
          <div class="category-add-bar">
            <el-input
              v-model="newCategoryName"
              placeholder="输入新分类名称"
              size="default"
              @keydown.enter="addCategory"
            />
            <el-button type="primary" @click="addCategory" :disabled="!newCategoryName.trim()">
              新增
            </el-button>
          </div>
          <el-divider />
          <div class="category-list">
            <div
              v-for="cat in categoryOptions"
              :key="cat"
              class="category-item"
            >
              <span>{{ cat }}</span>
              <el-button
                v-if="cat !== '未分类'"
                text
                type="danger"
                size="small"
                @click="deleteCategory(cat)"
              >
                删除
              </el-button>
            </div>
          </div>
        </div>
      </el-dialog>

      <!-- 查看详情对话框 -->
      <el-dialog v-model="showViewDialog" title="文档详情" width="750px">
        <el-descriptions :column="2" border v-if="viewData">
          <el-descriptions-item label="文档名称" :span="2">{{ viewData.title }}</el-descriptions-item>
          <el-descriptions-item label="文件名">{{ viewData.filename }}</el-descriptions-item>
          <el-descriptions-item label="文件类型">{{ viewData.file_type }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ viewData.category }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag :type="getStatusType(viewData.status)" effect="light">{{ viewData.status }}</el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="上传时间">{{ formatTime(viewData.upload_time) }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatFileSize(viewData.file_size) }}</el-descriptions-item>
          <el-descriptions-item label="内容长度">{{ (viewData.content_length || 0).toLocaleString() }} 字符</el-descriptions-item>
          <el-descriptions-item label="分片数量" :span="2">
            <el-tag type="success" size="small">{{ viewData.chunk_count || 0 }} 个分片</el-tag>
            <span style="margin-left: 0.5rem; color: #909399; font-size: 0.85rem">
              （已向量化并存入 Qdrant）
            </span>
          </el-descriptions-item>
          <el-descriptions-item label="标签" :span="2">
            <el-tag v-for="tag in viewData.tags" :key="tag" size="small" style="margin-right: 0.5rem">{{ tag }}</el-tag>
            <span v-if="!viewData.tags || viewData.tags.length === 0" style="color: #c0c4cc">无</span>
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
import {
  Document, Files, Folder, Connection, Cpu, Coin,
  Refresh, Upload, RefreshRight, Monitor, UploadFilled, FolderOpened
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const searchQuery = ref('')
const filterCategory = ref('')
const filterStatus = ref('')
const showUploadDialog = ref(false)
const showEditDialog = ref(false)
const saving = ref(false)
const showViewDialog = ref(false)
const showCategoryDialog = ref(false)
const newCategoryName = ref('')
const uploadFileList = ref<any[]>([])
const uploadRef = ref()
const uploading = ref(false)
const reindexing = ref(false)
const loading = ref(false)

const uploadForm = ref({
  category: '未分类',
  tags: '',
  chunkSize: 400,
  chunkOverlap: 100
})

const editForm = ref({
  id: '',
  title: '',
  category: '',
  tags: ''
})

const viewData = ref<any>(null)
const knowledgeList = ref<any[]>([])

const categoryOptions = ref(['评估标准', '方法论', '案例库', '技术文档', '作战数据', '未分类'])

const stats = ref({
  total_documents: 0,
  total_chunks: 0,
  qdrant_vectors: 0,
  categories: 0,
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
  const typeMap: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
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
    return new Date(time).toLocaleString('zh-CN')
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
        total_chunks: res.data.total_chunks || 0,
        qdrant_vectors: res.data.qdrant_vectors || 0,
        categories: res.data.categories || 0,
        total_size_formatted: res.data.total_size_formatted || '0 MB'
      }
    }
  } catch (e) {
    console.error('加载统计数据失败:', e)
  }
}

const loadData = async () => {
  loading.value = true
  try {
    const res = await api.get('/knowledge/list?page_size=200')
    if (res.items) {
      knowledgeList.value = res.items
      // 动态更新分类选项
      const cats = new Set(categoryOptions.value)
      res.items.forEach((item: any) => {
        if (item.category) cats.add(item.category)
      })
      categoryOptions.value = Array.from(cats)
    }
    await loadStats()
  } catch (e) {
    ElMessage.error('加载知识列表失败')
  } finally {
    loading.value = false
  }
}

// ── 分类管理 ──
const addCategory = async () => {
  const name = newCategoryName.value.trim()
  if (!name) return
  if (categoryOptions.value.includes(name)) {
    ElMessage.warning('分类已存在')
    return
  }
  try {
    const formData = new FormData()
    formData.append('name', name)
    const res = await fetch('/api/knowledge/category', { method: 'POST', body: formData })
    const data = await res.json()
    if (data.success) {
      categoryOptions.value = [...categoryOptions.value, name]
      newCategoryName.value = ''
      ElMessage.success('分类添加成功')
    }
  } catch (e) {
    ElMessage.error('添加失败')
  }
}

const deleteCategory = async (name: string) => {
  try {
    const res = await fetch(`/api/knowledge/category/${encodeURIComponent(name)}`, { method: 'DELETE' })
    const data = await res.json()
    if (data.success) {
      categoryOptions.value = categoryOptions.value.filter(c => c !== name)
      ElMessage.success('分类删除成功')
      await loadData()
    }
  } catch (e) {
    ElMessage.error('删除失败')
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
      formData.append('chunk_size', String(uploadForm.value.chunkSize))
      formData.append('chunk_overlap', String(uploadForm.value.chunkOverlap))

      const res = await api.post('/knowledge/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      })
      if (res.success) {
        successCount++
      } else {
        failCount++
        console.error(`文件 ${file.name} 上传失败:`, res.message)
      }
    } catch (e: any) {
      failCount++
      console.error(`文件 ${file.name} 上传失败:`, e?.response?.data || e)
    }
  }

  uploading.value = false

  if (failCount === 0) {
    ElMessage.success(`成功上传并向量化 ${successCount} 个文件`)
  } else {
    ElMessage.warning(`${successCount} 个成功，${failCount} 个失败`)
  }

  showUploadDialog.value = false
  uploadFileList.value = []
  uploadForm.value = { category: '未分类', tags: '', chunkSize: 500, chunkOverlap: 100 }
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
  if (saving.value) return
  saving.value = true
  try {
    const formData = new FormData()
    formData.append('title', editForm.value.title)
    formData.append('category', editForm.value.category)
    formData.append('tags', editForm.value.tags)
    const res = await api.put(`/knowledge/${editForm.value.id}`, formData)
    if (res.success) {
      ElMessage.success('修改成功（已同步更新向量标签）')
      showEditDialog.value = false
      await loadData()
    }
  } catch (e) {
    ElMessage.error('修改失败')
  } finally {
    saving.value = false
  }
}

const deleteKnowledge = async (row: any) => {
  ElMessageBox.confirm(
    `确定删除"${row.title}"吗？将从 Qdrant 中移除对应向量索引。`,
    '删除确认',
    { confirmButtonText: '确定删除', cancelButtonText: '取消', type: 'warning' }
  ).then(async () => {
    try {
      const res = await api.delete(`/knowledge/${row.id}`)
      ElMessage.success(res.message || '已删除')
      await loadData()
    } catch (e) {
      ElMessage.error('删除失败')
    }
  }).catch(() => {})
}

const reindexAll = async () => {
  ElMessageBox.confirm(
    '将重新向量化所有文档并写入 Qdrant，耗时取决于文档数量。确定继续？',
    '重建向量索引',
    { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
  ).then(async () => {
    reindexing.value = true
    try {
      const res = await api.post('/knowledge/reindex')
      if (res.success) {
        ElMessage.success(res.message || '索引重建完成')
        await loadData()
      } else {
        ElMessage.error(res.message || '索引重建失败')
      }
    } catch (e) {
      ElMessage.error('索引重建失败')
    } finally {
      reindexing.value = false
    }
  }).catch(() => {})
}

const openQdrantDashboard = () => {
  window.open(`http://${window.location.hostname}:6333/dashboard`, '_blank')
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
  margin-bottom: 1.5rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.header-left h2 {
  margin: 0;
  color: #303133;
  font-size: 1.5rem;
  font-weight: 600;
}

.engine-badge {
  font-size: 0.75rem;
}

.header-actions {
  display: flex;
  gap: 0.75rem;
}

.stats-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 1rem;
  margin-bottom: 1.5rem;
}

.stat-card {
  border-radius: 12px;
}

.stat-content {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.stat-icon {
  width: 52px;
  height: 52px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon.blue   { background: rgba(64, 158, 255, 0.12); color: #409eff; }
.stat-icon.cyan  { background: rgba(64, 211, 255, 0.12); color: #00b8d4; }
.stat-icon.green  { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
.stat-icon.orange { background: rgba(230, 162, 60, 0.12); color: #e6a23c; }
.stat-icon.purple { background: rgba(144, 147, 153, 0.12); color: #909399; }
.stat-icon.pink   { background: rgba(255, 0, 135, 0.1); color: #ff0087; }

.stat-info h3 {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  color: #303133;
  line-height: 1.2;
}

.stat-info p {
  margin: 0.15rem 0 0 0;
  font-size: 0.82rem;
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
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  flex-wrap: wrap;
  align-items: center;
}

.toolbar-spacer {
  flex: 1;
}

.chunk-count {
  color: #67c23a;
  font-weight: 600;
}

.selected-files {
  max-height: 200px;
  overflow-y: auto;
  padding: 0.75rem;
  background: #f5f7fa;
  border-radius: 8px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.4rem 0;
  border-bottom: 1px solid #ebeef5;
  font-size: 0.9rem;
}

.file-item:last-child {
  border-bottom: none;
}

.file-item .file-size {
  margin-left: auto;
  color: #909399;
  font-size: 0.82rem;
}

.no-files {
  color: #909399;
  text-align: center;
  padding: 1.5rem;
}

.chunk-settings {
  padding: 0.5rem 0;
}

.setting-hint {
  font-size: 0.78rem;
  color: #909399;
  margin-top: 0.25rem;
  line-height: 1.4;
}

/* ── 分类管理 ── */
.category-manage {
  min-height: 200px;
}

.category-add-bar {
  display: flex;
  gap: 12px;
}

.category-list {
  max-height: 300px;
  overflow-y: auto;
}

.category-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-radius: 8px;
  margin-bottom: 4px;
  background: var(--gray-50);
  transition: background 0.2s;
}

.category-item:hover {
  background: var(--gray-100);
}
</style>
