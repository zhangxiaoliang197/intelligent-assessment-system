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
          <el-button @click="exportOntology" :icon="Download">导出</el-button>
          <el-button @click="showEditDialog = true" :icon="Edit">编辑</el-button>
        </div>
      </div>

      <!-- 三栏布局 -->
      <div class="three-column-layout" v-loading="loading">
        <!-- 左面板：实体列表 -->
        <div class="left-panel">
          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>实体列表</span>
                <el-button size="small" type="primary" @click="showAddEntityDialog = true">添加</el-button>
              </div>
            </template>
            <el-input
              v-model="entitySearch"
              placeholder="搜索实体..."
              prefix-icon="Search"
              clearable
              size="small"
              style="margin-bottom: 0.75rem"
            />
            <div class="entity-list">
              <div
                v-for="entity in filteredEntities"
                :key="entity.id"
                :class="['entity-item', { active: selectedEntity?.id === entity.id }]"
                @click="selectEntity(entity)"
              >
                <div class="entity-info">
                  <span class="entity-name">{{ entity.name }}</span>
                  <el-tag size="small" :style="{ color: getEntityTypeColor(entity.type), borderColor: getEntityTypeColor(entity.type) }">
                    {{ entity.type }}
                  </el-tag>
                </div>
              </div>
              <el-empty v-if="!filteredEntities.length" description="暂无实体" :image-size="60" />
            </div>
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>关系列表</span>
                <el-button size="small" type="primary" @click="showAddRelationDialog = true">添加</el-button>
              </div>
            </template>
            <div class="relation-list">
              <div v-for="relation in relations" :key="relation.id" class="relation-item">
                <div class="relation-content">
                  <span class="relation-source">{{ relation.source_name }}</span>
                  <el-icon><Right /></el-icon>
                  <span class="relation-type">{{ relation.relation_type }}</span>
                  <el-icon><Right /></el-icon>
                  <span class="relation-target">{{ relation.target_name }}</span>
                </div>
                <el-button size="small" link type="danger" @click="deleteRelation(relation)">删除</el-button>
              </div>
              <el-empty v-if="!relations.length" description="暂无关系" :image-size="60" />
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
            <div ref="graphRef" class="graph-container"></div>
            <div class="graph-legend">
              <div v-for="type in entityTypeOptions" :key="type.name" class="legend-item">
                <span class="legend-dot" :style="{ background: type.color }"></span>
                <span>{{ type.name }}</span>
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
  ArrowLeft, Refresh, Download, Edit, ZoomIn, ZoomOut, RefreshRight, Right
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import {
  getOntology,
  updateOntology,
  exportOntology as exportOntologyApi,
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
  if (!entitySearch.value) return entities.value
  const kw = entitySearch.value.toLowerCase()
  return entities.value.filter(e => e.name.toLowerCase().includes(kw))
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

  const catIndex: Record<string, number> = {}
  const categories = entityTypeOptions.value.map((t: any, i: number) => {
    catIndex[t.name] = i
    return { name: t.name }
  })

  const idToName: Record<string, string> = {}
  const nodes = data.nodes.map((n: any) => {
    idToName[n.id] = n.name
    return {
      name: n.name,
      category: catIndex[n.type] ?? 0,
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
    legend: [{ data: categories.map((c: any) => c.name) }],
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
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
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
  gap: 1rem;
  overflow-y: auto;
}

.panel-card {
  flex-shrink: 0;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}

.entity-list {
  max-height: 300px;
  overflow-y: auto;
}

.entity-item {
  padding: 0.75rem;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  margin-bottom: 0.5rem;
}

.entity-item:hover {
  background: var(--bg-hover);
}

.entity-item.active {
  background: rgba(64, 158, 255, 0.1);
  border: 1px solid var(--primary-500);
}

.entity-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.entity-name {
  font-size: 0.9rem;
  color: var(--text-primary);
  font-weight: 500;
}

.relation-list {
  max-height: 240px;
  overflow-y: auto;
}

.relation-item {
  padding: 0.6rem 0.2rem;
  border-bottom: 1px solid var(--border-light);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.relation-content {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
}

.relation-source,
.relation-target {
  color: var(--primary-500);
  font-weight: 500;
}

.relation-type {
  color: var(--success-500);
}

.graph-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.graph-container {
  flex: 1;
  min-height: 500px;
}

.graph-toolbar {
  display: flex;
  gap: 0.5rem;
}

.graph-legend {
  display: flex;
  gap: 1rem;
  padding: 0.75rem;
  flex-wrap: wrap;
  border-top: 1px solid var(--border-light);
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.85rem;
  color: var(--text-secondary);
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}

.entity-detail {
  padding: 0.5rem 0;
}

.property-item {
  display: flex;
  gap: 0.5rem;
  margin: 0.25rem 0;
  font-size: 0.9rem;
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
  padding: 0.5rem 0;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border-light);
}

.stat-item:last-child {
  border-bottom: none;
}

.stat-label {
  color: var(--text-secondary);
}

.stat-value {
  font-weight: 600;
  color: var(--primary-500);
  font-size: 1.1rem;
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
