<template>
  <Layout>
    <div class="manual-build">
      <!-- 顶部工具栏 -->
      <div class="build-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回</el-button>
          <h2>手动构建本体</h2>
          <el-tag v-if="ontology" type="primary" size="small">{{ ontology.name }}</el-tag>
          <el-tag v-if="templateMode" type="warning" size="small">基于本体模型：{{ templateName }}</el-tag>
          <el-tag v-else type="info" size="small">空白构建</el-tag>
        </div>
        <div class="header-actions">
          <el-button @click="refreshAll" :icon="Refresh">刷新</el-button>
          <el-button @click="goDetail" :icon="View">查看图谱</el-button>
        </div>
      </div>

      <!-- 步骤条 -->
      <el-steps :active="currentStep" align-center class="build-steps">
        <el-step title="Phase A：实体类型定义" description="实体类型树 + 属性骨架 + 类型间关系" />
        <el-step title="Phase B：填实例" description="实体 + 属性值 + 关系" />
      </el-steps>

      <!-- Phase A：实体类型定义 -->
      <div v-if="currentStep === 0" class="phase-panel" v-loading="loading">
        <!-- 本体模型载入入口（仅空白模式显示） -->
        <el-card v-if="!templateMode" class="section-card">
          <template #header>
            <div class="panel-header">
              <span>从本体模型载入（可选）</span>
            </div>
          </template>
          <div class="template-loader">
            <el-select
              v-model="selectedTemplateId"
              placeholder="选择本体模型一键预填实体类型 + 属性骨架"
              clearable
              style="width: 360px"
            >
              <el-option
                v-for="tpl in templates"
                :key="tpl.id"
                :label="`${tpl.name}（${tpl.concepts_count} 类型）`"
                :value="tpl.id"
              />
            </el-select>
            <el-button type="primary" :disabled="!selectedTemplateId" :loading="prefilling" @click="applyTemplate">
              载入本体模型
            </el-button>
          </div>
        </el-card>

        <!-- A1 · 添加实体类型 -->
        <el-card class="section-card">
          <template #header>
            <div class="panel-header">
              <div class="panel-title clickable" @click="openEntityTypeDialog()">
                <el-icon :size="16"><Plus /></el-icon>
                <span>A1 · 添加实体类型</span>
                <span class="count-badge">{{ entityTypes.length }}</span>
              </div>
            </div>
          </template>
          <el-empty
            v-if="!entityTypes.length"
            description="暂无实体类型，请添加顶层类型（如：公司、人物、城市）"
            :image-size="80"
          />
          <div v-else class="type-tree-wrap">
            <el-tree
              :data="entityTypeTree"
              node-key="id"
              default-expand-all
              :expand-on-click-node="false"
              :props="{ label: 'name', children: 'children' }"
            >
              <template #default="{ data }">
                <div class="tree-node">
                  <div class="tree-node-left">
                    <span class="type-dot" :style="{ background: data.color || '#5470c6' }"></span>
                    <span class="tree-node-name">{{ data.name }}</span>
                    <el-tag v-if="data.parent_entity_type_name" size="small" type="info">
                      父：{{ data.parent_entity_type_name }}
                    </el-tag>
                    <el-tag v-if="data.parent_entity_type_id && !data.parent_entity_type_name" size="small" type="info">
                      已挂父类型
                    </el-tag>
                    <el-tag
                      v-if="data.property_schema && data.property_schema.length"
                      size="small"
                      :type="'success'"
                    >
                      {{ data.property_schema.length }} 属性
                    </el-tag>
                    <el-text v-else type="info" size="small">无属性骨架</el-text>
                  </div>
                  <div class="tree-node-actions">
                    <el-button size="small" link @click.stop="openEntityTypeDialog(undefined, data.id)">添加子类型</el-button>
                    <el-button size="small" link @click.stop="openEntityTypeDialog(data)">编辑</el-button>
                    <el-button size="small" link type="danger" @click.stop="removeEntityType(data)">删除</el-button>
                  </div>
                </div>
              </template>
            </el-tree>
            <p class="form-hint" style="margin-top: 0.5rem;">
              提示：子类型自动继承父类型的属性骨架（运行时并集计算），无需重复定义。
            </p>
          </div>
        </el-card>

        <!-- A2 · 添加类型间关系 -->
        <el-card class="section-card">
          <template #header>
            <div class="panel-header">
              <div class="panel-title clickable" @click="openEntityTypeRelationDialog">
                <el-icon :size="16"><Plus /></el-icon>
                <span>A2 · 添加类型间关系</span>
                <span class="count-badge">{{ entityTypeRelations.length }}</span>
              </div>
            </div>
          </template>

          <!-- 关系类型快捷管理（仍存储于本体 relation_types 字段） -->
          <div class="relation-types-bar">
            <span class="bar-label">关系类型：</span>
            <el-tag
              v-for="(rt, idx) in metaForm.relationTypes"
              :key="idx"
              size="small"
              closable
              @close="removeRelationType(idx)"
              class="rt-chip"
            >
              {{ rt.name }}
            </el-tag>
            <el-input
              v-model="newRelationType"
              size="small"
              style="width: 140px"
              placeholder="新关系类型名"
              @keyup.enter="addRelationType"
            />
            <el-button size="small" @click="addRelationType">添加</el-button>
          </div>

          <el-empty
            v-if="!entityTypeRelations.length"
            description="暂无类型间关系，可在两个实体类型间建立关系（如：公司 位于 城市）"
            :image-size="80"
          />
          <div v-else class="etype-relation-list">
            <div v-for="r in entityTypeRelations" :key="r.id" class="etype-relation-row">
              <span class="rel-name" :style="{ color: entityTypeColorById(r.source_entity_type_id) }">
                {{ entityTypeMap[r.source_entity_type_id] || '已删除' }}
              </span>
              <span class="rel-type">{{ r.relation_type }}</span>
              <span class="rel-arrow">→</span>
              <span class="rel-name" :style="{ color: entityTypeColorById(r.target_entity_type_id) }">
                {{ entityTypeMap[r.target_entity_type_id] || '已删除' }}
              </span>
              <el-text v-if="r.description" type="info" size="small" class="rel-desc">（{{ r.description }}）</el-text>
              <el-button size="small" link type="danger" @click="removeEntityTypeRelation(r)">删除</el-button>
            </div>
          </div>
        </el-card>

        <!-- 步骤导航 -->
        <div class="step-nav">
          <div class="step-nav-left">
            <el-button @click="goBack">取消</el-button>
            <el-button :icon="Files" :loading="submitting" @click="saveAsTemplate">另存为本体模型</el-button>
          </div>
          <el-button type="primary" @click="goPhaseB">
            下一步：填实例
            <el-icon class="el-icon--right"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </div>

      <!-- Phase B：填实例 -->
      <div v-if="currentStep === 1" class="phase-panel" v-loading="loading">
        <!-- B1 · 添加实体 -->
        <el-card class="section-card">
          <template #header>
            <div class="panel-header">
              <div class="panel-title clickable" @click="openEntityDialog()">
                <el-icon :size="16"><Plus /></el-icon>
                <span>B1 · 添加实体</span>
                <span class="count-badge">{{ entities.length }}</span>
              </div>
            </div>
          </template>
          <el-empty v-if="!entities.length" description="暂无实体，请添加具体实例（如：A公司、张三、上海）" :image-size="80" />
          <div v-else class="entity-grid">
            <div v-for="e in entities" :key="e.id" class="entity-card">
              <div class="entity-card-header">
                <span class="entity-dot" :style="{ background: entityTypeColorById(e.instance_of) }"></span>
                <span class="entity-card-name">{{ e.name }}</span>
                <el-tag size="small" type="info">{{ entityTypeMap[e.instance_of] || '未分类' }}</el-tag>
                <span class="entity-card-actions">
                  <el-button size="small" link @click="openEntityDialog(e)">编辑</el-button>
                  <el-button size="small" link type="danger" @click="removeEntity(e)">删除</el-button>
                </span>
              </div>
              <div v-if="e.properties && e.properties.length" class="entity-props">
                <div v-for="p in e.properties" :key="p.id" class="prop-row">
                  <span class="prop-name">{{ p.name }}</span>
                  <span class="prop-value">{{ p.value }}<template v-if="p.unit"> {{ p.unit }}</template></span>
                </div>
              </div>
              <el-text v-else type="info" size="small">无属性</el-text>
            </div>
          </div>
        </el-card>

        <!-- B2 · 添加实体间关系 -->
        <el-card class="section-card">
          <template #header>
            <div class="panel-header">
              <div class="panel-title clickable" @click="openRelationDialog">
                <el-icon :size="16"><Plus /></el-icon>
                <span>B2 · 添加实体间关系</span>
                <span class="count-badge">{{ relations.length }}</span>
              </div>
            </div>
          </template>
          <el-empty v-if="!relations.length" description="暂无关系" :image-size="80" />
          <div v-else class="relation-list">
            <div v-for="r in relations" :key="r.id" class="relation-row">
              <span class="rel-name" :style="{ color: entityTypeColorById(entityInstanceTypeMap[r.source_id]) }">{{ r.source_name }}</span>
              <span class="rel-type">{{ r.relation_type }}</span>
              <span class="rel-arrow">→</span>
              <span class="rel-name" :style="{ color: entityTypeColorById(entityInstanceTypeMap[r.target_id]) }">{{ r.target_name }}</span>
              <el-button size="small" link type="danger" @click="removeRelation(r)">删除</el-button>
            </div>
          </div>
        </el-card>

        <!-- 步骤导航 -->
        <div class="step-nav">
          <el-button @click="currentStep = 0">
            <el-icon><ArrowLeft /></el-icon>
            上一步
          </el-button>
          <el-button type="primary" @click="finishBuild">完成构建</el-button>
        </div>
      </div>

      <!-- 实体类型编辑对话框 -->
      <el-dialog
        v-model="showEntityTypeDialog"
        :title="entityTypeForm.id ? '编辑实体类型' : '添加实体类型'"
        width="760px"
        top="5vh"
      >
        <el-form :model="entityTypeForm" label-width="100px">
          <el-form-item label="类型名" required>
            <el-input v-model="entityTypeForm.name" placeholder="如：公司、人物、城市（实体类型）" />
          </el-form-item>
          <el-form-item label="父类型">
            <el-select
              v-model="entityTypeForm.parent_entity_type_id"
              :placeholder="parentLocked ? '子类型继承父类型属性骨架' : '选择父类型（留空为顶层类型）'"
              :disabled="parentLocked"
              clearable
              style="width: 100%"
            >
              <el-option
                v-for="t in parentOptions"
                :key="t.id"
                :label="parentOptionLabel(t)"
                :value="t.id"
              />
            </el-select>
            <span class="form-hint">
              {{ parentLocked
                ? '继承父类型属性骨架，可另外添加属性；如需调整父类型请编辑该类型'
                : '子类型自动继承父类型属性骨架；不可选择自身或后代作为父类型（防环）' }}
            </span>
          </el-form-item>
          <el-form-item label="颜色">
            <el-color-picker v-model="entityTypeForm.color" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="entityTypeForm.description" type="textarea" :rows="2" placeholder="该实体类型的简要释义" />
          </el-form-item>

          <!-- 继承的属性骨架（只读展示） -->
          <el-divider v-if="inheritedProperties.length">继承自父类型的属性（只读）</el-divider>
          <p v-if="inheritedProperties.length" class="form-hint" style="margin: -0.5rem 0 0.5rem 0.875rem;">
            以下属性继承自父类型，自动生效，无需重复定义；可在下方为本类型另加属性。
          </p>
          <div v-if="inheritedProperties.length" class="inherited-schema">
            <el-tag
              v-for="(p, i) in inheritedProperties"
              :key="i"
              size="small"
              :type="p.category === 'metric' ? 'warning' : 'info'"
              class="schema-chip"
            >
              {{ p.name }}<template v-if="p.unit">（{{ p.unit }}）</template>
            </el-tag>
          </div>

          <el-divider>属性骨架（property_schema）</el-divider>
          <p class="form-hint" style="margin: -0.5rem 0 0.75rem 0.875rem;">
            定义该类型自身应具备的属性结构，Phase B 添加实体时将按此骨架（含继承）生成属性行供赋值。
          </p>
          <div class="schema-editor">
            <div v-for="(p, idx) in entityTypeForm.property_schema" :key="idx" class="schema-row">
              <el-input v-model="p.name" placeholder="属性名" size="small" style="width: 140px" />
              <el-select v-model="p.category" placeholder="分类" size="small" style="width: 110px">
                <el-option label="描述型" value="descriptive" />
                <el-option label="指标型" value="metric" />
              </el-select>
              <el-select v-model="p.data_type" placeholder="数据类型" size="small" style="width: 110px">
                <el-option label="string" value="string" />
                <el-option label="number" value="number" />
                <el-option label="date" value="date" />
                <el-option label="enum" value="enum" />
              </el-select>
              <el-input v-model="p.unit" placeholder="单位（如 %、万元）" size="small" style="width: 120px" />
              <el-checkbox v-model="p.required">必填</el-checkbox>
              <el-button size="small" link type="danger" @click="entityTypeForm.property_schema.splice(idx, 1)">删除</el-button>
              <el-input v-model="p.description" placeholder="属性说明" size="small" style="width: 100%; margin-top: 4px" />
            </div>
            <el-button size="small" @click="addSchemaRow">+ 添加属性</el-button>
          </div>
        </el-form>
        <template #footer>
          <el-button @click="showEntityTypeDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEntityType">保存</el-button>
        </template>
      </el-dialog>

      <!-- 类型间关系编辑对话框 -->
      <el-dialog v-model="showEtypeRelationDialog" title="添加类型间关系" width="560px">
        <el-form :model="etypeRelationForm" label-width="100px">
          <el-form-item label="源类型" required>
            <el-select
              v-model="etypeRelationForm.source_entity_type_id"
              placeholder="选择源实体类型"
              style="width: 100%"
              filterable
            >
              <el-option
                v-for="t in entityTypes"
                :key="t.id"
                :label="t.name + (t.parent_entity_type_name ? '（父：' + t.parent_entity_type_name + '）' : '')"
                :value="t.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型" required>
            <el-select
              v-model="etypeRelationForm.relation_type"
              placeholder="选择或输入关系类型"
              style="width: 100%"
              filterable
              allow-create
              default-first-option
            >
              <el-option v-for="rt in metaForm.relationTypes" :key="rt.name" :label="rt.name" :value="rt.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标类型" required>
            <el-select
              v-model="etypeRelationForm.target_entity_type_id"
              placeholder="选择目标实体类型"
              style="width: 100%"
              filterable
            >
              <el-option
                v-for="t in entityTypes"
                :key="t.id"
                :label="t.name + (t.parent_entity_type_name ? '（父：' + t.parent_entity_type_name + '）' : '')"
                :value="t.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="etypeRelationForm.description" type="textarea" :rows="2" placeholder="该类型关系的释义（可选）" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showEtypeRelationDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEntityTypeRelation">添加</el-button>
        </template>
      </el-dialog>

      <!-- 实体编辑对话框 -->
      <el-dialog v-model="showEntityDialog" :title="entityForm.id ? '编辑实体' : '添加实体'" width="780px" top="5vh">
        <el-form :model="entityForm" label-width="100px">
          <el-form-item label="实体名" required>
            <el-input v-model="entityForm.name" placeholder="如：A公司、张三、上海（具体实例）" />
          </el-form-item>
          <el-form-item label="归属类型" required>
            <el-select
              v-model="entityForm.instance_of"
              placeholder="选择实体类型（EntityType）"
              style="width: 100%"
              filterable
              @change="onEntityTypeChange"
            >
              <el-option
                v-for="t in entityTypes"
                :key="t.id"
                :label="t.name + (t.parent_entity_type_name ? '（父：' + t.parent_entity_type_name + '）' : '')"
                :value="t.id"
              />
            </el-select>
          </el-form-item>
          <el-divider>属性赋值</el-divider>
          <p class="form-hint" style="margin: -0.5rem 0 0.75rem 0.875rem;">
            选中类型后自动按其属性骨架（含继承）生成属性行，请填入具体值；也可手动添加额外属性。
          </p>
          <div class="props-editor">
            <div v-for="(p, idx) in entityForm.properties" :key="idx" class="prop-edit-row">
              <el-input v-model="p.name" placeholder="属性名" size="small" style="width: 130px" />
              <el-input v-model="p.value" placeholder="属性值" size="small" style="width: 160px" />
              <el-select v-model="p.category" size="small" style="width: 100px">
                <el-option label="描述型" value="descriptive" />
                <el-option label="指标型" value="metric" />
              </el-select>
              <el-input v-model="p.unit" placeholder="单位" size="small" style="width: 80px" />
              <el-button size="small" link type="danger" @click="entityForm.properties.splice(idx, 1)">删除</el-button>
            </div>
            <el-button size="small" @click="addPropRow">+ 添加属性</el-button>
          </div>
        </el-form>
        <template #footer>
          <el-button @click="showEntityDialog = false">取消</el-button>
          <el-button type="primary" :loading="submitting" @click="submitEntity">保存</el-button>
        </template>
      </el-dialog>

      <!-- 关系编辑对话框 -->
      <el-dialog v-model="showRelationDialog" title="添加关系" width="560px">
        <el-form :model="relationForm" label-width="100px">
          <el-form-item label="源实体" required>
            <el-select v-model="relationForm.source_id" placeholder="选择源实体" style="width: 100%" filterable>
              <el-option v-for="e in entities" :key="e.id" :label="e.name" :value="e.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型" required>
            <el-select
              v-model="relationForm.relation_type"
              placeholder="选择或输入关系类型"
              style="width: 100%"
              filterable
              allow-create
              default-first-option
            >
              <el-option v-for="t in metaForm.relationTypes" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标实体" required>
            <el-select v-model="relationForm.target_id" placeholder="选择目标实体" style="width: 100%" filterable>
              <el-option v-for="e in entities" :key="e.id" :label="e.name" :value="e.id" />
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
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, ArrowRight, Refresh, Plus, View, Files
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import {
  getOntology,
  updateOntology,
  getEntityTypeList,
  createEntityType,
  updateEntityType,
  deleteEntityType,
  getEntityTypeRelationList,
  createEntityTypeRelation,
  deleteEntityTypeRelation,
  getEntityList,
  createEntity,
  updateEntity,
  deleteEntity,
  getRelationList,
  createRelation,
  deleteRelation
} from '@/services/ontology'
import {
  getMetaModelList,
  getMetaModel,
  saveMetaModelFromOntology
} from '@/services/ontologyMetaModel'
import { getBuildJobList, completeBuildJob } from '@/services/ontologyBuild'

