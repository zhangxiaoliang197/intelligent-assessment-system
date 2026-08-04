<template>
  <Layout>
    <div class="ontology-home">
      <!-- 页面头部 -->
      <div class="page-header">
        <div class="header-left">
          <h2>本体模型</h2>
          <el-tag type="primary" size="small" effect="dark" class="engine-badge">ECharts 知识图谱</el-tag>
        </div>
        <div class="header-actions">
          <el-button @click="refreshData" :icon="Refresh">刷新</el-button>
          <el-button type="primary" @click="showCreateDialog = true" :icon="Plus">新建本体</el-button>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="stats-cards">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon blue">
              <el-icon :size="36"><Box /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_ontologies }}</h3>
              <p>本体总数</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon cyan">
              <el-icon :size="36"><Collection /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_entities }}</h3>
              <p>实体总数</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon green">
              <el-icon :size="36"><Connection /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_relations }}</h3>
              <p>关系总数</p>
            </div>
          </div>
        </el-card>
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon purple">
              <el-icon :size="36"><SetUp /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.build_tasks_count }}</h3>
              <p>构建任务</p>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 工具栏 -->
      <div class="content-section">
        <div class="toolbar">
          <el-input
            v-model="searchQuery"
            placeholder="搜索本体名称..."
            prefix-icon="Search"
            clearable
            style="width: 280px"
          />
          <el-select v-model="filterStatus" placeholder="选择状态" clearable style="width: 130px">
            <el-option label="活跃" value="活跃" />
            <el-option label="归档" value="归档" />
          </el-select>
          <div class="toolbar-spacer" />
          <el-button type="primary" @click="showBuildDialog = true" :icon="DocumentAdd">
            文档构建
          </el-button>
          <el-upload :show-file-list="false" :before-upload="handleImportFile" accept=".json">
            <el-button :icon="Upload">导入 JSON</el-button>
          </el-upload>
        </div>

        <!-- 本体卡片网格 -->
        <div class="ontology-grid" v-loading="loading">
          <div v-for="ont in filteredOntologies" :key="ont.id" class="ontology-card">
            <div class="card-header">
              <h3>{{ ont.name }}</h3>
              <el-tag v-if="ont.is_default" type="warning" size="small">默认</el-tag>
            </div>
            <p class="card-desc">{{ ont.description || '暂无描述' }}</p>
            <div class="card-stats">
              <span><el-icon><Box /></el-icon> {{ ont.entities_count }} 实体</span>
              <span><el-icon><Connection /></el-icon> {{ ont.relations_count }} 关系</span>
            </div>
            <div class="card-meta">
              创建: {{ formatTime(ont.create_time) }}
            </div>
            <div class="card-actions">
              <el-button type="primary" size="small" @click="viewOntology(ont.id)">
                查看图谱
              </el-button>
              <el-dropdown trigger="click" @command="(cmd: string) => handleCardAction(cmd, ont)">
                <el-button size="small">
                  更多<el-icon class="el-icon--right"><ArrowDown /></el-icon>
                </el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="edit">编辑</el-dropdown-item>
                    <el-dropdown-item command="export">导出</el-dropdown-item>
                    <el-dropdown-item command="default" v-if="!ont.is_default">设为默认</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <el-empty v-if="!filteredOntologies.length && !loading" description="暂无本体模型" :image-size="120">
            <el-button type="primary" @click="showCreateDialog = true">创建第一个本体</el-button>
          </el-empty>
        </div>
      </div>

      <!-- 构建任务列表 -->
      <div class="content-section" v-if="buildTasks.length > 0">
        <div class="section-header">
          <h3>进行中的构建任务</h3>
          <el-button type="primary" size="small" @click="showBuildDialog = true">
            新建任务
          </el-button>
        </div>
        <div class="build-tasks-list">
          <div v-for="task in buildTasks" :key="task.id" class="build-task-card">
            <div class="task-header">
              <h4>{{ task.name }}</h4>
              <el-tag :type="getTaskStatusType(task.status)" size="small">
                {{ task.status }}
              </el-tag>
            </div>
            <div class="task-progress">
              <el-steps :active="getTaskStep(task)" align-center>
                <el-step title="上传文档" />
                <el-step title="提取概念" />
                <el-step title="构建结构" />
                <el-step title="生成本体" />
              </el-steps>
            </div>
            <div class="task-meta">
              <span>源文档: {{ task.source_filename }}</span>
              <span>创建: {{ formatTime(task.create_time) }}</span>
            </div>
            <div class="task-actions">
              <el-button type="primary" size="small" @click="continueBuild(task.id)">
                继续构建
              </el-button>
              <el-button size="small" type="danger" @click="deleteBuildTask(task.id)">
                删除
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 新建/编辑本体对话框 -->
      <el-dialog v-model="showCreateDialog" :title="editingOntology ? '编辑本体模型' : '新建本体模型'" width="700px">
        <el-form :model="ontologyForm" label-width="120px">
          <el-form-item label="本体名称" required>
            <el-input v-model="ontologyForm.name" placeholder="请输入本体名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input 
              v-model="ontologyForm.description" 
              type="textarea" 
              :rows="3"
              placeholder="请输入本体描述" 
            />
          </el-form-item>
          
          <el-divider>元模型定义</el-divider>
          
          <el-form-item label="实体类型">
            <div class="type-editor">
              <div v-for="(t, idx) in ontologyForm.entityTypes" :key="idx" class="type-row">
                <el-input v-model="t.name" placeholder="类型名" size="small" style="width: 160px" />
                <el-color-picker v-model="t.color" size="small" />
                <el-button size="small" link type="danger" @click="ontologyForm.entityTypes.splice(idx, 1)">
                  删除
                </el-button>
              </div>
              <el-button size="small" @click="ontologyForm.entityTypes.push({ name: '', color: '#5470c6' })">
                + 添加实体类型
              </el-button>
            </div>
          </el-form-item>
          
          <el-form-item label="关系类型">
            <div class="type-editor">
              <div v-for="(t, idx) in ontologyForm.relationTypes" :key="idx" class="type-row">
                <el-input v-model="t.name" placeholder="关系名" size="small" style="width: 160px" />
                <el-button size="small" link type="danger" @click="ontologyForm.relationTypes.splice(idx, 1)">
                  删除
                </el-button>
              </div>
              <el-button size="small" @click="ontologyForm.relationTypes.push({ name: '' })">
                + 添加关系类型
              </el-button>
            </div>
          </el-form-item>
        </el-form>
        
        <template #footer>
          <el-button @click="showCreateDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitOntology">
            {{ editingOntology ? '更新' : '创建' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- 导入 JSON 对话框 -->
      <el-dialog v-model="showImportDialog" title="导入本体 JSON" width="600px">
        <el-alert
          title="导入说明"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 1rem"
        >
          <template #default>
            <p>导入 JSON 文件将创建新的本体模型，不会覆盖现有本体。系统会自动映射实体 ID，确保关系不断链。</p>
          </template>
        </el-alert>
        
        <el-upload
          ref="uploadRef"
          :auto-upload="false"
          :limit="1"
          accept=".json"
          :on-change="handleImportFileChange"
          drag
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">拖拽 JSON 文件到此处，或 <em>点击选择</em></div>
          <template #tip>
            <div class="el-upload__tip">仅支持 .json 格式的本体导出文件</div>
          </template>
        </el-upload>
        
        <div v-if="importPreview" class="import-preview">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="本体名称">{{ importPreview.name }}</el-descriptions-item>
            <el-descriptions-item label="版本">{{ importPreview.version }}</el-descriptions-item>
            <el-descriptions-item label="实体数量">{{ importPreview.entities?.length || 0 }}</el-descriptions-item>
            <el-descriptions-item label="关系数量">{{ importPreview.relations?.length || 0 }}</el-descriptions-item>
            <el-descriptions-item label="描述" :span="2">{{ importPreview.description }}</el-descriptions-item>
          </el-descriptions>
        </div>
        
        <template #footer>
          <el-button @click="showImportDialog = false">取消</el-button>
          <el-button type="primary" :loading="importing" :disabled="!importFile" @click="submitImport">
            导入
          </el-button>
        </template>
      </el-dialog>

      <!-- 文档构建对话框 -->
      <el-dialog v-model="showBuildDialog" title="文档构建" width="600px">
        <el-alert
          title="从文档自动构建本体模型"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 1rem"
        >
          <template #default>
            <p>上传文档后，AI 将自动分析文档内容，提取概念和关系，生成本体模型。整个过程分为 4 个步骤，您可以在每步进行编辑和确认。</p>
          </template>
        </el-alert>
        
        <el-form :model="buildForm" label-width="100px">
          <el-form-item label="本体名称" required>
            <el-input v-model="buildForm.name" placeholder="请输入本体名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input 
              v-model="buildForm.description" 
              type="textarea" 
              :rows="3"
              placeholder="请输入本体描述" 
            />
          </el-form-item>
          <el-form-item label="选择文档" required>
            <el-upload
              ref="buildUploadRef"
              :auto-upload="false"
              :limit="1"
              accept=".pdf,.doc,.docx,.txt,.md"
              :on-change="handleBuildFileChange"
              drag
            >
              <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
              <div class="el-upload__text">拖拽文档到此处，或 <em>点击选择</em></div>
              <template #tip>
                <div class="el-upload__tip">支持 PDF / Word / TXT / Markdown 格式</div>
              </template>
            </el-upload>
          </el-form-item>
        </el-form>
        
        <template #footer>
          <el-button @click="showBuildDialog = false">取消</el-button>
          <el-button type="primary" :loading="creatingBuild" :disabled="!buildForm.file" @click="startBuild">
            开始构建
          </el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Box, Collection, Connection, SetUp,
  Refresh, Plus, DocumentAdd, Upload, UploadFilled, ArrowDown
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import {
  getOntologyList,
  getOntologyStats,
  createOntology,
  updateOntology,
  deleteOntology as deleteOntologyApi,
  setDefaultOntology,
  importOntology,
  exportOntology as exportOntologyApi
} from '@/services/ontology'
import { getBuildJobList, createBuildJob, deleteBuildJob } from '@/services/ontologyBuild'

const router = useRouter()

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)
const importing = ref(false)
const creatingBuild = ref(false)

const ontologies = ref<any[]>([])
const buildTasks = ref<any[]>([])
const searchQuery = ref('')
const filterStatus = ref('')

const stats = ref({
  total_ontologies: 0,
  total_entities: 0,
  total_relations: 0,
  build_tasks_count: 0
})

// 对话框开关
const showCreateDialog = ref(false)
const showImportDialog = ref(false)
const showBuildDialog = ref(false)

// 表单数据
const editingOntology = ref<any>(null)
const ontologyForm = ref({
  name: '',
  description: '',
  entityTypes: [
    { name: '概念', color: '#5470c6' },
    { name: '实体', color: '#91cc75' },
    { name: '属性', color: '#fac858' },
    { name: '事件', color: '#ee6666' }
  ],
  relationTypes: [
    { name: '包含' },
    { name: '关联' },
    { name: '影响' }
  ]
})

const importFile = ref<File | null>(null)
const importPreview = ref<any>(null)
const uploadRef = ref()

const buildForm = ref({
  name: '',
  description: '',
  file: null as File | null
})
const buildUploadRef = ref()

// ── 计算属性 ──
const filteredOntologies = computed(() => {
  return ontologies.value.filter(ont => {
    const matchSearch = !searchQuery.value || 
      ont.name.toLowerCase().includes(searchQuery.value.toLowerCase())
    const matchStatus = !filterStatus.value || ont.status === filterStatus.value
    return matchSearch && matchStatus
  })
})

// ── 数据加载 ──
const loadStats = async () => {
  try {
    const [statsRes, buildRes] = await Promise.all([
      getOntologyStats(),
      getBuildJobList()
    ])

    const statsData = (statsRes as any).data
    stats.value = {
      total_ontologies: statsData.total_ontologies || 0,
      total_entities: statsData.total_entities || 0,
      total_relations: statsData.total_relations || 0,
      build_tasks_count: ((buildRes as any).data || []).length
    }
  } catch (e) {
    console.error('加载统计数据失败:', e)
  }
}

const loadData = async () => {
  loading.value = true
  try {
    const [ontRes, buildRes] = await Promise.all([
      getOntologyList(),
      getBuildJobList()
    ])
    ontologies.value = (ontRes as any).items || []
    buildTasks.value = (buildRes as any).data || []
    await loadStats()
  } catch (e) {
    ElMessage.error('加载数据失败')
  } finally {
    loading.value = false
  }
}

const refreshData = () => {
  loadData()
  ElMessage.success('数据已刷新')
}

// ── 本体操作 ──
const viewOntology = (id: string) => {
  router.push(`/ontology/${id}`)
}

// 卡片下拉菜单统一处理
const handleCardAction = (cmd: string, ont: any) => {
  if (cmd === 'edit') editOntology(ont)
  else if (cmd === 'export') exportOntology(ont)
  else if (cmd === 'default') setDefault(ont)
  else if (cmd === 'delete') deleteOntology(ont)
}

const editOntology = (ont: any) => {
  editingOntology.value = ont
  ontologyForm.value = {
    name: ont.name,
    description: ont.description,
    entityTypes: JSON.parse(JSON.stringify(ont.entity_types || [])),
    relationTypes: JSON.parse(JSON.stringify(ont.relation_types || []))
  }
  showCreateDialog.value = true
}

const submitOntology = async () => {
  if (!ontologyForm.value.name) {
    ElMessage.warning('请填写本体名称')
    return
  }
  
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', ontologyForm.value.name)
    fd.append('description', ontologyForm.value.description)
    fd.append('entity_types', JSON.stringify(ontologyForm.value.entityTypes.filter(t => t.name)))
    fd.append('relation_types', JSON.stringify(ontologyForm.value.relationTypes.filter(t => t.name)))
    
    if (editingOntology.value) {
      await updateOntology(editingOntology.value.id, fd)
      ElMessage.success('本体更新成功')
    } else {
      await createOntology(fd)
      ElMessage.success('本体创建成功')
    }
    showCreateDialog.value = false
    editingOntology.value = null
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '操作失败')
  } finally {
    submitting.value = false
  }
}

