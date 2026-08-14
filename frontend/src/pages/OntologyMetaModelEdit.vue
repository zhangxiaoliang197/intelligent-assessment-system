<template>
  <Layout>
    <div class="meta-model-edit">
      <!-- 顶部工具栏 -->
      <div class="build-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回</el-button>
          <h2>{{ isEdit ? '编辑元模型' : '新建元模型' }}</h2>
          <el-tag v-if="isEdit" type="primary" size="small">{{ form.name }}</el-tag>
        </div>
        <div class="header-actions">
          <el-button type="primary" :loading="submitting" :icon="Check" @click="save">保存元模型</el-button>
        </div>
      </div>

      <!-- 基本信息 -->
      <el-card class="section-card">
        <template #header>
          <div class="panel-header"><span>基本信息</span></div>
        </template>
        <el-form :model="form" label-width="100px">
          <el-form-item label="元模型名称" required>
            <el-input v-model="form.name" placeholder="请输入元模型名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="form.description" type="textarea" :rows="2" placeholder="请输入元模型描述" />
          </el-form-item>
        </el-form>
      </el-card>

      <!-- 实体类型定义 -->
      <el-card class="section-card">
        <template #header>
          <div class="panel-header">
            <div class="panel-title clickable" @click="openEntityTypeDialog()">
              <el-icon :size="16"><Plus /></el-icon>
              <span>实体类型定义</span>
              <span class="count-badge">{{ form.entityTypes.length }}</span>
            </div>
          </div>
        </template>
        <el-empty
          v-if="!form.entityTypes.length"
          description="暂无实体类型，请添加顶层类型（如：公司、人物、城市）"
          :image-size="80"
        />
        <div v-else class="type-tree-wrap">
          <el-tree
            :data="entityTypeTree"
            node-key="name"
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
                  <el-tag v-if="data.property_schema && data.property_schema.length" size="small" type="success">
                    {{ data.property_schema.length }} 属性
                  </el-tag>
                  <el-text v-else type="info" size="small">无属性骨架</el-text>
                </div>
                <div class="tree-node-actions">
                  <el-button size="small" link @click.stop="openEntityTypeDialog(undefined, data.name)">添加子类型</el-button>
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

      <!-- 类型间关系 -->
      <el-card class="section-card">
        <template #header>
          <div class="panel-header">
            <div class="panel-title clickable" @click="openEntityTypeRelationDialog">
              <el-icon :size="16"><Plus /></el-icon>
              <span>类型间关系</span>
              <span class="count-badge">{{ form.entityTypeRelations.length }}</span>
            </div>
          </div>
        </template>

        <!-- 关系类型快捷管理 -->
        <div class="relation-types-bar">
          <span class="bar-label">关系类型：</span>
          <el-tag
            v-for="(rt, idx) in form.relationTypes"
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
          v-if="!form.entityTypeRelations.length"
          description="暂无类型间关系，可在两个实体类型间建立关系（如：公司 位于 城市）"
          :image-size="80"
        />
        <div v-else class="etype-relation-list">
          <div v-for="(r, idx) in form.entityTypeRelations" :key="idx" class="etype-relation-row">
            <span class="rel-name">{{ r.source_entity_type_name }}</span>
            <span class="rel-type">{{ r.relation_type }}</span>
            <span class="rel-arrow">→</span>
            <span class="rel-name">{{ r.target_entity_type_name }}</span>
            <el-text v-if="r.description" type="info" size="small" class="rel-desc">（{{ r.description }}）</el-text>
            <el-button size="small" link type="danger" @click="removeEntityTypeRelation(idx)">删除</el-button>
          </div>
        </div>
      </el-card>

      <!-- 实体类型编辑对话框 -->
      <el-dialog
        v-model="showEntityTypeDialog"
        :title="entityTypeForm.isEdit ? '编辑实体类型' : '添加实体类型'"
        width="760px"
        top="5vh"
      >
        <el-form :model="entityTypeForm" label-width="100px">
          <el-form-item label="类型名" required>
            <el-input v-model="entityTypeForm.name" placeholder="如：公司、人物、城市（实体类型）" />
          </el-form-item>
          <el-form-item label="父类型">
            <el-select
              v-model="entityTypeForm.parent_entity_type_name"
              :placeholder="parentLocked ? '子类型继承父类型属性骨架' : '选择父类型（留空为顶层类型）'"
              :disabled="parentLocked"
              clearable
              style="width: 100%"
            >
              <el-option v-for="t in parentOptions" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
            <span class="form-hint">
              {{ parentLocked
                ? '继承父类型属性骨架，可另外添加属性'
                : '子类型自动继承父类型属性骨架；不可选择自身或后代作为父类型（防环）' }}
            </span>
          </el-form-item>
          <el-form-item label="颜色">
            <el-color-picker v-model="entityTypeForm.color" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="entityTypeForm.description" type="textarea" :rows="2" placeholder="该实体类型的简要释义" />
          </el-form-item>

          <el-divider>属性骨架（property_schema）</el-divider>
          <p class="form-hint" style="margin: -0.5rem 0 0.75rem 0.875rem;">
            定义该类型自身应具备的属性结构，实例化实体时将按此骨架（含继承）生成属性行供赋值。
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
          <el-button type="primary" @click="submitEntityType">保存</el-button>
        </template>
      </el-dialog>

      <!-- 类型间关系编辑对话框 -->
      <el-dialog v-model="showEntityTypeRelationDialog" title="添加类型间关系" width="560px">
        <el-form :model="entityTypeRelationForm" label-width="100px">
          <el-form-item label="源类型" required>
            <el-select v-model="entityTypeRelationForm.source_entity_type_name" placeholder="选择源实体类型" style="width: 100%" filterable>
              <el-option v-for="t in form.entityTypes" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型" required>
            <el-select
              v-model="entityTypeRelationForm.relation_type"
              placeholder="选择或输入关系类型"
              style="width: 100%"
              filterable
              allow-create
              default-first-option
            >
              <el-option v-for="rt in form.relationTypes" :key="rt.name" :label="rt.name" :value="rt.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标类型" required>
            <el-select v-model="entityTypeRelationForm.target_entity_type_name" placeholder="选择目标实体类型" style="width: 100%" filterable>
              <el-option v-for="t in form.entityTypes" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="entityTypeRelationForm.description" type="textarea" :rows="2" placeholder="该类型关系的释义（可选）" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showEntityTypeRelationDialog = false">取消</el-button>
          <el-button type="primary" @click="submitEntityTypeRelation">添加</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Plus, Check } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import { getMetaModel, createMetaModel, updateMetaModel } from '@/services/ontologyMetaModel'

