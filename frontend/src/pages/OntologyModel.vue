<template>
  <Layout>
    <div class="ontology-container">
      <div class="page-layout">
        <div class="left-panel">
          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>本体模型</span>
                <el-button type="primary" size="small" @click="openCreateOntology">新建本体</el-button>
              </div>
            </template>
            <div class="ontology-list">
              <div
                v-for="ontology in ontologies"
                :key="ontology.id"
                :class="['ontology-item', { active: selectedOntology?.id === ontology.id }]"
                @click="selectOntology(ontology)"
              >
                <div class="ontology-info">
                  <h4>{{ ontology.name }}</h4>
                  <p>{{ ontology.description }}</p>
                </div>
                <div class="ontology-stats">
                  <span>实体: {{ ontology.entities_count }}</span>
                  <span>关系: {{ ontology.relations_count }}</span>
                </div>
                <div class="ontology-actions" @click.stop>
                  <el-button size="small" link @click="openEditOntology(ontology)">编辑</el-button>
                  <el-button size="small" link @click="exportOntology(ontology)">导出</el-button>
                  <el-button size="small" link type="danger" @click="deleteOntology(ontology)">删除</el-button>
                </div>
              </div>
              <el-empty v-if="!ontologies.length" description="暂无本体模型" :image-size="60" />
            </div>
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>实体列表</span>
                <el-button size="small" :disabled="!selectedOntology" @click="openAddEntity">添加实体</el-button>
              </div>
            </template>
            <div class="entity-list">
              <el-input v-model="entitySearch" placeholder="搜索实体..." size="small" style="margin-bottom: 1rem" />
              <div
                v-for="entity in filteredEntities"
                :key="entity.id"
                :class="['entity-item', { active: selectedEntity?.id === entity.id }]"
                @click="selectEntity(entity)"
              >
                <el-icon><Box /></el-icon>
                <span>{{ entity.name }}</span>
                <el-tag size="small">{{ entity.type }}</el-tag>
              </div>
              <el-empty v-if="!filteredEntities.length" description="暂无实体" :image-size="40" />
            </div>
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>关系列表</span>
                <el-button size="small" :disabled="!selectedOntology" @click="openAddRelation">添加关系</el-button>
              </div>
            </template>
            <div class="relation-list">
              <div
                v-for="relation in relations"
                :key="relation.id"
                class="relation-item"
              >
                <div class="relation-content">
                  <span class="relation-source">{{ relation.source_name }}</span>
                  <el-icon><Right /></el-icon>
                  <span class="relation-type">{{ relation.relation_type }}</span>
                  <el-icon><Right /></el-icon>
                  <span class="relation-target">{{ relation.target_name }}</span>
                </div>
                <el-button size="small" link type="danger" @click="deleteRelation(relation)">删除</el-button>
              </div>
              <el-empty v-if="!relations.length" description="暂无关系" :image-size="40" />
            </div>
          </el-card>
        </div>

        <div class="main-content">
          <el-card class="graph-card">
            <template #header>
              <div class="panel-header">
                <span>知识图谱 <span v-if="selectedOntology" class="graph-subtitle">— {{ selectedOntology.name }}</span></span>
                <div class="graph-actions">
                  <el-upload
                    :show-file-list="false"
                    :before-upload="importOntology"
                    accept=".json"
                  >
                    <el-button size="small">导入</el-button>
                  </el-upload>
                  <el-button size="small" @click="refreshGraph">刷新</el-button>
                </div>
              </div>
            </template>
            <div ref="graphRef" class="graph-container"></div>
          </el-card>
        </div>

        <div class="right-panel">
          <el-card class="panel-card">
            <template #header>
              <span>实体详情</span>
            </template>
            <div v-if="selectedEntity" class="entity-detail">
              <el-descriptions :column="1" border>
                <el-descriptions-item label="名称">
                  {{ selectedEntity.name }}
                </el-descriptions-item>
                <el-descriptions-item label="类型">
                  <el-tag>{{ selectedEntity.type }}</el-tag>
                </el-descriptions-item>
                <el-descriptions-item label="属性">
                  <div v-for="(value, key) in selectedEntity.properties" :key="key" class="property-item">
                    <span class="property-key">{{ key }}:</span>
                    <span class="property-value">{{ value }}</span>
                  </div>
                  <el-empty v-if="!Object.keys(selectedEntity.properties).length" description="无属性" :image-size="30" />
                </el-descriptions-item>
              </el-descriptions>
              <div class="detail-actions">
                <el-button size="small" @click="openEditEntity(selectedEntity)">编辑</el-button>
                <el-button size="small" type="danger" @click="deleteEntity(selectedEntity)">删除</el-button>
              </div>
            </div>
            <el-empty v-else description="请选择实体查看详情" />
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <span>统计信息</span>
            </template>
            <div class="stats-info">
              <div class="stat-item">
                <span class="stat-label">本体总数</span>
                <span class="stat-value">{{ ontologies.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">实体总数</span>
                <span class="stat-value">{{ entities.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">关系总数</span>
                <span class="stat-value">{{ relations.length }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <!-- 新建/编辑本体对话框 -->
      <el-dialog v-model="showOntologyDialog" :title="ontologyForm.id ? '编辑本体模型' : '新建本体模型'" width="640px">
        <el-form :model="ontologyForm" label-width="100px">
          <el-form-item label="本体名称">
            <el-input v-model="ontologyForm.name" placeholder="请输入本体名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="ontologyForm.description" type="textarea" :rows="2" placeholder="请输入描述" />
          </el-form-item>
          <el-form-item label="实体类型">
            <div class="type-editor">
              <div v-for="(t, idx) in ontologyForm.entityTypes" :key="idx" class="type-row">
                <el-input v-model="t.name" placeholder="类型名" size="small" style="width: 160px" />
                <el-color-picker v-model="t.color" size="small" />
                <el-button size="small" link type="danger" @click="ontologyForm.entityTypes.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="ontologyForm.entityTypes.push({ name: '', color: '#5470c6' })">+ 添加实体类型</el-button>
            </div>
          </el-form-item>
          <el-form-item label="关系类型">
            <div class="type-editor">
              <div v-for="(t, idx) in ontologyForm.relationTypes" :key="idx" class="type-row">
                <el-input v-model="t.name" placeholder="关系名" size="small" style="width: 160px" />
                <el-button size="small" link type="danger" @click="ontologyForm.relationTypes.splice(idx, 1)">删除</el-button>
              </div>
              <el-button size="small" @click="ontologyForm.relationTypes.push({ name: '' })">+ 添加关系类型</el-button>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showOntologyDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitOntology">确定</el-button>
        </template>
      </el-dialog>

      <!-- 添加/编辑实体对话框 -->
      <el-dialog v-model="showEntityDialog" :title="entityForm.id ? '编辑实体' : '添加实体'" width="560px">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名称">
            <el-input v-model="entityForm.name" placeholder="请输入实体名称" />
          </el-form-item>
          <el-form-item label="实体类型">
            <el-select v-model="entityForm.type" placeholder="请选择类型" style="width: 100%">
              <el-option
                v-for="t in entityTypeOptions"
                :key="t.name"
                :label="t.name"
                :value="t.name"
              />
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
          <el-button @click="showEntityDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEntity">确定</el-button>
        </template>
      </el-dialog>

      <!-- 添加关系对话框 -->
      <el-dialog v-model="showRelationDialog" title="添加关系" width="500px">
        <el-form :model="relationForm" label-width="100px">
          <el-form-item label="源实体">
            <el-select v-model="relationForm.sourceId" placeholder="请选择源实体" style="width: 100%">
              <el-option
                v-for="entity in entities"
                :key="entity.id"
                :label="entity.name"
                :value="entity.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="目标实体">
            <el-select v-model="relationForm.targetId" placeholder="请选择目标实体" style="width: 100%">
              <el-option
                v-for="entity in entities"
                :key="entity.id"
                :label="entity.name"
                :value="entity.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型">
            <el-select v-model="relationForm.type" placeholder="请选择关系类型" style="width: 100%">
              <el-option
                v-for="t in relationTypeOptions"
                :key="t.name"
                :label="t.name"
                :value="t.name"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="relationForm.weight" :min="0" :max="1" :step="0.1" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showRelationDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitRelation">添加</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, reactive } from 'vue'
import { Box, Right } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'
import service from '@/services/api'

// ── 响应式状态 ──
const graphRef = ref<HTMLElement | null>(null)
let chartInstance: echarts.ECharts | null = null

const ontologies = ref<any[]>([])
const entities = ref<any[]>([])
const relations = ref<any[]>([])

const selectedOntology = ref<any>(null)
const selectedEntity = ref<any>(null)
const entitySearch = ref('')
const submitting = ref(false)

// 对话框开关
const showOntologyDialog = ref(false)
const showEntityDialog = ref(false)
const showRelationDialog = ref(false)

// 本体表单（新建/编辑共用）
const ontologyForm = reactive<{ id: string; name: string; description: string; entityTypes: any[]; relationTypes: any[] }>({
  id: '',
  name: '',
  description: '',
  entityTypes: [],
  relationTypes: []
})

// 实体表单（添加/编辑共用）
const entityForm = reactive<{ id: string; name: string; type: string; props: { key: string; value: string }[] }>({
  id: '',
  name: '',
  type: '',
  props: []
})

// 关系表单
const relationForm = reactive<{ sourceId: string; targetId: string; type: string; weight: number }>({
  sourceId: '',
  targetId: '',
  type: '',
  weight: 1.0
})

// 当前本体的类型选项（从元模型动态加载）
const entityTypeOptions = computed(() => selectedOntology.value?.entity_types || [])
const relationTypeOptions = computed(() => selectedOntology.value?.relation_types || [])

// 实体搜索过滤
const filteredEntities = computed(() => {
  if (!entitySearch.value) return entities.value
  const kw = entitySearch.value.toLowerCase()
  return entities.value.filter(e => e.name.toLowerCase().includes(kw))
})

// ── 请求辅助 ──
/**
 * 以 FormData 发送 POST/PUT 请求（后端使用 Form 参数）
 * @param url 接口路径
 * @param data 表单数据
 */
async function postForm(url: string, data: Record<string, any>) {
  const fd = new FormData()
  for (const k in data) {
    if (data[k] !== undefined && data[k] !== null) {
      fd.append(k, data[k])
    }
  }
  return service.post(url, fd, { headers: { 'Content-Type': 'multipart/form-data' } })
}

/**
 * 将属性键值对数组转为对象
 * @param props 键值对数组
 */
function propsArrayToObject(props: { key: string; value: string }[]): Record<string, string> {
  const obj: Record<string, string> = {}
  for (const p of props) {
    if (p.key.trim()) obj[p.key.trim()] = p.value
  }
  return obj
}

/**
 * 将属性对象转为键值对数组（用于表单回显）
 * @param obj 属性对象
 */
function propsObjectToArray(obj: Record<string, string>): { key: string; value: string }[] {
  return Object.entries(obj || {}).map(([key, value]) => ({ key, value: String(value) }))
}

// ── 数据加载 ──
/** 加载本体列表 */
async function loadOntologies() {
  try {
    const res: any = await service.get('/ontology/list')
    ontologies.value = res.items || []
    // 若有选中本体，同步更新其引用
    if (selectedOntology.value) {
      const updated = ontologies.value.find(o => o.id === selectedOntology.value.id)
      if (updated) selectedOntology.value = updated
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载本体列表失败')
  }
}

/** 加载选中本体的实体与关系 */
async function loadOntologyDetail(ontologyId: string) {
  try {
    const [entRes, relRes, graphRes] = await Promise.all([
      service.get(`/ontology/${ontologyId}/entity/list`, { params: { page: 1, page_size: 1000 } }),
      service.get(`/ontology/${ontologyId}/relation/list`, { params: { page: 1, page_size: 1000 } }),
      service.get(`/ontology/${ontologyId}/graph`)
    ])
    entities.value = (entRes as any).items || []
    relations.value = (relRes as any).items || []
    selectedEntity.value = null
    renderGraph((graphRes as any).data)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载本体详情失败')
  }
}

// ── 本体操作 ──
/** 选中本体 */
function selectOntology(ontology: any) {
  selectedOntology.value = ontology
  loadOntologyDetail(ontology.id)
}

/** 打开新建本体对话框 */
function openCreateOntology() {
  Object.assign(ontologyForm, {
    id: '', name: '', description: '',
    entityTypes: [{ name: '概念', color: '#5470c6' }, { name: '实体', color: '#91cc75' }, { name: '属性', color: '#fac858' }, { name: '事件', color: '#ee6666' }],
    relationTypes: [{ name: '包含' }, { name: '关联' }, { name: '影响' }]
  })
  showOntologyDialog.value = true
}

/** 打开编辑本体对话框 */
function openEditOntology(ontology: any) {
  Object.assign(ontologyForm, {
    id: ontology.id,
    name: ontology.name,
    description: ontology.description,
    entityTypes: JSON.parse(JSON.stringify(ontology.entity_types || [])),
    relationTypes: JSON.parse(JSON.stringify(ontology.relation_types || []))
  })
  showOntologyDialog.value = true
}

/** 提交本体（新建或编辑） */
async function submitOntology() {
  if (!ontologyForm.name) {
    ElMessage.warning('请填写本体名称')
    return
  }
  const payload: Record<string, any> = {
    name: ontologyForm.name,
    description: ontologyForm.description,
    entity_types: JSON.stringify(ontologyForm.entityTypes.filter(t => t.name)),
    relation_types: JSON.stringify(ontologyForm.relationTypes.filter(t => t.name))
  }
  submitting.value = true
  try {
    if (ontologyForm.id) {
      await postForm(`/ontology/${ontologyForm.id}`, payload)
      ElMessage.success('本体更新成功')
    } else {
      await postForm('/ontology/create', payload)
      ElMessage.success('本体创建成功')
    }
    showOntologyDialog.value = false
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '操作失败')
  } finally {
    submitting.value = false
  }
}

/** 删除本体 */
async function deleteOntology(ontology: any) {
  try {
    await ElMessageBox.confirm(`确定删除本体"${ontology.name}"及其所有实体关系吗？`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  try {
    await service.delete(`/ontology/${ontology.id}`)
    ElMessage.success('删除成功')
    if (selectedOntology.value?.id === ontology.id) {
      selectedOntology.value = null
      entities.value = []
      relations.value = []
      selectedEntity.value = null
      renderGraph({ nodes: [], links: [] })
    }
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

/** 导出本体为 JSON 文件 */
async function exportOntology(ontology: any) {
  try {
    const res: any = await service.get(`/ontology/export/${ontology.id}`)
    const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${ontology.name}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '导出失败')
  }
}

/** 导入本体 JSON 文件 */
async function importOntology(file: File) {
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res: any = await service.post('/ontology/import', fd, { headers: { 'Content-Type': 'multipart/form-data' } })
    ElMessage.success(`导入成功：${res.data.entities_imported} 实体, ${res.data.relations_imported} 关系`)
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '导入失败')
  }
  return false // 阻止 el-upload 默认上传
}

// ── 实体操作 ──
/** 打开添加实体对话框 */
function openAddEntity() {
  Object.assign(entityForm, { id: '', name: '', type: '', props: [] })
  showEntityDialog.value = true
}

/** 打开编辑实体对话框 */
function openEditEntity(entity: any) {
  Object.assign(entityForm, {
    id: entity.id,
    name: entity.name,
    type: entity.type,
    props: propsObjectToArray(entity.properties)
  })
  showEntityDialog.value = true
}

/** 提交实体（添加或编辑） */
async function submitEntity() {
  if (!entityForm.name || !entityForm.type) {
    ElMessage.warning('请填写完整信息')
    return
  }
  if (!selectedOntology.value) return
  const oid = selectedOntology.value.id
  const payload = {
    name: entityForm.name,
    entity_type: entityForm.type,
    properties: JSON.stringify(propsArrayToObject(entityForm.props))
  }
  submitting.value = true
  try {
    if (entityForm.id) {
      await postForm(`/ontology/${oid}/entity/${entityForm.id}`, payload)
      ElMessage.success('实体更新成功')
    } else {
      await postForm(`/ontology/${oid}/entity`, payload)
      ElMessage.success('实体添加成功')
    }
    showEntityDialog.value = false
    await loadOntologyDetail(oid)
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '操作失败')
  } finally {
    submitting.value = false
  }
}

/** 删除实体 */
async function deleteEntity(entity: any) {
  if (!selectedOntology.value) return
  try {
    await ElMessageBox.confirm(`确定删除实体"${entity.name}"吗？关联关系将一并删除。`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  try {
    await service.delete(`/ontology/${selectedOntology.value.id}/entity/${entity.id}`)
    ElMessage.success('删除成功')
    selectedEntity.value = null
    await loadOntologyDetail(selectedOntology.value.id)
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

/** 选中实体 */
function selectEntity(entity: any) {
  selectedEntity.value = entity
}

// ── 关系操作 ──
/** 打开添加关系对话框 */
function openAddRelation() {
  Object.assign(relationForm, { sourceId: '', targetId: '', type: '', weight: 1.0 })
  showRelationDialog.value = true
}

/** 提交关系 */
async function submitRelation() {
  if (!relationForm.sourceId || !relationForm.targetId || !relationForm.type) {
    ElMessage.warning('请填写完整信息')
    return
  }
  if (!selectedOntology.value) return
  const oid = selectedOntology.value.id
  submitting.value = true
  try {
    await postForm(`/ontology/${oid}/relation`, {
      source_id: relationForm.sourceId,
      target_id: relationForm.targetId,
      relation_type: relationForm.type,
      weight: relationForm.weight
    })
    ElMessage.success('关系添加成功')
    showRelationDialog.value = false
    await loadOntologyDetail(oid)
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '操作失败')
  } finally {
    submitting.value = false
  }
}

/** 删除关系 */
async function deleteRelation(relation: any) {
  if (!selectedOntology.value) return
  try {
    await ElMessageBox.confirm('确定删除该关系吗？', '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  try {
    await service.delete(`/ontology/${selectedOntology.value.id}/relation/${relation.id}`)
    ElMessage.success('删除成功')
    await loadOntologyDetail(selectedOntology.value.id)
    await loadOntologies()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 图谱渲染 ──
/** 刷新图谱 */
function refreshGraph() {
  if (selectedOntology.value) {
    loadOntologyDetail(selectedOntology.value.id)
  } else {
    renderGraph({ nodes: [], links: [] })
  }
}

/**
 * 渲染知识图谱（节点用 id 标识，连线用 source_id/target_id）
 * @param data 图谱数据 {nodes, links}
 */
function renderGraph(data: { nodes: any[]; links: any[] }) {
  if (!graphRef.value) return
  if (!chartInstance) {
    chartInstance = echarts.init(graphRef.value)
  }

  // ECharts graph 的 data[].category 必须是 categories 数组的「数字索引」而非类型名字符串，
  // 否则节点无法归入图例分类、着色异常甚至不渲染。这里建立 类型名 -> 索引 映射。
  const catIndex: Record<string, number> = {}
  const categories = entityTypeOptions.value.map((t: any, i: number) => {
    catIndex[t.name] = i
    return { name: t.name }
  })

  // ECharts graph 的 links.source/target 默认按 name 匹配节点，建立 id->name 映射
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
      layout: 'force',
      roam: true,
      label: { show: true, position: 'bottom', fontSize: 12 },
      edgeSymbol: ['circle', 'arrow'],
      edgeSymbolSize: [4, 10],
      data: nodes,
      links: links,
      categories: categories,
      lineStyle: { opacity: 0.6, width: 2, curveness: 0 },
      force: { repulsion: 200, edgeLength: 150 }
    }]
  }

  chartInstance.setOption(option, true)
}

// ── 生命周期 ──
function handleResize() {
  chartInstance?.resize()
}

onMounted(async () => {
  await loadOntologies()
  // 默认选中第一个本体展示
  if (ontologies.value.length) {
    await nextTick()
    selectOntology(ontologies.value[0])
  } else {
    await nextTick()
    renderGraph({ nodes: [], links: [] })
  }
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  chartInstance?.dispose()
  chartInstance = null
})
</script>

<style scoped>
.ontology-container {
  height: 100%;
  padding: 1rem;
  overflow-x: auto;
  overflow-y: hidden;
}

.page-layout {
  display: flex;
  gap: 1rem;
  height: 100%;
}

.left-panel {
  width: 280px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
}

.main-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.right-panel {
  width: 280px;
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

.graph-subtitle {
  font-weight: 400;
  color: #909399;
  font-size: 0.85rem;
}

.ontology-list {
  max-height: 360px;
  overflow-y: auto;
}

.ontology-item {
  padding: 1rem;
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  margin-bottom: 0.5rem;
  cursor: pointer;
  transition: all 0.3s;
}

.ontology-item:hover {
  border-color: #409eff;
  background: #f5f7fa;
}

.ontology-item.active {
  border-color: #409eff;
  background: rgba(64, 158, 255, 0.1);
}

.ontology-info h4 {
  margin: 0 0 0.5rem 0;
  color: #303133;
  font-size: 0.95rem;
}

.ontology-info p {
  margin: 0;
  color: #909399;
  font-size: 0.8rem;
}

.ontology-stats {
  display: flex;
  gap: 1rem;
  margin-top: 0.5rem;
  font-size: 0.8rem;
  color: #606266;
}

.ontology-actions {
  margin-top: 0.5rem;
  display: flex;
  gap: 0.5rem;
}

.entity-list {
  max-height: 300px;
  overflow-y: auto;
}

.entity-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.entity-item:hover {
  background: #f5f7fa;
}

.entity-item.active {
  background: rgba(64, 158, 255, 0.1);
}

.relation-list {
  max-height: 240px;
  overflow-y: auto;
}

.relation-item {
  padding: 0.6rem 0.2rem;
  border-bottom: 1px solid #e4e7ed;
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
  color: #409eff;
  font-weight: 500;
}

.relation-type {
  color: #67c23a;
}

.graph-card {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.graph-container {
  flex: 1;
  min-width: 500px;
  min-height: 500px;
  height: 100%;
}

.graph-actions {
  display: flex;
  gap: 0.5rem;
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
  color: #606266;
  font-weight: 500;
}

.property-value {
  color: #303133;
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
  border-bottom: 1px solid #e4e7ed;
}

.stat-item:last-child {
  border-bottom: none;
}

.stat-label {
  color: #606266;
}

.stat-value {
  font-weight: 600;
  color: #409eff;
  font-size: 1.1rem;
}

.type-editor {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.type-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}
</style>
