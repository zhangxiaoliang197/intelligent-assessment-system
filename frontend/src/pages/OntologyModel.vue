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
          <el-button type="primary" @click="showCreateMethodDialog = true" :icon="Plus">新建本体</el-button>
        </div>
      </div>

      <!-- 统计卡片 -->
      <div class="stats-cards">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-icon cyan">
              <el-icon :size="36"><Files /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.total_meta_models }}</h3>
              <p>元模型数</p>
            </div>
          </div>
        </el-card>
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
            <div class="stat-icon indigo">
              <el-icon :size="36"><SetUp /></el-icon>
            </div>
            <div class="stat-info">
              <h3>{{ stats.build_tasks_count }}</h3>
              <p>进行中的构建任务</p>
            </div>
          </div>
        </el-card>
      </div>

      <!-- 元模型管理 -->
      <div class="content-section">
        <div class="section-header">
          <h3>元模型</h3>
          <el-button type="primary" size="small" :icon="Plus" @click="openCreateMetaModel">新建元模型</el-button>
        </div>
        <div v-loading="templateLoading">
          <el-empty
            v-if="!templates.length && !templateLoading"
            description="暂无元模型，可从任意本体「另存为元模型」"
            :image-size="100"
          />
          <div v-else class="template-list">
            <div v-for="tpl in templates" :key="tpl.id" class="template-card">
              <div class="tpl-header">
                <h4>{{ tpl.name }}</h4>
                <el-tag size="small" type="info">{{ tpl.entity_types_count || tpl.concepts_count }} 实体类型</el-tag>
              </div>
              <p class="tpl-desc">{{ tpl.description || '暂无描述' }}</p>
              <div class="tpl-meta">
                <span>实体类型 {{ tpl.entity_types_count }}</span>
                <span>关系类型 {{ tpl.relation_types_count }}</span>
                <span>更新: {{ formatTime(tpl.update_time) }}</span>
              </div>
              <div class="tpl-actions">
                <el-button size="small" @click="viewTemplate(tpl.id)">查看 Schema</el-button>
                <el-button size="small" @click="editMetaModel(tpl)">编辑</el-button>
                <el-button size="small" type="primary" @click="createFromTemplate(tpl.id)">基于元模型新建本体</el-button>
                <el-button size="small" type="danger" link @click="deleteTemplateItem(tpl)">删除</el-button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 已构建的本体 -->
      <div class="content-section">
        <div class="section-header">
          <h3>本体模型</h3>
        </div>
        <div class="toolbar">
          <el-input
            v-model="searchQuery"
            placeholder="搜索本体名称..."
            prefix-icon="Search"
            clearable
            style="width: 280px"
          />
          <el-select v-model="filterStatus" placeholder="选择状态" clearable style="width: 130px">
            <el-option label="全部" value="all" />
            <el-option label="活跃" value="活跃" />
            <el-option label="归档" value="归档" />
          </el-select>
          <div class="toolbar-spacer" />
        </div>

        <!-- 本体卡片网格 -->
        <div class="ontology-grid" v-loading="loading">
          <div v-for="ont in filteredOntologies" :key="ont.id" class="ontology-card">
            <div class="card-header">
              <h3>{{ ont.name }}</h3>
              <el-tag v-if="ont.status === '归档'" type="warning" size="small">已归档</el-tag>
            </div>
            <p class="card-desc">{{ ont.description || '暂无描述' }}</p>
            <div class="card-stats">
              <span><el-icon><SetUp /></el-icon> {{ ont.concepts_count }} 类型</span>
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
                    <el-dropdown-item command="template">另存为元模型</el-dropdown-item>
                    <el-dropdown-item command="archive" v-if="ont.status !== '归档'">归档</el-dropdown-item>
                    <el-dropdown-item command="restore" v-else>恢复</el-dropdown-item>
                    <el-dropdown-item command="delete" divided>删除</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <el-empty v-if="!filteredOntologies.length && !loading" description="暂无本体模型" :image-size="120">
            <el-button type="primary" @click="showCreateMethodDialog = true">创建第一个本体</el-button>
          </el-empty>
        </div>
      </div>

      <!-- 构建任务列表 -->
      <div class="content-section" v-if="buildTasks.length > 0">
        <div class="section-header">
          <h3>构建任务</h3>
        </div>
        <div class="build-tasks-list">
          <div v-for="task in buildTasks" :key="task.id" class="build-task-card">
            <div class="task-header">
              <h4>{{ task.name }}</h4>
              <div class="task-tags">
                <el-tag v-if="task.build_type === 'manual'" type="primary" size="small" effect="plain">
                  手动构建
                </el-tag>
                <el-tag v-else-if="task.build_type === 'document'" type="primary" size="small" effect="plain">
                  文档构建
                </el-tag>
                <el-tag :type="getTaskStatusType(task.status)" size="small">
                  {{ task.status }}
                </el-tag>
              </div>
            </div>
            <div class="task-progress">
              <el-steps v-if="task.build_type === 'manual'" :active="0" align-center>
                <el-step title="Phase A 实体类型" />
                <el-step title="Phase B 填实例" />
              </el-steps>
              <el-steps v-else :active="getTaskStep(task)" align-center>
                <el-step title="文档解析" />
                <el-step title="类型提取" />
                <el-step title="实体提取" />
                <el-step title="分析验证" />
              </el-steps>
            </div>
            <div class="task-meta">
              <span v-if="task.build_type === 'manual'">方式: 手动构建（未完成，可继续）</span>
              <span v-else>源文档: {{ task.source_filename }}</span>
              <span>创建: {{ formatTime(task.create_time) }}</span>
            </div>
            <div class="task-actions">
              <el-button type="primary" size="small" @click="continueBuild(task)">
                继续构建
              </el-button>
              <el-button size="small" type="danger" @click="deleteBuildTask(task.id)">
                删除
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 新建方式选择对话框 -->
      <el-dialog v-model="showCreateMethodDialog" title="选择新建方式" width="600px">
        <p class="create-method-tip">请选择本体的创建方式：</p>
        <div class="create-method-grid">
          <div class="method-card" @click="handleCreateMethod('build')">
            <div class="method-icon orange">
              <el-icon :size="28"><Document /></el-icon>
            </div>
            <h4>文档构建</h4>
            <p>上传文档，AI 自动分析提取实体类型与关系，生成候选本体</p>
          </div>
          <div class="method-card" @click="handleCreateMethod('import')">
            <div class="method-icon green">
              <el-icon :size="28"><Upload /></el-icon>
            </div>
            <h4>导入 JSON</h4>
            <p>导入已有本体导出文件，创建新的本体模型</p>
          </div>
          <div class="method-card" @click="handleCreateMethod('manual')">
            <div class="method-icon blue">
              <el-icon :size="28"><EditPen /></el-icon>
            </div>
            <h4>手动构建</h4>
            <p>向导式分步构建：先搭骨架（类+属性+关系类型），再填实例（实体+属性值+关系）</p>
          </div>
        </div>
      </el-dialog>

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
            <p>上传文档后，AI 将自动分析文档内容，提取实体类型和关系，生成本体模型。整个过程分为 4 个步骤，您可以在每步进行编辑和确认。</p>
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

      <!-- 手动构建对话框：填写命名/描述 -->
      <el-dialog v-model="showManualDialog" title="手动构建本体" width="560px">
        <el-alert
          title="从零手动构建本体模型"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom: 1rem"
        >
          <template #default>
            <p>以向导式分步构建：先搭骨架（实体类型 + 属性骨架 + 类型间关系），再填实例（实体 + 属性值 + 实体间关系）。可随时退出，之后从「进行中的构建任务」继续。</p>
          </template>
        </el-alert>
        <el-form :model="manualForm" label-width="100px">
          <el-form-item label="本体名称" required>
            <el-input v-model="manualForm.name" placeholder="请输入本体名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input
              v-model="manualForm.description"
              type="textarea"
              :rows="3"
              placeholder="请输入本体描述"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showManualDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="startManualBuild">
            开始构建
          </el-button>
        </template>
      </el-dialog>

      <!-- 元模型 Schema 查看对话框 -->
      <el-dialog v-model="showTemplateDetailDialog" :title="`元模型 Schema：${templateDetail?.name || ''}`" width="720px" top="5vh">
        <div v-if="templateDetail" class="template-detail">
          <el-descriptions :column="2" border style="margin-bottom: 1rem">
            <el-descriptions-item label="实体类型">
              {{ templateDetail.entity_types.map((t: any) => t.name).join('、') || '无' }}
            </el-descriptions-item>
            <el-descriptions-item label="关系类型">
              {{ templateDetail.relation_types.map((t: any) => t.name).join('、') || '无' }}
            </el-descriptions-item>
          </el-descriptions>
          <h4 style="margin: 0.5rem 0">实体类型清单（{{ templateDetail.entity_types.length }}）</h4>
          <el-collapse>
            <el-collapse-item
              v-for="(c, idx) in templateDetail.entity_types"
              :key="idx"
              :title="`${c.name}（${c.parent_entity_type_name ? '父类：' + c.parent_entity_type_name : '顶层类型'}）`"
            >
              <p v-if="c.description" style="color: #606266; margin: 0 0 0.5rem">{{ c.description }}</p>
              <el-table v-if="c.property_schema && c.property_schema.length" :data="c.property_schema" size="small" border>
                <el-table-column prop="name" label="属性名" width="140" />
                <el-table-column prop="category" label="分类" width="100" />
                <el-table-column prop="data_type" label="数据类型" width="100" />
                <el-table-column prop="unit" label="单位" width="80" />
                <el-table-column prop="description" label="说明" />
              </el-table>
              <el-text v-else type="info" size="small">无属性骨架</el-text>
            </el-collapse-item>
          </el-collapse>
        </div>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  Box, SetUp,
  Refresh, Plus, Document, Upload, UploadFilled, EditPen, ArrowDown, Files
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import {
  getOntologyList,
  getOntologyStats,
  createOntology,
  updateOntology,
  deleteOntology as deleteOntologyApi,
  archiveOntology as archiveOntologyApi,
  restoreOntology as restoreOntologyApi,
  importOntology,
  exportOntology as exportOntologyApi
} from '@/services/ontology'
import { getBuildJobList, createBuildJob, createManualBuildJob, deleteBuildJob } from '@/services/ontologyBuild'
import {
  getMetaModelList,
  getMetaModel,
  saveMetaModelFromOntology,
  deleteMetaModel as deleteMetaModelApi
} from '@/services/ontologyMetaModel'

