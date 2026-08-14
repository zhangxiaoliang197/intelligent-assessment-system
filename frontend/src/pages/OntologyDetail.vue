<template>
  <Layout>
    <div class="ontology-detail">
      <!-- 顶部工具栏 -->
      <div class="detail-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回</el-button>
          <h2>{{ ontology?.name || '本体详情' }}</h2>
          <el-tag v-if="ontology?.status === '归档'" type="warning" size="small">已归档</el-tag>
        </div>
        <div class="header-actions">
          <el-button @click="refreshData" :icon="Refresh">刷新</el-button>
          <el-button @click="showEditDialog = true" :icon="Edit">编辑</el-button>
          <el-button v-if="ontology?.status !== '归档'" @click="archiveOntology" :icon="FolderChecked">归档</el-button>
          <el-button v-else @click="restoreOntology" :icon="FolderChecked">恢复</el-button>
          <el-button @click="exportOntology" :icon="Download">导出</el-button>
        </div>
      </div>

      <!-- 三栏布局 -->
      <div class="three-column-layout" v-loading="loading">
        <!-- 左面板：实体列表 + 关系列表 -->
        <div class="left-panel">
          <el-card class="panel-card list-card">
            <template #header>
              <div class="panel-header">
                <div class="panel-title">
                  <span>实体列表</span>
                  <span class="count-badge">{{ filteredEntities.length }}</span>
                </div>
                <el-button size="small" type="primary" :icon="Plus" @click="showAddEntityDialog = true">添加</el-button>
              </div>
            </template>
            <div class="list-toolbar">
              <el-input
                v-model="entitySearch"
                placeholder="搜索实体"
                :prefix-icon="Search"
                clearable
                size="small"
              />
              <el-select
                v-model="entityTypeFilter"
                placeholder="全部类型"
                clearable
                size="small"
                class="type-filter"
              >
                <el-option v-for="t in entityTypeOptions" :key="t.name" :label="t.name" :value="t.name">
                  <span class="option-dot" :style="{ background: t.color }"></span>
                  {{ t.name }}
                </el-option>
              </el-select>
            </div>
            <div class="entity-list custom-scroll">
              <div
                v-for="entity in filteredEntities"
                :key="entity.id"
                :class="['entity-item', { active: selectedEntity?.id === entity.id }]"
                :style="{ '--entity-color': getEntityTypeColor(entity.type) }"
                @click="selectEntity(entity)"
              >
                <span class="entity-dot"></span>
                <div class="entity-main">
                  <span class="entity-name" :title="entity.name">{{ entity.name }}</span>
                  <span class="entity-type">{{ entity.type }}</span>
                </div>
                <span class="entity-degree" :title="`关联 ${degreeMap[entity.id] || 0} 条关系`">
                  <el-icon><Connection /></el-icon>{{ degreeMap[entity.id] || 0 }}
                </span>
              </div>
              <el-empty v-if="!filteredEntities.length" description="暂无实体" :image-size="56" />
            </div>
          </el-card>

          <el-card class="panel-card list-card relation-card">
            <template #header>
              <div class="panel-header">
                <div class="panel-title">
                  <span>关系列表</span>
                  <span class="count-badge">{{ filteredRelations.length }}</span>
                </div>
                <el-button size="small" type="primary" :icon="Plus" @click="showAddRelationDialog = true">添加</el-button>
              </div>
            </template>
            <div class="list-toolbar">
              <el-input
                v-model="relationSearch"
                placeholder="搜索关系"
                :prefix-icon="Search"
                clearable
                size="small"
              />
            </div>
            <div class="relation-list custom-scroll">
              <div
                v-for="relation in filteredRelations"
                :key="relation.id"
                class="relation-item"
              >
                <!-- 第一行：源实体 + 关系类型 -->
                <div class="rel-line">
                  <span
                    class="rel-dot"
                    :style="{ background: getEntityTypeColor(entityTypeMap[relation.source_id]) }"
                  ></span>
                  <span
                    class="rel-name"
                    :style="{ color: getEntityTypeColor(entityTypeMap[relation.source_id]) }"
                    :title="relation.source_name"
                  >{{ relation.source_name }}</span>
                  <span class="rel-type">{{ relation.relation_type }}</span>
                </div>
                <!-- 第二行：目标实体 + 删除按钮 -->
                <div class="rel-line rel-line-target">
                  <span class="rel-connector">↳</span>
                  <span
                    class="rel-dot"
                    :style="{ background: getEntityTypeColor(entityTypeMap[relation.target_id]) }"
                  ></span>
                  <span
                    class="rel-name"
                    :style="{ color: getEntityTypeColor(entityTypeMap[relation.target_id]) }"
                    :title="relation.target_name"
                  >{{ relation.target_name }}</span>
                  <el-button size="small" link type="danger" class="relation-delete" @click="deleteRelation(relation)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <el-empty v-if="!filteredRelations.length" description="暂无关系" :image-size="56" />
            </div>
          </el-card>
        </div>

        <!-- 中间：图谱可视化 -->
        <div class="center-panel">
          <el-card class="graph-card">
            <template #header>
              <div class="panel-header">
                <span>知识图谱</span>
                <div class="graph-toolbar">
                  <el-button-group>
                    <el-button size="small" @click="zoomIn">
                      <el-icon><ZoomIn /></el-icon>
                    </el-button>
                    <el-button size="small" @click="zoomOut">
                      <el-icon><ZoomOut /></el-icon>
                    </el-button>
                    <el-button size="small" @click="resetZoom">
                      <el-icon><RefreshRight /></el-icon>
                    </el-button>
                  </el-button-group>
                  <el-select v-model="layoutType" size="small" style="width: 120px" @change="renderGraph">
                    <el-option label="力导向" value="force" />
                    <el-option label="环形" value="circular" />
                  </el-select>
                  <el-button
                    size="small"
                    type="warning"
                    :disabled="!expandedTypeIds.size"
                    @click="resetExpand"
                  >
                    <el-icon><Fold /></el-icon> 收起全部实例（{{ expandedTypeIds.size }}）
                  </el-button>
                </div>
                <div class="graph-hint">左键实体类型→分解为其实例（类型消失）；右键实例→收起为所属类型；刷新恢复全部类型</div>
              </div>
            </template>
            <div class="graph-wrapper">
              <div ref="graphRef" class="graph-container"></div>
              <div class="graph-legend-overlay">
                <div v-for="type in entityTypeOptions" :key="type.name" class="legend-item">
                  <span class="legend-dot" :style="{ background: type.color }"></span>
                  <span>{{ type.name }}</span>
                </div>
              </div>
            </div>
          </el-card>
        </div>

        <!-- 右面板：实体详情 -->
        <div class="right-panel">
          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>实体详情</span>
                <el-button v-if="selectedEntity" size="small" @click="showEditEntityDialog = true">编辑</el-button>
              </div>
            </template>
            <div v-if="selectedEntity" class="entity-detail">
              <el-descriptions :column="1" border>
                <el-descriptions-item label="名称">
                  {{ selectedEntity.name }}
                </el-descriptions-item>
                <el-descriptions-item label="类型">
                  <el-tag :style="{ color: getEntityTypeColor(selectedEntity.type), borderColor: getEntityTypeColor(selectedEntity.type) }">
                    {{ selectedEntity.type }}
                  </el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="属性">
                  <div v-if="displayProperties.length">
                    <div v-for="p in displayProperties" :key="p.name" class="property-item">
                      <span class="property-key">{{ p.name }}:</span>
                      <span class="property-value">{{ p.value }}<template v-if="p.unit"> {{ p.unit }}</template></span>
                    </div>
                  </div>
                  <el-empty v-else description="无属性" :image-size="40" />
                </el-descriptions-item>
              </el-descriptions>
              <div class="detail-actions">
                <el-button size="small" type="danger" @click="deleteEntity(selectedEntity)">删除</el-button>
              </div>
            </div>
            <el-empty v-else description="请选择实体查看详情" :image-size="80" />
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <span>统计信息</span>
            </template>
            <div class="stats-info">
              <div class="stat-item">
                <span class="stat-label">实体数量</span>
                <span class="stat-value">{{ entities.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">关系数量</span>
                <span class="stat-value">{{ relations.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">实体类型</span>
                <span class="stat-value">{{ entityTypeOptions.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">关系类型</span>
                <span class="stat-value">{{ relationTypeOptions.length }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <!-- 编辑本体对话框 -->
      <el-dialog v-model="showEditDialog" title="编辑本体模型" width="700px">
        <el-form :model="editForm" label-width="120px">
          <el-form-item label="本体名称" required>
            <el-input v-model="editForm.name" placeholder="请输入本体名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="editForm.description" type="textarea" :rows="3" placeholder="请输入本体描述" />
          </el-form-item>
          <el-divider>元模型定义</el-divider>
          <el-form-item label="实体类型">
            <div class="type-editor">
              <div v-for="(t, idx) in editForm.entityTypes" :key="idx" class="type-row">
                <el-input v-model="t.name" placeholder="类型名" size="small" style="width: 160px" />
                <el-color-picker v-model="t.color" size="small" />
                <el-button size="small" link type="danger" @click="editForm.entityTypes.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="editForm.entityTypes.push({ name: '', color: '#5470c6' })">+ 添加实体类型</el-button>
            </div>
          </el-form-item>
          <el-form-item label="关系类型">
            <div class="type-editor">
              <div v-for="(t, idx) in editForm.relationTypes" :key="idx" class="type-row">
                <el-input v-model="t.name" placeholder="关系名" size="small" style="width: 160px" />
                <el-button size="small" link type="danger" @click="editForm.relationTypes.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="editForm.relationTypes.push({ name: '' })">+ 添加关系类型</el-button>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showEditDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEdit">更新</el-button>
        </template>
      </el-dialog>

      <!-- 添加实体对话框 -->
      <el-dialog v-model="showAddEntityDialog" title="添加实体" width="780px" top="5vh" @open="resetEntityForm">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名称" required>
            <el-input v-model="entityForm.name" placeholder="请输入实体名称" />
          </el-form-item>
          <el-form-item label="归属实体类型" required>
            <el-select
              v-model="entityForm.instance_of"
              placeholder="请选择实体类型（类型）"
              style="width: 100%"
              @change="onEntityTypeChange"
            >
              <el-option
                v-for="c in entityTypes"
                :key="c.id"
                :label="`${c.name}（${c.parent_entity_type_name ? '父类：' + c.parent_entity_type_name : '顶层类型'}）`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="属性">
            <div class="type-editor" style="width: 100%">
              <div v-for="(p, idx) in entityForm.properties" :key="idx" class="prop-edit-row">
                <el-input v-model="p.name" placeholder="属性名" size="small" style="width: 130px" />
                <el-input v-model="p.value" placeholder="属性值" size="small" style="width: 150px" />
                <el-select v-model="p.category" size="small" style="width: 100px">
                  <el-option label="描述型" value="descriptive" />
                  <el-option label="指标型" value="metric" />
                </el-select>
                <el-input v-model="p.unit" placeholder="单位" size="small" style="width: 80px" />
                <el-button size="small" link type="danger" @click="entityForm.properties.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="entityForm.properties.push({ name: '', value: '', category: 'descriptive', data_type: 'string', unit: '', source_snippet: '' })">+ 添加属性</el-button>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddEntityDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEntity">添加</el-button>
        </template>
      </el-dialog>

      <!-- 编辑实体对话框 -->
      <el-dialog v-model="showEditEntityDialog" title="编辑实体" width="780px" top="5vh">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名称" required>
            <el-input v-model="entityForm.name" placeholder="请输入实体名称" />
          </el-form-item>
          <el-form-item label="归属实体类型" required>
            <el-select
              v-model="entityForm.instance_of"
              placeholder="请选择实体类型（类型）"
              style="width: 100%"
              @change="onEntityTypeChange"
            >
              <el-option
                v-for="c in entityTypes"
                :key="c.id"
                :label="`${c.name}（${c.parent_entity_type_name ? '父类：' + c.parent_entity_type_name : '顶层类型'}）`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>

          <el-form-item label="属性">
            <div class="type-editor" style="width: 100%">
              <div v-for="(p, idx) in entityForm.properties" :key="idx" class="prop-edit-row">
                <el-input v-model="p.name" placeholder="属性名" size="small" style="width: 130px" />
                <el-input v-model="p.value" placeholder="属性值" size="small" style="width: 150px" />
                <el-select v-model="p.category" size="small" style="width: 100px">
                  <el-option label="描述型" value="descriptive" />
                  <el-option label="指标型" value="metric" />
                </el-select>
                <el-input v-model="p.unit" placeholder="单位" size="small" style="width: 80px" />
                <el-button size="small" link type="danger" @click="entityForm.properties.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="entityForm.properties.push({ name: '', value: '', category: 'descriptive', data_type: 'string', unit: '', source_snippet: '' })">+ 添加属性</el-button>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showEditEntityDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEditEntity">更新</el-button>
        </template>
      </el-dialog>

      <!-- 添加关系对话框 -->
      <el-dialog v-model="showAddRelationDialog" title="添加关系" width="500px">
        <el-form :model="relationForm" label-width="100px">
          <el-form-item label="源实体" required>
            <el-select v-model="relationForm.sourceId" placeholder="请选择源实体" style="width: 100%">
              <el-option v-for="entity in entities" :key="entity.id" :label="entity.name" :value="entity.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标实体" required>
            <el-select v-model="relationForm.targetId" placeholder="请选择目标实体" style="width: 100%">
              <el-option v-for="entity in entities" :key="entity.id" :label="entity.name" :value="entity.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型" required>
            <el-select v-model="relationForm.type" placeholder="请选择关系类型" style="width: 100%">
              <el-option v-for="t in relationTypeOptions" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="relationForm.weight" :min="0" :max="1" :step="0.1" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddRelationDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitRelation">添加</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, Refresh, Download, Edit, FolderChecked, ZoomIn, ZoomOut, RefreshRight, Delete,
  Plus, Search, Connection, Fold
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import {
  getOntology,
  updateOntology,
  exportOntology as exportOntologyApi,
  archiveOntology as archiveOntologyApi,
  restoreOntology as restoreOntologyApi,
  getEntityList,
  getRelationList,
  getGraphData,
  getConceptList,
  createEntity,
  updateEntity
} from '@/services/ontology'
import service from '@/services/api'

const route = useRoute()
const router = useRouter()
const ontologyId = route.params.id as string

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)

const ontology = ref<any>(null)
const entityTypes = ref<any[]>([])
const entities = ref<any[]>([])
const relations = ref<any[]>([])
const selectedEntity = ref<any>(null)
const entitySearch = ref('')
const entityTypeFilter = ref('')
const relationSearch = ref('')
const layoutType = ref('force')

const graphRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

// ── 图谱实例展开/收起 ──
// rawGraphData 缓存后端原始图谱数据，expandedTypeIds 记录已展开实例的类型 ID
// 类型节点始终常驻：收起态仅显示类型节点（其实例隐藏）；展开态实例环绕类型节点出现
// 左键类型 → 展开/收起实例；右键实例 → 收回所属类型
const rawGraphData = ref<{ nodes: any[]; links: any[] }>({ nodes: [], links: [] })
const expandedTypeIds = ref<Set<string>>(new Set())

// 对话框开关
const showEditDialog = ref(false)
const showAddEntityDialog = ref(false)
const showEditEntityDialog = ref(false)
const showAddRelationDialog = ref(false)

// 表单数据
const editForm = ref({
  name: '',
  description: '',
  entityTypes: [] as any[],
  relationTypes: [] as any[]
})

const entityForm = ref({
  id: '',
  name: '',
  instance_of: '',
  is_primary: false,
  source_snippet: '',
  properties: [] as { name: string; value: string; category: string; data_type: string; unit: string; source_snippet: string }[]
})

const relationForm = ref({
  sourceId: '',
  targetId: '',
  type: '',
  weight: 1.0
})

// ── 计算属性 ──
const entityTypeOptions = computed(() => ontology.value?.entity_types || [])
const relationTypeOptions = computed(() => ontology.value?.relation_types || [])

const filteredEntities = computed(() => {
  const kw = entitySearch.value.trim().toLowerCase()
  return entities.value.filter(e => {
    const matchKw = !kw || (e.name || '').toLowerCase().includes(kw)
    const matchType = !entityTypeFilter.value || e.type === entityTypeFilter.value
    return matchKw && matchType
  })
})

const entityTypeMap = computed(() => {
  const map: Record<string, string> = {}
  entities.value.forEach(e => { map[e.id] = e.type })
  return map
})

/** 每个实体关联的关系条数（出度 + 入度），用于列表右侧显示连接数 */
const degreeMap = computed(() => {
  const map: Record<string, number> = {}
  relations.value.forEach(r => {
    map[r.source_id] = (map[r.source_id] || 0) + 1
    map[r.target_id] = (map[r.target_id] || 0) + 1
  })
  return map
})

const filteredRelations = computed(() => {
  if (!relationSearch.value) return relations.value
  const kw = relationSearch.value.toLowerCase()
  return relations.value.filter(r =>
    (r.source_name || '').toLowerCase().includes(kw) ||
    (r.target_name || '').toLowerCase().includes(kw) ||
    (r.relation_type || '').toLowerCase().includes(kw)
  )
})

/** 选中实体的属性展示列表：兼容新 List[Property] 与旧 Dict 格式。 */
const displayProperties = computed(() => {
  const props = selectedEntity.value?.properties
  if (!props) return []
  if (Array.isArray(props)) {
    // 新结构化格式：List[Property]
    return props.map((p: any) => ({
      name: p.name || '',
      value: p.value !== undefined && p.value !== null ? String(p.value) : '',
      unit: p.unit || ''
    }))
  }
  // 旧 Dict 格式（迁移残留）：{k: v} → [{name: k, value: v}]
  return Object.entries(props).map(([k, v]) => ({
    name: k,
    value: String(v),
    unit: ''
  }))
})

// ── 数据加载 ──
const loadOntology = async () => {
  loading.value = true
  try {
    const res: any = await getOntology(ontologyId)
    ontology.value = res.data
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载本体失败')
  } finally {
    loading.value = false
  }
}

const loadConcepts = async () => {
  try {
    const res: any = await getConceptList(ontologyId)
    entityTypes.value = res.items || []
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载实体类型失败')
  }
}

const loadEntities = async () => {
  try {
    const res: any = await getEntityList(ontologyId)
    entities.value = res.items || []
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载实体失败')
  }
}

const loadRelations = async () => {
  try {
    const res: any = await getRelationList(ontologyId)
    relations.value = res.items || []
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载关系失败')
  }
}

const loadGraph = async () => {
  try {
    const res: any = await getGraphData(ontologyId)
    // 缓存原始数据供实例分解/收回重算
    rawGraphData.value = { nodes: res.data.nodes || [], links: res.data.links || [] }
    // 默认全部为类型态：只显示实体类型节点，左键类型展开（分解）为其实例
    expandedTypeIds.value = new Set()
    renderGraph()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载图谱失败')
  }
}

const refreshData = async () => {
  await Promise.all([loadOntology(), loadConcepts(), loadEntities(), loadRelations(), loadGraph()])
  ElMessage.success('数据已刷新')
}

// ── 图谱渲染（类型与实例两态互斥：分解语义）──
// 统一「可见代表节点」模型：每条逻辑边连接两端各自的可见代表
// - 实体-实体关系边：所属类型未分解 → 代表为类型节点；已分解 → 代表为实例本身
// - 类型级边（SUB_CONCEPT_OF / EntityTypeRelation）：两端类型节点均未分解（可见）时才渲染
// - instance_of 边（类型→实例）：不渲染，实例出现后靠位置/同色表达归属
const renderGraph = () => {
  if (!graphRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(graphRef.value)
    // 阻止默认右键菜单，让 ECharts contextmenu 事件生效
    graphRef.value.addEventListener('contextmenu', (e) => e.preventDefault())
    // 注册图谱交互事件
    chartInstance.on('contextmenu', handleGraphContextMenu)
    chartInstance.on('click', handleGraphClick)
  }
  chartInstance.resize()

  const raw = rawGraphData.value
  if (!raw.nodes.length) return

  const expanded = expandedTypeIds.value
  const isExpanded = (typeId?: string) => !!typeId && expanded.has(typeId)

  // 预索引：类型节点 / 实体节点
  const typeNodes = raw.nodes.filter((n: any) => n.node_type === 'concept')
  const entityNodes = raw.nodes.filter((n: any) => n.node_type === 'entity')
  const typeNodeById: Record<string, any> = {}
  for (const n of typeNodes) typeNodeById[n.id] = n
  const entityById: Record<string, any> = {}
  for (const e of entityNodes) entityById[e.id] = e

  // 父类型集合（SUB_CONCEPT_OF 边的 source 是父类型），用于节点大小区分
  const parentConceptIds = new Set<string>()
  for (const l of raw.links) {
    if (l.relation === 'SUB_CONCEPT_OF') parentConceptIds.add(l.source)
  }

  // 类别（颜色）映射，与列表/图例一致
  const catIndex: Record<string, number> = {}
  const categories = entityTypeOptions.value.map((t: any, i: number) => {
    catIndex[t.name] = i
    return { name: t.name, itemStyle: { color: t.color || '#409eff' } }
  })
  const fallbackCatIndex = categories.length
  categories.push({ name: '[未分类]', itemStyle: { color: '#409eff' } })

  // 全量 id→name 映射（含隐藏实体，用于边代表节点名称解析）
  const idToName: Record<string, string> = {}
  for (const n of raw.nodes) idToName[n.id] = n.name

  // 每个类型拥有的实例数（类型节点 tooltip 用）
  const instanceCount: Record<string, number> = {}
  for (const e of entityNodes) {
    if (e.concept_id) instanceCount[e.concept_id] = (instanceCount[e.concept_id] || 0) + 1
  }

  // ── 节点：类型节点与其实例两态互斥（分解语义）──
  // 已分解的类型：类型节点消失，仅显示其实例；未分解：仅显示类型节点
  const displayNodes: any[] = []
  for (const n of typeNodes) {
    if (isExpanded(n.id)) {
      // 分解态：类型节点消失，其实例原位出现
      for (const e of entityNodes) {
        if (e.concept_id === n.id) {
          displayNodes.push({
            name: e.name,
            id: e.id,
            category: catIndex[e.type] ?? fallbackCatIndex,
            symbolSize: 32,
            draggable: true,
            // 自定义字段供事件处理识别
            nodeType: 'entity',
            conceptId: e.concept_id,
            // 实例节点白细边，与类型节点粗黑边区分
            itemStyle: { borderColor: '#fff', borderWidth: 1.5 }
          })
        }
      }
    } else {
      // 收起态：仅显示类型节点（父类型 > 子类型，加粗边框）
      displayNodes.push({
        name: n.name,
        id: n.id,
        category: catIndex[n.type] ?? fallbackCatIndex,
        symbolSize: parentConceptIds.has(n.id) ? 65 : 55,
        draggable: true,
        nodeType: 'entityType',
        conceptId: n.id,
        itemStyle: { borderColor: '#333', borderWidth: 2 },
        label: { fontWeight: 'bold' }
      })
    }
  }

  // 可见节点集合：边两端代表节点必须在可见集合内才渲染
  const visibleNodeIds = new Set(displayNodes.map(n => n.id))

  // ── 边：连接两端各自的可见代表，去重去自环 ──
  const displayLinks: any[] = []
  const seenEdges = new Set<string>()
  const pushEdge = (srcId: string, tgtId: string, relation: string, dashed = false) => {
    if (srcId === tgtId) return // 去自环（同类型收起后内部边消失）
    if (!visibleNodeIds.has(srcId) || !visibleNodeIds.has(tgtId)) return
    const edgeKey = `${srcId}-${tgtId}-${relation}`
    if (seenEdges.has(edgeKey)) return // 去重
    seenEdges.add(edgeKey)
    displayLinks.push({
      // ECharts graph 按 id 匹配节点建边，必须用节点 id（不能用 name）
      source: srcId,
      target: tgtId,
      value: relation,
      // 额外保留名称用于 tooltip 展示，不影响边匹配
      sourceName: idToName[srcId] || srcId,
      targetName: idToName[tgtId] || tgtId,
      // 归属边（instance_of）细虚线弱化，与业务关系边区分
      lineStyle: dashed ? { type: 'dashed', width: 1, opacity: 0.45 } : { type: 'solid' }
    })
  }

  for (const l of raw.links) {
    const relation = l.relation
    // 类型级边（SUB_CONCEPT_OF / EntityTypeRelation）：类型节点常驻，始终渲染
    if (typeNodeById[l.source] && typeNodeById[l.target]) {
      pushEdge(l.source, l.target, relation)
      continue
    }
    // 实例归属边（instance_of）：实例出现后靠位置+同色表达归属，不渲染归属边
    if (relation === 'instance_of') continue
    // 实体-实体关系边：提升/降级到两端可见代表
    const srcEntity = entityById[l.source]
    const tgtEntity = entityById[l.target]
    if (srcEntity && tgtEntity) {
      const srcRep = isExpanded(srcEntity.concept_id) ? srcEntity.id : (srcEntity.concept_id || srcEntity.id)
      const tgtRep = isExpanded(tgtEntity.concept_id) ? tgtEntity.id : (tgtEntity.concept_id || tgtEntity.id)
      pushEdge(srcRep, tgtRep, relation)
    }
  }

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        // 图谱更新/动画期间 tooltip 可能拿到空 data，直接返回空避免报错
        if (!p.data) return ''
        if (p.dataType === 'edge') {
          const sName = p.data.sourceName || p.data.source
          const tName = p.data.targetName || p.data.target
          return `${sName} → ${tName}<br/>关系: ${p.data.value || ''}`
        }
        const d = p.data
        if (d.nodeType === 'entityType') {
          const cnt = instanceCount[d.conceptId] || 0
          const state = expandedTypeIds.value.has(d.conceptId) ? '左键收起实例' : '左键分解为实例'
          return `${d.name}（实体类型）<br/>${cnt} 个实例 · ${state}`
        }
        return `${d.name}<br/>右键收起所属类型`
      }
    },
    series: [{
      type: 'graph',
      layout: layoutType.value,
      roam: true,
      label: { show: true, position: 'bottom', fontSize: 12 },
      edgeSymbol: ['circle', 'arrow'],
      edgeSymbolSize: [4, 10],
      data: displayNodes,
      links: displayLinks,
      categories: categories,
      lineStyle: { opacity: 0.6, width: 2, curveness: 0 },
      force: layoutType.value === 'force' ? { repulsion: 200, edgeLength: 150 } : undefined,
      circular: layoutType.value === 'circular' ? { rotateLabel: true } : undefined
    }]
  }

  chartInstance.setOption(option, true)
}

// ── 图谱实例分解交互 ──
/** 右键实例 → 收回其所属类型（实例消失，恢复为类型节点） */
const handleGraphContextMenu = (params: any) => {
  if (params.dataType !== 'node' || !params.data) return
  const node = params.data
  if (node.nodeType === 'entity' && node.conceptId) {
    collapseType(node.conceptId)
  }
}

/** 左键类型 → 分解为实例（实例态）/ 收回（类型态）切换；左键实例 → 选中展示详情 */
const handleGraphClick = (params: any) => {
  if (params.dataType !== 'node' || !params.data) return
  const node = params.data
  if (node.nodeType === 'entityType') {
    if (expandedTypeIds.value.has(node.conceptId)) {
      collapseType(node.conceptId)
    } else {
      expandType(node.conceptId)
    }
  } else if (node.nodeType === 'entity') {
    const entity = entities.value.find(e => e.name === node.name)
    if (entity) selectEntity(entity)
  }
}

/** 分解类型：类型节点消失，其实例原位出现；无实例的类型不可分解 */
const expandType = (typeId: string) => {
  const hasInstances = rawGraphData.value.nodes.some(
    (n: any) => n.node_type === 'entity' && n.concept_id === typeId
  )
  if (!hasInstances) {
    ElMessage.info('该类型暂无实体实例，无法分解')
    return
  }
  const newSet = new Set(expandedTypeIds.value)
  newSet.add(typeId)
  expandedTypeIds.value = newSet
  renderGraph()
}

/** 收回类型：实例消失，恢复为类型节点 */
const collapseType = (typeId: string) => {
  const newSet = new Set(expandedTypeIds.value)
  newSet.delete(typeId)
  expandedTypeIds.value = newSet
  renderGraph()
}

/** 收起全部实例：回到全类型态（等价刷新后的初始视图） */
const resetExpand = () => {
  expandedTypeIds.value = new Set()
  renderGraph()
}

const zoomIn = () => {
  if (!chartInstance) return
  const option: any = chartInstance.getOption()
  const series = option.series[0]
  const currentZoom = series.zoom || 1
  chartInstance.setOption({ series: [{ zoom: currentZoom * 1.2 }] })
}

const zoomOut = () => {
  if (!chartInstance) return
  const option: any = chartInstance.getOption()
  const series = option.series[0]
  const currentZoom = series.zoom || 1
  chartInstance.setOption({ series: [{ zoom: currentZoom / 1.2 }] })
}

const resetZoom = () => {
  if (!chartInstance) return
  chartInstance.setOption({ series: [{ zoom: 1 }] })
}

// ── 实体操作 ──
const selectEntity = (entity: any) => {
  selectedEntity.value = entity
  // 兼容新 List[Property] 与旧 Dict 两种格式，统一映射为表单结构化属性
  let formProps: any[] = []
  const raw = entity.properties
  if (Array.isArray(raw)) {
    formProps = raw.map((p: any) => ({
      name: p.name || '',
      value: p.value !== undefined && p.value !== null ? String(p.value) : '',
      category: p.category || 'descriptive',
      data_type: p.data_type || 'string',
      unit: p.unit || '',
      source_snippet: p.source_snippet || ''
    }))
  } else if (raw && typeof raw === 'object') {
    formProps = Object.entries(raw).map(([k, v]) => ({
      name: k,
      value: String(v),
      category: 'descriptive',
      data_type: 'string',
      unit: '',
      source_snippet: ''
    }))
  }
  entityForm.value = {
    id: entity.id,
    name: entity.name,
    instance_of: entity.instance_of || '',
    is_primary: !!entity.is_primary,
    source_snippet: entity.source_snippet || '',
    properties: formProps
  }
}

const getEntityTypeColor = (type: string) => {
  const found = entityTypeOptions.value.find((t: any) => t.name === type)
  return found?.color || '#409eff'
}

/** 重置实体表单为空白（用于打开「添加实体」对话框） */
const resetEntityForm = () => {
  entityForm.value = {
    id: '',
    name: '',
    instance_of: '',
    is_primary: false,
    source_snippet: '',
    properties: []
  }
}

/** 选中实体类型时按其 property_schema 自动生成属性行 */
const onEntityTypeChange = (conceptId: string) => {
  const concept = entityTypes.value.find(c => c.id === conceptId)
  if (!concept) return
  // 仅在表单属性为空时自动填充，避免覆盖已编辑的值
  if (entityForm.value.properties.length === 0 && concept.property_schema?.length) {
    entityForm.value.properties = concept.property_schema.map((ps: any) => ({
      name: ps.name || '',
      value: '',
      category: ps.category || 'descriptive',
      data_type: ps.data_type || 'string',
      unit: ps.unit || '',
      source_snippet: ''
    }))
  }
}

const submitEntity = async () => {
  if (!entityForm.value.name || !entityForm.value.instance_of) {
    ElMessage.warning('请填写实体名并选择归属实体类型')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', entityForm.value.name)
    fd.append('instance_of', entityForm.value.instance_of)
    fd.append('is_primary', String(entityForm.value.is_primary))
    fd.append('source_snippet', entityForm.value.source_snippet)
    fd.append('properties', JSON.stringify(entityForm.value.properties.filter(p => p.name)))

    await createEntity(ontologyId, fd)
    ElMessage.success('实体添加成功')
    showAddEntityDialog.value = false
    resetEntityForm()
    await Promise.all([loadEntities(), loadRelations(), loadGraph()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '添加失败')
  } finally {
    submitting.value = false
  }
}

const submitEditEntity = async () => {
  if (!entityForm.value.name || !entityForm.value.instance_of) {
    ElMessage.warning('请填写实体名并选择归属实体类型')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', entityForm.value.name)
    fd.append('instance_of', entityForm.value.instance_of)
    fd.append('is_primary', String(entityForm.value.is_primary))
    fd.append('source_snippet', entityForm.value.source_snippet)
    fd.append('properties', JSON.stringify(entityForm.value.properties.filter(p => p.name)))

    await updateEntity(ontologyId, entityForm.value.id, fd)
    ElMessage.success('实体更新成功')
    showEditEntityDialog.value = false
    await Promise.all([loadEntities(), loadRelations(), loadGraph()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '更新失败')
  } finally {
    submitting.value = false
  }
}

const deleteEntity = async (entity: any) => {
  try {
    await ElMessageBox.confirm(`确定删除实体"${entity.name}"吗？关联关系将一并删除。`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }

  try {
    await service.delete(`/ontology/${ontologyId}/entity/${entity.id}`)
    ElMessage.success('删除成功')
    selectedEntity.value = null
    await Promise.all([loadEntities(), loadRelations(), loadGraph()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 关系操作 ──
const submitRelation = async () => {
  if (!relationForm.value.sourceId || !relationForm.value.targetId || !relationForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('source_id', relationForm.value.sourceId)
    fd.append('target_id', relationForm.value.targetId)
    fd.append('relation_type', relationForm.value.type)
    fd.append('weight', relationForm.value.weight.toString())

    await service.post(`/ontology/${ontologyId}/relation`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('关系添加成功')
    showAddRelationDialog.value = false
    relationForm.value = { sourceId: '', targetId: '', type: '', weight: 1.0 }
    await Promise.all([loadRelations(), loadGraph()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '添加失败')
  } finally {
    submitting.value = false
  }
}

const deleteRelation = async (relation: any) => {
  try {
    await ElMessageBox.confirm('确定删除该关系吗？', '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }

  try {
    await service.delete(`/ontology/${ontologyId}/relation/${relation.id}`)
    ElMessage.success('删除成功')
    await Promise.all([loadRelations(), loadGraph()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 本体操作 ──
const submitEdit = async () => {
  if (!editForm.value.name) {
    ElMessage.warning('请填写本体名称')
    return
  }

  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', editForm.value.name)
    fd.append('description', editForm.value.description)
    fd.append('entity_types', JSON.stringify(editForm.value.entityTypes.filter(t => t.name)))
    fd.append('relation_types', JSON.stringify(editForm.value.relationTypes.filter(t => t.name)))

    await updateOntology(ontologyId, fd)
    ElMessage.success('本体更新成功')
    showEditDialog.value = false
    await loadOntology()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '更新失败')
  } finally {
    submitting.value = false
  }
}

// 归档本体：确认后调用后端归档接口，归档后参与下游数据联动
const archiveOntology = async () => {
  try {
    await ElMessageBox.confirm(`确定将本体「${ontology.value?.name || ''}」归档吗？归档后参与下游数据联动。`, '归档确认', {
      confirmButtonText: '归档', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }

  try {
    await archiveOntologyApi(ontologyId)
    ElMessage.success('归档成功')
    await refreshData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '归档失败')
  }
}

// 恢复本体：取消归档，恢复为活跃，不再参与下游数据联动
const restoreOntology = async () => {
  try {
    await restoreOntologyApi(ontologyId)
    ElMessage.success('已恢复为活跃')
    await refreshData()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '恢复失败')
  }
}

const exportOntology = async () => {
  try {
    const res: any = await exportOntologyApi(ontologyId)
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ontology.value?.name || 'ontology'}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '导出失败')
  }
}

const goBack = () => {
  router.push('/ontology')
}

// ── 生命周期 ──
const handleResize = () => {
  chartInstance?.resize()
}

watch(showEditDialog, (val) => {
  if (val && ontology.value) {
    editForm.value = {
      name: ontology.value.name,
      description: ontology.value.description,
      entityTypes: JSON.parse(JSON.stringify(ontology.value.entity_types || [])),
      relationTypes: JSON.parse(JSON.stringify(ontology.value.relation_types || []))
    }
  }
})

onMounted(async () => {
  await Promise.all([loadOntology(), loadConcepts(), loadEntities(), loadRelations()])
  await nextTick()
  await loadGraph()
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.ontology-detail {
  height: 100%;
  padding: 1.5rem;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 1rem;
}

.header-left h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.5rem;
  font-weight: 600;
}

.header-actions {
  display: flex;
  gap: 0.75rem;
}

.three-column-layout {
  display: flex;
  gap: 1rem;
  flex: 1;
  min-height: 0;
}

.left-panel {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  min-height: 0;
}

.center-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.right-panel {
  width: 320px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  overflow-y: auto;
}

.panel-card {
  flex-shrink: 0;
}

.panel-card :deep(.el-card__body) {
  padding: 1.25rem;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: var(--text-base);
  color: var(--text-primary);
}

/* 计数徽标：与页面其它统计数字保持同一视觉语言 */
.count-badge {
  min-width: 22px;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--radius-full);
  background: var(--primary-50);
  color: var(--primary-600);
  font-size: var(--text-xs);
  font-weight: 600;
  line-height: 20px;
  text-align: center;
}

/* ── 列表卡片：等分左栏高度，列表区自身滚动 ── */
.list-card {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}

.list-card :deep(.el-card__body) {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: 0.875rem 1rem 1rem;
}

.list-toolbar {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
  flex-shrink: 0;
}

.list-toolbar .el-input {
  flex: 1;
}

.type-filter {
  width: 108px;
  flex-shrink: 0;
}

.option-dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
}

/* ── 实体列表 ── */
.entity-list {
  flex: 1;
  min-height: 96px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 -0.25rem;
  padding: 0 0.25rem;
}

.entity-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.625rem;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition-fast);
  border-left: 2px solid transparent;
}

.entity-item:hover {
  background: var(--bg-hover);
}

.entity-item.active {
  background: var(--bg-active);
  border-left-color: var(--entity-color, var(--primary-500));
}

.entity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
  background: var(--entity-color, var(--primary-500));
}

.entity-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1px;
}

.entity-name {
  font-size: var(--text-base);
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.entity-type {
  font-size: var(--text-xs);
  color: var(--text-muted);
}

.entity-degree {
  display: flex;
  align-items: center;
  gap: 2px;
  flex-shrink: 0;
  font-size: var(--text-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
}

.entity-degree .el-icon {
  font-size: 12px;
}

/* ── 关系列表：两行结构，避免长实体名横向溢出 ── */
.relation-list {
  flex: 1;
  min-height: 96px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin: 0 -0.25rem;
  padding: 0 0.25rem;
}

.relation-item {
  padding: 0.5rem 0.625rem;
  border-radius: var(--radius-md);
  transition: background var(--transition-fast);
}

.relation-item:hover {
  background: var(--bg-hover);
}

.rel-line {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  min-width: 0;
}

.rel-line-target {
  margin-top: 2px;
}

.rel-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}

.rel-name {
  min-width: 0;
  font-size: var(--text-sm);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 关系类型：中性灰色胶囊，不与实体类型色抢视觉 */
.rel-type {
  flex-shrink: 0;
  margin-left: auto;
  padding: 1px 7px;
  border-radius: var(--radius-full);
  background: var(--gray-100);
  color: var(--text-tertiary);
  font-size: var(--text-xs);
  font-weight: 500;
  white-space: nowrap;
}

.rel-connector {
  flex-shrink: 0;
  width: 10px;
  color: var(--text-muted);
  font-size: var(--text-xs);
  line-height: 1;
}

.relation-delete {
  opacity: 0;
  transition: opacity var(--transition-fast);
  margin-left: auto;
  padding: 2px;
  flex-shrink: 0;
}

.relation-item:hover .relation-delete {
  opacity: 1;
}

.graph-card {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.graph-card :deep(.el-card__body) {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding: 0;
}

.graph-wrapper {
  flex: 1;
  position: relative;
  min-height: 400px;
}

.graph-container {
  width: 100%;
  height: 100%;
}

.graph-toolbar {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  flex-wrap: wrap;
}

.graph-hint {
  font-size: 0.75rem;
  color: var(--el-text-color-secondary, #909399);
  margin-top: 0.25rem;
}

.graph-legend-overlay {
  position: absolute;
  top: 12px;
  right: 12px;
  background: rgba(255, 255, 255, 0.92);
  backdrop-filter: blur(8px);
  border-radius: 8px;
  padding: 10px 14px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.1);
  z-index: 10;
  max-width: 200px;
}

.graph-legend-overlay .legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8rem;
  color: var(--text-regular);
  padding: 2px 0;
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.entity-detail {
  padding: 0.75rem 0;
}

.property-item {
  display: flex;
  gap: 0.5rem;
  margin: 0.5rem 0;
  font-size: 0.85rem;
}

.property-key {
  color: var(--text-secondary);
  font-weight: 500;
}

.property-value {
  color: var(--text-primary);
}

.detail-actions {
  margin-top: 1rem;
  display: flex;
  gap: 0.5rem;
}

.stats-info {
  padding: 0.25rem 0;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.65rem 0;
  border-bottom: 1px solid var(--border-light);
}

.stat-item:last-child {
  border-bottom: none;
}

.stat-label {
  color: var(--text-secondary);
  font-size: 0.85rem;
}

.stat-value {
  font-weight: 600;
  color: var(--primary-500);
  font-size: 1rem;
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

.prop-edit-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}
</style>