const route = useRoute()
const router = useRouter()
const ontologyId = route.params.id as string
const queryTemplateId = (route.query.template as string) || ''

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)
const savingMeta = ref(false)
const prefilling = ref(false)
const currentStep = ref(0)

const ontology = ref<any>(null)
const entityTypes = ref<any[]>([])           // v3：实体类型列表（含 parent_entity_type_id 层级 + property_schema）
const entityTypeRelations = ref<any[]>([])   // v3：类型间关系
const entities = ref<any[]>([])
const relations = ref<any[]>([])

// 本体模型表单（v3：仅保留 name/description/relationTypes，entityTypes 改由 EntityType CRUD 管理）
const metaForm = ref({
  name: '',
  description: '',
  relationTypes: [] as any[]
})
const newRelationType = ref('')

// 模板相关
const templateMode = ref(false)
const templateName = ref('')
const templates = ref<any[]>([])
const templateLoading = ref(false)
const selectedTemplateId = ref('')

// 当前本体对应的手动构建任务（用于「完成构建」时标记完成）
const manualJobId = ref('')

// 实体类型对话框
const showEntityTypeDialog = ref(false)
// 是否锁定父类型（通过「添加子类型」入口打开时为 true，防止误改父类型）
const parentLocked = ref(false)
const entityTypeForm = ref({
  id: '',
  name: '',
  description: '',
  color: '',
  parent_entity_type_id: '',
  parent_entity_type_name: '',
  property_schema: [] as any[]
})

