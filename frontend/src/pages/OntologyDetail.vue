<template>
  <Layout>
    <div class="ontology-detail">
      <!-- 顶部工具栏 -->
      <div class="detail-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回</el-button>
          <h2>{{ ontology?.name || '本体详情' }}</h2>
          <el-tag v-if="ontology?.is_default" type="warning" size="small">默认</el-tag>
        </div>
        <div class="header-actions">
          <el-button @click="refreshData" :icon="Refresh">刷新</el-button>
          <el-button @click="showEditDialog = true" :icon="Edit">编辑</el-button>
          <el-button @click="archiveOntology" :icon="FolderChecked">归档</el-button>
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
                </div>
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
                  <div v-if="Object.keys(selectedEntity.properties || {}).length">
                    <div v-for="(value, key) in selectedEntity.properties" :key="key" class="property-item">
                      <span class="property-key">{{ key }}:</span>
                      <span class="property-value">{{ value }}</span>
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
      <el-dialog v-model="showAddEntityDialog" title="添加实体" width="560px">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名称" required>
            <el-input v-model="entityForm.name" placeholder="请输入实体名称" />
          </el-form-item>
          <el-form-item label="实体类型" required>
            <el-select v-model="entityForm.type" placeholder="请选择类型" style="width: 100%">
              <el-option v-for="t in entityTypeOptions" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="属性">
            <div class="type-editor" style="width: 100%">
              <div v-for="(p, idx) in entityForm.props" :key="idx" class="type-row">
                <el-input v-model="p.key" placeholder="属性名" size="small" style="width: 140px" />
                <el-input v-model="p.value" placeholder="属性值" size="small" style="width: 200px" />
                <el-button size="small" link type="danger" @click="entityForm.props.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="entityForm.props.push({ key: '', value: '' })">+ 添加属性</el-button>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddEntityDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEntity">添加</el-button>
        </template>
      </el-dialog>

      <!-- 编辑实体对话框 -->
      <el-dialog v-model="showEditEntityDialog" title="编辑实体" width="560px">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名称" required>
            <el-input v-model="entityForm.name" placeholder="请输入实体名称" />
          </el-form-item>
          <el-form-item label="实体类型" required>
            <el-select v-model="entityForm.type" placeholder="请选择类型" style="width: 100%">
              <el-option v-for="t in entityTypeOptions" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="属性">
            <div class="type-editor" style="width: 100%">
              <div v-for="(p, idx) in entityForm.props" :key="idx" class="type-row">
                <el-input v-model="p.key" placeholder="属性名" size="small" style="width: 140px" />
                <el-input v-model="p.value" placeholder="属性值" size="small" style="width: 200px" />
                <el-button size="small" link type="danger" @click="entityForm.props.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="entityForm.props.push({ key: '', value: '' })">+ 添加属性</el-button>
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
  Plus, Search, Connection
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import {
  getOntology,
  updateOntology,
  exportOntology as exportOntologyApi,
  archiveOntology as archiveOntologyApi,
  getEntityList,
  getRelationList,
  getGraphData
} from '@/services/ontology'
import service from '@/services/api'

const route = useRoute()
const router = useRouter()
const ontologyId = route.params.id as string

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)

const ontology = ref<any>(null)
const entities = ref<any[]>([])
const relations = ref<any[]>([])
const selectedEntity = ref<any>(null)
const entitySearch = ref('')
const entityTypeFilter = ref('')
const relationSearch = ref('')
const layoutType = ref('force')

const graphRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

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
  type: '',
  props: [] as { key: string; value: string }[]
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
    renderGraph(res.data)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载图谱失败')
  }
}

const refreshData = async () => {
  await Promise.all([loadOntology(), loadEntities(), loadRelations(), loadGraph()])
  ElMessage.success('数据已刷新')
}

