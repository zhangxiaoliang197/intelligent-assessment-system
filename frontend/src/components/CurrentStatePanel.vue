<template>
  <div class="current-state-panel" :class="{ collapsed: !expanded }">
    <!-- 头部：点击展开/收起 -->
    <div class="panel-header" @click="toggle">
      <el-icon class="toggle-icon"><ArrowDown v-if="expanded" /><ArrowRight v-else /></el-icon>
      <span class="panel-title">当前本体 / 实体</span>
      <span class="panel-summary">
        类型: {{ entityTypes.length }} | 类型关系: {{ typeRelations.length }} | 实体: {{ entities.length }} | 实例关系: {{ instanceRelations.length }}
      </span>
    </div>

    <!-- 展开内容 -->
    <div v-show="expanded" class="panel-body">
      <el-tabs v-model="activeTab" class="panel-tabs">
        <!-- 本体 Tab：实体类型 + 类型关系 -->
        <el-tab-pane label="实体类型" name="types">
          <div class="item-list">
            <el-tree
              v-if="entityTypes.length"
              :data="entityTypeTree"
              node-key="name"
              default-expand-all
              :expand-on-click-node="false"
              :props="{ children: 'children', label: 'name' }"
              class="type-tree"
            >
              <template #default="{ data }">
                <div class="state-item tree-item">
                  <div class="item-info">
                    <span class="item-color" :style="{ background: data.color || '#409eff' }"></span>
                    <span class="item-name">{{ data.name }}</span>
                    <span class="item-desc">{{ data.description || '' }}</span>
                  </div>
                  <div class="item-actions">
                    <el-button link type="primary" size="small" @click.stop="openEditDialog('entity_type', data, data._idx)">编辑</el-button>
                    <el-button link type="danger" size="small" @click.stop="handleDelete('entity_type', data, data._idx)">删除</el-button>
                  </div>
                </div>
              </template>
            </el-tree>
            <div class="item-list-footer">
              <el-button link type="primary" size="small" @click="openEditDialog('entity_type', null, -1)">+ 新增实体类型</el-button>
            </div>
            <div v-if="!entityTypes.length" class="empty-hint">暂无实体类型，等待 AI 提取或手动新增</div>
          </div>
        </el-tab-pane>

        <!-- 类型关系 Tab -->
        <el-tab-pane label="类型关系" name="etRelations">
          <div class="item-list">
            <div v-for="(r, idx) in typeRelations" :key="idx" class="state-item">
              <div class="item-info">
                <span class="rel-source">{{ r.source_entity_type_name || r.source_type_name }}</span>
                <el-icon class="rel-arrow"><ArrowRight /></el-icon>
                <span class="rel-target">{{ r.target_entity_type_name || r.target_type_name }}</span>
                <el-tag size="small" type="info" class="rel-tag">{{ r.relation_type }}</el-tag>
              </div>
              <div class="item-actions">
                <el-button link type="primary" size="small" @click="openEditDialog('et_relation', r, idx)">编辑</el-button>
                <el-button link type="danger" size="small" @click="handleDelete('et_relation', r, idx)">删除</el-button>
              </div>
            </div>
            <div class="item-list-footer">
              <el-button link type="primary" size="small" @click="openEditDialog('et_relation', null, -1)">+ 新增类型关系</el-button>
            </div>
            <div v-if="!typeRelations.length" class="empty-hint">暂无类型关系，等待 AI 提取或手动新增</div>
          </div>
        </el-tab-pane>

        <!-- 实体 Tab -->
        <el-tab-pane label="实体" name="entities">
          <div class="item-list">
            <div v-for="(e, idx) in entities" :key="e.name || idx" class="state-item">
              <div class="item-info">
                <span class="item-name">{{ e.name }}</span>
                <span class="item-meta">属于: {{ e.instance_of || e.type || '未分类' }}</span>
              </div>
              <div class="item-actions">
                <el-button link type="primary" size="small" @click="openEditDialog('entity', e, idx)">编辑</el-button>
                <el-button link type="danger" size="small" @click="handleDelete('entity', e, idx)">删除</el-button>
              </div>
            </div>
            <div class="item-list-footer">
              <el-button link type="primary" size="small" @click="openEditDialog('entity', null, -1)">+ 新增实体</el-button>
            </div>
            <div v-if="!entities.length" class="empty-hint">暂无实体，等待 AI 提取或手动新增</div>
          </div>
        </el-tab-pane>

        <!-- 实例关系 Tab -->
        <el-tab-pane label="实例关系" name="relations">
          <div class="item-list">
            <div v-for="(r, idx) in instanceRelations" :key="idx" class="state-item">
              <div class="item-info">
                <span class="rel-source">{{ r.source }}</span>
                <el-icon class="rel-arrow"><ArrowRight /></el-icon>
                <span class="rel-target">{{ r.target }}</span>
                <el-tag size="small" type="info" class="rel-tag">{{ r.relation_type }}</el-tag>
              </div>
              <div class="item-actions">
                <el-button link type="primary" size="small" @click="openEditDialog('relation', r, idx)">编辑</el-button>
                <el-button link type="danger" size="small" @click="handleDelete('relation', r, idx)">删除</el-button>
              </div>
            </div>
            <div class="item-list-footer">
              <el-button link type="primary" size="small" @click="openEditDialog('relation', null, -1)">+ 新增实例关系</el-button>
            </div>
            <div v-if="!instanceRelations.length" class="empty-hint">暂无实例关系，等待 AI 提取或手动新增</div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 编辑对话框 -->
    <el-dialog v-model="editDialogVisible" :title="editDialogTitle" width="520px" destroy-on-close>
      <el-form :model="editForm" label-width="80px" label-position="top">
        <template v-if="editType === 'entity_type'">
          <el-form-item label="名称">
            <el-input v-model="editForm.name" placeholder="实体类型名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="描述" />
          </el-form-item>
          <el-form-item label="颜色">
            <el-color-picker v-model="editForm.color" />
          </el-form-item>
        </template>

        <template v-else-if="editType === 'et_relation'">
          <el-form-item label="源类型">
            <el-select v-model="editForm.source_entity_type_name" placeholder="选择源实体类型" filterable>
              <el-option v-for="et in entityTypes" :key="et.name" :label="et.name" :value="et.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标类型">
            <el-select v-model="editForm.target_entity_type_name" placeholder="选择目标实体类型" filterable>
              <el-option v-for="et in entityTypes" :key="et.name" :label="et.name" :value="et.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型">
            <el-input v-model="editForm.relation_type" placeholder="如：包含、关联、依赖" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="editForm.description" type="textarea" :rows="2" placeholder="关系描述" />
          </el-form-item>
        </template>

        <template v-else-if="editType === 'entity'">
          <el-form-item label="名称">
            <el-input v-model="editForm.name" placeholder="实体名称" />
          </el-form-item>
          <el-form-item label="所属类型">
            <el-select v-model="editForm.instance_of" placeholder="选择实体类型" filterable>
              <el-option v-for="et in entityTypes" :key="et.name" :label="et.name" :value="et.name" />
            </el-select>
          </el-form-item>
        </template>

        <template v-else-if="editType === 'relation'">
          <el-form-item label="源实体">
            <el-select v-model="editForm.source" placeholder="选择源实体" filterable>
              <el-option v-for="e in entities" :key="e.name" :label="e.name" :value="e.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="目标实体">
            <el-select v-model="editForm.target" placeholder="选择目标实体" filterable>
              <el-option v-for="e in entities" :key="e.name" :label="e.name" :value="e.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型">
            <el-input v-model="editForm.relation_type" placeholder="如：合作、竞争、隶属" />
          </el-form-item>
        </template>
      </el-form>

      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmEdit" :loading="editing">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { ArrowDown, ArrowRight } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { editBuildState } from '@/services/ontologyBuild'