// 类型间关系对话框
const showEtypeRelationDialog = ref(false)
const etypeRelationForm = ref({
  source_entity_type_id: '',
  target_entity_type_id: '',
  relation_type: '',
  description: ''
})

// 实体对话框
const showEntityDialog = ref(false)
const entityForm = ref({
  id: '',
  name: '',
  instance_of: '',
  properties: [] as any[]
})

// 关系对话框
const showRelationDialog = ref(false)
const relationForm = ref({
  source_id: '',
  target_id: '',
  relation_type: '',
  weight: 1.0
})

// ── 计算属性 ──
// 实体类型 id → name 映射
const entityTypeMap = computed(() => {
  const map: Record<string, string> = {}
  entityTypes.value.forEach(t => { map[t.id] = t.name })
  return map
})

// 实体实例 id → instance_of（EntityType id）映射，用于关系列表着色
const entityInstanceTypeMap = computed(() => {
  const map: Record<string, string> = {}
  entities.value.forEach(e => { map[e.id] = e.instance_of })
  return map
})

// 将扁平的 entityTypes 列表构建为树形结构（按 parent_entity_type_id 组织）
const entityTypeTree = computed(() => {
  const build = (parentId: string | null): any[] => {
    return entityTypes.value
      .filter(t => {
        const pid = t.parent_entity_type_id
        if (parentId === null) return !pid
        return pid === parentId
      })
      .map(t => ({
        ...t,
        children: build(t.id)
      }))
  }
  return build(null)
})