const route = useRoute()
const router = useRouter()
const metaModelId = route.params.id as string | undefined
const isEdit = computed(() => !!metaModelId)

// ── 元模型表单（字段与后端 TemplateModel 对齐） ──
const form = reactive({
  name: '',
  description: '',
  relationTypes: [] as { name: string; description: string }[],
  entityTypes: [] as {
    name: string
    description: string
    color: string
    parent_entity_type_name: string
    property_schema: any[]
  }[],
  entityTypeRelations: [] as {
    source_entity_type_name: string
    target_entity_type_name: string
    relation_type: string
    description: string
  }[]
})

const submitting = ref(false)
const newRelationType = ref('')

// ── 实体类型对话框 ──
const showEntityTypeDialog = ref(false)
const parentLocked = ref(false)
const entityTypeForm = reactive({
  isEdit: false,
  originalName: '',
  name: '',
  description: '',
  color: '',
  parent_entity_type_name: '',
  property_schema: [] as any[]
})

// ── 类型间关系对话框 ──
const showEntityTypeRelationDialog = ref(false)
const entityTypeRelationForm = reactive({
  source_entity_type_name: '',
  target_entity_type_name: '',
  relation_type: '',
  description: ''
})

// ── 实体类型树（按 parent_entity_type_name 组织） ──
const entityTypeTree = computed(() => {
  const build = (parentName: string | null): any[] => {
    return form.entityTypes
      .filter(t => {
        const pn = t.parent_entity_type_name
        if (parentName === null) return !pn
        return pn === parentName
      })
      .map(t => ({ ...t, children: build(t.name) }))
  }
  return build(null)
})