const deleteOntology = async (ont: any) => {
  try {
    await ElMessageBox.confirm(`确定删除本体"${ont.name}"及其所有实体关系吗？`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  
  try {
    await deleteOntologyApi(ont.id)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

const setDefault = async (ont: any) => {
  try {
    await setDefaultOntology(ont.id)
    ElMessage.success(`已将「${ont.name}」设为默认本体`)
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '设置失败')
  }
}

const exportOntology = async (ont: any) => {
  try {
    const res: any = await exportOntologyApi(ont.id)
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ont.name}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '导出失败')
  }
}

// ── 导入操作 ──
const handleImportFile = (file: File) => {
  importFile.value = file
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      importPreview.value = JSON.parse(e.target?.result as string)
    } catch {
      importPreview.value = null
    }
  }
  reader.readAsText(file)
  showImportDialog.value = true
  return false
}

const handleImportFileChange = (file: any) => {
  importFile.value = file.raw
  const reader = new FileReader()
  reader.onload = (e) => {
    try {
      importPreview.value = JSON.parse(e.target?.result as string)
    } catch {
      importPreview.value = null
    }
  }
  reader.readAsText(file.raw)
}

const submitImport = async () => {
  if (!importFile.value) return
  
  importing.value = true
  try {
    await importOntology(importFile.value)
    ElMessage.success('导入成功')
    showImportDialog.value = false
    importFile.value = null
    importPreview.value = null
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '导入失败')
  } finally {
    importing.value = false
  }
}

