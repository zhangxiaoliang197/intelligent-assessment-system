<template>
  <Layout>
    <div class="admin-container">
      <el-tabs v-model="activeTab" class="admin-tabs">
        <el-tab-pane label="数据库配置" name="database">
          <div class="tab-content">
            <div class="section-header">
              <h3>已配置的数据库</h3>
              <el-button type="primary" @click="openAddDatabase">新增数据库</el-button>
            </div>

            <el-table :data="databases" stripe>
              <el-table-column prop="name" label="名称" min-width="140" />
              <el-table-column prop="type" label="类型" width="110">
                <template #default="scope">
                  <el-tag :type="getDbTypeTag(scope.row.type)">{{ scope.row.type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="host" label="主机" min-width="130" />
              <el-table-column prop="port" label="端口" width="80" />
              <el-table-column prop="database" label="数据库" min-width="120" />
              <el-table-column label="状态" width="110">
                <template #default="scope">
                  <el-tag :type="getStatusTag(scope.row.status)">
                    {{ scope.row.status || '未连接' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" min-width="300">
                <template #default="scope">
                  <el-button size="small" type="success" @click="testConnection(scope.row)" :loading="scope.row.testing">
                    测试连接
                  </el-button>
                  <el-button size="small" @click="openEditDatabase(scope.row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteDatabase(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <el-divider />

            <div class="section-header">
              <h3>数据库驱动管理</h3>
              <el-button type="primary" @click="showUploadDriver = true">上传驱动</el-button>
            </div>

            <el-table :data="drivers" stripe>
              <el-table-column prop="name" label="驱动名称" min-width="150" />
              <el-table-column prop="driverClass" label="驱动类" min-width="200" />
              <el-table-column label="类型" width="80">
                <template #default>
                  <el-tag type="success" size="small">内置</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="scope">
                  <el-button size="small" type="danger" disabled>删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <!-- 上传驱动对话框 -->
            <el-dialog v-model="showUploadDriver" title="上传数据库驱动" width="500px">
              <el-form :model="driverForm" label-width="100px">
                <el-form-item label="驱动名称">
                  <el-input v-model="driverForm.name" placeholder="请输入驱动名称" />
                </el-form-item>
                <el-form-item label="驱动类">
                  <el-input v-model="driverForm.driverClass" placeholder="如：dm.jdbc.driver.DmDriver" />
                </el-form-item>
                <el-form-item label="JAR包">
                  <el-upload :auto-upload="false" :limit="1" accept=".jar">
                    <el-button>选择JAR文件</el-button>
                    <template #tip><div class="el-upload__tip">仅支持 .jar 格式</div></template>
                  </el-upload>
                </el-form-item>
              </el-form>
              <template #footer>
                <el-button @click="showUploadDriver = false">取消</el-button>
                <el-button type="primary" @click="uploadDriver">上传</el-button>
              </template>
            </el-dialog>
          </div>
        </el-tab-pane>

        <el-tab-pane label="数据集管理" name="dataset">
          <div class="tab-content">
            <div class="section-header">
              <h3>数据集列表</h3>
              <el-button type="primary" @click="openAddDataset">创建数据集</el-button>
            </div>

            <el-table :data="datasets" stripe>
              <el-table-column prop="name" label="名称" min-width="160" />
              <el-table-column prop="description" label="描述" />
              <el-table-column label="关联数据库" min-width="140">
                <template #default="scope">
                  {{ getDbName(scope.row.databaseId) }}
                </template>
              </el-table-column>
              <el-table-column prop="tableName" label="数据表" width="150" />
              <el-table-column prop="records" label="记录数" width="85" />
              <el-table-column label="操作" min-width="260">
                <template #default="scope">
                  <el-button size="small" @click="openTableStructure(scope.row)">表结构</el-button>
                  <el-button size="small" @click="editDataset(scope.row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteDataset(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="指标管理" name="indicator">
          <div class="tab-content">
            <div class="section-header">
              <h3>评估指标库</h3>
              <el-button type="primary" @click="openAddIndicator">新建指标</el-button>
            </div>

            <el-table :data="indicators" stripe>
              <el-table-column prop="name" label="指标名称" min-width="160" />
              <el-table-column prop="category" label="分类" width="100" />
              <el-table-column label="关联数据集" width="140">
                <template #default="scope">
                  <el-tag v-if="scope.row.datasetId" type="success" size="small">{{ getDsName(scope.row.datasetId) }}</el-tag>
                  <el-tag v-else type="info" size="small">未关联</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="formula" label="计算公式" />
              <el-table-column prop="weight" label="权重" width="80" />
              <el-table-column label="操作" min-width="300">
                <template #default="scope">
                  <el-button size="small" type="success" @click="openIndicatorLink(scope.row)">关联</el-button>
                  <el-button size="small" @click="openEditIndicator(scope.row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteIndicator(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="大模型配置" name="llm">
          <div class="tab-content">
            <div class="section-header">
              <h3>大模型配置</h3>
              <el-button type="primary" @click="openLlmDialog()">新增配置</el-button>
            </div>

            <el-table :data="llmConfigs" style="width: 100%" stripe>
              <el-table-column type="index" label="#" width="50" />
              <el-table-column prop="name" label="配置名称" min-width="120" />
              <el-table-column prop="type" label="模型类型" width="120">
                <template #default="{ row }">
                  <el-tag size="small" :type="row.type === 'vllm' ? 'warning' : ''">{{ row.type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="model" label="模型" min-width="140" />
              <el-table-column prop="apiUrl" label="API地址" min-width="200" show-overflow-tooltip />
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.isActive" type="success" size="small">使用中</el-tag>
                  <el-tag v-else type="info" size="small">未激活</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="200" align="center">
                <template #default="{ row }">
                  <el-button v-if="!row.isActive" type="success" size="small" @click="activateLlmConfig(row)">启用</el-button>
                  <el-button v-else size="small" disabled>当前</el-button>
                  <el-button size="small" @click="openLlmDialog(row)">编辑</el-button>
                  <el-button type="danger" size="small" @click="deleteLlmConfig(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div style="margin-top: 12px; color: #909399; font-size: 12px;">
              提示：点击「启用」将切换当前使用的大模型，系统将自动使用激活的配置进行问答。
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>

      <!-- 大模型配置 新增/编辑对话框 -->
      <el-dialog v-model="showLlmDialog" :title="editingLlmId ? '编辑大模型配置' : '新增大模型配置'" width="600px">
        <el-form :model="llmForm" label-width="100px">
          <el-form-item label="配置名称" required>
            <el-input v-model="llmForm.name" placeholder="如：DeepSeek生产、本地vLLM测试" />
          </el-form-item>
          <el-form-item label="模型类型">
            <el-select v-model="llmForm.type" placeholder="请选择模型类型" style="width: 100%">
              <el-option-group label="云服务 API">
                <el-option label="DeepSeek" value="deepseek" />
                <el-option label="OpenAI（兼容）" value="openai" />
                <el-option label="Qwen-DashScope（阿里云）" value="qwen" />
                <el-option label="ChatGLM（智谱AI）" value="chatglm" />
              </el-option-group>
              <el-option-group label="本地部署">
                <el-option label="vLLM（OpenAI兼容）" value="vllm" />
              </el-option-group>
            </el-select>
          </el-form-item>
          <el-form-item label="模型名称">
            <el-input v-model="llmForm.model" :placeholder="modelPlaceholder" />
          </el-form-item>
          <el-form-item label="API地址">
            <el-input v-model="llmForm.apiUrl" :placeholder="apiUrlPlaceholder" />
          </el-form-item>
          <el-form-item label="API密钥">
            <el-input v-model="llmForm.apiKey" :type="apiKeyTypeVal" :placeholder="apiKeyPlaceholderVal" show-password />
          </el-form-item>
          <el-form-item label="Temperature">
            <el-slider v-model="llmForm.temperature" :min="0" :max="1" :step="0.1" show-stops :marks="tempMarks" />
          </el-form-item>
          <el-form-item label="Max Tokens">
            <el-input-number v-model="llmForm.maxTokens" :min="100" :max="32000" :step="100" />
          </el-form-item>
          <el-form-item label="Top-P">
            <el-slider v-model="llmForm.topP" :min="0" :max="1" :step="0.05" show-stops :marks="topPMarks" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showLlmDialog = false">取消</el-button>
          <el-button type="primary" @click="saveLlmConfig">{{ editingLlmId ? '保存' : '创建' }}</el-button>
        </template>
      </el-dialog>

      <!-- 新增/编辑数据库对话框 -->
      <el-dialog v-model="showDbDialog" :title="editingDbId ? '编辑数据库' : '新增数据库'" width="600px">
        <el-form :model="dbForm" label-width="100px">
          <el-form-item label="数据库名称">
            <el-input v-model="dbForm.name" placeholder="请输入数据库名称" />
          </el-form-item>
          <el-form-item label="数据库类型">
            <el-select v-model="dbForm.type" placeholder="请选择数据库类型" style="width: 100%">
              <el-option label="MySQL" value="MySQL" />
              <el-option label="PostgreSQL" value="PostgreSQL" />
              <el-option label="Oracle" value="Oracle" />
              <el-option label="达梦数据库V8.1" value="达梦数据库V8.1" />
              <el-option label="SQL Server" value="SQL Server" />
            </el-select>
          </el-form-item>
          <el-form-item label="主机地址">
            <el-input v-model="dbForm.host" placeholder="请输入主机地址" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input-number v-model="dbForm.port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="数据库名">
            <el-input v-model="dbForm.database" placeholder="请输入数据库名" />
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="dbForm.username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="dbForm.password" type="password" placeholder="请输入密码" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showDbDialog = false">取消</el-button>
          <el-button type="primary" @click="saveDatabase" :loading="savingDb">
            {{ editingDbId ? '保存（需重新测试连接）' : '确定' }}
          </el-button>
        </template>
      </el-dialog>

      <!-- 新增/编辑数据集对话框 -->
      <el-dialog v-model="showDsDialog" title="创建数据集" width="600px">
        <el-form :model="dsForm" label-width="100px">
          <el-form-item label="数据集名称">
            <el-input v-model="dsForm.name" placeholder="请输入数据集名称" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="dsForm.description" type="textarea" :rows="3" placeholder="请输入描述" />
          </el-form-item>
          <el-form-item label="关联数据库">
            <el-select v-model="dsForm.databaseId" placeholder="请选择关联数据库" style="width: 100%">
              <el-option v-for="db in databases" :key="db.id" :label="db.name" :value="db.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="SQL">
            <el-input v-model="dsForm.sql" type="textarea" :rows="5" placeholder="请输入SQL查询" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showDsDialog = false">取消</el-button>
          <el-button type="primary" @click="saveDataset">创建</el-button>
        </template>
      </el-dialog>

      <!-- 新增/编辑指标对话框 -->
      <el-dialog v-model="showIndDialog" :title="editingIndId ? '编辑指标' : '新建指标'" width="600px">
        <el-form :model="indForm" label-width="100px">
          <el-form-item label="指标名称">
            <el-input v-model="indForm.name" placeholder="请输入指标名称" />
          </el-form-item>
          <el-form-item label="分类">
            <el-select v-model="indForm.category" placeholder="请选择分类" style="width: 100%">
              <el-option label="综合指标" value="综合指标" />
              <el-option label="性能指标" value="性能指标" />
              <el-option label="效能指标" value="效能指标" />
              <el-option label="保障指标" value="保障指标" />
            </el-select>
          </el-form-item>
          <el-form-item label="计算公式">
            <el-input v-model="indForm.formula" type="textarea" :rows="3" placeholder="请输入计算公式" />
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="indForm.description" type="textarea" :rows="3" placeholder="请输入指标说明" />
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="indForm.weight" :min="0" :max="1" :step="0.1" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showIndDialog = false">取消</el-button>
          <el-button type="primary" @click="saveIndicator">确定</el-button>
        </template>
      </el-dialog>

      <!-- 表结构 / 字段标注 对话框 -->
      <el-dialog v-model="showStructDialog" title="数据表结构" width="900px" top="3vh">
        <div v-if="structColumns.length > 0">
          <div style="margin-bottom:12px;color:#606266">
            <span>数据表：<strong>{{ currentStructTable }}</strong></span>
            <span style="margin-left:20px">共 {{ structColumns.length }} 个字段</span>
          </div>
          <el-table :data="structColumns" stripe max-height="400">
            <el-table-column prop="columnName" label="字段名" width="160" />
            <el-table-column prop="dataType" label="类型" width="120" />
            <el-table-column label="主键" width="70">
              <template #default="scope">
                <el-tag v-if="scope.row.isPrimaryKey" type="danger" size="small">PK</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="comment" label="数据库注释" min-width="140" />
            <el-table-column label="业务标注" min-width="180">
              <template #default="scope">
                <el-input v-model="scope.row.annotation" placeholder="字段含义标注" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="业务含义" min-width="160">
              <template #default="scope">
                <el-input v-model="scope.row.businessMeaning" placeholder="业务说明" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="数据分类" width="120">
              <template #default="scope">
                <el-select v-model="scope.row.dataCategory" placeholder="分类" size="small" clearable>
                  <el-option label="维度" value="维度" />
                  <el-option label="度量" value="度量" />
                  <el-option label="属性" value="属性" />
                  <el-option label="时间" value="时间" />
                  <el-option label="标识" value="标识" />
                </el-select>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div v-else style="text-align:center;padding:40px;color:#999">
          请先输入表名并读取表结构
        </div>
        <template #footer>
          <el-button @click="showStructDialog = false">取消</el-button>
          <el-button type="primary" @click="saveFieldAnnotations">保存标注</el-button>
        </template>
      </el-dialog>

      <!-- 指标关联对话框 -->
      <el-dialog v-model="showLinkDialog" title="指标关联配置" width="700px">
        <el-form label-width="100px">
          <el-form-item label="关联数据集">
            <el-select v-model="linkForm.datasetId" placeholder="选择数据集" style="width:100%" @change="onLinkDatasetChange">
              <el-option v-for="ds in datasets" :key="ds.id" :label="ds.name" :value="ds.id" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="linkFields.length > 0" label="字段映射">
            <el-table :data="linkFields" stripe size="small">
              <el-table-column prop="columnName" label="字段" width="160" />
              <el-table-column prop="annotation" label="标注" min-width="150" />
              <el-table-column label="映射权重" width="120">
                <template #default="scope">
                  <el-input-number v-model="scope.row.mapWeight" :min="0" :max="1" :step="0.1" size="small" />
                </template>
              </el-table-column>
            </el-table>
          </el-form-item>
          <el-form-item label="计算方法">
            <el-input v-model="linkForm.calculationMethod" type="textarea" :rows="4" placeholder="描述指标如何通过字段计算，如：SUM(销售额)/COUNT(DISTINCT 客户ID)" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showLinkDialog = false">取消</el-button>
          <el-button type="primary" @click="saveIndicatorLink">保存关联</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const activeTab = ref('database')

// ==================== 数据库配置 ====================
const databases = ref<any[]>([])
const drivers = ref<any[]>([])
const showDbDialog = ref(false)
const editingDbId = ref<string | null>(null)
const savingDb = ref(false)
const showUploadDriver = ref(false)
const driverForm = ref({
  name: '',
  driverClass: ''
})

const dbForm = ref({
  name: '',
  type: 'MySQL',
  host: 'localhost',
  port: 3306,
  database: '',
  username: 'root',
  password: ''
})

const getDbTypeTag = (type: string) => {
  const m: Record<string, string> = {
    MySQL: 'primary',
    PostgreSQL: 'success',
    Oracle: 'warning',
    '达梦数据库V8.1': 'danger',
    'SQL Server': 'info'
  }
  return m[type] || 'info'
}

const getStatusTag = (status: string) => {
  if (status === '已连接') return 'success'
  if (status === '失败') return 'danger'
  return 'info'
}

async function loadDatabases() {
  try {
    const res = await api.get('/admin/database/list')
    if (res && res.success && res.databases) {
      databases.value = res.databases.map((db: any) => ({
        ...db,
        testing: false
      }))
    }
  } catch (e) {
    console.warn('加载数据库列表失败')
  }
}

async function loadDrivers() {
  try {
    const res = await api.get('/admin/driver/list')
    if (res && res.success && res.drivers) {
      drivers.value = res.drivers
    }
  } catch (e) {
    console.warn('加载驱动列表失败')
  }
}

async function uploadDriver() {
  if (!driverForm.value.name || !driverForm.value.driverClass) {
    ElMessage.warning('请填写驱动名称和驱动类')
    return
  }
  try {
    const res = await api.post('/admin/driver', driverForm.value)
    if (res && res.success) {
      drivers.value.push({
        id: res.id || 'driver_' + Date.now(),
        name: driverForm.value.name,
        driverClass: driverForm.value.driverClass,
        urlTemplate: 'jdbc:custom://localhost:port/database'
      })
      ElMessage.success('驱动已上传')
      showUploadDriver.value = false
      driverForm.value = { name: '', driverClass: '' }
    }
  } catch (e: any) {
    ElMessage.error('上传失败: ' + (e.message || '未知错误'))
  }
}

function openAddDatabase() {
  editingDbId.value = null
  dbForm.value = { name: '', type: 'MySQL', host: 'localhost', port: 3306, database: '', username: 'root', password: '' }
  showDbDialog.value = true
}

function openEditDatabase(row: any) {
  editingDbId.value = row.id
  dbForm.value = {
    name: row.name,
    type: row.type,
    host: row.host,
    port: row.port,
    database: row.database,
    username: row.username,
    password: ''  // 密码不回显
  }
  showDbDialog.value = true
}

async function saveDatabase() {
  if (!dbForm.value.name || !dbForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }
  savingDb.value = true
  try {
    if (editingDbId.value) {
      const res = await api.put(`/admin/database/${editingDbId.value}`, dbForm.value)
      if (res && res.success) {
        // 编辑后状态重置为未连接
        const idx = databases.value.findIndex((d: any) => d.id === editingDbId.value)
        if (idx >= 0) {
          databases.value[idx] = { ...databases.value[idx], ...dbForm.value, status: '未连接', dbVersion: null, latency: null, errorMsg: null }
        }
        ElMessage.success('数据库已更新，请重新测试连接')
      }
    } else {
      const res = await api.post('/admin/database', dbForm.value)
      if (res && res.success && res.id) {
        databases.value.push({
          id: res.id,
          ...dbForm.value,
          status: '未连接',
          testing: false
        })
        ElMessage.success('数据库已添加，请点击"测试连接"验证')
      }
    }
    showDbDialog.value = false
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.message || '未知错误'))
  } finally {
    savingDb.value = false
  }
}

async function testConnection(row: any) {
  row.testing = true
  try {
    const res = await api.post(`/admin/database/${row.id}/test`)
    if (res && res.success) {
      row.status = '已连接'
      row.dbVersion = res.dbVersion
      row.latency = res.latency
      row.errorMsg = null
      ElMessage.success(`连接成功 (${res.latency}) — ${res.dbVersion || ''}`)
    } else {
      row.status = '失败'
      row.errorMsg = res?.error || res?.message || '连接失败'
      ElMessage.error(`连接失败: ${row.errorMsg}`)
    }
  } catch (e: any) {
    row.status = '失败'
    row.errorMsg = e.message || '请求异常'
    ElMessage.error('请求失败: ' + (e.message || '未知错误'))
  } finally {
    row.testing = false
  }
}

async function deleteDatabase(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除数据库"${row.name}"吗？`, '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await api.delete(`/admin/database/${row.id}`)
    databases.value = databases.value.filter((d: any) => d.id !== row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    if (e !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.message || '未知错误'))
    }
  }
}

function getDbName(dbId: string) {
  const db = databases.value.find((d: any) => d.id === dbId)
  return db ? db.name : dbId
}

// ==================== 数据集 ====================
const datasets = ref<any[]>([])
const showDsDialog = ref(false)
const dsForm = ref({ name: '', description: '', databaseId: '', sql: '' })

async function loadDatasets() {
  try {
    const res = await api.get('/admin/dataset/list')
    if (res && res.success && res.datasets) {
      datasets.value = res.datasets
    }
  } catch (e) {
    console.warn('加载数据集失败')
  }
}

function openAddDataset() {
  dsForm.value = { name: '', description: '', databaseId: '', sql: '' }
  showDsDialog.value = true
}

async function saveDataset() {
  if (!dsForm.value.name) {
    ElMessage.warning('请填写数据集名称')
    return
  }
  try {
    const res = await api.post('/admin/dataset', dsForm.value)
    if (res && res.success) {
      datasets.value.push({
        id: res.id,
        ...dsForm.value,
        records: 0
      })
      showDsDialog.value = false
      ElMessage.success('数据集已创建')
    }
  } catch (e: any) {
    ElMessage.error('创建失败: ' + (e.message || '未知错误'))
  }
}

async function editDataset(row: any) {
  dsForm.value = { ...row }
  showDsDialog.value = true
}

async function deleteDataset(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除数据集"${row.name}"吗？`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    await api.delete(`/admin/dataset/${row.id}`)
    datasets.value = datasets.value.filter((d: any) => d.id !== row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ==================== 数据表结构 & 字段标注 ====================
const showStructDialog = ref(false)
const structColumns = ref<any[]>([])
const currentStructDs = ref<string>('')
const currentStructTable = ref('')
const structTableInput = ref('')

async function openTableStructure(row: any) {
  currentStructDs.value = row.id
  structColumns.value = []

  // Validate dataset has a database
  if (!row.databaseId) {
    ElMessage.warning('数据集未关联数据库，请先编辑数据集选择关联的数据库')
    return
  }
  // Check database connection status
  const linkedDb = databases.value.find((d: any) => d.id === row.databaseId)
  if (!linkedDb) {
    ElMessage.error('关联的数据库配置已不存在，请重新编辑数据集')
    return
  }
  if (linkedDb.status !== '已连接') {
    ElMessage.warning(`数据库"${linkedDb.name}"尚未连接，请先在数据库配置中测试连接`)
    return
  }

  // Try to load existing cached structure
  try {
    const res = await api.get(`/admin/dataset/${row.id}/structure`)
    if (res && res.success && res.columns && res.columns.length > 0) {
      currentStructTable.value = res.tableName || row.tableName || ''
      structColumns.value = res.columns.map((c: any) => ({
        ...c,
        annotation: c.annotation || '',
        businessMeaning: c.businessMeaning || '',
        dataCategory: c.dataCategory || ''
      }))
      // Merge existing annotations
      try {
        const faRes = await api.get(`/admin/dataset/${row.id}/fields`)
        if (faRes && faRes.success && faRes.fields) {
          faRes.fields.forEach((fa: any) => {
            const col = structColumns.value.find((c: any) => c.columnName === fa.columnName)
            if (col) {
              col.annotation = fa.annotation || ''
              col.businessMeaning = fa.businessMeaning || ''
              col.dataCategory = fa.dataCategory || ''
            }
          })
        }
      } catch {}
      showStructDialog.value = true
      return
    }
  } catch (e: any) {
    if (e?.response?.status === 400) {
      ElMessage.warning(e.response.data?.message || '无法读取表结构，请检查数据库连接')
      return
    }
  }

  // Need to read structure - prompt for table name
  try {
    const { value: tableName } = await ElMessageBox.prompt('请输入要读取的数据表名', '读取表结构', {
      confirmButtonText: '读取', cancelButtonText: '取消',
      inputValue: row.tableName || ''
    })
    if (!tableName) return

    const res = await api.post(`/admin/dataset/${row.id}/read-structure`, { tableName })
    if (res && res.success) {
      currentStructTable.value = res.tableName
      structColumns.value = res.columns.map((c: any) => ({
        ...c,
        annotation: '',
        businessMeaning: '',
        dataCategory: ''
      }))
      // Update local dataset
      const ds = datasets.value.find((d: any) => d.id === row.id)
      if (ds) ds.tableName = res.tableName
    } else {
      ElMessage.error(res?.message || '读取失败')
      return
    }
    showStructDialog.value = true
  } catch (e: any) {
    if (e !== 'cancel') {
      const msg = e?.response?.data?.message || e?.message || '读取表结构失败'
      ElMessage.error(msg)
    }
  }
}

async function saveFieldAnnotations() {
  if (!currentStructDs.value) return
  const fields = structColumns.value.map(c => ({
    columnName: c.columnName,
    columnType: c.dataType,
    isPrimaryKey: !!c.isPrimaryKey,
    isNullable: !!c.isNullable,
    columnComment: c.comment || '',
    annotation: c.annotation || '',
    businessMeaning: c.businessMeaning || '',
    dataCategory: c.dataCategory || ''
  }))
  try {
    const res = await api.post(`/admin/dataset/${currentStructDs.value}/fields`, fields)
    if (res && res.success) {
      ElMessage.success(`标注已保存（${res.total} 个字段）`)
    }
  } catch (e: any) {
    ElMessage.error('标注保存失败: ' + (e.message || ''))
  }
}

// ==================== 指标 ====================
const indicators = ref<any[]>([])
const showIndDialog = ref(false)
const editingIndId = ref<string | null>(null)
const indForm = ref({ name: '', category: '', formula: '', description: '', weight: 0.5 })

async function loadIndicators() {
  try {
    const res = await api.get('/admin/indicator/list')
    if (res && res.success && res.indicators) {
      indicators.value = res.indicators
    }
  } catch (e) {
    console.warn('加载指标失败')
  }
}

function openAddIndicator() {
  editingIndId.value = null
  indForm.value = { name: '', category: '', formula: '', description: '', weight: 0.5 }
  showIndDialog.value = true
}

function openEditIndicator(row: any) {
  editingIndId.value = row.id
  indForm.value = {
    name: row.name,
    category: row.category,
    formula: row.formula || '',
    description: row.description || '',
    weight: row.weight ?? 0.5
  }
  showIndDialog.value = true
}

async function saveIndicator() {
  if (!indForm.value.name || !indForm.value.category) {
    ElMessage.warning('请填写完整信息')
    return
  }
  try {
    if (editingIndId.value) {
      await api.put(`/admin/indicator/${editingIndId.value}`, indForm.value)
      loadIndicators()
      ElMessage.success('指标已更新')
    } else {
      const res = await api.post('/admin/indicator', indForm.value)
      if (res && res.success) {
        indicators.value.push({
          id: res.id,
          ...indForm.value
        })
        ElMessage.success('指标已创建')
      }
    }
    showIndDialog.value = false
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.message || '未知错误'))
  }
}

async function deleteIndicator(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除指标"${row.name}"吗？`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    await api.delete(`/admin/indicator/${row.id}`)
    indicators.value = indicators.value.filter((i: any) => i.id !== row.id)
    ElMessage.success('已删除')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ==================== 指标关联 ====================
const showLinkDialog = ref(false)
const linkingIndId = ref<string>('')
const linkFields = ref<any[]>([])
const linkForm = ref({ datasetId: '', calculationMethod: '' })

function getDsName(dsId: string) {
  const ds = datasets.value.find((d: any) => d.id === dsId)
  return ds ? ds.name : dsId
}

async function openIndicatorLink(row: any) {
  linkingIndId.value = row.id
  linkForm.value = { datasetId: row.datasetId || '', calculationMethod: row.calculationMethod || '' }
  linkFields.value = []

  // Load existing linkage data
  try {
    const res = await api.get(`/admin/indicator/${row.id}/linkage`)
    if (res && res.success && res.data) {
      linkForm.value.datasetId = res.data.datasetId || ''
      linkForm.value.calculationMethod = res.data.calculationMethod || ''

      if (res.data.linkedFields) {
        // Parse field mapping
        let mapping: Record<string, number> = {}
        try {
          if (res.data.fieldMapping) mapping = JSON.parse(res.data.fieldMapping)
        } catch {}

        linkFields.value = res.data.linkedFields.map((f: any) => ({
          columnName: f.columnName,
          annotation: f.annotation || f.columnComment || '',
          mapWeight: mapping[f.columnName] ?? 0
        }))
      }
    }
  } catch {}

  // If no fields loaded yet but dataset is set, load fields
  if (linkFields.value.length === 0 && linkForm.value.datasetId) {
    await loadLinkFields()
  }

  showLinkDialog.value = true
}

async function onLinkDatasetChange(dsId: string) {
  linkForm.value.datasetId = dsId
  linkFields.value = []
  if (dsId) await loadLinkFields()
}

async function loadLinkFields() {
  try {
    const res = await api.get(`/admin/dataset/${linkForm.value.datasetId}/fields`)
    if (res && res.success && res.fields) {
      linkFields.value = res.fields.map((f: any) => ({
        columnName: f.columnName,
        annotation: f.annotation || f.columnComment || '',
        mapWeight: 0
      }))
    }
  } catch { /* ignore */ }
}

async function saveIndicatorLink() {
  if (!linkingIndId.value) return
  // Build field mapping from weights
  const mapping: Record<string, number> = {}
  linkFields.value.forEach(f => {
    if (f.mapWeight > 0) mapping[f.columnName] = f.mapWeight
  })

  try {
    const body: any = {
      datasetId: linkForm.value.datasetId || null,
      fieldMapping: JSON.stringify(mapping),
      calculationMethod: linkForm.value.calculationMethod
    }
    await api.post(`/admin/indicator/${linkingIndId.value}/link-dataset`, body)
    ElMessage.success('指标关联已保存')
    showLinkDialog.value = false
    loadIndicators()
  } catch (e: any) {
    ElMessage.error('保存关联失败: ' + (e.message || ''))
  }
}

// ==================== 大模型 多配置管理 ====================
const llmConfigs = ref<any[]>([])
const showLlmDialog = ref(false)
const editingLlmId = ref('')
const llmForm = ref({
  name: '', type: 'deepseek', apiUrl: '', apiKey: '', model: '',
  temperature: 0.7, maxTokens: 2000, topP: 0.9
})

const tempMarks = { 0: '0', 0.5: '0.5', 1: '1' }
const topPMarks = { 0: '0', 0.5: '0.5', 1: '1' }

const llmPresets: Record<string, Partial<any>> = {
  deepseek:  { apiUrl: 'https://api.deepseek.com/v1',            model: 'deepseek-chat' },
  openai:    { apiUrl: 'https://api.openai.com/v1',              model: 'gpt-4o' },
  qwen:      { apiUrl: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-turbo' },
  chatglm:   { apiUrl: 'https://open.bigmodel.cn/api/paas/v4',   model: 'glm-4' },
  vllm:      { apiUrl: 'http://localhost:8000/v1',               model: 'Qwen2.5-7B-Instruct' },
}

const modelPlaceholder = computed(() => {
  const presets: Record<string, string> = {
    deepseek: 'deepseek-chat', openai: 'gpt-4o', qwen: 'qwen-turbo',
    chatglm: 'glm-4', vllm: 'Qwen2.5-7B-Instruct'
  }
  return presets[llmForm.value.type] || '请输入模型名称'
})
const apiUrlPlaceholder = computed(() => {
  const presets: Record<string, string> = {
    deepseek: 'https://api.deepseek.com/v1', openai: 'https://api.openai.com/v1',
    qwen: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    chatglm: 'https://open.bigmodel.cn/api/paas/v4', vllm: 'http://localhost:8000/v1'
  }
  return presets[llmForm.value.type] || '请输入API地址'
})
const apiKeyTypeVal = computed(() => llmForm.value.type === 'vllm' ? 'text' : 'password')
const apiKeyPlaceholderVal = computed(() => llmForm.value.type === 'vllm' ? '本地部署无需密钥' : '请输入API Key')

// 切换类型时自动填充默认值
watch(() => llmForm.value.type, (newType) => {
  const preset = llmPresets[newType]
  if (preset) {
    if (preset.apiUrl) llmForm.value.apiUrl = preset.apiUrl as string
    if (preset.model) llmForm.value.model = preset.model as string
    if (newType === 'vllm') llmForm.value.apiKey = ''
  }
})

function openLlmDialog(row?: any) {
  if (row) {
    editingLlmId.value = row.id
    llmForm.value = {
      name: row.name || '', type: row.type || 'deepseek', apiUrl: row.apiUrl || '',
      apiKey: row.apiKey || '', model: row.model || '',
      temperature: row.temperature ?? 0.7, maxTokens: row.maxTokens ?? 2000, topP: row.topP ?? 0.9
    }
  } else {
    editingLlmId.value = ''
    llmForm.value = { name: '', type: 'deepseek', apiUrl: '', apiKey: '', model: '', temperature: 0.7, maxTokens: 2000, topP: 0.9 }
  }
  showLlmDialog.value = true
}

async function saveLlmConfig() {
  if (!llmForm.value.name.trim()) { ElMessage.warning('请输入配置名称'); return }
  try {
    if (editingLlmId.value) {
      await api.put(`/admin/config/llm/${editingLlmId.value}`, llmForm.value)
      ElMessage.success('配置已更新')
    } else {
      const res = await api.post('/admin/config/llm', llmForm.value)
      ElMessage.success(res.message || '配置已保存')
    }
    showLlmDialog.value = false
    loadLlmConfigs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '保存失败')
  }
}

async function activateLlmConfig(row: any) {
  try {
    await api.put(`/admin/config/llm/${row.id}/activate`)
    ElMessage.success(`已切换至: ${row.name}`)
    loadLlmConfigs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '切换失败')
  }
}

async function deleteLlmConfig(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除配置「${row.name}」吗？`, '确认', { type: 'warning' })
    await api.delete(`/admin/config/llm/${row.id}`)
    ElMessage.success('配置已删除')
    loadLlmConfigs()
  } catch { /* cancelled */ }
}

async function loadLlmConfigs() {
  try {
    const res = await api.get('/admin/config/llm/list')
    if (res && res.success) {
      llmConfigs.value = res.configs || []
    }
  } catch {}
}

// ==================== 初始化 ====================
onMounted(() => {
  loadDatabases()
  loadDrivers()
  loadDatasets()
  loadIndicators()
  loadLlmConfigs()
})
</script>

<style scoped>
.admin-container { height: 100%; padding: 2rem; overflow-y: auto; }
.admin-tabs { background: rgba(255, 255, 255, 0.95); border-radius: 12px; padding: 1.5rem; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
.tab-content { padding: 1rem 0; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
.section-header h3 { margin: 0; color: #303133; font-size: 1.1rem; font-weight: 600; }
.llm-form { max-width: 600px; }
</style>