// 父类型可选项（排除自身及所有后代，防止成环）
const parentOptions = computed(() => {
  if (!entityTypeForm.name) return form.entityTypes
  const forbidden = new Set<string>([entityTypeForm.name, ...getDescendantNames(entityTypeForm.name)])
  return form.entityTypes.filter(t => !forbidden.has(t.name))
})

// 收集某个类型的后代 name（递归）
const getDescendantNames = (name: string): string[] => {
  const result: string[] = []
  const collect = (parentName: string) => {
    form.entityTypes.forEach(t => {
      if (t.parent_entity_type_name === parentName) {
        result.push(t.name)
        collect(t.name)
      }
    })
  }
  collect(name)
  return result
}

// ── 实体类型操作 ──
const openEntityTypeDialog = (entityType?: any, parentName?: string) => {
  if (entityType) {
    parentLocked.value = false
    Object.assign(entityTypeForm, {
      isEdit: true,
      originalName: entityType.name,
      name: entityType.name,
      description: entityType.description || '',
      color: entityType.color || '',
      parent_entity_type_name: entityType.parent_entity_type_name || '',
      property_schema: JSON.parse(JSON.stringify(entityType.property_schema || []))
    })
  } else {
    parentLocked.value = !!parentName
    Object.assign(entityTypeForm, {
      isEdit: false,
      originalName: '',
      name: '',
      description: '',
      color: '',
      parent_entity_type_name: parentName || '',
      property_schema: []
    })
  }
  showEntityTypeDialog.value = true
}

const addSchemaRow = () => {
  entityTypeForm.property_schema.push({
    name: '',
    category: 'descriptive',
    data_type: 'string',
    unit: '',
    required: false,
    description: ''
  })
}

const submitEntityType = () => {
  const name = entityTypeForm.name.trim()
  if (!name) {
    ElMessage.warning('请填写类型名')
    return
  }
  // 重名校验（排除自身）
  const duplicate = form.entityTypes.some(t => t.name === name && t.name !== entityTypeForm.originalName)
  if (duplicate) {
    ElMessage.warning('该类型名已存在')
    return
  }
  // 父类型不能成环
  if (entityTypeForm.parent_entity_type_name) {
    const forbidden = new Set<string>([name, ...getDescendantNames(name)])
    if (forbidden.has(entityTypeForm.parent_entity_type_name)) {
      ElMessage.warning('父类型不能选择自身或后代类型（会形成环）')
      return
    }
  }

  const payload = {
    name,
    description: entityTypeForm.description,
    color: entityTypeForm.color || '#5470c6',
    parent_entity_type_name: entityTypeForm.parent_entity_type_name || '',
    property_schema: entityTypeForm.property_schema.filter((p: any) => p.name)
  }

  if (entityTypeForm.isEdit) {
    const idx = form.entityTypes.findIndex(t => t.name === entityTypeForm.originalName)
    if (idx >= 0) form.entityTypes[idx] = payload
  } else {
    form.entityTypes.push(payload)
  }
  showEntityTypeDialog.value = false
}