// ── 构建任务操作 ──
const handleBuildFileChange = (file: any) => {
  buildForm.value.file = file.raw
}

const startBuild = async () => {
  if (!buildForm.value.name || !buildForm.value.file) {
    ElMessage.warning('请填写本体名称并选择文档')
    return
  }
  
  creatingBuild.value = true
  try {
    const fd = new FormData()
    fd.append('file', buildForm.value.file)
    fd.append('name', buildForm.value.name)
    fd.append('description', buildForm.value.description)
    
    const res: any = await createBuildJob(fd)
    ElMessage.success('构建任务创建成功')
    showBuildDialog.value = false
    buildForm.value = { name: '', description: '', file: null }
    await loadData()
    
    // 跳转到构建页面
    router.push(`/ontology-build/${res.data.job_id}`)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '创建失败')
  } finally {
    creatingBuild.value = false
  }
}

const continueBuild = (jobId: string) => {
  router.push(`/ontology-build/${jobId}`)
}

const deleteBuildTask = async (jobId: string) => {
  try {
    await ElMessageBox.confirm('确定删除该构建任务吗？', '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  
  try {
    await deleteBuildJob(jobId)
    ElMessage.success('删除成功')
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

const getTaskStatusType = (status: string) => {
  const typeMap: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
    'completed': 'success',
    'draft': 'warning',
    'abandoned': 'info'
  }
  return typeMap[status] || 'info'
}

const getTaskStep = (task: any) => {
  // 后端 step: 0=上传+元模型, 1=概念提取, 2=层次结构, 3=序列化, 4=完成
  // 前端 4 步：上传文档(0) / 提取概念(1) / 构建结构(2) / 生成本体(3)
  if (task.status === 'completed') return 3
  if (task.step >= 3) return 3   // step2 已确认，等待生成
  if (task.step >= 2) return 2
  if (task.step >= 1) return 1
  return 0
}

const formatTime = (time: string) => {
  if (!time) return ''
  try {
    return new Date(time).toLocaleString('zh-CN')
  } catch {
    return time
  }
}

// ── 生命周期 ──
onMounted(() => {
  loadData()
})
</script>

<style scoped>
.ontology-home {
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
  color: var(--text-primary);
  font-size: 1.4rem;
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
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.stat-icon.blue { background: rgba(64, 158, 255, 0.12); color: #409eff; }
.stat-icon.cyan { background: rgba(64, 211, 255, 0.12); color: #00b8d4; }
.stat-icon.green { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
.stat-icon.purple { background: rgba(144, 147, 153, 0.12); color: #909399; }

.stat-info h3 {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.stat-info p {
  margin: 0.15rem 0 0 0;
  font-size: 0.82rem;
  color: var(--text-tertiary);
}

.content-section {
  background: white;
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 1.5rem;
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

.ontology-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1.5rem;
}

.ontology-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-6);
  transition: all var(--transition-normal);
}

.ontology-card:hover {
  border-color: var(--primary-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-3);
}

.card-header h3 {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.card-desc {
  color: var(--text-tertiary);
  font-size: var(--text-sm);
  line-height: var(--leading-relaxed);
  margin-bottom: var(--space-4);
  min-height: 36px;
}

.card-stats {
  display: flex;
  gap: var(--space-6);
  margin-bottom: var(--space-3);
  font-size: var(--text-sm);
  color: var(--text-secondary);
}

.card-stats span {
  display: flex;
  align-items: center;
  gap: var(--space-1);
}

.card-meta {
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: var(--space-4);
}

.card-actions {
  display: flex;
  gap: var(--space-2);
  flex-wrap: wrap;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.build-tasks-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 1rem;
}

.build-task-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: var(--space-5);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--space-4);
}

.task-header h4 {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--text-primary);
}

.task-progress {
  margin-bottom: var(--space-4);
}

.task-meta {
  display: flex;
  gap: var(--space-4);
  font-size: var(--text-xs);
  color: var(--text-muted);
  margin-bottom: var(--space-4);
}

.task-actions {
  display: flex;
  gap: var(--space-2);
}

.type-editor {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.type-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.import-preview {
  margin-top: 1rem;
}
</style>