// 父类型可选项（排除自身及所有后代，防止成环）
const parentOptions = computed(() => {
  if (!entityTypeForm.value.id) return entityTypes.value
  const forbidden = new Set<string>([entityTypeForm.value.id, ...getDescendantIds(entityTypeForm.value.id)])
  return entityTypes.value.filter(t => !forbidden.has(t.id))
})

// 当前编辑类型从父链继承的属性骨架（只读展示）
const inheritedProperties = computed(() => {
  if (!entityTypeForm.value.parent_entity_type_id) return []
  return getEffectivePropertySchema(entityTypeForm.value.parent_entity_type_id, entityTypeForm.value.id)
})

// ── 工具方法 ──
// 收集某个类型的所有后代 id（递归）
const getDescendantIds = (id: string): string[] => {
  const result: string[] = []
  const collect = (parentId: string) => {
    entityTypes.value.forEach(t => {
      if (t.parent_entity_type_id === parentId) {
        result.push(t.id)
        collect(t.id)
      }
    })
  }
  collect(id)
  return result
}

// 计算某类型的有效属性骨架：自身 + 祖先链并集（祖先在前，自身在后）
// excludeId 用于避免在编辑场景下把自身属性重复计入
const getEffectivePropertySchema = (typeId: string, excludeId?: string): any[] => {
  const chain: any[] = []
  const visited = new Set<string>()
  let current = entityTypes.value.find(t => t.id === typeId)
  while (current && !visited.has(current.id)) {
    visited.add(current.id)
    chain.unshift(current)
    current = entityTypes.value.find(t => t.id === current?.parent_entity_type_id)
  }
  const result: any[] = []
  chain.forEach(t => {
    if (excludeId && t.id === excludeId) return
    if (Array.isArray(t.property_schema)) {
      result.push(...t.property_schema)
    }
  })
  return result
}