const props = defineProps<{
  jobId: string
  state: any
}>()

const emit = defineEmits<{
  (e: 'stateChanged'): void
}>()

const expanded = ref(false)
const activeTab = ref('types')

// 实体类型（平铺，保留层级字段与原始索引，供树构建和编辑/删除使用）
const entityTypes = computed(() => {
  return (props.state?.entity_types || []).map((et: any, idx: number) => ({
    name: et.name || '',
    description: et.description || '',
    color: et.color || '',
    parent_entity_type_name: et.parent_entity_type_name || '',
    _idx: idx,
  }))
})

// 实体类型树（按 parent_entity_type_name 组装，供 el-tree 折叠展示父/子类型）
const entityTypeTree = computed(() => {
  const list = entityTypes.value
  const map = new Map<string, any>()
  list.forEach((et: any) => {
    map.set(et.name, { ...et, children: [] })
  })
  const roots: any[] = []
  list.forEach((et: any) => {
    const node = map.get(et.name)
    if (!node) return
    const parent = et.parent_entity_type_name ? map.get(et.parent_entity_type_name) : undefined
    if (parent && parent.name !== et.name) {
      parent.children.push(node)
    } else {
      roots.push(node)
    }
  })
  return roots
})

// 类型关系
const typeRelations = computed(() => {
  return (props.state?.entity_type_relations || []).map((r: any) => ({
    source_entity_type_name: r.source_entity_type_name || r.source_type_name || '',
    target_entity_type_name: r.target_entity_type_name || r.target_type_name || '',
    relation_type: r.relation_type || '',
    description: r.description || '',
  }))
})

