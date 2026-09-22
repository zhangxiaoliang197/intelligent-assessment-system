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
              <el-table-column prop="urlTemplate" label="连接模板" min-width="250" show-overflow-tooltip />
              <el-table-column label="状态" width="80">
                <template #default="scope">
                  <el-tag :type="scope.row.hasJar ? 'success' : 'warning'" size="small">
                    {{ scope.row.hasJar ? '已上传' : '待上传' }}
                  </el-tag>
                </template>
              </el-table-column>
              <el-table-column label="JAR文件" min-width="140">
                <template #default="scope">
                  <span v-if="scope.row.jarFileName" style="font-size:12px;color:#909399">{{ scope.row.jarFileName }}</span>
                  <span v-else style="color:#c0c4cc">-</span>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="80">
                <template #default="scope">
                  <el-button size="small" type="danger" @click="deleteDriver(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>

            <!-- 上传驱动对话框 -->
            <el-dialog v-model="showUploadDriver" title="上传数据库驱动" width="500px">
              <el-form :model="driverForm" label-width="100px">
                <el-form-item label="数据库类型" required>
                  <el-select v-model="driverForm.type" placeholder="请选择数据库类型" style="width: 100%" @change="onDriverTypeChange">
                    <el-option v-for="d in driverPresets" :key="d" :label="d" :value="d" />
                  </el-select>
                </el-form-item>
                <el-form-item label="驱动名称" required>
                  <el-input v-model="driverForm.name" placeholder="如：MySQL 8.0、PostgreSQL 16" />
                </el-form-item>
                <el-form-item label="JAR包" required>
                  <el-upload ref="driverUploadRef" :auto-upload="false" :limit="1" accept=".jar" :on-change="onDriverFileChange">
                    <el-button>选择JAR文件</el-button>
                    <template #tip><div class="el-upload__tip">同一数据库不同版本可上传不同JAR包</div></template>
                  </el-upload>
                </el-form-item>
              </el-form>
              <template #footer>
                <el-button @click="showUploadDriver = false">取消</el-button>
                <el-button type="primary" @click="uploadDriver" :loading="uploadingDriver">上传</el-button>
              </template>
            </el-dialog>
          </div>
        </el-tab-pane>

        <el-tab-pane label="数据集管理" name="dataset">
          <div class="tab-content">
            <div class="section-header">
              <h3>数据集列表</h3>
              <div>
                <el-button style="margin-right:8px" @click="toggleAllGroups">
                  {{ allGroupsExpanded ? '全部收起' : '全部展开' }}
                </el-button>
                <el-button type="primary" @click="openSelectDataset">选择数据集</el-button>
              </div>
            </div>

            <!-- 按数据源分层：组头显示库信息与注解状态，组内沿用原有表格与全部操作 -->
            <el-collapse v-model="expandedGroups" class="ds-groups">
              <el-collapse-item
                v-for="group in groupedDatasets"
                :key="group.key"
                :name="group.key"
              >
                <template #title>
                  <div class="ds-group-title">
                    <span class="ds-group-name">{{ group.name }}</span>
                    <el-tag v-if="group.missingDb" size="small" type="danger" effect="plain">数据源缺失</el-tag>
                    <span class="ds-group-meta">{{ group.meta }}</span>
                    <el-tag size="small" type="info" effect="plain">{{ group.datasets.length }} 个数据集</el-tag>
                    <el-tag v-if="group.unvalidated" size="small" type="warning" effect="plain">
                      未校验 {{ group.unvalidated }}
                    </el-tag>
                    <!-- 数据源缺失/未关联时，提供一键改指（@click.stop 避免触发展开收起） -->
                    <el-button
                      v-if="group.rank > 0"
                      size="small"
                      type="warning"
                      link
                      @click.stop="openReassignDialog(group)"
                    >{{ group.missingDb ? '重新指定数据源' : '指定数据源' }}</el-button>
                  </div>
                </template>

                <el-table :data="group.datasets" stripe>
                  <el-table-column prop="name" label="名称" min-width="160" />
                  <el-table-column prop="description" label="描述" />
                  <el-table-column prop="tableName" label="数据表" width="150" />
                  <el-table-column prop="records" label="记录数" width="85" />
                  <el-table-column label="注解状态" width="150">
                    <template #default="scope">
                      <el-tag v-if="scope.row.annotationValidatedAt" type="success" size="small">
                        已校验 {{ formatValidatedAt(scope.row.annotationValidatedAt) }}
                      </el-tag>
                      <el-tag v-else type="info" size="small">未校验</el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" min-width="500">
                    <template #default="scope">
                      <el-button size="small" @click="openTableStructure(scope.row)">表结构</el-button>
                      <el-button size="small" @click="openDatasetSemantic(scope.row)">语义注解</el-button>
                      <el-button size="small" @click="validateAnnotations(scope.row)">校验注解</el-button>
                      <el-button size="small" @click="openAnnotationDrafts(scope.row)">AI 注解草稿</el-button>
                      <el-button size="small" @click="editDataset(scope.row)">编辑</el-button>
                      <el-button size="small" type="danger" @click="deleteDataset(scope.row)">删除</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </el-collapse-item>
            </el-collapse>

            <el-empty v-if="groupedDatasets.length === 0" description="暂无数据集" />
          </div>
        </el-tab-pane>

        <el-tab-pane label="指标管理" name="indicator">
          <div class="tab-content">
            <div class="section-header">
              <h3>评估指标库</h3>
              <div>
                <el-button type="primary" @click="openAddIndicator">新建指标</el-button>
                <el-button style="margin-left:8px" @click="openKbImport">从知识库导入</el-button>
              </div>
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
                  <el-button size="small" type="primary" @click="openIndicatorSpec(scope.row)">配置规格</el-button>
                  <el-button size="small" @click="openEditIndicator(scope.row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteIndicator(scope.row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <el-tab-pane label="语义目录" name="catalog">
          <div class="tab-content">
            <div class="section-header">
              <h3>语义目录（业务概念 → 物理列）</h3>
              <div>
                <el-select v-model="catalogFilterDb" placeholder="数据源" clearable style="width:180px;margin-right:8px" @change="loadSynonyms">
                  <el-option v-for="db in databases" :key="db.id" :label="db.name" :value="db.id" />
                </el-select>
                <el-input v-model="catalogKeyword" placeholder="搜索概念/表/列" clearable style="width:220px;margin-right:8px" @keyup.enter="loadSynonyms" />
                <el-button @click="loadSynonyms">搜索</el-button>
                <el-button type="primary" @click="openSynonymDialog()">新增同义词</el-button>
                <el-button @click="rebuildCatalogFromTab">重建索引</el-button>
              </div>
            </div>
            <el-table :data="synonyms" stripe v-loading="synonymsLoading">
              <el-table-column prop="concept" label="业务概念" min-width="150" />
              <el-table-column prop="tableName" label="表" width="150" />
              <el-table-column prop="columnName" label="列" width="150" />
              <el-table-column prop="columnComment" label="列注释" min-width="160" show-overflow-tooltip />
              <el-table-column prop="datasetName" label="数据集" min-width="120" />
              <el-table-column label="来源" width="110">
                <template #default="scope">
                  <el-tag size="small" :type="['manual', 'llm-confirmed'].includes(scope.row.source) ? 'success' : 'info'">{{ scope.row.source }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150">
                <template #default="scope">
                  <el-button size="small" @click="openSynonymDialog(scope.row)">编辑</el-button>
                  <el-button size="small" type="danger" @click="deleteSynonym(scope.row)">删除</el-button>
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
                  <el-tag size="small" :type="row.type === 'vllm' ? 'warning' : undefined">{{ row.type }}</el-tag>
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
              <el-table-column label="操作" width="270" align="center">
                <template #default="{ row }">
                  <el-button size="small" type="primary" plain :loading="row.testing" @click="testLlmConnection(row)">测试</el-button>
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
        <el-tab-pane label="地图服务配置" name="map">
          <div class="tab-content">
            <div class="section-header">
              <h3>地图服务配置</h3>
              <el-button type="primary" @click="openMapDialog()">新增配置</el-button>
            </div>

            <el-table :data="mapConfigs" style="width: 100%" stripe>
              <el-table-column type="index" label="#" width="50" />
              <el-table-column prop="name" label="配置名称" min-width="150" />
              <el-table-column prop="type" label="服务类型" width="130">
                <template #default="{ row }">
                  <el-tag size="small">{{ row.type }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="baseUrl" label="服务地址" min-width="200" show-overflow-tooltip />
              <el-table-column label="状态" width="100" align="center">
                <template #default="{ row }">
                  <el-tag v-if="row.isActive" type="success" size="small">使用中</el-tag>
                  <el-tag v-else type="info" size="small">未激活</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="270" align="center">
                <template #default="{ row }">
                  <el-button v-if="!row.isActive" type="success" size="small" @click="activateMapConfig(row)">启用</el-button>
                  <el-button v-else size="small" disabled>当前</el-button>
                  <el-button size="small" @click="openMapDialog(row)">编辑</el-button>
                  <el-button type="danger" size="small" @click="deleteMapConfig(row)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
            <div style="margin-top: 12px; color: #909399; font-size: 12px;">
              提示：点击「启用」将切换当前地图服务，智能问答、指标分析、评估分析中的地图将使用激活的服务。
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
            <!-- max_tokens 为单次输出上限，实际取值以所用模型 max_output_tokens 为准（如 deepseek-reasoner 等 reasoning 模型，24000-32000 已足够容纳 reasoning 思考链 + content；超过模型上限会被网关拒绝 HTTP 400） -->
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

      <!-- 地图服务配置 新增/编辑对话框 -->
      <el-dialog v-model="showMapDialog" :title="editingMapId ? '编辑地图服务' : '新增地图服务'" width="500px">
        <el-form :model="mapForm" label-width="80px">
          <el-form-item label="配置名称" required>
            <el-input v-model="mapForm.name" placeholder="如：GeoWebCache 内网地图、高德瓦片服务" />
          </el-form-item>
          <el-form-item label="服务类型">
            <el-select v-model="mapForm.type" placeholder="请选择服务类型" style="width: 100%">
              <el-option label="GeoWebCache" value="geowebcache" />
              <el-option label="自定义瓦片服务" value="custom" />
              <el-option label="高德地图" value="amap" />
            </el-select>
          </el-form-item>
          <el-form-item label="服务地址">
            <el-input v-model="mapForm.baseUrl" :disabled="mapForm.type === 'amap'" :placeholder="mapForm.type === 'geowebcache' ? '如：/geowebcache 或 http://192.168.1.100:9090/geowebcache' : mapForm.type === 'amap' ? '高德地图无需配置服务地址' : '如：http://192.168.1.100:9090/tiles/{z}/{x}/{y}.png'" />
          </el-form-item>
          <div style="color: #909399; font-size: 12px; margin-top: 8px;">
            <template v-if="mapForm.type === 'geowebcache'">GeoWebCache 将自动叠加 6 层标准图层（省级、城市、水域、水系、道路、铁路）。</template>
            <template v-else-if="mapForm.type === 'amap'">高德地图将自动加载矢量底图与路网注记（GCJ02 坐标，与前端标注坐标一致，无需服务地址）。</template>
            <template v-else>自定义服务将使用地址作为单层瓦片源。</template>
          </div>
        </el-form>
        <template #footer>
          <el-button @click="showMapDialog = false">取消</el-button>
          <el-button type="primary" @click="saveMapConfig">{{ editingMapId ? '保存' : '创建' }}</el-button>
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
              <el-option v-for="d in drivers" :key="d.id" :label="d.name + (d.hasJar ? '' : ' (需上传JAR)')" :value="d.name" :disabled="!d.hasJar" />
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

      <!-- 选择数据集对话框 -->
      <el-dialog v-model="showSelectDsDialog" title="选择数据集" width="700px">
        <div style="margin-bottom: 16px;">
          <span style="color: #606266; font-weight: 500;">选择数据库：</span>
          <el-select v-model="selectDsDbId" placeholder="请选择已连接的数据库" style="width: 300px; margin-left: 8px;" @change="onSelectDsDbChange" :loading="loadingDbTables">
            <el-option v-for="db in connectedDatabases" :key="db.id" :label="db.name" :value="db.id" />
          </el-select>
        </div>

        <div v-if="selectDsDbId && !loadingDbTables">
          <div style="margin-bottom: 12px; color: #606266;">
            <span>数据表列表</span>
            <span style="margin-left: 12px; color: #909399; font-size: 12px;">
              共 {{ dbTables.length }} 张表，可勾选多张后批量注册，也可单张「选择」
            </span>
          </div>
          <el-table :data="dbTables" stripe max-height="400" @selection-change="onTableSelectionChange">
            <el-table-column type="selection" width="45" />
            <el-table-column type="index" label="#" width="50" />
            <el-table-column prop="tableName" label="表名" min-width="200" />
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button type="primary" size="small" @click.stop="onSelectTable(row)">选择</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <div v-if="selectDsDbId && loadingDbTables" style="text-align: center; padding: 40px; color: #909399;">
          <el-icon class="is-loading"><Loading /></el-icon>
          <span style="margin-left: 8px;">正在加载数据表...</span>
        </div>

        <div v-if="!selectDsDbId" style="text-align: center; padding: 40px; color: #909399;">
          请先选择一个已连接的数据库
        </div>

        <template #footer>
          <el-button @click="showSelectDsDialog = false">取消</el-button>
          <el-button
            type="primary"
            :disabled="selectedTables.length === 0"
            :loading="registeringTables"
            @click="confirmBatchRegister"
          >注册选中的 {{ selectedTables.length }} 张表</el-button>
        </template>
      </el-dialog>

      <!-- 重新指定数据源（数据源缺失/未关联分组一键改指） -->
      <el-dialog
        v-model="showReassignDialog"
        :title="reassignGroup?.missingDb ? '重新指定数据源' : '指定数据源'"
        width="560px"
      >
        <div style="color: #606266; line-height: 1.9;">
          <p style="margin: 0;">当前归属：<b>{{ reassignGroup?.name }}</b>（{{ reassignGroup?.meta }}）</p>
          <p style="margin: 0 0 8px;">将把该分组下 <b>{{ reassignGroup?.datasets?.length || 0 }}</b> 个数据集改指到：</p>
          <el-select v-model="reassignTargetDbId" placeholder="选择目标数据源" style="width: 100%">
            <el-option
              v-for="db in databases"
              :key="db.id"
              :label="`${db.name}（${db.type} · ${db.database}）`"
              :value="db.id"
            />
          </el-select>
          <p style="color: #e6a23c; font-size: 12px; margin: 12px 0 0;">
            提示：目标数据源需包含这些数据集对应的同名数据表，否则取数与注解校验仍会失败。
          </p>
        </div>
        <template #footer>
          <el-button @click="showReassignDialog = false">取消</el-button>
          <el-button
            type="primary"
            :disabled="!reassignTargetDbId"
            :loading="reassigning"
            @click="confirmReassign"
          >确认改指</el-button>
        </template>
      </el-dialog>

      <!-- AI 注解草稿审核抽屉：草稿未通过审核前不影响正式注解 -->
      <el-drawer v-model="showDraftDrawer" :title="`AI 注解草稿：${draftDatasetName}`" size="62%">
        <div class="draft-toolbar">
          <el-select v-model="draftStatus" size="small" style="width: 130px" @change="loadDrafts">
            <el-option label="待审" value="draft" />
            <el-option label="已通过" value="approved" />
            <el-option label="已驳回" value="rejected" />
            <el-option label="全部" value="" />
          </el-select>
          <el-button size="small" type="primary" :loading="draftGenerating" @click="generateDrafts">
            {{ draftItems.length ? '重新生成草稿' : '生成草稿（调用大模型）' }}
          </el-button>
          <el-button size="small" type="success" :disabled="!draftBatchId || draftStatus !== 'draft'"
                     @click="approveDraftBatch">整批通过</el-button>
          <el-button size="small" type="danger" plain :disabled="!draftBatchId || draftStatus !== 'draft'"
                     @click="rejectDraftBatch">整批驳回</el-button>
          <el-button size="small" plain :disabled="!draftBatchId" @click="discardDraftBatch">丢弃整批</el-button>
          <span class="draft-hint">
            草稿经「格式 + 结构 + 值域」三层校验；红色问题为硬错误（禁批量通过），需人工改写或驳回
          </span>
        </div>

        <el-empty v-if="!draftLoading && draftItems.length === 0"
                  description="暂无草稿：点上方「生成草稿」调用大模型产出建议" />
        <el-skeleton v-if="draftLoading" :rows="6" animated />

        <div v-for="item in draftItems" :key="item.id" class="draft-item">
          <div class="draft-head">
            <el-tag size="small" :type="item.scope === 'dataset' ? 'warning' : 'info'" effect="plain">
              {{ item.scope === 'dataset' ? '数据集级语义' : `字段 ${item.columnName}` }}
            </el-tag>
            <el-tag size="small" :type="draftStatusTag(item.status)">{{ draftStatusText(item.status) }}</el-tag>
            <span class="draft-meta">来源 {{ item.source }}｜模型 {{ item.model || '-' }}</span>
            <div class="draft-actions">
              <el-button v-if="item.status === 'draft'" size="small" type="success" plain
                         @click="approveDraft(item)">通过</el-button>
              <!-- 有硬错误时提供单条强制通过：需填理由、留痕；整批通过仍不接受带硬错误的条目 -->
              <el-button v-if="item.status === 'draft' && draftList(item.issuesJson).length" size="small"
                         type="warning" plain @click="forceApproveDraft(item)">强制通过</el-button>
              <el-button v-if="item.status === 'draft'" size="small" type="danger" plain
                         @click="rejectDraft(item)">驳回</el-button>
              <el-button v-if="item.status === 'rejected'" size="small" type="primary" plain
                         :loading="regeneratingId === item.id" @click="regenerateDraft(item)">按意见重生成</el-button>
            </div>
          </div>

          <el-input v-model="item.draftJson" type="textarea" :rows="3" size="small"
                    :disabled="item.status !== 'draft'"
                    @change="saveDraft(item)" />

          <div v-if="draftList(item.issuesJson).length" class="draft-issues">
            <div v-for="(issue, idx) in draftList(item.issuesJson)" :key="idx">✕ {{ issue }}</div>
          </div>
          <div v-if="draftList(item.warningsJson).length" class="draft-warnings">
            <div v-for="(warn, idx) in draftList(item.warningsJson)" :key="idx">! {{ warn }}</div>
          </div>
          <div v-if="draftList(item.sampledJson).length" class="draft-meta">
            真实取值样例：{{ draftList(item.sampledJson).join('、') }}
          </div>
          <div v-if="item.reviewRemark" class="draft-meta">驳回意见：{{ item.reviewRemark }}</div>
        </div>
      </el-drawer>

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
      <el-dialog v-model="showStructDialog" title="数据表结构" width="96%" top="3vh">
        <div v-if="structColumns.length > 0">
          <div style="margin-bottom:12px;color:#606266">
            <span>数据表：<strong>{{ currentStructTable }}</strong></span>
            <span style="margin-left:20px">共 {{ structColumns.length }} 个字段</span>
          </div>
          <el-table :data="structColumns" stripe max-height="400">
            <el-table-column prop="columnName" label="字段名" width="160">
              <template #default="scope">
                <div>{{ scope.row.columnName }}</div>
                <el-tooltip v-if="scope.row.semanticInvalid"
                  content="原 semanticJson 不是合法 JSON，已按空处理；保存后将以本次填写的内容覆盖">
                  <div style="color:#e6a23c;font-size:12px">原注解不是合法 JSON</div>
                </el-tooltip>
              </template>
            </el-table-column>
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
            <el-table-column label="字段角色" width="150">
              <template #default="scope">
                <el-select v-model="scope.row.role" placeholder="未设置" size="small" style="width:100%">
                  <el-option label="未设置" value="" />
                  <el-option v-for="r in SEMANTIC_ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="象形符号" width="130">
              <template #default="scope">
                <el-select v-model="scope.row.symbol" placeholder="未设置" size="small" style="width:100%">
                  <el-option label="未设置" value="" />
                  <el-option v-for="s in SEMANTIC_SYMBOL_OPTIONS" :key="s" :label="s" :value="s" />
                </el-select>
              </template>
            </el-table-column>
            <el-table-column label="单位" width="90">
              <template #default="scope">
                <el-input v-model="scope.row.unit" placeholder="如 km" size="small" maxlength="32" />
              </template>
            </el-table-column>
            <el-table-column label="值映射" min-width="170">
              <template #default="scope">
                <el-input v-model="scope.row.valuesText" type="textarea" :rows="2" size="small"
                  placeholder="每行一条，如 蓝方=blue" />
              </template>
            </el-table-column>
            <el-table-column label="同义词" min-width="170">
              <template #default="scope">
                <el-input v-model="scope.row.synonymsText" type="textarea" :rows="2" size="small"
                  placeholder="每行一条，如 飞机=aircraft" />
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

      <!-- 数据集语义注解 对话框 -->
      <el-dialog v-model="showDsSemanticDialog" :title="`数据集语义注解：${dsSemanticDsName}`" width="640px">
        <div v-if="dsSemanticInvalid" style="margin-bottom:12px;color:#e6a23c;font-size:12px">
          原语义注解不是合法 JSON，已按空处理；保存后将以本次填写的内容覆盖。
        </div>
        <el-form label-width="120px">
          <el-form-item label="实体大类">
            <el-select v-model="dsSemanticForm.entityKind" placeholder="未设置" style="width:100%">
              <el-option label="未设置" value="" />
              <el-option v-for="k in SEMANTIC_ENTITY_KIND_OPTIONS" :key="k.value" :label="k.label" :value="k.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="默认符号">
            <el-select v-model="dsSemanticForm.symbolDefault" placeholder="未设置" style="width:100%">
              <el-option label="未设置" value="" />
              <el-option v-for="s in SEMANTIC_SYMBOL_OPTIONS" :key="s" :label="s" :value="s" />
            </el-select>
          </el-form-item>
          <el-form-item label="航迹拆分键">
            <el-input v-model="dsSemanticForm.trackGroupKey" placeholder="逗号分隔的列名，如 aircraft_id,mission_id" />
          </el-form-item>
          <el-form-item label="事件时间列">
            <el-input v-model="dsSemanticForm.eventTimeColumn" placeholder="事件时间列名，如 event_time" />
          </el-form-item>
          <el-form-item label="几何列">
            <div style="display:flex;gap:8px;width:100%">
              <el-input v-model="dsSemanticForm.lngColumn" placeholder="经度列" />
              <el-input v-model="dsSemanticForm.latColumn" placeholder="纬度列" />
              <el-input v-model="dsSemanticForm.radiusColumn" placeholder="半径列（可选）" />
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showDsSemanticDialog = false">取消</el-button>
          <el-button type="primary" @click="saveDatasetSemantic">保存</el-button>
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

      <!-- 指标规格配置（Indicator Spec） -->
      <el-dialog v-model="showSpecDialog" title="指标规格配置（可编译查询规格）" width="860px" top="4vh">
        <el-form label-width="100px">
          <el-form-item label="指标公式">
            <el-input :model-value="specIndicator?.formula || ''" readonly />
          </el-form-item>
          <el-form-item label="绑定状态">
            <el-tag v-if="specBindStatus === 'ready'" type="success" size="small">ready（可编译查询）</el-tag>
            <el-tag v-else type="warning" size="small">{{ specBindStatus === 'pending' ? 'pending（待确认）' : 'not_ready（存在缺口）' }}</el-tag>
          </el-form-item>
          <el-form-item label="规格 JSON">
            <el-input v-model="specJson" type="textarea" :rows="14"
              placeholder='{"sourceTables":[...],"keyMappings":[...],"bindings":[...],"dimensions":[...],"parameters":[...]}' />
          </el-form-item>
          <el-form-item label="语义目录">
            <el-collapse>
              <el-collapse-item :title="`数据源表结构（${catalogTables.length} 张表，含字段标注/注释）`">
                <div v-for="t in catalogTables" :key="t.tableName" style="margin-bottom:8px">
                  <b>{{ t.tableName }}</b>
                  <span v-if="t.datasetName !== t.tableName" style="color:#888">（{{ t.datasetName }}）</span>
                  <div v-if="t.keyMappings" style="color:#409eff;font-size:12px">连接键: {{ t.keyMappings }}</div>
                  <div v-for="c in (t.columns || [])" :key="c.columnName" style="font-size:12px;margin-left:12px">
                    {{ c.columnName }} ({{ c.dataType }})
                    <span v-if="c.comment || c.annotation || c.businessMeaning" style="color:#666">
                      — {{ c.comment || c.annotation || c.businessMeaning }}
                    </span>
                  </div>
                </div>
                <el-button size="small" @click="rebuildCatalog">重建目录索引</el-button>
              </el-collapse-item>
            </el-collapse>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="suggestSpecBindings" :loading="suggestingSpec">LLM 建议绑定</el-button>
          <el-button @click="validateSpecJson" :loading="validatingSpec">校验</el-button>
          <el-button @click="dryRunSpec" :loading="dryRunningSpec">试运行 (dry-run)</el-button>
          <el-button @click="showSpecDialog = false">取消</el-button>
          <el-button type="primary" @click="saveIndicatorSpec">保存规格</el-button>
        </template>
        <div v-if="specFeedback" style="margin-top:8px;white-space:pre-wrap;font-size:12px;color:#666">{{ specFeedback }}</div>
      </el-dialog>

      <!-- 知识库指标一键导入 -->
      <el-dialog v-model="showKbImportDialog" title="从知识库导入指标（解析候选 → LLM 建议规格 → 人工确认保存）" width="880px" top="4vh">
        <div style="display:flex;gap:8px;margin-bottom:8px">
          <el-select v-model="kbImportDocId" placeholder="选择知识库文档" filterable style="flex:1">
            <el-option v-for="doc in kbDocs" :key="doc.id" :label="`${doc.title}（${doc.category || '未分类'}）`" :value="doc.id" />
          </el-select>
          <el-select v-model="kbImportDbId" placeholder="目标数据源" style="width:220px">
            <el-option v-for="db in databases" :key="db.id" :label="db.name" :value="db.id" />
          </el-select>
          <el-button @click="loadKbDocs">刷新</el-button>
          <el-button type="primary" @click="parseKbDoc" :loading="parsingKb">解析并生成建议</el-button>
        </div>
        <div v-if="kbImportHint" style="font-size:12px;color:#909399;margin-bottom:8px">{{ kbImportHint }}</div>
        <div v-if="kbCandidates.length" style="max-height:56vh;overflow:auto">
          <div v-for="(cand, i) in kbCandidates" :key="i" style="border:1px solid #ebeef5;border-radius:6px;padding:10px;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap">
              <b>{{ cand.name }}</b>
              <code style="font-size:12px">{{ cand.formula }}</code>
              <el-tag size="small" type="info">terms: {{ (cand.terms || []).join('、') || '-' }}</el-tag>
            </div>
            <div v-if="cand.suggestError" style="font-size:12px;color:#f56c6c">建议生成失败：{{ cand.suggestError }}</div>
            <div v-else style="display:flex;gap:8px;align-items:flex-start">
              <el-input v-model="cand._specText" type="textarea" :rows="7" style="flex:1" placeholder="规格 JSON（可人工修正）" />
              <div style="display:flex;flex-direction:column;gap:6px">
                <el-button size="small" type="primary" @click="saveImportedIndicator(cand)">保存为新指标</el-button>
                <el-button size="small" @click="saveImportedIndicator(cand, true)">保存并在编辑器确认</el-button>
              </div>
            </div>
          </div>
        </div>
      </el-dialog>

      <!-- 同义词编辑 -->
      <el-dialog v-model="showSynonymDialog" :title="synonymForm.id ? '编辑同义词' : '新增同义词'" width="560px">
        <el-form :model="synonymForm" label-width="100px">
          <el-form-item label="业务概念" required>
            <el-input v-model="synonymForm.concept" placeholder="如：销售额 / 物品类别 / 订单数" />
          </el-form-item>
          <el-form-item label="数据源">
            <el-select v-model="synonymForm.databaseId" clearable placeholder="选择数据源" style="width:100%" @change="onSynonymDbChange">
              <el-option v-for="db in databases" :key="db.id" :label="db.name" :value="db.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="数据集">
            <el-select v-model="synonymForm.datasetId" clearable placeholder="选择数据集" style="width:100%" @change="onSynonymDsChange">
              <el-option v-for="ds in datasets" :key="ds.id" :label="`${ds.name}（${ds.tableName}）`" :value="ds.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="表名" required>
            <el-input v-model="synonymForm.tableName" placeholder="物理表名" />
          </el-form-item>
          <el-form-item label="列名" required>
            <el-input v-model="synonymForm.columnName" placeholder="物理列名" />
          </el-form-item>
          <el-form-item label="列注释">
            <el-input v-model="synonymForm.columnComment" placeholder="可选" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="showSynonymDialog = false">取消</el-button>
          <el-button type="primary" @click="saveSynonym" :loading="savingSynonym">保存</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, h } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'

const activeTab = ref('database')

// ==================== 数据库配置 ====================
const databases = ref<any[]>([])
const drivers = ref<any[]>([])
const driverPresets = ['MySQL', 'PostgreSQL', 'Oracle', '达梦数据库V8.1', 'SQL Server']
const showDbDialog = ref(false)
const editingDbId = ref<string | null>(null)
const savingDb = ref(false)
const showUploadDriver = ref(false)
const uploadingDriver = ref(false)
const driverUploadRef = ref<any>(null)
const driverForm = ref({
  type: '',
  name: ''
})
const driverFile = ref<File | null>(null)

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
  const m: Record<string, 'primary' | 'success' | 'warning' | 'info' | 'danger'> = {
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

function onDriverFileChange(file: any) {
  driverFile.value = file.raw
}

function onDriverTypeChange(type: string) {
  if (!driverForm.value.name) {
    driverForm.value.name = type
  }
}

async function uploadDriver() {
  if (!driverForm.value.type) {
    ElMessage.warning('请选择数据库类型')
    return
  }
  if (!driverForm.value.name.trim()) {
    ElMessage.warning('请输入驱动名称')
    return
  }
  if (!driverFile.value) {
    ElMessage.warning('请选择JAR文件')
    return
  }
  uploadingDriver.value = true
  try {
    const formData = new FormData()
    formData.append('file', driverFile.value)
    formData.append('name', driverForm.value.name.trim())
    formData.append('type', driverForm.value.type)
    const res = await api.post('/admin/driver/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    if (res && res.success) {
      ElMessage.success('驱动上传成功')
      showUploadDriver.value = false
      driverForm.value = { type: '', name: '' }
      driverFile.value = null
      await loadDrivers()
    }
  } catch (e: any) {
    ElMessage.error('上传失败: ' + (e?.serverMessage || e?.message || '未知错误'))
  } finally {
    uploadingDriver.value = false
  }
}

async function deleteDriver(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除驱动"${row.name}"吗？`, '提示', {
      confirmButtonText: '确定', cancelButtonText: '取消', type: 'warning'
    })
    await api.delete(`/admin/driver/${row.id}`)
    drivers.value = drivers.value.filter((d: any) => d.id !== row.id)
    ElMessage.success('驱动已删除')
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('删除失败: ' + (e?.serverMessage || ''))
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
    ElMessage.error('保存失败: ' + (e?.serverMessage || e?.message || '未知错误'))
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
    row.errorMsg = e?.serverMessage || e?.message || '请求异常'
    ElMessage.error('连接失败: ' + row.errorMsg)
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
      ElMessage.error('删除失败: ' + (e?.serverMessage || e?.message || '未知错误'))
    }
  }
}

// ==================== 数据集 ====================
const datasets = ref<any[]>([])
const showSelectDsDialog = ref(false)
const selectDsDbId = ref('')
const dbTables = ref<any[]>([])
const loadingDbTables = ref(false)

// ── 数据集按数据源分层显示 ──
// 分组键取 databaseId；未关联数据源（或该数据源已被删除/不可用）的数据集单独成组并排在最后，
// 避免"看不见"或被误认为正常数据源。组头展示库名与类型/主机，组内沿用原有表格与全部操作按钮。
const UNASSIGNED_GROUP_KEY = '__unassigned__'
const expandedGroups = ref<string[]>([])
let groupsInitialized = false

/** 数据源列表已加载（用于区分"数据源已删除"与"列表尚未返回"两种情况） */
const databasesLoaded = computed(() => databases.value.length > 0)

const groupedDatasets = computed(() => {
  const groups = new Map<string, any>()
  datasets.value.forEach((ds: any) => {
    const key = ds.databaseId ? String(ds.databaseId) : UNASSIGNED_GROUP_KEY
    if (!groups.has(key)) {
      groups.set(key, { key, databaseId: ds.databaseId || '', datasets: [] })
    }
    groups.get(key).datasets.push(ds)
  })
  return Array.from(groups.values())
    .map((group: any) => {
      const db = databases.value.find((item: any) => item.id === group.databaseId)
      // 数据源缺失：已拿到数据源列表，但该 databaseId 不在其中（数据源被删/不可用）
      const missingDb = !!group.databaseId && databasesLoaded.value && !db
      const metaParts = db
        ? [db.type, db.host, db.port ? `:${db.port}` : '', db.database].filter(Boolean)
        : []
      const name = db
        ? db.name
        : group.databaseId
          ? (missingDb ? `数据源缺失（${group.databaseId}）` : group.databaseId)
          : '未关联数据源'
      const meta = db
        ? metaParts.join(' · ')
        : (missingDb ? '该数据源已删除或不可用，请重新指定' : '未选择数据源')
      return {
        key: group.key,
        datasets: group.datasets,
        name,
        meta,
        missingDb,
        // 排序优先级：正常数据源 0 → 数据源缺失 1 → 未关联数据源 2
        rank: db ? 0 : (group.databaseId ? 1 : 2),
        unvalidated: group.datasets.filter((ds: any) => !ds.annotationValidatedAt).length,
      }
    })
    .sort((a: any, b: any) => {
      if (a.rank !== b.rank) return a.rank - b.rank
      return String(a.name).localeCompare(String(b.name), 'zh-Hans-CN')
    })
})

const allGroupsExpanded = computed(
  () => groupedDatasets.value.length > 0
    && expandedGroups.value.length === groupedDatasets.value.length,
)

function toggleAllGroups() {
  expandedGroups.value = allGroupsExpanded.value
    ? []
    : groupedDatasets.value.map((group: any) => group.key)
}

// 首次拿到数据时默认全部展开；此后尊重用户的折叠状态（重新加载不回弹）
watch(groupedDatasets, (groups) => {
  if (groupsInitialized || groups.length === 0) return
  groupsInitialized = true
  expandedGroups.value = groups.map((group: any) => group.key)
}, { immediate: true })

// 仅显示已连接的数据库
const connectedDatabases = computed(() => 
  databases.value.filter((db: any) => db.status === '已连接')
)

// ── 重新指定数据源（数据源缺失/未关联分组一键改指）──
const showReassignDialog = ref(false)
const reassignGroup = ref<any>(null)
const reassignTargetDbId = ref('')
const reassigning = ref(false)

function openReassignDialog(group: any) {
  reassignGroup.value = group
  reassignTargetDbId.value = ''
  showReassignDialog.value = true
}

async function confirmReassign() {
  const group = reassignGroup.value
  const target = databases.value.find((db: any) => db.id === reassignTargetDbId.value)
  if (!group || !target) return
  reassigning.value = true
  let done = 0
  const failed: string[] = []
  try {
    for (const ds of group.datasets) {
      try {
        // 只改归属数据源（表名/名称/描述保持原样），复用数据集更新接口
        const res = await api.put(`/admin/dataset/${ds.id}`, {
          databaseId: target.id,
          tableName: ds.tableName,
          description: ds.description,
        })
        if (res && res.success) done += 1
        else failed.push(ds.name || ds.tableName)
      } catch {
        failed.push(ds.name || ds.tableName)
      }
    }
    await loadDatasets()
    if (!expandedGroups.value.includes(target.id)) expandedGroups.value.push(target.id)
    showReassignDialog.value = false
    if (failed.length) {
      ElMessage.warning(`已改指 ${done} 个数据集，失败 ${failed.length} 个（${failed.slice(0, 3).join('、')}）`)
    } else {
      ElMessage.success(`已将 ${done} 个数据集改指到「${target.name}」`)
    }
  } finally {
    reassigning.value = false
  }
}

// ── AI 注解草稿（LLM 生成 + 人工审核）──
// 草稿与正式注解物理隔离：只有「通过」才会写入生效注解并触发页面服务缓存失效。
const showDraftDrawer = ref(false)
const draftDatasetId = ref('')
const draftDatasetName = ref('')
const draftItems = ref<any[]>([])
const draftStatus = ref('draft')
const draftBatchId = ref('')
const draftLoading = ref(false)
const draftGenerating = ref(false)
const regeneratingId = ref('')

/** 后端返回的 issues/warnings/sampled 均为 JSON 字符串，统一解析成数组供展示 */
function draftList(json: any): string[] {
  if (Array.isArray(json)) return json.map((i) => String(i))
  if (!json) return []
  try {
    const parsed = JSON.parse(String(json))
    return Array.isArray(parsed) ? parsed.map((i) => String(i)) : []
  } catch {
    return [String(json)]
  }
}

function draftStatusText(status: string): string {
  return { draft: '待审', approved: '已通过', rejected: '已驳回', superseded: '已被新版取代' }[status] || status
}

function draftStatusTag(status: string): 'success' | 'danger' | 'info' | 'warning' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'draft') return 'warning'
  return 'info'
}

async function openAnnotationDrafts(row: any) {
  draftDatasetId.value = row.id
  draftDatasetName.value = row.name || row.tableName || ''
  draftStatus.value = 'draft'
  draftItems.value = []
  draftBatchId.value = ''
  showDraftDrawer.value = true
  await loadDrafts()
}

async function loadDrafts() {
  if (!draftDatasetId.value) return
  draftLoading.value = true
  try {
    const res = await api.get(`/admin/dataset/${draftDatasetId.value}/annotations/drafts`, {
      params: { status: draftStatus.value },
    })
    draftItems.value = res?.items || []
    // 批次号取待审草稿里的第一个（整批操作以此为准）
    draftBatchId.value = draftItems.value.find((i: any) => i.status === 'draft')?.batchId || ''
  } catch (e: any) {
    ElMessage.error('加载草稿失败：' + (e?.serverMessage || e?.message || '未知错误'))
    draftItems.value = []
  } finally {
    draftLoading.value = false
  }
}

async function generateDrafts() {
  if (!draftDatasetId.value) return
  draftGenerating.value = true
  try {
    const res = await api.post(`/admin/dataset/${draftDatasetId.value}/annotations/draft/generate`, {})
    if (res?.success) {
      ElMessage.success(res.message || '草稿已生成')
      if (Array.isArray(res.notes) && res.notes.length) {
        ElMessage.warning({ message: res.notes.join('；'), duration: 6000 })
      }
      draftStatus.value = 'draft'
      await loadDrafts()
    }
  } catch (e: any) {
    ElMessage.error('生成草稿失败：' + (e?.serverMessage || e?.message || '未知错误'))
  } finally {
    draftGenerating.value = false
  }
}

async function saveDraft(item: any) {
  try {
    const res = await api.put(`/admin/annotations/draft/${item.id}`, { draftJson: item.draftJson })
    if (res?.success) {
      ElMessage.success('草稿已更新并重新校验')
      await loadDrafts()
    }
  } catch (e: any) {
    ElMessage.error('保存草稿失败：' + (e?.serverMessage || e?.message || '未知错误'))
    await loadDrafts()
  }
}

/**
 * 强制通过：仅在草稿存在硬错误（如注解值未在采样中出现，但人工确认其真实存在）时使用。
 * 必须填写理由，后端会把理由与当时的硬错误一并留痕。
 */
async function forceApproveDraft(item: any) {
  try {
    const { value } = await ElMessageBox.prompt(
      `该草稿存在硬错误，确认强制通过？请说明判定依据（例如"该取值确实存在，只是未进入采样 TOP-N"）\n\n`
      + draftList(item.issuesJson).join('\n'),
      '强制通过草稿',
      { confirmButtonText: '确认强制通过', cancelButtonText: '取消', inputPlaceholder: '填写判定依据（必填）' },
    )
    if (!value || !value.trim()) {
      ElMessage.warning('强制通过必须填写理由')
      return
    }
    const res = await api.post(`/admin/annotations/draft/${item.id}/approve`, { force: true, remark: value })
    if (res?.success) {
      ElMessage.success(res.message || '已强制通过')
      await loadDrafts()
      await loadDatasets()
    }
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('强制通过失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

async function approveDraft(item: any) {
  try {
    const res = await api.post(`/admin/annotations/draft/${item.id}/approve`, {})
    if (res?.success) {
      ElMessage.success(res.message || '草稿已生效')
      await loadDrafts()
      await loadDatasets()
    }
  } catch (e: any) {
    ElMessage.error('通过失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

async function rejectDraft(item: any) {
  try {
    const { value } = await ElMessageBox.prompt('驳回意见（可留空；填了可用于「按意见重生成」）', '驳回草稿', {
      confirmButtonText: '确认驳回', cancelButtonText: '取消', inputPlaceholder: '例如：阵营列不要臆造枚举',
    })
    const res = await api.post(`/admin/annotations/draft/${item.id}/reject`, { remark: value || '' })
    if (res?.success) {
      ElMessage.success('已驳回')
      await loadDrafts()
    }
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('驳回失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

async function regenerateDraft(item: any) {
  regeneratingId.value = item.id
  try {
    const res = await api.post(`/admin/annotations/draft/${item.id}/regenerate`, {})
    if (res?.success) {
      ElMessage.success(res.message || '已重生成')
      draftStatus.value = 'draft'
      await loadDrafts()
    }
  } catch (e: any) {
    ElMessage.error('重生成失败：' + (e?.serverMessage || e?.message || '未知错误'))
  } finally {
    regeneratingId.value = ''
  }
}

async function approveDraftBatch() {
  if (!draftBatchId.value) return
  try {
    const res = await api.post(`/admin/annotations/drafts/batch/${draftBatchId.value}/approve`, {})
    if (res?.success) {
      if (Array.isArray(res.skipped) && res.skipped.length) {
        ElMessageBox.alert(res.skipped.join('\n'), '部分草稿未通过（存在硬错误或校验未通过）', {
          confirmButtonText: '知道了', type: 'warning',
        }).catch(() => { /* 关闭提示不算异常 */ })
      } else {
        ElMessage.success(res.message || '整批已通过')
      }
      await loadDrafts()
      await loadDatasets()
    }
  } catch (e: any) {
    ElMessage.error('整批通过失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

async function rejectDraftBatch() {
  if (!draftBatchId.value) return
  try {
    const { value } = await ElMessageBox.prompt('整批驳回意见（可留空）', '整批驳回', {
      confirmButtonText: '确认驳回', cancelButtonText: '取消',
    })
    const res = await api.post(`/admin/annotations/drafts/batch/${draftBatchId.value}/reject`, { remark: value || '' })
    if (res?.success) {
      ElMessage.success(res.message || '整批已驳回')
      await loadDrafts()
    }
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('整批驳回失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

async function discardDraftBatch() {
  if (!draftBatchId.value) return
  try {
    await ElMessageBox.confirm('确定丢弃该批次的全部草稿吗？丢弃后不可恢复。', '丢弃草稿', {
      confirmButtonText: '确定丢弃', cancelButtonText: '取消', type: 'warning',
    })
    const res = await api.delete(`/admin/annotations/drafts/batch/${draftBatchId.value}`)
    if (res?.success) {
      ElMessage.success(res.message || '已丢弃')
      await loadDrafts()
    }
  } catch (e: any) {
    if (e !== 'cancel') ElMessage.error('丢弃失败：' + (e?.serverMessage || e?.message || '未知错误'))
  }
}

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

function openSelectDataset() {
  selectDsDbId.value = ''
  dbTables.value = []
  selectedTables.value = []
  showSelectDsDialog.value = true
}

async function onSelectDsDbChange(dbId: string) {
  if (!dbId) return
  loadingDbTables.value = true
  dbTables.value = []
  selectedTables.value = []
  try {
    const res = await api.get(`/admin/database/${dbId}/tables`)
    if (res && res.success && res.tables) {
      dbTables.value = res.tables
      if (res.tables.length === 0) {
        ElMessage.warning(res.hint || '该数据库中未发现用户表，请检查数据库连接或手动刷新')
      }
    } else {
      ElMessage.warning(res?.message || '获取数据表失败')
    }
  } catch (e: any) {
    ElMessage.error('获取数据表失败: ' + (e.message || ''))
  } finally {
    loadingDbTables.value = false
  }
}

// ── 选择数据集：单张 / 批量注册 ──
const selectedTables = ref<any[]>([])
const registeringTables = ref(false)

function onTableSelectionChange(rows: any[]) {
  selectedTables.value = rows
}

/** 批量注册勾选的数据表：跳过已注册、逐张登记，最后一次性汇总结果并刷新列表 */
async function confirmBatchRegister() {
  const dbId = selectDsDbId.value
  const db = databases.value.find((item: any) => item.id === dbId)
  if (!db || selectedTables.value.length === 0) return
  registeringTables.value = true
  let added = 0
  let skipped = 0
  const failed: string[] = []
  try {
    for (const row of selectedTables.value) {
      const tableName = row.tableName
      const exists = datasets.value.some((item: any) => item.databaseId === dbId && item.tableName === tableName)
      if (exists) {
        skipped += 1
        continue
      }
      try {
        const res = await api.post('/admin/dataset', {
          name: `${db.name} - ${tableName}`,
          description: `来自数据库 ${db.name} 的数据表 ${tableName}`,
          databaseId: dbId,
          tableName,
        })
        if (res && res.success) added += 1
        else failed.push(tableName)
      } catch {
        failed.push(tableName)
      }
    }
    await loadDatasets()
    // 新注册的数据集落在该数据源分组内，若被折叠则展开便于确认
    if (!expandedGroups.value.includes(dbId)) expandedGroups.value.push(dbId)
    if (failed.length) {
      ElMessage.warning(`已注册 ${added} 张，跳过已存在 ${skipped} 张，失败 ${failed.length} 张（${failed.slice(0, 3).join('、')}）`)
    } else {
      ElMessage.success(`已注册 ${added} 张数据表` + (skipped ? `，跳过已存在 ${skipped} 张` : ''))
      showSelectDsDialog.value = false
    }
  } finally {
    registeringTables.value = false
  }
}

async function onSelectTable(row: any) {
  const tableName = row.tableName
  const dbId = selectDsDbId.value
  const db = databases.value.find((d: any) => d.id === dbId)
  if (!db) return

  // 检查是否已存在相同的数据集
  const exists = datasets.value.find((d: any) => d.databaseId === dbId && d.tableName === tableName)
  if (exists) {
    ElMessage.warning(`数据表「${tableName}」已添加`)
    return
  }

  try {
    const res = await api.post('/admin/dataset', {
      name: `${db.name} - ${tableName}`,
      description: `来自数据库 ${db.name} 的数据表 ${tableName}`,
      databaseId: dbId,
      tableName: tableName
    })
    if (res && res.success) {
      datasets.value.push({
        id: res.id,
        name: `${db.name} - ${tableName}`,
        description: `来自数据库 ${db.name} 的数据表 ${tableName}`,
        databaseId: dbId,
        tableName: tableName,
        records: 0
      })
      showSelectDsDialog.value = false
      ElMessage.success(`已添加数据集：${tableName}`)
    }
  } catch (e: any) {
    ElMessage.error('添加失败: ' + (e.message || '未知错误'))
  }
}

async function editDataset(row: any) {
  // 简化编辑：直接弹窗修改名称和描述
  try {
    const { value } = await ElMessageBox.prompt('请输入数据集名称', '编辑数据集', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      inputValue: row.name
    })
    if (value) {
      await api.put(`/admin/dataset/${row.id}`, { name: value, description: row.description })
      row.name = value
      ElMessage.success('已更新')
    }
  } catch { /* cancelled */ }
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

// ==================== 领域语义注解（semantic_json） ====================
// 以下白名单与后端 resources/semantic-schema.json 保持一致，只能选择不允许自由输入
const SEMANTIC_ROLE_OPTIONS = [
  { label: '标识 (id)', value: 'id' },
  { label: '名称 (name)', value: 'name' },
  { label: '时间 (time)', value: 'time' },
  { label: '经度 (lng)', value: 'lng' },
  { label: '纬度 (lat)', value: 'lat' },
  { label: '半径 (radius)', value: 'radius' },
  { label: '序号 (seq)', value: 'seq' },
  { label: '度量 (measure)', value: 'measure' },
  { label: '维度 (dimension)', value: 'dimension' },
  { label: '状态 (status)', value: 'status' },
  { label: '高度 (altitude)', value: 'altitude' },
  { label: '速度 (speed)', value: 'speed' },
  { label: '航向 (heading)', value: 'heading' }
]

const SEMANTIC_SYMBOL_OPTIONS = [
  'fighter', 'awacs', 'recon', 'bomber', 'base', 'sam', 'radar',
  'coastal', 'flag', 'depot', 'fuel', 'anchor', 'runway', 'tower',
  'boom', 'cross', 'magnifier', 'ring', 'dot'
]

const SEMANTIC_ENTITY_KIND_OPTIONS = [
  { label: '空中目标 (air)', value: 'air' },
  { label: '地面设施 (ground_facility)', value: 'ground_facility' },
  { label: '基地 (base)', value: 'base' },
  { label: '其他 (other)', value: 'other' }
]

/**
 * 解析 semanticJson 字符串。
 * 返回解析结果与"原值不是合法 JSON"标记，解析失败时按空处理但不阻断界面。
 */
function parseSemanticJson(raw: any): { data: Record<string, any>; invalid: boolean } {
  if (raw === null || raw === undefined || String(raw).trim() === '') {
    return { data: {}, invalid: false }
  }
  try {
    const parsed = JSON.parse(String(raw))
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { data: {}, invalid: true }
    }
    return { data: parsed, invalid: false }
  } catch {
    return { data: {}, invalid: true }
  }
}

/**
 * 「原始值=规范值」多行文本 → 键值对象。
 * 按行拆分，跳过空行，按第一个 = 拆分，两侧都有值才保留。
 */
function parseMappingText(text: any): Record<string, string> {
  const mapping: Record<string, string> = {}
  String(text ?? '').split('\n').forEach(line => {
    const trimmed = line.trim()
    if (!trimmed) return
    const index = trimmed.indexOf('=')
    if (index < 0) return
    const key = trimmed.slice(0, index).trim()
    const value = trimmed.slice(index + 1).trim()
    if (key && value) mapping[key] = value
  })
  return mapping
}

/** 键值对象 → 「原始值=规范值」多行文本 */
function formatMappingText(mapping: any): string {
  if (!mapping || typeof mapping !== 'object') return ''
  return Object.entries(mapping).map(([key, value]) => `${key}=${value}`).join('\n')
}

/** 从异常对象中取出后端返回的校验明细（兼容响应拦截器的两种 reject 形态） */
function extractServerErrors(e: any): string[] {
  const errors = e?.response?.data?.errors ?? e?.data?.errors ?? e?.errors
  return Array.isArray(errors) ? errors.map((item: any) => String(item)) : []
}

/** 语义注解保存失败提示：展示后端 message 与逐条校验明细，不提示保存成功 */
async function showSemanticSaveError(e: any, actionLabel: string) {
  const errors = extractServerErrors(e)
  const message = e?.serverMessage || e?.response?.data?.message || e?.message || '请求失败'
  if (errors.length === 0) {
    ElMessage.error(`${actionLabel}失败：${message}`)
    return
  }
  await ElMessageBox.alert(
    h('div', { style: 'white-space: pre-line; max-height: 50vh; overflow: auto;' },
      [message, ...errors].join('\n')),
    '语义注解格式校验未通过',
    { confirmButtonText: '知道了', type: 'error' }
  ).catch(() => { /* 关闭提示弹窗不算异常 */ })
}

/** 保存成功但后端返回警告（如页面服务缓存失效失败）时提示用户 */
function showSemanticWarnings(warnings: any) {
  if (!Array.isArray(warnings) || warnings.length === 0) return
  ElMessage({
    type: 'warning',
    message: h('div', { style: 'white-space: pre-line;' }, warnings.join('\n'))
  })
}

/** 校验时间只展示到分钟，避免列表列宽被秒/毫秒撑开 */
function formatValidatedAt(value: string): string {
  const text = String(value || '').replace('T', ' ')
  return text.length >= 16 ? text.slice(5, 16) : text
}

/**
 * 手动校验注解：结构错误（需修正后重新保存）+ 值域告警 + 表结构是否已变化。
 * 不落库，仅返回校验结论，供改过表结构后随时复核。
 */
async function validateAnnotations(row: any) {
  try {
    const res = await api.post(`/admin/dataset/${row.id}/annotations/validate`, {})
    const errors: string[] = Array.isArray(res?.errors) ? res.errors.map((i: any) => String(i)) : []
    const warnings: string[] = Array.isArray(res?.warnings) ? res.warnings.map((i: any) => String(i)) : []
    const lines: string[] = []
    if (typeof res?.message === 'string' && res.message) lines.push(res.message)
    if (res?.expired) lines.push('表结构自上次校验后已变化，建议复核注解（列增删/改名/注释调整都会触发）')
    if (errors.length) lines.push(`结构错误（${errors.length} 处，保存会被拒绝）：` + errors.map(i => `\n・${i}`).join(''))
    if (warnings.length) lines.push(`提示（${warnings.length} 条，不影响保存）：` + warnings.map(i => `\n・${i}`).join(''))
    if (!res?.structureChecked) lines.push('未能读取表结构，本次只做了格式与语义规则校验')
    await ElMessageBox.alert(
      h('div', { style: 'white-space: pre-line; max-height: 55vh; overflow: auto;' }, lines.join('\n')),
      '注解校验结果',
      {
        confirmButtonText: '知道了',
        type: errors.length ? 'error' : (warnings.length || res?.expired ? 'warning' : 'success')
      }
    ).catch(() => { /* 关闭提示弹窗不算异常 */ })
  } catch (e: any) {
    ElMessage.error(`注解校验失败：${e?.response?.data?.message || e?.message || '请求失败'}`)
  }
}

// ==================== 数据集级语义注解 ====================
const showDsSemanticDialog = ref(false)
const dsSemanticDsId = ref('')
const dsSemanticDsName = ref('')
// 原 semanticJson 不是合法 JSON 时给出行内提示
const dsSemanticInvalid = ref(false)
const dsSemanticForm = ref({
  entityKind: '',
  symbolDefault: '',
  trackGroupKey: '',
  eventTimeColumn: '',
  lngColumn: '',
  latColumn: '',
  radiusColumn: ''
})

/** 打开数据集语义注解对话框，从列表行的 semanticJson 解析回填 */
function openDatasetSemantic(row: any) {
  const parsed = parseSemanticJson(row.semanticJson)
  const data = parsed.data
  const geometry = data.geometry && typeof data.geometry === 'object' ? data.geometry : {}
  const groupKey = data.trackGroupKey
  dsSemanticDsId.value = row.id
  dsSemanticDsName.value = row.name || ''
  dsSemanticInvalid.value = parsed.invalid
  dsSemanticForm.value = {
    entityKind: data.entityKind || '',
    symbolDefault: data.symbolDefault || '',
    trackGroupKey: Array.isArray(groupKey) ? groupKey.join(',') : (typeof groupKey === 'string' ? groupKey : ''),
    eventTimeColumn: data.eventTimeColumn || '',
    lngColumn: geometry.lngColumn || '',
    latColumn: geometry.latColumn || '',
    radiusColumn: geometry.radiusColumn || ''
  }
  showDsSemanticDialog.value = true
}

/** 组装数据集级语义 JSON；全部为空时返回空串（表示清除语义） */
function buildDatasetSemantic(): string {
  const form = dsSemanticForm.value
  const semantic: Record<string, any> = {}
  if (form.entityKind) semantic.entityKind = form.entityKind
  if (form.symbolDefault) semantic.symbolDefault = form.symbolDefault
  const groupKeys = Array.from(new Set(form.trackGroupKey.split(',').map(key => key.trim()).filter(Boolean)))
  if (groupKeys.length > 0) semantic.trackGroupKey = groupKeys
  const eventTimeColumn = form.eventTimeColumn.trim()
  if (eventTimeColumn) semantic.eventTimeColumn = eventTimeColumn
  const lngColumn = form.lngColumn.trim()
  const latColumn = form.latColumn.trim()
  // 经度列与纬度列必须成对配置，否则不写入 geometry（避免后端校验失败）
  if (lngColumn && latColumn) {
    const geometry: Record<string, string> = { lngColumn, latColumn }
    const radiusColumn = form.radiusColumn.trim()
    if (radiusColumn) geometry.radiusColumn = radiusColumn
    semantic.geometry = geometry
  }
  return Object.keys(semantic).length > 0 ? JSON.stringify(semantic) : ''
}

async function saveDatasetSemantic() {
  if (!dsSemanticDsId.value) return
  try {
    const res = await api.put(`/admin/dataset/${dsSemanticDsId.value}/semantic`, {
      semanticJson: buildDatasetSemantic()
    })
    if (res && res.success) {
      ElMessage.success(res.message || '语义注解已保存')
      loadDatasets()
      // 存在警告说明缓存未失效，保留对话框便于按提示重试保存
      if (!Array.isArray(res.warnings) || res.warnings.length === 0) {
        showDsSemanticDialog.value = false
      }
      showSemanticWarnings(res.warnings)
    }
  } catch (e: any) {
    await showSemanticSaveError(e, '语义注解保存')
  }
}

// ==================== 数据表结构 & 字段标注 ====================
const showStructDialog = ref(false)
const structColumns = ref<any[]>([])
const currentStructDs = ref<string>('')
const currentStructTable = ref('')

/** 为表结构行补充编辑态：字段语义是嵌套 JSON，先转成表格可编辑的扁平字段 */
function decorateStructColumns(columns: any[]): any[] {
  return columns.map((c: any) => ({
    ...c,
    annotation: c.annotation || '',
    businessMeaning: c.businessMeaning || '',
    dataCategory: c.dataCategory || '',
    role: '',
    symbol: '',
    unit: '',
    valuesText: '',
    synonymsText: '',
    semanticInvalid: false
  }))
}

/** 把已保存的字段标注（含 semanticJson）回填到表结构行 */
function applyFieldAnnotations(fields: any[]) {
  fields.forEach((fa: any) => {
    const col = structColumns.value.find((c: any) => c.columnName === fa.columnName)
    if (!col) return
    col.annotation = fa.annotation || ''
    col.businessMeaning = fa.businessMeaning || ''
    col.dataCategory = fa.dataCategory || ''
    const parsed = parseSemanticJson(fa.semanticJson)
    col.semanticInvalid = parsed.invalid
    col.role = parsed.data.role || ''
    col.symbol = parsed.data.symbol || ''
    col.unit = parsed.data.unit || ''
    col.valuesText = formatMappingText(parsed.data.values)
    col.synonymsText = formatMappingText(parsed.data.synonyms)
  })
}

/** 组装单行的字段级语义 JSON；没有填写任何语义时返回空串 */
function buildFieldSemantic(row: any): string {
  const semantic: Record<string, any> = {}
  if (row.role) semantic.role = row.role
  if (row.symbol) semantic.symbol = row.symbol
  const unit = String(row.unit || '').trim()
  if (unit) semantic.unit = unit
  const values = parseMappingText(row.valuesText)
  if (Object.keys(values).length > 0) semantic.values = values
  const synonyms = parseMappingText(row.synonymsText)
  if (Object.keys(synonyms).length > 0) semantic.synonyms = synonyms
  return Object.keys(semantic).length > 0 ? JSON.stringify(semantic) : ''
}

async function openTableStructure(row: any) {
  currentStructDs.value = row.id
  structColumns.value = []

  // 验证数据集是否关联了数据库
  if (!row.databaseId) {
    ElMessage.warning('数据集未关联数据库，请先编辑数据集选择关联的数据库')
    return
  }
  // 检查数据库连接状态
  const linkedDb = databases.value.find((d: any) => d.id === row.databaseId)
  if (!linkedDb) {
    ElMessage.error('关联的数据库配置已不存在，请重新编辑数据集')
    return
  }
  if (linkedDb.status !== '已连接') {
    ElMessage.warning(`数据库"${linkedDb.name}"尚未连接，请先在数据库配置中测试连接`)
    return
  }

  // 尝试加载已缓存的表结构
  try {
    const res = await api.get(`/admin/dataset/${row.id}/structure`)
    if (res && res.success && res.columns && res.columns.length > 0) {
      currentStructTable.value = res.tableName || row.tableName || ''
      structColumns.value = decorateStructColumns(res.columns)
      // 合并已有的标注信息（含领域语义注解）
      try {
        const faRes = await api.get(`/admin/dataset/${row.id}/fields`)
        if (faRes && faRes.success && faRes.fields) {
          applyFieldAnnotations(faRes.fields)
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

  // 需要读取表结构 - 提示输入表名
  try {
    const { value: tableName } = await ElMessageBox.prompt('请输入要读取的数据表名', '读取表结构', {
      confirmButtonText: '读取', cancelButtonText: '取消',
      inputValue: row.tableName || ''
    })
    if (!tableName) return

    const res = await api.post(`/admin/dataset/${row.id}/read-structure`, { tableName })
    if (res && res.success) {
      currentStructTable.value = res.tableName
      structColumns.value = decorateStructColumns(res.columns)
      // 更新本地数据集信息
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
    dataCategory: c.dataCategory || '',
    semanticJson: buildFieldSemantic(c)
  }))
  try {
    const res = await api.post(`/admin/dataset/${currentStructDs.value}/fields`, fields)
    if (res && res.success) {
      ElMessage.success(`标注已保存（${res.total} 个字段）`)
      showSemanticWarnings(res.warnings)
    }
  } catch (e: any) {
    await showSemanticSaveError(e, '标注保存')
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

  // 加载已有的关联数据
  try {
    const res = await api.get(`/admin/indicator/${row.id}/linkage`)
    if (res && res.success && res.data) {
      linkForm.value.datasetId = res.data.datasetId || ''
      linkForm.value.calculationMethod = res.data.calculationMethod || ''

      if (res.data.linkedFields) {
        // 解析字段映射
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

  // 如果尚未加载字段但已设置数据集，则加载字段
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
  // 根据权重构建字段映射
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

// ==================== Indicator Spec ====================
const showSpecDialog = ref(false)
const specIndicator = ref<any>(null)
const specJson = ref('')
const specBindStatus = ref('not_ready')
const catalogTables = ref<any[]>([])
const specFeedback = ref('')
const suggestingSpec = ref(false)
const validatingSpec = ref(false)
const dryRunningSpec = ref(false)

function buildEmptySpec(ind: any) {
  return {
    formula: ind?.formula || '',
    sourceTables: [],
    keyMappings: [],
    bindings: [],
    dimensions: [],
    parameters: [],
    grain: { groupBy: [], distinct: false }
  }
}

async function openIndicatorSpec(row: any) {
  specIndicator.value = row
  specBindStatus.value = row.bindStatus || 'not_ready'
  let spec: any = null
  try {
    if (row.indicatorSpec) spec = typeof row.indicatorSpec === 'string' ? JSON.parse(row.indicatorSpec) : row.indicatorSpec
  } catch { spec = null }
  specJson.value = spec ? JSON.stringify(spec, null, 2) : JSON.stringify(buildEmptySpec(row), null, 2)
  specFeedback.value = ''
  await loadCatalog()
  showSpecDialog.value = true
}

async function loadCatalog() {
  try {
    const res = await api.get('/admin/catalog/database')
    if (res && res.success) catalogTables.value = res.tables || []
  } catch { catalogTables.value = [] }
}

async function rebuildCatalog() {
  try {
    const res = await api.post('/admin/catalog/rebuild', {})
    if (res && res.success) {
      specFeedback.value = `目录重建完成：新增 ${res.created || 0}，更新 ${res.updated || 0}，总计 ${res.total || 0}`
      await loadCatalog()
    }
  } catch (e: any) {
    specFeedback.value = '目录重建失败: ' + (e.serverMessage || e.message || '')
  }
}

function parseSpecOrWarn(): any | null {
  try {
    const parsed = JSON.parse(specJson.value)
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      specFeedback.value = '规格必须是 JSON 对象'
      return null
    }
    return parsed
  } catch (e: any) {
    specFeedback.value = '规格 JSON 解析失败: ' + (e.message || e)
    return null
  }
}

async function validateSpecJson() {
  const spec = parseSpecOrWarn()
  if (!spec) return
  validatingSpec.value = true
  try {
    const res = await api.post('/admin/indicator/spec/validate', { indicatorSpec: JSON.stringify(spec) })
    specFeedback.value = res.ready
      ? `校验通过：绑定 ${res.bindingCount || 0} 项，无缺口`
      : `校验未通过：\n${(res.errors || []).join('\n') || '存在缺口'}\n未绑定项: ${(res.missingTerms || []).join('、') || '无'}`
  } catch (e: any) {
    specFeedback.value = '校验失败: ' + (e.serverMessage || e.message || '')
  } finally {
    validatingSpec.value = false
  }
}

async function dryRunSpec() {
  if (!specIndicator.value?.id) return
  dryRunningSpec.value = true
  specFeedback.value = ''
  try {
    const res = await api.post(`/admin/indicator/${specIndicator.value.id}/dry-run`)
    const lines = (res.checks || []).map((c: any) => `[${c.ok ? 'OK' : 'FAIL'}] ${c.table} — ${c.message}`)
    specFeedback.value = `dry-run ${res.dryRunOk ? '通过' : '未通过'}：\n` + lines.join('\n')
  } catch (e: any) {
    specFeedback.value = 'dry-run 失败: ' + (e.serverMessage || e.message || '')
  } finally {
    dryRunningSpec.value = false
  }
}

async function suggestSpecBindings() {
  const ind = specIndicator.value
  if (!ind) return
  suggestingSpec.value = true
  specFeedback.value = ''
  try {
    const body: any = {
      indicator_name: ind.name || '',
      formula: ind.formula || '',
      current_spec: parseSpecOrWarn() || {}
    }
    const res = await api.post('/evaluation/indicator-spec/suggest', body)
    if (res && res.success && res.suggestedSpec) {
      specJson.value = JSON.stringify(res.suggestedSpec, null, 2)
      specFeedback.value = '已生成绑定建议（LLM 建议，保存前请校验/dry-run 并人工确认）'
    } else {
      specFeedback.value = '建议生成失败: ' + (res?.message || '')
    }
  } catch (e: any) {
    specFeedback.value = '建议生成失败: ' + (e.serverMessage || e.message || '')
  } finally {
    suggestingSpec.value = false
  }
}

async function saveIndicatorSpec() {
  const spec = parseSpecOrWarn()
  if (!spec) return
  if (!specIndicator.value?.id) return
  try {
    const res = await api.post(`/admin/indicator/${specIndicator.value.id}/spec`, { indicatorSpec: JSON.stringify(spec) })
    specBindStatus.value = res.bindStatus || 'not_ready'
    specFeedback.value = res.ready
      ? `规格已保存，状态 ready（绑定 ${res.bindingCount || 0} 项）`
      : `规格已保存，状态 ${res.bindStatus}。\n${(res.errors || []).join('\n') || '存在缺口'}`
    ElMessage.success('指标规格已保存')
    loadIndicators()
  } catch (e: any) {
    specFeedback.value = '保存失败: ' + (e.serverMessage || e.message || '')
  }
}

// ==================== 语义目录维护（同义词增删改） ====================
const synonyms = ref<any[]>([])
const synonymsLoading = ref(false)
const catalogFilterDb = ref('')
const catalogKeyword = ref('')
const showSynonymDialog = ref(false)
const savingSynonym = ref(false)
const synonymForm = ref<any>({
  id: '', concept: '', databaseId: '', datasetId: '',
  tableName: '', columnName: '', columnComment: ''
})

async function loadSynonyms() {
  synonymsLoading.value = true
  try {
    const params: any = { limit: 500 }
    if (catalogFilterDb.value) params.databaseId = catalogFilterDb.value
    if (catalogKeyword.value.trim()) params.keyword = catalogKeyword.value.trim()
    const res = await api.get('/admin/catalog/synonyms', { params })
    if (res && res.success) synonyms.value = res.items || []
  } catch (e: any) {
    ElMessage.error('加载语义目录失败: ' + (e.serverMessage || e.message || ''))
  } finally {
    synonymsLoading.value = false
  }
}

function openSynonymDialog(row?: any) {
  synonymForm.value = row
    ? {
        id: row.id || '',
        concept: row.concept || '',
        databaseId: row.databaseId || '',
        datasetId: row.datasetId || '',
        tableName: row.tableName || '',
        columnName: row.columnName || '',
        columnComment: row.columnComment || ''
      }
    : { id: '', concept: '', databaseId: '', datasetId: '', tableName: '', columnName: '', columnComment: '' }
  showSynonymDialog.value = true
}

async function saveSynonym() {
  if (!synonymForm.value.concept.trim() || !synonymForm.value.columnName.trim()) {
    ElMessage.warning('业务概念与列名必填')
    return
  }
  savingSynonym.value = true
  try {
    await api.post('/admin/catalog/synonym', {
      concept: synonymForm.value.concept.trim(),
      databaseId: synonymForm.value.databaseId || '',
      datasetId: synonymForm.value.datasetId || '',
      tableName: synonymForm.value.tableName || '',
      columnName: synonymForm.value.columnName.trim(),
      columnComment: synonymForm.value.columnComment || '',
      source: 'manual'
    })
    ElMessage.success('同义词已保存')
    showSynonymDialog.value = false
    await loadSynonyms()
  } catch (e: any) {
    ElMessage.error('保存失败: ' + (e.serverMessage || e.message || ''))
  } finally {
    savingSynonym.value = false
  }
}

async function deleteSynonym(row: any) {
  try {
    await ElMessageBox.confirm(`确认删除同义词「${row.concept} → ${row.tableName}.${row.columnName}」？`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await api.delete(`/admin/catalog/synonym/${row.id}`)
    ElMessage.success('已删除')
    await loadSynonyms()
  } catch (e: any) {
    ElMessage.error('删除失败: ' + (e.serverMessage || e.message || ''))
  }
}

async function rebuildCatalogFromTab() {
  try {
    const res = await api.post('/admin/catalog/rebuild', {})
    if (res && res.success) {
      ElMessage.success(`目录重建完成：新增 ${res.created || 0}，更新 ${res.updated || 0}，总计 ${res.total || 0}`)
      await loadSynonyms()
    }
  } catch (e: any) {
    ElMessage.error('重建失败: ' + (e.serverMessage || e.message || ''))
  }
}

function onSynonymDbChange() {
  synonymForm.value.datasetId = ''
  synonymForm.value.tableName = ''
}

function onSynonymDsChange(dsId: string) {
  const ds = datasets.value.find((d: any) => d.id === dsId)
  if (ds) {
    if (ds.tableName) synonymForm.value.tableName = ds.tableName
    if (ds.databaseId && !synonymForm.value.databaseId) synonymForm.value.databaseId = ds.databaseId
  }
}

// ==================== 知识库指标一键导入 ====================
const showKbImportDialog = ref(false)
const kbDocs = ref<any[]>([])
const kbImportDocId = ref('')
const kbImportDbId = ref('')
const kbCandidates = ref<any[]>([])
const parsingKb = ref(false)
const kbImportHint = ref('')

async function openKbImport() {
  showKbImportDialog.value = true
  kbImportHint.value = ''
  kbCandidates.value = []
  if (!databases.value.length) await loadDatabases()
  kbImportDbId.value = kbImportDbId.value || databases.value[0]?.id || ''
  await loadKbDocs()
}

async function loadKbDocs() {
  try {
    const res = await api.get('/knowledge/list?page_size=200')
    if (res && res.success) kbDocs.value = res.items || []
  } catch (e: any) {
    ElMessage.error('加载知识库文档失败: ' + (e.serverMessage || e.message || ''))
  }
}

async function parseKbDoc() {
  if (!kbImportDocId.value) { ElMessage.warning('请先选择知识库文档'); return }
  if (!kbImportDbId.value) { ElMessage.warning('请选择目标数据源'); return }
  parsingKb.value = true
  kbImportHint.value = ''
  kbCandidates.value = []
  try {
    const res = await api.post('/evaluation/indicator-spec/import-from-knowledge', {
      knowledge_id: kbImportDocId.value,
      database_id: kbImportDbId.value
    })
    if (res && res.success) {
      kbCandidates.value = (res.candidates || []).map((c: any) => ({
        ...c,
        _specText: c.suggestedSpec ? JSON.stringify(c.suggestedSpec, null, 2) : ''
      }))
      kbImportHint.value = kbCandidates.value.length
        ? `解析到 ${kbCandidates.value.length} 个候选指标，均为待确认规格（LLM 建议），保存前请人工核对。`
        : ''
    } else {
      ElMessage.warning(res?.message || '解析失败')
      kbImportHint.value = res?.contentPreview ? '文档内容预览：\n' + String(res.contentPreview).slice(0, 300) : ''
    }
  } catch (e: any) {
    ElMessage.error('解析失败: ' + (e.serverMessage || e.message || ''))
  } finally {
    parsingKb.value = false
  }
}

async function saveImportedIndicator(cand: any, openEditor = false) {
  let spec: any = null
  try { spec = JSON.parse(cand._specText) } catch { spec = null }
  if (!spec) { ElMessage.warning('规格 JSON 无效，无法保存'); return }
  const savingMsg = ElMessage({ message: '保存中…', type: 'info', duration: 0 })
  try {
    const created = await api.post('/admin/indicator', {
      name: cand.name,
      formula: cand.formula,
      category: '知识库导入',
      description: `从知识库导入（${cand.source || ''}）`
    })
    const id = created.id
    const saved = await api.post(`/admin/indicator/${id}/spec`, { indicatorSpec: JSON.stringify(spec) })
    savingMsg.close()
    ElMessage.success(
      `指标「${cand.name}」已保存${saved.ready ? '（ready）' : `（${saved.bindStatus || 'not_ready'}，可在规格编辑器补缺口）`}`
    )
    await loadIndicators()
    if (openEditor) {
      openIndicatorSpec({
        id, name: cand.name, formula: cand.formula,
        indicatorSpec: JSON.stringify(spec), bindStatus: saved.bindStatus || 'not_ready'
      })
    }
  } catch (e: any) {
    savingMsg.close()
    ElMessage.error('保存失败: ' + (e.serverMessage || e.message || ''))
  }
}

// ==================== 大模型 多配置管理 ====================
const llmConfigs = ref<any[]>([])
const showLlmDialog = ref(false)
const editingLlmId = ref('')
const llmForm = ref({
  name: '', type: 'deepseek', apiUrl: '', apiKey: '', model: '',
  temperature: 0.3, maxTokens: 32000, topP: 0.9
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

// 切换类型时自动填充默认值（仅新增模式生效，编辑模式跳过避免覆盖用户配置）
watch(() => llmForm.value.type, (newType, _oldType) => {
  if (editingLlmId.value) return  // 编辑模式跳过，保留原有配置
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

async function testLlmConnection(row: any) {
  row.testing = true
  try {
    const res = await api.post(`/admin/config/llm/${row.id}/test`)
    if (res && res.success) {
      ElMessage.success(`测试成功 (${res.latency}) — API 正常响应`)
    } else {
      ElMessage.error(`测试失败: ${res?.message || '未知错误'}`)
    }
  } catch (e: any) {
    ElMessage.error('测试异常: ' + (e?.serverMessage || e?.message || '请求失败'))
  } finally {
    row.testing = false
  }
}

// ==================== 地图服务配置管理 ====================
const mapConfigs = ref<any[]>([])
const showMapDialog = ref(false)
const editingMapId = ref('')
const mapForm = ref({ name: '', type: 'geowebcache', baseUrl: '' })

function openMapDialog(row?: any) {
  if (row) {
    editingMapId.value = row.id
    mapForm.value = {
      name: row.name || '',
      type: row.type || 'geowebcache',
      baseUrl: row.baseUrl || '',
    }
  } else {
    editingMapId.value = ''
    mapForm.value = { name: '', type: 'geowebcache', baseUrl: '' }
  }
  showMapDialog.value = true
}

async function saveMapConfig() {
  if (!mapForm.value.name.trim()) { ElMessage.warning('请输入配置名称'); return }
  if (mapForm.value.type !== 'amap' && !mapForm.value.baseUrl.trim()) { ElMessage.warning('请输入服务地址'); return }

  const payload = {
    name: mapForm.value.name,
    type: mapForm.value.type,
    baseUrl: mapForm.value.baseUrl,
  }

  try {
    if (editingMapId.value) {
      await api.put(`/admin/config/map/${editingMapId.value}`, payload)
      ElMessage.success('地图配置已更新')
    } else {
      const res = await api.post('/admin/config/map', payload)
      ElMessage.success(res.message || '地图配置已保存')
    }
    showMapDialog.value = false
    loadMapConfigs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '保存失败')
  }
}

async function activateMapConfig(row: any) {
  try {
    await api.put(`/admin/config/map/${row.id}/activate`)
    ElMessage.success(`已切换至: ${row.name}`)
    loadMapConfigs()
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.message || '切换失败')
  }
}

async function deleteMapConfig(row: any) {
  try {
    await ElMessageBox.confirm(`确定删除配置「${row.name}」吗？`, '确认', { type: 'warning' })
    await api.delete(`/admin/config/map/${row.id}`)
    ElMessage.success('配置已删除')
    loadMapConfigs()
  } catch { /* cancelled */ }
}

async function loadMapConfigs() {
  try {
    const res = await api.get('/admin/config/map/list')
    if (res && res.success) {
      mapConfigs.value = res.configs || []
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
  loadMapConfigs()
})
</script>

<style scoped>
.admin-container { height: 100%; padding: 2rem; overflow-y: auto; }
.admin-tabs { background: rgba(255, 255, 255, 0.95); border-radius: 12px; padding: 1.5rem; box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1); }
.tab-content { padding: 1rem 0; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1.5rem; }
.section-header h3 { margin: 0; color: #303133; font-size: 1.1rem; font-weight: 600; }
.llm-form { max-width: 600px; }

/* ── 数据集按数据源分层 ── */
.ds-groups { border-top: none; }
.ds-groups :deep(.el-collapse-item__header) { height: auto; line-height: 1.6; padding: 0.5rem 0; }
.ds-group-title { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.ds-group-name { color: #303133; font-weight: 600; font-size: 0.95rem; }
.ds-group-meta { color: #909399; font-size: 0.8rem; }

/* ── AI 注解草稿审核抽屉 ── */
.draft-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
.draft-hint { font-size: 12px; color: #909399; }
.draft-item { border: 1px solid #ebeef5; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.draft-head { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; flex-wrap: wrap; }
.draft-actions { margin-left: auto; }
.draft-meta { font-size: 12px; color: #909399; margin-top: 6px; word-break: break-all; }
.draft-issues { color: #dc2626; font-size: 12px; margin-top: 6px; white-space: pre-line; }
.draft-warnings { color: #d97706; font-size: 12px; margin-top: 6px; white-space: pre-line; }
</style>
