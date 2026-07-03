<template>
  <Layout>
    <div class="admin-container">
      <el-tabs v-model="activeTab" class="admin-tabs">
        <el-tab-pane label="数据库配置" name="database">
          <div class="tab-content">
            <div class="section-header">
              <h3>已配置的数据库</h3>
              <el-button type="primary" @click="showAddDatabase = true">新增数据库</el-button>
            </div>

            <el-table :data="databases" style="width: 100%" stripe>
              <el-table-column prop="name" label="名称" width="150" />
              <el-table-column prop="type" label="类型" width="120">
                <template #default="scope">
                  <el-tag :type="getDbTypeTag(scope.row.type)">{{ scope.row.type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="host" label="主机" width="150" />
              <el-table-column prop="port" label="端口" width="100" />
              <el-table-column prop="database" label="数据库" width="150" />
              <el-table-column prop="status" label="状态" width="100">
                <template #default="scope">
                  <el-tag :type="scope.row.status === '已连接' ? 'success' : 'info'">
                    {{ scope.row.status }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="250">
                <template #default="scope">
                  <el-button size="small" @click="testConnection(scope.row)">测试连接</el-button>
                  <el-button size="small" @click="editDatabase(scope.row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteDatabase(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <el-divider />

            <div class="section-header">
              <h3>数据库驱动管理</h3>
              <el-button @click="showUploadDriver = true">上传驱动</el-button>
            </div>

            <el-table :data="drivers" style="width: 100%" stripe>
              <el-table-column prop="name" label="驱动名称" width="180" />
              <el-table-column prop="driverClass" label="驱动类" />
              <el-table-column prop="defaultJar" label="默认JAR包" />
              <el-table-column label="类型" width="100">
                <template #default="scope">
                  <el-tag :type="scope.row.isBuiltIn ? 'success' : 'info'" size="small">
                    {{ scope.row.isBuiltIn ? '内置' : '自定义' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="120">
                <template #default="scope">
                  <el-button 
                    size="small" 
                    type="danger" 
                    :disabled="scope.row.isBuiltIn"
                    @click="deleteDriver(scope.row)"
                  >
                    删除
                  </el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="数据集管理" name="dataset">
          <div class="tab-content">
            <div class="section-header">
              <h3>数据集列表</h3>
              <el-button type="primary" @click="showAddDataset = true">创建数据集</el-button>
            </div>

            <el-table :data="datasets" style="width: 100%" stripe>
              <el-table-column prop="name" label="名称" width="180" />
              <el-table-column prop="description" label="描述" />
              <el-table-column prop="databaseId" label="关联数据库" width="150" />
              <el-table-column prop="records" label="记录数" width="100" />
              <el-table-column label="操作" width="200">
                <template #default="scope">
                  <el-button size="small" @click="viewDataset(scope.row)">查看</el-button>
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
              <el-button type="primary" @click="showAddIndicator = true">新建指标</el-button>
            </div>

            <el-table :data="indicators" style="width: 100%" stripe>
              <el-table-column prop="name" label="指标名称" width="180" />
              <el-table-column prop="category" label="分类" width="150" />
              <el-table-column prop="formula" label="计算公式" />
              <el-table-column label="操作" width="200">
                <template #default="scope">
                  <el-button size="small" @click="viewIndicator(scope.row)">查看</el-button>
                  <el-button size="small" @click="editIndicator(scope.row)">编辑</el-button>
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
              <el-button type="primary" @click="saveLlmConfig">保存配置</el-button>
            </div>

            <el-form :model="llmConfig" label-width="120px" class="llm-form">
              <el-form-item label="模型类型">
                <el-select v-model="llmConfig.type" placeholder="请选择模型类型" style="width: 100%">
                  <el-option label="DeepSeek" value="deepseek" />
                  <el-option label="OpenAI兼容" value="openai" />
                  <el-option label="Ollama（本地部署）" value="ollama" />
                  <el-option label="Qwen（通义千问）" value="qwen" />
                  <el-option label="ChatGLM（智谱）" value="chatglm" />
                </el-select>
              </el-form-item>
              <el-form-item label="模型名称">
                <el-input v-model="llmConfig.model" placeholder="deepseek-chat" />
              </el-form-item>
              <el-form-item label="API地址">
                <el-input v-model="llmConfig.apiUrl" placeholder="https://api.deepseek.com/v1" />
              </el-form-item>
              <el-form-item label="API密钥">
                <el-input v-model="llmConfig.apiKey" type="password" placeholder="sk-xxxxxxxxxxxxxxxx" show-password />
                <div class="form-tip">Ollama 本地部署无需填写密钥</div>
              </el-form-item>
              <el-form-item label="Temperature">
                <el-slider v-model="llmConfig.temperature" :min="0" :max="1" :step="0.1" show-stops :marks="tempMarks" />
              </el-form-item>
              <el-form-item label="Max Tokens">
                <el-input-number v-model="llmConfig.maxTokens" :min="100" :max="8000" :step="100" />
              </el-form-item>
              <el-form-item label="Top P">
                <el-slider v-model="llmConfig.topP" :min="0" :max="1" :step="0.1" />
              </el-form-item>
            </el-form>
          </div>
        </el-tab-pane>
      </el-tabs>

      <el-dialog v-model="showAddDatabase" title="新增数据库" width="600px">
        <el-form :model="databaseForm" label-width="100px">
          <el-form-item label="数据库名称">
            <el-input v-model="databaseForm.name" placeholder="请输入数据库名称" />
          </el-form-item>
          <el-form-item label="数据库类型">
            <el-select v-model="databaseForm.type" placeholder="请选择数据库类型" style="width: 100%">
              <el-option label="MySQL" value="MySQL" />
              <el-option label="PostgreSQL" value="PostgreSQL" />
              <el-option label="Oracle" value="Oracle" />
              <el-option label="达梦数据库V8.1" value="达梦数据库V8.1" />
              <el-option label="SQL Server" value="SQL Server" />
            </el-select>
          </el-form-item>
          <el-form-item label="主机地址">
            <el-input v-model="databaseForm.host" placeholder="请输入主机地址" />
          </el-form-item>
          <el-form-item label="端口">
            <el-input-number v-model="databaseForm.port" :min="1" :max="65535" />
          </el-form-item>
          <el-form-item label="数据库名">
            <el-input v-model="databaseForm.database" placeholder="请输入数据库名" />
          </el-form-item>
          <el-form-item label="用户名">
            <el-input v-model="databaseForm.username" placeholder="请输入用户名" />
          </el-form-item>
          <el-form-item label="密码">
            <el-input v-model="databaseForm.password" type="password" placeholder="请输入密码" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddDatabase = false">取消</el-button>
          <el-button type="primary" @click="addDatabase">确定</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showUploadDriver" title="上传数据库驱动" width="500px">
        <el-form label-width="100px">
          <el-form-item label="驱动名称">
            <el-input v-model="driverForm.name" placeholder="请输入驱动名称" />
          </el-form-item>
          <el-form-item label="驱动类">
            <el-input v-model="driverForm.driverClass" placeholder="请输入驱动类名，如：dm.jdbc.driver.DmDriver" />
          </el-form-item>
          <el-form-item label="选择JAR包">
            <el-upload
              ref="driverUploadRef"
              :auto-upload="false"
              :limit="1"
              accept=".jar"
              :on-change="handleDriverFileChange"
            >
              <el-button type="primary">选择JAR文件</el-button>
              <template #tip>
                <div class="el-upload__tip">支持JAR格式的数据库驱动文件</div>
              </template>
            </el-upload>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showUploadDriver = false">取消</el-button>
          <el-button type="primary" @click="uploadDriver">上传</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showAddDataset" title="创建数据集" width="600px">
        <el-form :model="datasetForm" label-width="100px">
          <el-form-item label="数据集名称">
            <el-input v-model="datasetForm.name" placeholder="请输入数据集名称" />
          </el-form-item>
          <el-form-item label="数据集描述">
            <el-input v-model="datasetForm.description" type="textarea" :rows="3" placeholder="请输入数据集描述" />
          </el-form-item>
          <el-form-item label="关联数据库">
            <el-select v-model="datasetForm.databaseId" placeholder="请选择关联数据库" style="width: 100%">
              <el-option
                v-for="db in databases"
                :key="db.id"
                :label="db.name"
                :value="db.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="SQL查询">
            <el-input v-model="datasetForm.sql" type="textarea" :rows="5" placeholder="请输入SQL查询语句" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddDataset = false">取消</el-button>
          <el-button type="primary" @click="addDataset">创建</el-button>
        </template>
      </el-dialog>

      <el-dialog v-model="showAddIndicator" title="新建指标" width="600px">
        <el-form :model="indicatorForm" label-width="100px">
          <el-form-item label="指标名称">
            <el-input v-model="indicatorForm.name" placeholder="请输入指标名称" />
          </el-form-item>
          <el-form-item label="指标分类">
            <el-select v-model="indicatorForm.category" placeholder="请选择分类" style="width: 100%">
              <el-option label="综合指标" value="综合指标" />
              <el-option label="性能指标" value="性能指标" />
              <el-option label="效能指标" value="效能指标" />
              <el-option label="保障指标" value="保障指标" />
            </el-select>
          </el-form-item>
          <el-form-item label="计算公式">
            <el-input v-model="indicatorForm.formula" type="textarea" :rows="3" placeholder="请输入计算公式" />
          </el-form-item>
          <el-form-item label="指标说明">
            <el-input v-model="indicatorForm.description" type="textarea" :rows="3" placeholder="请输入指标详细说明" />
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="indicatorForm.weight" :min="0" :max="1" :step="0.1" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showAddIndicator = false">取消</el-button>
          <el-button type="primary" @click="addIndicator">创建</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const activeTab = ref('database')

const databases = ref<any[]>([
  { id: '1', name: '评估数据库', type: 'PostgreSQL', host: 'localhost', port: 5432, database: 'assessment_db', username: 'admin', status: '已连接' },
  { id: '2', name: '知识库', type: 'MySQL', host: 'localhost', port: 3306, database: 'knowledge_db', username: 'root', status: '已连接' },
  { id: '3', name: '作战数据', type: '达梦数据库V8.1', host: '192.168.1.100', port: 5236, database: 'combat_db', username: 'SYSDBA', status: '未连接' }
])

const drivers = ref<any[]>([
  { id: '1', name: 'MySQL', driverClass: 'com.mysql.cj.jdbc.Driver', defaultJar: 'mysql-connector-java-8.0.33.jar', isBuiltIn: true },
  { id: '2', name: 'PostgreSQL', driverClass: 'org.postgresql.Driver', defaultJar: 'postgresql-42.6.0.jar', isBuiltIn: true },
  { id: '3', name: '达梦数据库V8.1', driverClass: 'dm.jdbc.driver.DmDriver', defaultJar: 'DmJdbcDriver18.jar', isBuiltIn: true },
  { id: '4', name: 'Oracle', driverClass: 'oracle.jdbc.OracleDriver', defaultJar: 'ojdbc11.jar', isBuiltIn: true },
  { id: '5', name: 'SQL Server', driverClass: 'com.microsoft.sqlserver.jdbc.SQLServerDriver', defaultJar: 'mssql-jdbc-12.4.2.jar', isBuiltIn: true }
])

const datasets = ref<any[]>([
  { id: '1', name: '作战效能数据', description: '包含各类作战效能评估数据', databaseId: '评估数据库', records: 1250 },
  { id: '2', name: '打击能力数据', description: '武器系统打击能力相关数据', databaseId: '作战数据', records: 3480 },
  { id: '3', name: '生存能力评估', description: '装备生存能力评估数据', databaseId: '作战数据', records: 890 }
])

const indicators = ref<any[]>([
  { id: '1', name: '作战效能指数', category: '综合指标', formula: '(打击能力 + 生存能力 + 保障能力) / 3' },
  { id: '2', name: '打击能力指数', category: '性能指标', formula: '命中率 × 摧毁率' },
  { id: '3', name: '任务完成度', category: '效能指标', formula: '完成任务数 / 总任务数 × 100%' }
])

const llmConfig = ref({
  type: 'deepseek',
  apiUrl: 'https://api.deepseek.com/v1',
  apiKey: '',
  model: 'deepseek-chat',
  temperature: 0.7,
  maxTokens: 2000,
  topP: 0.9
})

const tempMarks = {
  0: '0',
  0.5: '0.5',
  1: '1'
}

const showAddDatabase = ref(false)
const showUploadDriver = ref(false)
const showAddDataset = ref(false)
const showAddIndicator = ref(false)

const databaseForm = ref({
  name: '',
  type: '',
  host: '',
  port: 5432,
  database: '',
  username: '',
  password: ''
})

const driverForm = ref({
  name: '',
  driverClass: ''
})

const datasetForm = ref({
  name: '',
  description: '',
  databaseId: '',
  sql: ''
})

const indicatorForm = ref({
  name: '',
  category: '',
  formula: '',
  description: '',
  weight: 0.5
})

const driverUploadRef = ref()

const getDbTypeTag = (type: string) => {
  const typeMap: Record<string, string> = {
    'MySQL': 'primary',
    'PostgreSQL': 'success',
    'Oracle': 'warning',
    '达梦数据库V8.1': 'danger',
    'SQL Server': 'info'
  }
  return typeMap[type] || 'info'
}

const testConnection = (row: any) => {
  ElMessage.success(`正在测试连接：${row.name}`)
  setTimeout(() => {
    row.status = '已连接'
    ElMessage.success('连接测试成功！')
  }, 1000)
}

const editDatabase = (row: any) => {
  databaseForm.value = { ...row }
  showAddDatabase.value = true
}

const deleteDatabase = (row: any) => {
  ElMessageBox.confirm(`确定删除数据库"${row.name}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    databases.value = databases.value.filter(d => d.id !== row.id)
    ElMessage.success('删除成功')
  }).catch(() => {})
}

const addDatabase = () => {
  if (!databaseForm.value.name || !databaseForm.value.type) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  const newDb = {
    id: Date.now().toString(),
    ...databaseForm.value,
    status: '未连接'
  }
  
  databases.value.push(newDb)
  showAddDatabase.value = false
  databaseForm.value = { name: '', type: '', host: '', port: 5432, database: '', username: '', password: '' }
  ElMessage.success('数据库添加成功')
}

const handleDriverFileChange = (file: any) => {
  ElMessage.info(`已选择文件：${file.name}`)
}

const uploadDriver = () => {
  if (!driverForm.value.name || !driverForm.value.driverClass) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  const newDriver = {
    id: Date.now().toString(),
    ...driverForm.value,
    defaultJar: '用户上传',
    isBuiltIn: false
  }
  
  drivers.value.push(newDriver)
  showUploadDriver.value = false
  driverForm.value = { name: '', driverClass: '' }
  ElMessage.success('驱动上传成功')
}

const deleteDriver = (row: any) => {
  ElMessageBox.confirm(`确定删除驱动"${row.name}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    drivers.value = drivers.value.filter(d => d.id !== row.id)
    ElMessage.success('删除成功')
  }).catch(() => {})
}

const viewDataset = (row: any) => {
  ElMessage.info(`查看数据集：${row.name}`)
}

const editDataset = (row: any) => {
  datasetForm.value = { ...row }
  showAddDataset.value = true
}

const deleteDataset = (row: any) => {
  ElMessageBox.confirm(`确定删除数据集"${row.name}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    datasets.value = datasets.value.filter(d => d.id !== row.id)
    ElMessage.success('删除成功')
  }).catch(() => {})
}

const addDataset = () => {
  if (!datasetForm.value.name) {
    ElMessage.warning('请填写数据集名称')
    return
  }
  
  const newDataset = {
    id: Date.now().toString(),
    ...datasetForm.value,
    records: 0
  }
  
  datasets.value.push(newDataset)
  showAddDataset.value = false
  datasetForm.value = { name: '', description: '', databaseId: '', sql: '' }
  ElMessage.success('数据集创建成功')
}

const viewIndicator = (row: any) => {
  ElMessage.info(`查看指标：${row.name}`)
}

const editIndicator = (row: any) => {
  indicatorForm.value = { ...row }
  showAddIndicator.value = true
}

const deleteIndicator = (row: any) => {
  ElMessageBox.confirm(`确定删除指标"${row.name}"吗？`, '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(() => {
    indicators.value = indicators.value.filter(i => i.id !== row.id)
    ElMessage.success('删除成功')
  }).catch(() => {})
}

const addIndicator = () => {
  if (!indicatorForm.value.name || !indicatorForm.value.category) {
    ElMessage.warning('请填写完整信息')
    return
  }
  
  const newIndicator = {
    id: Date.now().toString(),
    ...indicatorForm.value
  }
  
  indicators.value.push(newIndicator)
  showAddIndicator.value = false
  indicatorForm.value = { name: '', category: '', formula: '', description: '', weight: 0.5 }
  ElMessage.success('指标创建成功')
}

const saveLlmConfig = async () => {
  try {
    // 保存到后端
    await api.post('/config/llm', llmConfig.value)
    
    // 同时保存到本地存储作为备份
    localStorage.setItem('llmConfig', JSON.stringify(llmConfig.value))
    
    ElMessage.success('大模型配置保存成功')
  } catch (e) {
    // 即使后端保存失败，也保存到本地存储
    localStorage.setItem('llmConfig', JSON.stringify(llmConfig.value))
    ElMessage.warning('后端保存失败，但配置已保存到本地，刷新后将自动加载')
  }
}

const loadLlmConfig = async () => {
  // 首先尝试从本地存储加载
  const savedConfig = localStorage.getItem('llmConfig')
  if (savedConfig) {
    try {
      const config = JSON.parse(savedConfig)
      llmConfig.value = config
      console.log('✓ 从本地存储加载大模型配置成功')
    } catch (e) {
      console.error('加载本地配置失败:', e)
    }
  }
  
  // 然后尝试从后端加载（优先使用后端配置）
  try {
    const response = await api.get('/config/llm')
    if (response && response.success && response.data) {
      llmConfig.value = response.data
      // 保存到本地存储
      localStorage.setItem('llmConfig', JSON.stringify(response.data))
      console.log('✓ 从服务器加载大模型配置成功')
    }
  } catch (err) {
    console.warn('无法从服务器加载配置，将使用现有配置:', err)
  }
}

onMounted(() => {
  ElMessage.info('基础管理系统加载完成')
  loadLlmConfig()
})
</script>

<style scoped>
.admin-container {
  height: 100%;
  padding: 2rem;
  overflow-y: auto;
}

.admin-tabs {
  background: rgba(255, 255, 255, 0.95);
  border-radius: 12px;
  padding: 1.5rem;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
}

.tab-content {
  padding: 1rem 0;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}

.section-header h3 {
  margin: 0;
  color: #303133;
  font-size: 1.1rem;
  font-weight: 600;
}

.llm-form {
  max-width: 600px;
}
.form-tip {
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}

</style>
