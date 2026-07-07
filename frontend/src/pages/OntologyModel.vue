<template>
  <Layout>
    <div class="ontology-container">
      <div class="page-layout">
        <div class="left-panel">
          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>本体模型</span>
                <el-button type="primary" size="small" @click="showCreateOntology = true">新建本体</el-button>
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
                  <span>实体: {{ ontology.entities }}</span>
                  <span>关系: {{ ontology.relations }}</span>
                </div>
              </div>
            </div>
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>实体列表</span>
                <el-button size="small" @click="showAddEntity = true">添加实体</el-button>
              </div>
            </template>
            <div class="entity-list">
              <el-input v-model="entitySearch" placeholder="搜索实体..." size="small" style="margin-bottom: 1rem" />
              <div
                v-for="entity in filteredEntities"
                :key="entity.id"
                class="entity-item"
                @click="selectEntity(entity)"
              >
                <el-icon><Box /></el-icon>
                <span>{{ entity.name }}</span>
                <el-tag size="small">{{ entity.type }}</el-tag>
              </div>
            </div>
          </el-card>

          <el-card class="panel-card">
            <template #header>
              <div class="panel-header">
                <span>关系列表</span>
                <el-button size="small" @click="showAddRelation = true">添加关系</el-button>
              </div>
            </template>
            <div class="relation-list">
              <div
                v-for="relation in relations"
                :key="relation.id"
                class="relation-item"
              >
                <div class="relation-content">
                  <span class="relation-source">{{ relation.source }}</span>
                  <el-icon><Right /></el-icon>
                  <span class="relation-type">{{ relation.type }}</span>
                  <el-icon><Right /></el-icon>
                  <span class="relation-target">{{ relation.target }}</span>
                </div>
              </div>
            </div>
          </el-card>
        </div>

        <div class="main-content">
          <el-card class="graph-card">
            <template #header>
              <div class="panel-header">
                <span>知识图谱</span>
                <div class="graph-actions">
                  <el-button size="small" @click="refreshGraph">刷新</el-button>
                  <el-button size="small" @click="exportGraph">导出</el-button>
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
                </el-descriptions-item>
              </el-descriptions>
              <div class="detail-actions">
                <el-button size="small" @click="editEntity(selectedEntity)">编辑</el-button>
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
                <span class="stat-label">实体总数</span>
                <span class="stat-value">{{ entities.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">关系总数</span>
                <span class="stat-value">{{ relations.length }}</span>
              </div>
              <div class="stat-item">
                <span class="stat-label">本体模型数</span>
                <span class="stat-value">{{ ontologies.length }}</span>
              </div>
            </div>
          </el-card>
        </div>
      </div>

      <el-dialog v-model="showCreateOntology" title="新建本体模型" width="500px">
        <el-form :model="ontologyForm" label-width="100px">
          <el-form-item label="本体名称">
            <el-input v-model="ontologyForm.name" placeholder="请输入本体名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="ontologyForm.description" type="textarea" :rows="3" placeholder="请输入描述" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showCreateOntology = false">取消</el-button>
          <el-button type="primary" @click="createOntology">创建</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showAddEntity" title="添加实体" width="500px">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名称">
            <el-input v-model="entityForm.name" placeholder="请输入实体名称" />
          </el-form-item>
          <el-form-item label="实体类型">
            <el-select v-model="entityForm.type" placeholder="请选择类型" style="width: 100%">
              <el-option label="概念" value="概念" />
              <el-option label="实体" value="实体" />
              <el-option label="属性" value="属性" />
              <el-option label="事件" value="事件" />
            </el-select>
          </el-form-item>
          <el-form-item label="属性">
            <el-input v-model="entityForm.properties" type="textarea" :rows="3" placeholder="格式：key:value,多个用逗号分隔" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddEntity = false">取消</el-button>
          <el-button type="primary" @click="addEntity">添加</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showAddRelation" title="添加关系" width="500px">
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
              <el-option label="包含" value="包含" />
              <el-option label="关联" value="关联" />
              <el-option label="继承" value="继承" />
              <el-option label="实现" value="实现" />
            </el-select>
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="relationForm.weight" :min="0" :max="1" :step="0.1" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddRelation = false">取消</el-button>
          <el-button type="primary" @click="addRelation">添加</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { Box, Right } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import Layout from '@/components/Layout.vue'

const graphRef = ref<HTMLElement | null>(null)

const showCreateOntology = ref(false)
const showAddEntity = ref(false)
const showAddRelation = ref(false)

const selectedOntology = ref<any>(null)
const selectedEntity = ref<any>(null)

const entitySearch = ref('')

const ontologies = ref([
  { id: '1', name: '作战评估本体', description: '作战效能评估相关的本体模型', entities: 128, relations: 256 },
  { id: '2', name: '武器系统本体', description: '武器系统分类和属性', entities: 89, relations: 145 },
  { id: '3', name: '战术动作本体', description: '战术动作和策略', entities: 67, relations: 98 }
])

const entities = ref<{ id: string; name: string; type: string; properties: Record<string, string> }[]>([
  { id: '1', name: '作战效能', type: '概念', properties: { 定义: '综合评估指标', 重要性: '高' } },
  { id: '2', name: '打击能力', type: '概念', properties: { 定义: '武器打击效果', 权重: '0.4' } },
  { id: '3', name: '生存能力', type: '概念', properties: { 定义: '存活概率', 权重: '0.3' } },
  { id: '4', name: '保障能力', type: '概念', properties: { 定义: '后勤保障水平', 权重: '0.3' } },
  { id: '5', name: '命中率', type: '属性', properties: { 公式: '命中/射击*100%', 单位: '%' } },
  { id: '6', name: '摧毁率', type: '属性', properties: { 公式: '摧毁/命中*100%', 单位: '%' } }
])

const relations = ref([
  { id: '1', source: '作战效能', type: '包含', target: '打击能力' },
  { id: '2', source: '作战效能', type: '包含', target: '生存能力' },
  { id: '3', source: '作战效能', type: '包含', target: '保障能力' },
  { id: '4', source: '打击能力', type: '影响', target: '命中率' },
  { id: '5', source: '打击能力', type: '影响', target: '摧毁率' }
])

const ontologyForm = ref({
  name: '',
  description: ''
})

const entityForm = ref({
  name: '',
  type: '',
  properties: ''
})

const relationForm = ref({
  sourceId: '',
  targetId: '',
  type: '',
  weight: 1.0
})

const filteredEntities = computed(() => {
  if (!entitySearch.value) return entities.value
  return entities.value.filter(e => 
    e.name.toLowerCase().includes(entitySearch.value.toLowerCase())
  )
})

const selectOntology = (ontology: any) => {
  selectedOntology.value = ontology
  ElMessage.info(`已选择本体模型：${ontology.name}`)
}

const selectEntity = (entity: any) => {
  selectedEntity.value = entity
}

const createOntology = () => {
  if (!ontologyForm.value.name) {
    ElMessage.warning('请填写本体名称')
    return
  }
  
  const newOntology = {
    id: Date.now().toString(),
    ...ontologyForm.value,
    entities: 0,
    relations: 0
  }
  
  ontologies.value.push(newOntology)
  showCreateOntology.value = false
  ontologyForm.value = { name: '', description: '' }
  ElMessage.success('本体模型创建成功')
}

const addEntity = () => {
  if (!entityForm.value.name || !entityForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  const properties: Record<string, string> = {}
  if (entityForm.value.properties) {
    entityForm.value.properties.split(',').forEach(prop => {
      const [key, value] = prop.split(':')
      if (key && value) {
        properties[key.trim()] = value.trim()
      }
    })
  }
  
  const newEntity = {
    id: Date.now().toString(),
    name: entityForm.value.name,
    type: entityForm.value.type,
    properties
  }
  
  entities.value.push(newEntity)
  showAddEntity.value = false
  entityForm.value = { name: '', type: '', properties: '' }
  ElMessage.success('实体添加成功')
  initGraph()
}

const editEntity = (entity: any) => {
  ElMessage.info(`编辑实体：${entity.name}`)
}

const deleteEntity = (entity: any) => {
  ElMessageBox.confirm(`确定删除实体"${entity.name}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    entities.value = entities.value.filter(e => e.id !== entity.id)
    relations.value = relations.value.filter(r => r.source !== entity.name && r.target !== entity.name)
    selectedEntity.value = null
    ElMessage.success('删除成功')
    initGraph()
  }).catch(() => {})
}

const addRelation = () => {
  if (!relationForm.value.sourceId || !relationForm.value.targetId || !relationForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  const sourceEntity = entities.value.find(e => e.id === relationForm.value.sourceId)
  const targetEntity = entities.value.find(e => e.id === relationForm.value.targetId)
  
  const newRelation = {
    id: Date.now().toString(),
    source: sourceEntity?.name || '',
    target: targetEntity?.name || '',
    type: relationForm.value.type
  }
  
  relations.value.push(newRelation)
  showAddRelation.value = false
  relationForm.value = { sourceId: '', targetId: '', type: '', weight: 1.0 }
  ElMessage.success('关系添加成功')
  initGraph()
}

const refreshGraph = () => {
  initGraph()
  ElMessage.success('图谱已刷新')
}

const exportGraph = () => {
  ElMessage.info('导出图谱功能开发中')
}

const initGraph = () => {
  if (!graphRef.value) return

  const chart = echarts.init(graphRef.value)

  const nodes = entities.value.map((entity) => ({
    name: entity.name,
    category: entity.type,
    draggable: true
  }))

  const links = relations.value.map(relation => ({
    source: relation.source,
    target: relation.target,
    lineStyle: {
      type: 'solid'
    }
  }))

  const option = {
    tooltip: {
      trigger: 'item',
      triggerOn: 'mousemove'
    },
    legend: [
      {
        data: ['概念', '实体', '属性', '事件']
      }
    ],
    series: [
      {
        type: 'graph',
        layout: 'force',
        symbolSize: 50,
        roam: true,
        label: {
          show: true,
          position: 'bottom',
          fontSize: 12
        },
        edgeSymbol: ['circle', 'arrow'],
        edgeSymbolSize: [4, 10],
        data: nodes,
        links: links,
        categories: [
          { name: '概念' },
          { name: '实体' },
          { name: '属性' },
          { name: '事件' }
        ],
        lineStyle: {
          opacity: 0.6,
          width: 2,
          curveness: 0
        },
        force: {
          repulsion: 100,
          edgeLength: 120
        }
      }
    ]
  }

  chart.setOption(option)
}

onMounted(() => {
  nextTick(() => {
    initGraph()
  })
})
</script>

<style scoped>
.ontology-container {
  height: 100%;
  padding: 1rem;
  overflow: hidden;
}

.page-layout {
  display: flex;
  gap: 1rem;
  height: 100%;
}

.left-panel {
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.right-panel {
  width: 320px;
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

.ontology-list {
  max-height: 300px;
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

.relation-list {
  max-height: 200px;
  overflow-y: auto;
}

.relation-item {
  padding: 0.75rem;
  border-bottom: 1px solid #e4e7ed;
}

.relation-content {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.9rem;
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
</style>