const router = useRouter()

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)
const importing = ref(false)
const creatingBuild = ref(false)

const ontologies = ref<any[]>([])
const buildTasks = ref<any[]>([])
const searchQuery = ref('')
const filterStatus = ref('all')

const stats = ref({
  total_meta_models: 0,
  total_ontologies: 0,
  total_entities: 0,
  total_relations: 0,
  build_tasks_count: 0
})

// 对话框开关
const showCreateDialog = ref(false)
const showImportDialog = ref(false)
const showBuildDialog = ref(false)
const showCreateMethodDialog = ref(false)

// 表单数据
const editingOntology = ref<any>(null)
const ontologyForm = ref({
  name: '',
  description: '',
  // 实体类型空白启动：不预填任何类型，完全由用户逐个定义
  entityTypes: [] as any[],
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

// 手动构建对话框（命名 + 描述）
const showManualDialog = ref(false)
const manualForm = ref({
  name: '',
  description: ''
})

// ── 元模型状态 ──
const templates = ref<any[]>([])
const templateLoading = ref(false)
const showTemplateDetailDialog = ref(false)
const templateDetail = ref<any>(null)

// ── 计算属性 ──
const filteredOntologies = computed(() => {
  return ontologies.value.filter(ont => {
    const matchSearch = !searchQuery.value || 
      ont.name.toLowerCase().includes(searchQuery.value.toLowerCase())
    const matchStatus = filterStatus.value === 'all' || !filterStatus.value || ont.status === filterStatus.value
    // 「构建中」的本体（手动构建未完成）不显示在已完成本体列表
    return matchSearch && matchStatus && ont.status !== '构建中'
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
    const allTasks = ((buildRes as any).data || []) as any[]
    stats.value = {
      total_meta_models: statsData.total_meta_models || 0,
      total_ontologies: statsData.total_ontologies || 0,
      total_entities: statsData.total_entities || 0,
      total_relations: statsData.total_relations || 0,
      build_tasks_count: allTasks.filter(t => t.status !== 'completed').length
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
    buildTasks.value = ((buildRes as any).data || []).filter((t: any) => t.status !== 'completed')
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
  else if (cmd === 'template') saveAsTemplate(ont)
  else if (cmd === 'archive') archiveOntology(ont)
  else if (cmd === 'restore') restoreOntology(ont)
  else if (cmd === 'delete') deleteOntology(ont)
}

// 新建方式选择：根据用户选择打开对应对话框
const handleCreateMethod = (type: string) => {
  showCreateMethodDialog.value = false
  if (type === 'build') {
    showBuildDialog.value = true
  } else if (type === 'import') {
    showImportDialog.value = true
  } else if (type === 'manual') {
    // 手动构建：先弹窗填写命名/描述，再创建空本体并进入向导页
    manualForm.value = { name: '', description: '' }
    showManualDialog.value = true
  }
}

// 启动手动构建：创建空本体 + 手动构建任务，跳转到向导页
const startManualBuild = async () => {
  if (!manualForm.value.name?.trim()) {
    ElMessage.warning('请输入本体名称')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', manualForm.value.name.trim())
    fd.append('description', manualForm.value.description)
    // 手动构建未完成前：本体标记为「构建中」，不显示在已完成本体列表，仅作为进行中任务
    fd.append('status', '构建中')
    // 实体类型空白启动：不预填类型，由用户在向导页逐个定义
    fd.append('entity_types', JSON.stringify([]))
    fd.append('relation_types', JSON.stringify([
      { name: '关联' }, { name: '影响' }
    ]))
    const res: any = await createOntology(fd)
    const newId = res.data?.id || res.id
    // 创建手动构建任务：纳入「进行中的构建任务」，未完成可退出页面，下次点击继续
    try {
      const jfd = new FormData()
      jfd.append('name', manualForm.value.name.trim())
      jfd.append('description', manualForm.value.description)
      jfd.append('ontology_id', newId)
      await createManualBuildJob(jfd)
    } catch (e) {
      console.warn('创建手动构建任务失败，本次仍可继续构建:', e)
    }
    showManualDialog.value = false
    ElMessage.success('已创建空本体，进入向导页')
    router.push(`/ontology/manual/${newId}`)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '创建本体失败')
  } finally {
    submitting.value = false
  }
}

// ── 元模型操作 ──
const loadTemplates = async () => {
  templateLoading.value = true
  try {
    const res: any = await getMetaModelList()
    templates.value = res.items || res.data || []
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载元模型列表失败')
  } finally {
    templateLoading.value = false
  }
}

// 新建元模型：跳转到元模型编辑页
const openCreateMetaModel = () => {
  router.push('/ontology/meta-model/new')
}

// 编辑元模型：跳转到元模型编辑页
const editMetaModel = (tpl: any) => {
  router.push(`/ontology/meta-model/${tpl.id}/edit`)
}

// 另存为元模型：从已有本体抽取 schema 层
const saveAsTemplate = async (ont: any) => {
  let name = ''
  try {
    const result = await ElMessageBox.prompt(
      `将本体「${ont.name}」的 schema 层（元模型+实体类型+属性骨架）抽取为元模型，实例数据不会进入元模型。`,
      '另存为元模型',
      {
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputPlaceholder: '请输入元模型名称',
        inputValue: `${ont.name} 元模型`
      }
    )
    name = result.value
  } catch { return }

  if (!name?.trim()) {
    ElMessage.warning('请输入元模型名称')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', name.trim())
    fd.append('description', ont.description || '')
    await saveMetaModelFromOntology(ont.id, fd)
    ElMessage.success('元模型创建成功')
    await Promise.all([loadTemplates(), loadStats()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '元模型创建失败')
  } finally {
    submitting.value = false
  }
}

// 基于元模型新建本体：创建空本体后跳转向导页，带上 template 查询参数触发预填
const createFromTemplate = async (templateId: string) => {
  submitting.value = true
  try {
    const fd = new FormData()
    const tpl = templates.value.find(t => t.id === templateId)
    fd.append('name', `${tpl?.name || '元模型本体'} - 副本`)
    fd.append('description', `基于元模型「${tpl?.name || ''}」创建`)
    fd.append('entity_types', JSON.stringify([]))
    fd.append('relation_types', JSON.stringify([]))
    const res: any = await createOntology(fd)
    const newId = res.data?.id || res.id
    ElMessage.success('已创建空本体，正在载入元模型骨架...')
    router.push(`/ontology/manual/${newId}?template=${templateId}`)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '创建本体失败')
  } finally {
    submitting.value = false
  }
}

// 查看元模型 schema 详情
const viewTemplate = async (templateId: string) => {
  try {
    const res: any = await getMetaModel(templateId)
    templateDetail.value = res.data
    showTemplateDetailDialog.value = true
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载元模型详情失败')
  }
}

// 删除元模型
const deleteTemplateItem = async (tpl: any) => {
  try {
    await ElMessageBox.confirm(
      `确定删除元模型「${tpl.name}」吗？已基于该元模型创建的本体/任务不受影响。`,
      '提示',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }

  try {
    await deleteMetaModelApi(tpl.id)
    ElMessage.success('元模型已删除')
    await Promise.all([loadTemplates(), loadStats()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
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

const archiveOntology = async (ont: any) => {
  try {
    await ElMessageBox.confirm(`确定将本体「${ont.name}」归档吗？归档后参与下游数据联动。`, '归档确认', {
      confirmButtonText: '归档', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  try {
    await archiveOntologyApi(ont.id)
    ElMessage.success(`已将「${ont.name}」归档`)
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '归档失败')
  }
}

const restoreOntology = async (ont: any) => {
  try {
    await restoreOntologyApi(ont.id)
    ElMessage.success(`已将「${ont.name}」恢复为活跃`)
    await loadData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '恢复失败')
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

const continueBuild = (task: any) => {
  // 手动构建任务：进入手动构建向导页继续；文档构建任务：进入构建页
  if (task.build_type === 'manual') {
    router.push(`/ontology/manual/${task.ontology_id}`)
    return
  }
  router.push(`/ontology-build/${task.id}`)
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
  // 后端 step: 0=文档解析, 1=类型提取, 2=实体提取, 3=分析验证, 4=完成
  // 前端 4 步：文档解析(0) / 类型提取(1) / 实体提取(2) / 分析验证(3)
  if (task.status === 'completed') return 3
  if (task.step >= 3) return 3   // 分析验证阶段
  if (task.step >= 2) return 2   // 实体提取阶段
  if (task.step >= 1) return 1   // 类型提取阶段
  return 0                        // 文档解析阶段
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
  // 预加载元模型列表，供元模型管理与「基于元模型新建本体」使用
  loadTemplates()
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

.stat-icon.cyan { background: rgba(6, 182, 212, 0.12); color: #06b6d4; }
.stat-icon.blue { background: rgba(64, 158, 255, 0.12); color: #409eff; }
.stat-icon.indigo { background: rgba(99, 102, 241, 0.12); color: #6366f1; }

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
  margin-bottom: 1.5rem;
  flex-wrap: wrap;
  align-items: center;
}

.toolbar-spacer {
  flex: 1;
}

.ontology-grid {
  display: grid;
  /* 固定列宽 320px，不随数量拉伸；放不下自动换行，新卡片在尾部追加 */
  grid-template-columns: repeat(auto-fill, 320px);
  justify-content: start;
  gap: 1.5rem;
}

.ontology-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  height: 220px;
  display: flex;
  flex-direction: column;
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
  margin-bottom: 0.75rem;
}

.card-header h3 {
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.card-desc {
  color: var(--text-tertiary);
  font-size: 0.875rem;
  line-height: 1.6;
  margin-bottom: 1rem;
  flex-shrink: 0; /* 防止被固定高度卡片压缩裁切，保证描述文字完整显示 */
  /* 固定高度下超出两行省略 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-stats {
  display: flex;
  gap: 1.5rem;
  margin-bottom: 0.75rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.card-stats span {
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

.card-meta {
  font-size: 0.8rem;
  color: var(--text-muted);
  margin-bottom: 1rem;
}

.card-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 0.75rem;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
}

.section-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
}

.build-tasks-list {
  display: grid;
  /* 与本体卡片同宽同策略：固定 320px，尾部追加换行 */
  grid-template-columns: repeat(auto-fill, 320px);
  justify-content: start;
  gap: 1rem;
}

.build-task-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: 1.25rem;
  height: 190px;
  display: flex;
  flex-direction: column;
  transition: all 0.2s;
}

.build-task-card:hover {
  border-color: var(--primary-300);
  box-shadow: var(--shadow-sm);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.task-header h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

.task-progress {
  margin-bottom: 0.75rem;
}

.task-progress :deep(.el-step__title) {
  font-size: 0.7rem;
}

.task-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 0.75rem;
  /* 超长源文件名省略，避免撑破固定宽度 */
  overflow: hidden;
  white-space: nowrap;
}

.task-tags {
  display: flex;
  gap: 0.375rem;
  align-items: center;
  flex-shrink: 0;
}

.task-actions {
  display: flex;
  gap: 0.5rem;
  margin-top: auto;
  padding-top: 0.5rem;
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

.create-method-tip {
  margin: 0 0 1rem 0;
  color: var(--text-secondary);
  font-size: 0.9rem;
}

.create-method-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.method-card {
  border: 1px solid var(--border-light);
  border-radius: 12px;
  padding: 1.25rem;
  text-align: center;
  cursor: pointer;
  transition: all 0.2s;
}

.method-card:hover {
  border-color: var(--primary-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.method-icon {
  width: 48px;
  height: 48px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 0.75rem auto;
}

.method-icon.orange { background: rgba(230, 162, 60, 0.12); color: #e6a23c; }
.method-icon.green { background: rgba(103, 194, 58, 0.12); color: #67c23a; }
.method-icon.blue { background: rgba(64, 158, 255, 0.12); color: #409eff; }

.method-card h4 {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.method-card p {
  margin: 0;
  font-size: 0.8rem;
  line-height: 1.5;
  color: var(--text-tertiary);
}

/* ── 元模型 ── */
.template-list {
  display: grid;
  /* 固定列宽 320px，与本体卡片网格一致；放不下自动换行 */
  grid-template-columns: repeat(auto-fill, 320px);
  justify-content: start;
  gap: 1.5rem;
}

.template-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  height: 220px;
  display: flex;
  flex-direction: column;
  transition: all var(--transition-normal);
}

.template-card:hover {
  border-color: var(--primary-300);
  box-shadow: var(--shadow-md);
  transform: translateY(-2px);
}

.tpl-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.tpl-header h4 {
  margin: 0;
  font-size: 1rem;
  font-weight: 600;
  color: var(--text-primary);
}

.tpl-desc {
  margin: 0 0 0.75rem 0;
  font-size: 0.825rem;
  color: var(--text-tertiary);
  line-height: 1.5;
  min-height: 24px;
  flex-shrink: 0; /* 防止被固定高度卡片压缩裁切，保证描述文字完整显示 */
  /* 与本体卡片描述一致：超出两行省略 */
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tpl-meta {
  display: flex;
  gap: 1rem;
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-bottom: 0.75rem;
}

.tpl-actions {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-top: auto;
  padding-top: 0.5rem;
}

.template-detail h4 {
  margin: 0.5rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