// 实体
const entities = computed(() => {
  return (props.state?.entities || []).map((e: any) => ({
    name: e.name || '',
    instance_of: e.instance_of || e.type || '',
  }))
})

// 实例关系
const instanceRelations = computed(() => {
  return (props.state?.relations || []).map((r: any) => ({
    source: r.source || '',
    target: r.target || '',
    relation_type: r.relation_type || '',
  }))
})

// 自动展开：当有数据时默认展开
watch(() => props.state?.entity_types?.length, (val) => {
  if (val > 0 && !expanded.value) {
    expanded.value = true
  }
}, { immediate: true })

const toggle = () => {
  expanded.value = !expanded.value
}

// ── 编辑对话框 ──
const editDialogVisible = ref(false)
const editType = ref('entity_type') // entity_type | et_relation | entity | relation
const editIndex = ref(-1)           // -1 表示新增
const editing = ref(false)
const editForm = ref<Record<string, any>>({})

const editDialogTitle = computed(() => {
  const isNew = editIndex.value < 0
  const prefix = isNew ? '新增' : '编辑'
  const typeMap: Record<string, string> = {
    entity_type: '实体类型',
    et_relation: '类型关系',
    entity: '实体',
    relation: '实例关系',
  }
  return `${prefix}${typeMap[editType.value] || ''}`
})

const openEditDialog = (type: string, item: any, idx: number) => {
  editType.value = type
  editIndex.value = idx
  if (item) {
    editForm.value = { ...item }
  } else {
    // 新建默认值
    if (type === 'entity_type') {
      editForm.value = { name: '', description: '', color: '#409eff' }
    } else if (type === 'et_relation') {
      editForm.value = { source_entity_type_name: '', target_entity_type_name: '', relation_type: '', description: '' }
    } else if (type === 'entity') {
      editForm.value = { name: '', instance_of: '' }
    } else if (type === 'relation') {
      editForm.value = { source: '', target: '', relation_type: '' }
    }
  }
  editDialogVisible.value = true
}

const confirmEdit = async () => {
  const isNew = editIndex.value < 0
  let op = ''
  const target: Record<string, any> = {}

  switch (editType.value) {
    case 'entity_type':
      op = isNew ? 'add_entity_type' : 'update_entity_type'
      target.name = editForm.value.name
      target.description = editForm.value.description
      target.color = editForm.value.color
      break
    case 'et_relation':
      op = isNew ? 'add_et_relation' : 'delete_et_relation'
      target.source_entity_type_name = editForm.value.source_entity_type_name
      target.target_entity_type_name = editForm.value.target_entity_type_name
      target.relation_type = editForm.value.relation_type
      target.description = editForm.value.description
      if (!isNew) {
        // 更新类型关系：先删后加
        const oldItem = typeRelations.value[editIndex.value]
        if (oldItem) {
          editing.value = true
          try {
            await editBuildState(props.jobId, {
              op: 'delete_et_relation',
              target: {
                source_entity_type_name: oldItem.source_entity_type_name,
                target_entity_type_name: oldItem.target_entity_type_name,
              },
            })
            await editBuildState(props.jobId, { op: 'add_et_relation', target })
            ElMessage.success('类型关系已更新')
            editDialogVisible.value = false
            emit('stateChanged')
          } catch (e: any) {
            ElMessage.error(e?.serverMessage || '更新失败')
          } finally {
            editing.value = false
          }
          return
        }
      }
      break
    case 'entity':
      op = isNew ? 'add_entity' : 'update_entity'
      target.name = editForm.value.name
      target.instance_of = editForm.value.instance_of
      break
    case 'relation':
      op = isNew ? 'add_relation' : 'delete_relation'
      target.source = editForm.value.source
      target.target = editForm.value.target
      target.relation_type = editForm.value.relation_type
      if (!isNew) {
        const oldItem = instanceRelations.value[editIndex.value]
        if (oldItem) {
          editing.value = true
          try {
            await editBuildState(props.jobId, {
              op: 'delete_relation',
              target: { source: oldItem.source, target: oldItem.target },
            })
            await editBuildState(props.jobId, { op: 'add_relation', target })
            ElMessage.success('实例关系已更新')
            editDialogVisible.value = false
            emit('stateChanged')
          } catch (e: any) {
            ElMessage.error(e?.serverMessage || '更新失败')
          } finally {
            editing.value = false
          }
          return
        }
      }
      break
  }

  if (!target.name && !target.source) {
    ElMessage.warning('请填写必要字段')
    return
  }

  editing.value = true
  try {
    const res: any = await editBuildState(props.jobId, { op, target })
    ElMessage.success(res?.message || '操作成功')
    editDialogVisible.value = false
    emit('stateChanged')
  } catch (e: any) {
    ElMessage.error(e?.serverMessage || '操作失败')
  } finally {
    editing.value = false
  }
}