const removeEntityType = async (entityType: any) => {
  try {
    await ElMessageBox.confirm(
      `确定删除实体类型「${entityType.name}」吗？其子类型将变为顶层类型。`,
      '提示',
      { confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning' }
    )
  } catch { return }
  form.entityTypes = form.entityTypes.filter(t => t.name !== entityType.name)
  // 解除子类型指向该类型的父引用
  form.entityTypes.forEach(t => {
    if (t.parent_entity_type_name === entityType.name) t.parent_entity_type_name = ''
  })
  // 清理关联的类型间关系
  form.entityTypeRelations = form.entityTypeRelations.filter(
    r => r.source_entity_type_name !== entityType.name && r.target_entity_type_name !== entityType.name
  )
}

// ── 关系类型管理 ──
const addRelationType = () => {
  const name = newRelationType.value.trim()
  if (!name) {
    ElMessage.warning('请输入关系类型名')
    return
  }
  if (form.relationTypes.some(rt => rt.name === name)) {
    ElMessage.warning('该关系类型已存在')
    return
  }
  form.relationTypes.push({ name, description: '' })
  newRelationType.value = ''
}

const removeRelationType = (idx: number) => {
  form.relationTypes.splice(idx, 1)
}

// ── 类型间关系操作 ──
const openEntityTypeRelationDialog = () => {
  if (!form.entityTypes.length) {
    ElMessage.warning('请先添加实体类型')
    return
  }
  Object.assign(entityTypeRelationForm, {
    source_entity_type_name: '',
    target_entity_type_name: '',
    relation_type: '',
    description: ''
  })
  showEntityTypeRelationDialog.value = true
}

const submitEntityTypeRelation = () => {
  const { source_entity_type_name, target_entity_type_name, relation_type } = entityTypeRelationForm
  if (!source_entity_type_name || !target_entity_type_name || !relation_type.trim()) {
    ElMessage.warning('请填写完整的类型间关系信息')
    return
  }
  if (source_entity_type_name === target_entity_type_name) {
    ElMessage.warning('源类型与目标类型不能相同')
    return
  }
  form.entityTypeRelations.push({
    source_entity_type_name,
    target_entity_type_name,
    relation_type: relation_type.trim(),
    description: entityTypeRelationForm.description
  })
  showEntityTypeRelationDialog.value = false
}

const removeEntityTypeRelation = (idx: number) => {
  form.entityTypeRelations.splice(idx, 1)
}

// ── 保存 ──
const save = async () => {
  if (!form.name?.trim()) {
    ElMessage.warning('请输入元模型名称')
    return
  }
  if (!form.entityTypes.length) {
    ElMessage.warning('请至少添加一个实体类型')
    return
  }
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('name', form.name.trim())
    fd.append('description', form.description)
    fd.append('entity_types', JSON.stringify(form.entityTypes))
    fd.append('relation_types', JSON.stringify(form.relationTypes))
    fd.append('entity_type_relations', JSON.stringify(form.entityTypeRelations))
    if (isEdit.value) {
      await updateMetaModel(metaModelId!, fd)
      ElMessage.success('元模型已更新')
    } else {
      await createMetaModel(fd)
      ElMessage.success('元模型已创建')
    }
    router.push('/ontology')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '保存失败')
  } finally {
    submitting.value = false
  }
}

const goBack = () => {
  router.push('/ontology')
}

// ── 加载（编辑模式） ──
const loadMetaModel = async () => {
  if (!metaModelId) return
  try {
    const res: any = await getMetaModel(metaModelId)
    const data = res.data
    form.name = data.name
    form.description = data.description || ''
    form.relationTypes = (data.relation_types || []).map((rt: any) => ({ name: rt.name, description: rt.description || '' }))
    form.entityTypes = (data.entity_types || []).map((et: any) => ({
      name: et.name,
      description: et.description || '',
      color: et.color || '#5470c6',
      parent_entity_type_name: et.parent_entity_type_name || '',
      property_schema: (et.property_schema || []).map((ps: any) => ({ ...ps }))
    }))
    form.entityTypeRelations = (data.entity_type_relations || []).map((r: any) => ({
      source_entity_type_name: r.source_entity_type_name,
      target_entity_type_name: r.target_entity_type_name,
      relation_type: r.relation_type,
      description: r.description || ''
    }))
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载元模型失败')
  }
}

onMounted(() => {
  if (isEdit.value) loadMetaModel()
})
</script>

<style scoped>
.meta-model-edit {
  height: 100%;
  padding: 1.5rem;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.build-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
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

.schema-editor {
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

.form-hint {
  font-size: 0.75rem;
  color: var(--text-muted);
  margin-left: 0.5rem;
}
</style>
