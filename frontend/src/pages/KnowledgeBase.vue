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
          <el-table-column prop="upload_time" label="上传时间" width="180" />
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

      <el-dialog v-model="showUploadDialog" title="上传知识文档" width="600px">
        <el-form :model="uploadForm" label-width="100px">
          <el-form-item label="选择文件">
            <el-upload
              ref="uploadRef"
              :auto-upload="false"
              :limit="10"
              multiple
              accept=".pdf,.doc,.docx,.xls,.xlsx,.txt,.md"
              :file-list="uploadFileList"
              @change="handleFileChange"
            >
              <el-button type="primary">选择文件</el-button>
              <template #tip>
                <div class="el-upload__tip">支持PDF、Word、Excel、TXT、Markdown格式，单个文件不超过100MB</div>
              </template>
            </el-upload>
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
          <el-button type="primary" @click="uploadKnowledge">上传</el-button>
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
          <el-descriptions-item label="上传时间">{{ viewData.upload_time }}</el-descriptions-item>
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
import { Document, SuccessFilled, Clock, Folder } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'

const searchQuery = ref('')
const filterCategory = ref('')
const filterStatus = ref('')
const showUploadDialog = ref(false)
const showEditDialog = ref(false)
const showViewDialog = ref(false)
const uploadFileList = ref<any[]>([])
const uploadRef = ref()

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

const knowledgeList = ref<any[]>([
  { id: '1', title: '作战效能评估标准', filename: '作战效能评估标准.pdf', file_type: 'PDF文档', category: '评估标准', tags: ['效能', '评估'], status: '已完成', upload_time: '2026-05-27 10:30', parse_time: '2026-05-27 10:35', content: '作战效能评估标准文档内容...' },
  { id: '2', title: '指标体系构建方法', filename: '指标体系构建方法.docx', file_type: 'Word文档', category: '方法论', tags: ['指标', '方法'], status: '已完成', upload_time: '2026-05-26 15:20', parse_time: '2026-05-26 15:25', content: '指标体系构建方法文档内容...' },
  { id: '3', title: '历史评估案例', filename: '历史评估案例.xlsx', file_type: 'Excel表格', category: '案例库', tags: ['案例', '历史'], status: '待解析', upload_time: '2026-05-25 09:15', parse_time: null, content: '' },
  { id: '4', title: '打击能力分析报告', filename: '打击能力分析报告.pdf', file_type: 'PDF文档', category: '作战数据', tags: ['打击', '分析'], status: '解析中', upload_time: '2026-05-24 14:00', parse_time: null, content: '' }
])

const categories = ref(['评估标准', '方法论', '案例库', '技术文档', '作战数据', '未分类'])

const stats = ref({
  total_documents: 4,
  parsed_documents: 2,
  pending_documents: 2,
  categories: 5
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
  const typeMap: Record<string, string> = {
    '已完成': 'success',
    '解析中': 'warning',
    '待解析': 'info',
    '解析失败': 'danger'
  }
  return typeMap[status] || 'info'
}

const loadData = () => {
  ElMessage.info('数据已刷新')
}

const handleFileChange = (file: any, files: any[]) => {
  uploadFileList.value = files
}

const uploadKnowledge = () => {
  if (uploadFileList.value.length === 0) {
    ElMessage.warning('请选择要上传的文件')
    return
  }

  uploadFileList.value.forEach(file => {
    const newKnowledge = {
      id: Date.now().toString() + Math.random().toString(36).substr(2, 9),
      title: file.name.replace(/\.[^/.]+$/, ''),
      filename: file.name,
      file_type: getFileType(file.name),
      category: uploadForm.value.category,
      tags: uploadForm.value.tags.split(',').filter(t => t.trim()),
      status: '待解析',
      upload_time: new Date().toLocaleString(),
      parse_time: null,
      content: ''
    }
    knowledgeList.value.unshift(newKnowledge)
  })

  stats.value.total_documents = knowledgeList.value.length
  stats.value.pending_documents = knowledgeList.value.filter(k => k.status === '待解析').length

  showUploadDialog.value = false
  uploadFileList.value = []
  uploadForm.value = { category: '未分类', tags: '' }

  ElMessage.success(`成功上传 ${uploadFileList.value.length} 个文件`)
}

const getFileType = (filename: string) => {
  const ext = filename.split('.').pop()?.toLowerCase()
  const typeMap: Record<string, string> = {
    'pdf': 'PDF文档',
    'doc': 'Word文档',
    'docx': 'Word文档',
    'xls': 'Excel表格',
    'xlsx': 'Excel表格',
    'txt': '文本文件',
    'md': 'Markdown文档'
  }
  return typeMap[ext || ''] || '未知类型'
}

const viewKnowledge = (row: any) => {
  viewData.value = row
  showViewDialog.value = true
}

const parseKnowledge = (row: any) => {
  row.status = '解析中'
  ElMessage.info(`正在解析：${row.title}`)

  setTimeout(() => {
    row.status = '已完成'
    row.parse_time = new Date().toLocaleString()
    row.content = `这是知识文档"${row.title}"的解析内容。包含关键信息和数据提取结果...`
    stats.value.parsed_documents = knowledgeList.value.filter(k => k.status === '已完成').length
    stats.value.pending_documents = knowledgeList.value.filter(k => k.status !== '已完成').length
    ElMessage.success(`解析完成：${row.title}`)
  }, 2000)
}

const parseAll = () => {
  const pendingList = knowledgeList.value.filter(k => k.status === '待解析')
  if (pendingList.length === 0) {
    ElMessage.warning('没有待解析的文档')
    return
  }

  ElMessage.info(`开始批量解析 ${pendingList.length} 个文档`)

  pendingList.forEach((item, index) => {
    setTimeout(() => {
      item.status = '已完成'
      item.parse_time = new Date().toLocaleString()
      item.content = `这是知识文档"${item.title}"的解析内容...`
      stats.value.parsed_documents = knowledgeList.value.filter(k => k.status === '已完成').length
      stats.value.pending_documents = knowledgeList.value.filter(k => k.status !== '已完成').length

      if (index === pendingList.length - 1) {
        ElMessage.success('批量解析完成')
      }
    }, (index + 1) * 2000)
  })
}

const editKnowledge = (row: any) => {
  editForm.value = {
    id: row.id,
    title: row.title,
    category: row.category,
    tags: row.tags.join(',')
  }
  showEditDialog.value = true
}

const saveEdit = () => {
  const knowledge = knowledgeList.value.find(k => k.id === editForm.value.id)
  if (knowledge) {
    knowledge.title = editForm.value.title
    knowledge.category = editForm.value.category
    knowledge.tags = editForm.value.tags.split(',').filter(t => t.trim())
    showEditDialog.value = false
    ElMessage.success('修改成功')
  }
}

const deleteKnowledge = (row: any) => {
  ElMessageBox.confirm(`确定删除知识文档"${row.title}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    knowledgeList.value = knowledgeList.value.filter(k => k.id !== row.id)
    stats.value.total_documents = knowledgeList.value.length
    stats.value.parsed_documents = knowledgeList.value.filter(k => k.status === '已完成').length
    stats.value.pending_documents = knowledgeList.value.filter(k => k.status !== '已完成').length
    ElMessage.success('删除成功')
  }).catch(() => {})
}

const refreshData = () => {
  loadData()
}

onMounted(() => {
  ElMessage.info('知识库加载完成')
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
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
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
</style>