const parentOptionLabel = (t: any) => {
  return t.parent_entity_type_name
    ? `${t.name}（父：${t.parent_entity_type_name}）`
    : t.name
}

// 按 EntityType id 取颜色（实例卡片/关系着色用）
const entityTypeColorById = (typeId?: string) => {
  if (!typeId) return '#409eff'
  const found = entityTypes.value.find(t => t.id === typeId)
  return found?.color || '#409eff'
}

// ── 数据加载 ──
const loadOntology = async () => {
  try {
    const res: any = await getOntology(ontologyId)
    ontology.value = res.data
    metaForm.value = {
      name: res.data.name,
      description: res.data.description,
      relationTypes: JSON.parse(JSON.stringify(res.data.relation_types || []))
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载本体失败')
  }
}

const loadEntityTypes = async () => {
  try {
    const res: any = await getEntityTypeList(ontologyId)
    // 兼容 res.items / res.data 两种返回结构
    entityTypes.value = res.items || res.data || []
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载实体类型失败')
  }
}

const loadEntityTypeRelations = async () => {
  try {
    const res: any = await getEntityTypeRelationList(ontologyId)
    entityTypeRelations.value = res.items || res.data || []
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载类型间关系失败')
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

const loadTemplates = async () => {
  templateLoading.value = true
  try {
    const res: any = await getMetaModelList()
    templates.value = res.items || res.data || []
  } catch {
    // 静默失败，模板库非必需
  } finally {
    templateLoading.value = false
  }
}

// 查找当前本体对应的手动构建任务（用于完成时标记 completed）
const loadManualJob = async () => {
  try {
    const res: any = await getBuildJobList()
    const jobs = ((res as any).data || []) as any[]
    const job = jobs.find(j => j.build_type === 'manual' && j.ontology_id === ontologyId)
    if (job) manualJobId.value = job.id
  } catch {
    // 非必需：查不到则完成时不标记（仅影响任务列表展示）
  }
}

const refreshAll = async () => {
  loading.value = true
  try {
    await Promise.all([
      loadOntology(),
      loadEntityTypes(),
      loadEntityTypeRelations(),
      loadEntities(),
      loadRelations()
    ])
    ElMessage.success('数据已刷新')
  } finally {
    loading.value = false
  }
}

// ── 模板预填 ──
const applyTemplateById = async (tplId: string) => {
  prefilling.value = true
  try {
    const res: any = await getMetaModel(tplId)
    const tpl = res.data
    templateName.value = tpl.name
    templateMode.value = true

    // 1. 保存本体的 relation_types（v3 不再保存 entity_types，由 EntityType CRUD 管理）
    const fd = new FormData()
    fd.append('name', metaForm.value.name)
    fd.append('description', metaForm.value.description)
    fd.append('relation_types', JSON.stringify(tpl.relation_types || []))
    await updateOntology(ontologyId, fd)
    await loadOntology()

    // 2. 逐个创建实体类型（含属性骨架）
    let created = 0
    const nameToId: Record<string, string> = {}
    const entityTypes = tpl.entity_types || []
    // 第一遍：创建所有类型（暂不挂父层级）
    for (const et of entityTypes) {
      const cfd = new FormData()
      cfd.append('name', et.name)
      cfd.append('description', et.description || '')
      cfd.append('color', et.color || '')
      cfd.append('property_schema', JSON.stringify(et.property_schema || []))
      const createdRes: any = await createEntityType(ontologyId, cfd)
      const createdId = createdRes?.id || createdRes?.data?.id
      if (createdId) nameToId[et.name] = createdId
      created++
    }
    await loadEntityTypes()

    // 3. 第二遍：对标注 parent_entity_type_name（父类型名）的，补挂 parent_entity_type_id
    for (const et of entityTypes) {
      if (!et.parent_entity_type_name) continue
      const typeId = nameToId[et.name]
      const parentId = nameToId[et.parent_entity_type_name]
      if (!typeId || !parentId || typeId === parentId) continue
      const parentType = entityTypes.value.find(t => t.id === parentId)
      const ufd = new FormData()
      ufd.append('name', et.name)
      ufd.append('description', et.description || '')
      ufd.append('color', et.color || '')
      ufd.append('property_schema', JSON.stringify(et.property_schema || []))
      ufd.append('parent_entity_type_id', parentId)
      ufd.append('parent_entity_type_name', parentType?.name || et.parent_entity_type_name)
      await updateEntityType(ontologyId, typeId, ufd)
    }
    await loadEntityTypes()

    // 4. 载入类型间关系（按 name 映射到新建实体类型 ID 后创建）
    const etypeRelations = tpl.entity_type_relations || []
    for (const r of etypeRelations) {
      const sourceId = nameToId[r.source_entity_type_name]
      const targetId = nameToId[r.target_entity_type_name]
      if (!sourceId || !targetId) continue
      const rfd = new FormData()
      rfd.append('source_entity_type_id', sourceId)
      rfd.append('target_entity_type_id', targetId)
      rfd.append('relation_type', r.relation_type)
      rfd.append('description', r.description || '')
      await createEntityTypeRelation(ontologyId, rfd)
    }
    await loadEntityTypeRelations()

    ElMessage.success(`本体模型「${tpl.name}」已载入：${created} 个实体类型`)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '本体模型载入失败')
  } finally {
    prefilling.value = false
  }
}

const applyTemplate = () => {
  if (!selectedTemplateId.value) return
  applyTemplateById(selectedTemplateId.value)
}

// ── 关系类型快捷管理（持久化到本体 relation_types） ──
const addRelationType = async () => {
  const name = newRelationType.value.trim()
  if (!name) {
    ElMessage.warning('请输入关系类型名')
    return
  }
  if (metaForm.value.relationTypes.some(rt => rt.name === name)) {
    ElMessage.warning('该关系类型已存在')
    return
  }
  metaForm.value.relationTypes.push({ name, description: '' })
  newRelationType.value = ''
  await saveRelationTypes()
}

const removeRelationType = async (idx: number) => {
  metaForm.value.relationTypes.splice(idx, 1)
  await saveRelationTypes()
}

const saveRelationTypes = async () => {
  savingMeta.value = true
  try {
    const fd = new FormData()
    fd.append('name', metaForm.value.name)
    fd.append('description', metaForm.value.description)
    fd.append('relation_types', JSON.stringify(metaForm.value.relationTypes.filter(t => t.name)))
    await updateOntology(ontologyId, fd)
    ElMessage.success('关系类型已更新')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '保存关系类型失败')
  } finally {
    savingMeta.value = false
  }
}

// ── 实体类型操作 ──
// 打开实体类型弹框：entityType 为编辑对象；parentId 传入表示添加子类型（锁定父类型）
const openEntityTypeDialog = (entityType?: any, parentId?: string) => {
  if (entityType) {
    parentLocked.value = false
    entityTypeForm.value = {
      id: entityType.id,
      name: entityType.name,
      description: entityType.description || '',
      color: entityType.color || '',
      parent_entity_type_id: entityType.parent_entity_type_id || '',
      parent_entity_type_name: entityType.parent_entity_type_name || '',
      property_schema: JSON.parse(JSON.stringify(entityType.property_schema || []))
    }
  } else {
    parentLocked.value = !!parentId
    entityTypeForm.value = {
      id: '',
      name: '',
      description: '',
      color: '',
      parent_entity_type_id: parentId || '',
      parent_entity_type_name: '',
      property_schema: []
    }
    // 若指定了父类型，预填父类型名
    if (parentId) {
      const parent = entityTypes.value.find(t => t.id === parentId)
      entityTypeForm.value.parent_entity_type_name = parent?.name || ''
    }
  }
  showEntityTypeDialog.value = true
}

const addSchemaRow = () => {
  entityTypeForm.value.property_schema.push({
    name: '',
    category: 'descriptive',
    data_type: 'string',
    unit: '',
    required: false,
    description: ''
  })
}

const submitEntityType = async () => {
  if (!entityTypeForm.value.name.trim()) {
    ElMessage.warning('请填写类型名')
    return
  }
  // 校验父类型不能成环（parentOptions 已过滤，这里二次保险）
  if (entityTypeForm.value.id && entityTypeForm.value.parent_entity_type_id) {
    const forbidden = new Set<string>([entityTypeForm.value.id, ...getDescendantIds(entityTypeForm.value.id)])
    if (forbidden.has(entityTypeForm.value.parent_entity_type_id)) {
      ElMessage.warning('父类型不能选择自身或后代类型（会形成环）')
      return
    }
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', entityTypeForm.value.name.trim())
    fd.append('description', entityTypeForm.value.description)
    fd.append('color', entityTypeForm.value.color)
    fd.append('property_schema', JSON.stringify(entityTypeForm.value.property_schema.filter(p => p.name)))
    // 父类型 id：空串清除层级（v3 后端约定）
    fd.append('parent_entity_type_id', entityTypeForm.value.parent_entity_type_id || '')
    // 同步父类型名（便于列表展示，后端可能也会自动回填）
    const parent = entityTypes.value.find(t => t.id === entityTypeForm.value.parent_entity_type_id)
    fd.append('parent_entity_type_name', parent?.name || '')

    if (entityTypeForm.value.id) {
      await updateEntityType(ontologyId, entityTypeForm.value.id, fd)
      ElMessage.success('实体类型已更新')
    } else {
      await createEntityType(ontologyId, fd)
      ElMessage.success('实体类型已添加')
    }
    showEntityTypeDialog.value = false
    await loadEntityTypes()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '保存失败')
  } finally {
    submitting.value = false
  }
}