// ── 图谱渲染 ──
const renderGraph = (data: { nodes: any[]; links: any[] }) => {
  if (!graphRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(graphRef.value)
  }
  // 确保画布尺寸与容器一致，避免 flex 布局初始化时高度为 0
  chartInstance.resize()

  const catIndex: Record<string, number> = {}
  const categories = entityTypeOptions.value.map((t: any, i: number) => {
    catIndex[t.name] = i
    // 用后端 entity_types.color 作为节点颜色，与图例/实例列表保持一致；
    // 若某类型无 color 则走兜底 #409eff，避免 echarts 默认色板导致错位
    return { name: t.name, itemStyle: { color: t.color || '#409eff' } }
  })
  // 兜底类别：实体类型在 entity_types 中找不到时使用，颜色与 getEntityTypeColor 兜底 #409eff 一致
  const fallbackCatIndex = categories.length
  categories.push({ name: '[未分类]', itemStyle: { color: '#409eff' } })

  const idToName: Record<string, string> = {}
  const nodes = data.nodes.map((n: any) => {
    idToName[n.id] = n.name
    return {
      name: n.name,
      // 类型找不到时指向兜底类别（[未分类]，颜色 #409eff），与列表兜底保持一致
      category: catIndex[n.type] ?? fallbackCatIndex,
      symbolSize: 50,
      draggable: true
    }
  })

  const links = data.links.map((l: any) => ({
    source: idToName[l.source] || l.source,
    target: idToName[l.target] || l.target,
    value: l.relation,
    lineStyle: { type: 'solid' }
  }))

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (p: any) => {
        if (p.dataType === 'edge') {
          return `${p.data.source} → ${p.data.target}<br/>关系: ${p.data.value || ''}`
        }
        return p.data.name
      }
    },
    series: [{
      type: 'graph',
      layout: layoutType.value,
      roam: true,
      label: { show: true, position: 'bottom', fontSize: 12 },
      edgeSymbol: ['circle', 'arrow'],
      edgeSymbolSize: [4, 10],
      data: nodes,
      links: links,
      categories: categories,
      lineStyle: { opacity: 0.6, width: 2, curveness: 0 },
      force: layoutType.value === 'force' ? { repulsion: 200, edgeLength: 150 } : undefined,
      circular: layoutType.value === 'circular' ? { rotateLabel: true } : undefined
    }]
  }

  chartInstance.setOption(option, true)
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
  entityForm.value = {
    id: entity.id,
    name: entity.name,
    type: entity.type,
    props: Object.entries(entity.properties || {}).map(([k, v]) => ({ key: k, value: String(v) }))
  }
}

const getEntityTypeColor = (type: string) => {
  const found = entityTypeOptions.value.find((t: any) => t.name === type)
  return found?.color || '#409eff'
}

const submitEntity = async () => {
  if (!entityForm.value.name || !entityForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }

  submitting.value = true
  try {
    const propsObj: Record<string, string> = {}
    entityForm.value.props.forEach(p => {
      if (p.key.trim()) propsObj[p.key.trim()] = p.value
    })

    const fd = new FormData()
    fd.append('name', entityForm.value.name)
    fd.append('entity_type', entityForm.value.type)
    fd.append('properties', JSON.stringify(propsObj))

    await service.post(`/ontology/${ontologyId}/entity`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('实体添加成功')
    showAddEntityDialog.value = false
    entityForm.value = { id: '', name: '', type: '', props: [] }
    await Promise.all([loadEntities(), loadRelations(), loadGraph()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '添加失败')
  } finally {
    submitting.value = false
  }
}

const submitEditEntity = async () => {
  if (!entityForm.value.name || !entityForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }

  submitting.value = true
  try {
    const propsObj: Record<string, string> = {}
    entityForm.value.props.forEach(p => {
      if (p.key.trim()) propsObj[p.key.trim()] = p.value
    })

    const fd = new FormData()
    fd.append('name', entityForm.value.name)
    fd.append('entity_type', entityForm.value.type)
    fd.append('properties', JSON.stringify(propsObj))

    await service.put(`/ontology/${ontologyId}/entity/${entityForm.value.id}`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
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

// 归档本体：确认后调用后端归档接口，归档后返回列表页
const archiveOntology = async () => {
  try {
    await ElMessageBox.confirm(`确定将本体「${ontology.value?.name || ''}」归档吗？归档后不再作为默认本体，可在列表的「归档」筛选中查看。`, '归档确认', {
      confirmButtonText: '归档', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }

  try {
    await archiveOntologyApi(ontologyId)
    ElMessage.success('归档成功')
    goBack()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '归档失败')
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
  await Promise.all([loadOntology(), loadEntities(), loadRelations()])
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
</style>