// ── 删除 ──
const handleDelete = async (type: string, item: any, _idx: number) => {
  let op = ''
  const target: Record<string, any> = {}

  switch (type) {
    case 'entity_type':
      op = 'delete_entity_type'
      target.name = item.name
      break
    case 'et_relation':
      op = 'delete_et_relation'
      target.source_entity_type_name = item.source_entity_type_name
      target.target_entity_type_name = item.target_entity_type_name
      break
    case 'entity':
      op = 'delete_entity'
      target.name = item.name
      break
    case 'relation':
      op = 'delete_relation'
      target.source = item.source
      target.target = item.target
      break
  }

  try {
    await ElMessageBox.confirm(`确认删除「${type === 'entity_type' || type === 'entity' ? item.name : item.source_entity_type_name + ' → ' + item.target_entity_type_name}」？`, '删除确认', { type: 'warning' })
  } catch {
    return
  }

  try {
    const res: any = await editBuildState(props.jobId, { op, target })
    ElMessage.success(res?.message || '删除成功')
    emit('stateChanged')
  } catch (e: any) {
    ElMessage.error(e?.serverMessage || '删除失败')
  }
}
</script>

<style scoped>
.current-state-panel {
  background: #fafbfc;
  border-bottom: 1px solid #ebeef5;
  flex-shrink: 0;
  overflow: hidden;
  transition: max-height 0.3s ease;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  cursor: pointer;
  user-select: none;
  transition: background 0.15s;
}
.panel-header:hover {
  background: #f0f2f5;
}

.toggle-icon {
  font-size: 0.85rem;
  color: #909399;
  flex-shrink: 0;
}

.panel-title {
  font-size: 0.85rem;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
}

.panel-summary {
  font-size: 0.72rem;
  color: #909399;
  margin-left: auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.panel-body {
  max-height: 320px;
  overflow-y: auto;
  border-top: 1px solid #ebeef5;
}

.panel-tabs :deep(.el-tabs__header) {
  margin-bottom: 0;
  padding: 0 0.75rem;
}
.panel-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 1px;
}

.item-list {
  padding: 0.5rem 0.75rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.state-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.4rem 0.5rem;
  border-radius: 6px;
  background: #fff;
  border: 1px solid #ebeef5;
  transition: background 0.15s;
}
.state-item:hover {
  background: #f5f7fa;
}

.item-info {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  min-width: 0;
  flex: 1;
  overflow: hidden;
}

.item-color {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.item-name {
  font-size: 0.8rem;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
}

.item-desc {
  font-size: 0.72rem;
  color: #909399;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.item-meta {
  font-size: 0.72rem;
  color: #a0a4ad;
  white-space: nowrap;
}

.item-actions {
  display: flex;
  gap: 0.25rem;
  flex-shrink: 0;
  margin-left: 0.5rem;
}

.rel-source, .rel-target {
  font-size: 0.8rem;
  font-weight: 500;
  color: #303133;
  white-space: nowrap;
}

.rel-arrow {
  font-size: 0.7rem;
  color: #c0c4cc;
  flex-shrink: 0;
}

.rel-tag {
  flex-shrink: 0;
}

.item-list-footer {
  padding: 0.25rem 0.5rem;
}

.empty-hint {
  padding: 1rem;
  text-align: center;
  font-size: 0.78rem;
  color: #c0c4cc;
}

/* 实体类型树：让节点占满宽度、去掉重边框，保留 hover 反馈 */
.type-tree {
  background: transparent;
}
.type-tree :deep(.el-tree-node__content) {
  height: auto;
  padding: 0.1rem 0;
  border-radius: 6px;
}
.tree-item {
  flex: 1;
  min-width: 0;
  border: none !important;
  background: transparent !important;
  padding: 0.25rem 0.4rem;
}
.tree-item:hover {
  background: #f5f7fa !important;
}
</style>