const removeEntityType = async (entityType: any) => {
  try {
    await ElMessageBox.confirm(
      `确定删除实体类型「${entityType.name}」吗？若有实体或子类型引用需先迁移。`,
      '提示',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  try {
    await deleteEntityType(ontologyId, entityType.id)
    ElMessage.success('实体类型已删除')
    await loadEntityTypes()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 类型间关系操作 ──
const openEntityTypeRelationDialog = () => {
  if (!entityTypes.value.length) {
    ElMessage.warning('请先添加实体类型')
    return
  }
  etypeRelationForm.value = {
    source_entity_type_id: '',
    target_entity_type_id: '',
    relation_type: '',
    description: ''
  }
  showEtypeRelationDialog.value = true
}

const submitEntityTypeRelation = async () => {
  if (
    !etypeRelationForm.value.source_entity_type_id ||
    !etypeRelationForm.value.target_entity_type_id ||
    !etypeRelationForm.value.relation_type.trim()
  ) {
    ElMessage.warning('请填写完整的类型间关系信息')
    return
  }
  if (etypeRelationForm.value.source_entity_type_id === etypeRelationForm.value.target_entity_type_id) {
    ElMessage.warning('源类型与目标类型不能相同')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('source_entity_type_id', etypeRelationForm.value.source_entity_type_id)
    fd.append('target_entity_type_id', etypeRelationForm.value.target_entity_type_id)
    fd.append('relation_type', etypeRelationForm.value.relation_type.trim())
    fd.append('description', etypeRelationForm.value.description)
    await createEntityTypeRelation(ontologyId, fd)
    ElMessage.success('类型间关系已添加')
    showEtypeRelationDialog.value = false
    await loadEntityTypeRelations()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '添加失败')
  } finally {
    submitting.value = false
  }
}

const removeEntityTypeRelation = async (relation: any) => {
  try {
    await ElMessageBox.confirm('确定删除该类型间关系吗？', '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  try {
    await deleteEntityTypeRelation(ontologyId, relation.id)
    ElMessage.success('类型间关系已删除')
    await loadEntityTypeRelations()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 实体操作 ──
const openEntityDialog = (entity?: any) => {
  if (entity) {
    entityForm.value = {
      id: entity.id,
      name: entity.name,
      instance_of: entity.instance_of || '',
      properties: (entity.properties || []).map((p: any) => ({
        name: p.name || '',
        value: p.value !== undefined && p.value !== null ? String(p.value) : '',
        category: p.category || 'descriptive',
        data_type: p.data_type || 'string',
        unit: p.unit || ''
      }))
    }
  } else {
    entityForm.value = {
      id: '',
      name: '',
      instance_of: '',
      properties: []
    }
  }
  showEntityDialog.value = true
}

// 选中实体类型时按其有效属性骨架（自身 + 继承）自动生成属性行
const onEntityTypeChange = (typeId: string) => {
  if (!typeId) return
  // 仅在 properties 为空时自动填充，避免覆盖已编辑的值
  if (entityForm.value.properties.length > 0) return
  const schema = getEffectivePropertySchema(typeId)
  if (!schema.length) return
  entityForm.value.properties = schema.map((ps: any) => ({
    name: ps.name || '',
    value: '',
    category: ps.category || 'descriptive',
    data_type: ps.data_type || 'string',
    unit: ps.unit || ''
  }))
}

const addPropRow = () => {
  entityForm.value.properties.push({
    name: '',
    value: '',
    category: 'descriptive',
    data_type: 'string',
    unit: ''
  })
}

const submitEntity = async () => {
  if (!entityForm.value.name.trim() || !entityForm.value.instance_of) {
    ElMessage.warning('请填写实体名并选择归属类型')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', entityForm.value.name.trim())
    fd.append('instance_of', entityForm.value.instance_of)
    fd.append('properties', JSON.stringify(entityForm.value.properties.filter(p => p.name)))
    if (entityForm.value.id) {
      await updateEntity(ontologyId, entityForm.value.id, fd)
      ElMessage.success('实体已更新')
    } else {
      await createEntity(ontologyId, fd)
      ElMessage.success('实体已添加')
    }
    showEntityDialog.value = false
    await loadEntities()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '保存失败')
  } finally {
    submitting.value = false
  }
}

const removeEntity = async (entity: any) => {
  try {
    await ElMessageBox.confirm(
      `确定删除实体「${entity.name}」吗？关联关系将一并删除。`,
      '提示',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  try {
    await deleteEntity(ontologyId, entity.id)
    ElMessage.success('实体已删除')
    await Promise.all([loadEntities(), loadRelations()])
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 关系操作 ──
const openRelationDialog = () => {
  if (!entities.value.length) {
    ElMessage.warning('请先添加实体再建立关系')
    return
  }
  relationForm.value = { source_id: '', target_id: '', relation_type: '', weight: 1.0 }
  showRelationDialog.value = true
}

const submitRelation = async () => {
  if (!relationForm.value.source_id || !relationForm.value.target_id || !relationForm.value.relation_type) {
    ElMessage.warning('请填写完整关系信息')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('source_id', relationForm.value.source_id)
    fd.append('target_id', relationForm.value.target_id)
    fd.append('relation_type', relationForm.value.relation_type)
    fd.append('weight', String(relationForm.value.weight))
    await createRelation(ontologyId, fd)
    ElMessage.success('关系已添加')
    showRelationDialog.value = false
    await loadRelations()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '添加失败')
  } finally {
    submitting.value = false
  }
}

const removeRelation = async (relation: any) => {
  try {
    await ElMessageBox.confirm('确定删除该关系吗？', '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
  } catch { return }
  try {
    await deleteRelation(ontologyId, relation.id)
    ElMessage.success('关系已删除')
    await loadRelations()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '删除失败')
  }
}

// ── 流程导航 ──
const goPhaseB = () => {
  if (!entityTypes.value.length) {
    ElMessage.warning('请先在 Phase A 添加至少一个实体类型，再进入 Phase B 填实例')
    return
  }
  currentStep.value = 1
}

const finishBuild = async () => {
  // 标记手动构建任务完成（从「进行中的构建任务」列表移除）
  if (manualJobId.value) {
    try {
      await completeBuildJob(manualJobId.value)
    } catch (e) {
      console.warn('标记构建任务完成失败:', e)
    }
  }
  ElMessage.success('本体构建完成，可在详情页查看图谱')
  router.push(`/ontology/${ontologyId}`)
}

const goDetail = () => {
  router.push(`/ontology/${ontologyId}`)
}

const goBack = () => {
  router.push('/ontology')
}

const saveAsTemplate = async () => {
  let name = ''
  try {
    const result = await ElMessageBox.prompt(
      '将当前本体的 schema 层（实体类型 + 属性骨架 + 类型间关系）抽取为本体模型，实例数据不会进入本体模型。',
      '另存为本体模型',
      {
        confirmButtonText: '保存',
        cancelButtonText: '取消',
        inputPlaceholder: '请输入本体模型名称',
        inputValue: `${ontology.value?.name || ''} 本体模型`
      }
    )
    name = result.value
  } catch { return }
  if (!name?.trim()) {
    ElMessage.warning('请输入本体模型名称')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', name.trim())
    fd.append('description', ontology.value?.description || '')
    await saveMetaModelFromOntology(ontologyId, fd)
    ElMessage.success('本体模型已保存，可在文档构建或新建本体时复用')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '保存本体模型失败')
  } finally {
    submitting.value = false
  }
}

// ── 生命周期 ──
onMounted(async () => {
  loading.value = true
  try {
    await loadOntology()
    await Promise.all([
      loadEntityTypes(),
      loadEntityTypeRelations(),
      loadEntities(),
      loadRelations(),
      loadTemplates(),
      loadManualJob()
    ])
    // 若带 template 查询参数，自动触发模板预填
    if (queryTemplateId) {
      await applyTemplateById(queryTemplateId)
    }
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.manual-build {
  height: 100%;
  padding: 1.5rem;
  overflow-y: auto;
}

.build-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.25rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.header-left h2 {
  margin: 0;
  font-size: 1.4rem;
  font-weight: 600;
  color: var(--text-primary);
}

.header-actions {
  display: flex;
  gap: 0.5rem;
}

.build-steps {
  margin-bottom: 1.5rem;
  background: white;
  padding: 1rem 1.5rem;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.phase-panel {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.section-card {
  border-radius: 12px;
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
}

/* 可点击的标题（点击打开对应添加对话框） */
.panel-title.clickable {
  cursor: pointer;
  padding: 2px 6px;
  border-radius: var(--radius-md);
  transition: background 0.2s, color 0.2s;
  user-select: none;
}

.panel-title.clickable:hover {
  background: var(--primary-50);
  color: var(--primary-600);
}

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

.template-loader {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

/* ── 实体类型树 ── */
.type-tree-wrap {
  display: flex;
  flex-direction: column;
}

.type-tree-wrap :deep(.el-tree-node__content) {
  height: auto;
  min-height: 36px;
  padding: 4px 0;
}

.tree-node {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 4px 6px;
  gap: 0.5rem;
}

.tree-node-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.tree-node-name {
  font-weight: 600;
  color: var(--text-primary);
}

.type-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.tree-node-actions {
  display: flex;
  gap: 0.25rem;
  margin-left: auto;
}

/* ── 类型间关系 ── */
.relation-types-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.5rem 0.75rem;
  margin-bottom: 0.75rem;
  background: var(--bg-hover);
  border-radius: var(--radius-md);
}

.bar-label {
  font-size: 0.825rem;
  font-weight: 600;
  color: var(--text-secondary);
}

.rt-chip {
  margin-right: 0;
}

.etype-relation-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.etype-relation-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  flex-wrap: wrap;
}

.rel-name {
  font-weight: 500;
}

.rel-type {
  padding: 1px 8px;
  border-radius: var(--radius-full);
  background: var(--gray-100);
  color: var(--text-tertiary);
  font-size: 0.75rem;
}

.rel-arrow {
  color: var(--text-muted);
}

.rel-desc {
  margin-left: 0.25rem;
}

/* ── 实体网格 ── */
.entity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 1rem;
}

.entity-card {
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: 1rem;
}

.entity-card-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  flex-wrap: wrap;
}

.entity-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.entity-card-name {
  font-weight: 600;
  color: var(--text-primary);
}

.entity-card-actions {
  margin-left: auto;
  display: flex;
  gap: 0.25rem;
}

.entity-props {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.prop-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.825rem;
  padding: 2px 0;
}

.prop-name {
  color: var(--text-secondary);
}

.prop-value {
  color: var(--text-primary);
  font-weight: 500;
}

/* ── 关系列表 ── */
.relation-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.relation-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  background: var(--bg-card);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}

/* ── 步骤导航 ── */
.step-nav {
  display: flex;
  justify-content: space-between;
  padding: 1rem 0;
}

.step-nav-left {
  display: flex;
  gap: 0.5rem;
}

/* ── 对话框内编辑器 ── */
.schema-editor,
.props-editor {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding-left: 0.875rem;
}

.schema-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.5rem;
  background: var(--bg-hover);
  border-radius: var(--radius-md);
}

.prop-edit-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  padding: 0.5rem;
  background: var(--bg-hover);
  border-radius: var(--radius-md);
}

.inherited-schema {
  display: flex;
  gap: 0.25rem;
  flex-wrap: wrap;
  padding: 0.5rem 0.875rem;
  margin-bottom: 0.5rem;
  background: var(--bg-hover);
  border-radius: var(--radius-md);
}

.schema-chip {
  margin-right: 0;
}

.form-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-left: 0.5rem;
}

</style>
