<template>
  <Layout>
    <div class="solution-container">
      <!-- 左侧边栏 -->
      <div class="sidebar">
        <div class="sidebar-section">
          <div class="sidebar-section-header">
            <h3 class="sidebar-title">导航</h3>
            <el-button class="new-session-btn" type="primary" :disabled="analyzing" @click="newSession">
              <el-icon><Plus /></el-icon> 新会话
            </el-button>
          </div>
          <div class="nav-item" @click="goTo('/knowledge')">
            <el-icon><Collection /></el-icon>
            <span>知识库</span>
          </div>
          <div class="nav-item" @click="goTo('/ontology')">
            <el-icon><Box /></el-icon>
            <span>本体模型</span>
          </div>
        </div>
        <div class="sidebar-section">
          <h3 class="sidebar-title">历史记录</h3>
          <div class="history-list custom-scroll">
            <div
              v-for="item in historyList"
              :key="item.id"
              :class="['history-item', { active: item.id === sessionId }]"
            >
              <div class="history-item-main" :class="{ disabled: analyzing }" @click="loadHistory(item)">
                <el-icon><Document /></el-icon>
                <div class="history-item-content">
                  <span class="history-item-title">{{ item.title ? (item.title.length > 20 ? item.title.substring(0, 20) + '...' : item.title) : (item.query ? (item.query.length > 20 ? item.query.substring(0, 20) + '...' : item.query) : '') }}</span>
                  <span class="history-item-time">{{ item.time || formatTime(item.timestamp || item.last_active) }}</span>
                </div>
              </div>
              <el-button class="history-delete-btn" size="small" text type="danger" :disabled="analyzing" @click.stop="deleteHistory(item.id)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 主内容区 -->
      <div class="main-content">
        <!-- 顶部栏 -->
        <div class="top-bar">
          <div class="skill-selector">
            <span class="label">Skills：</span>
            <el-select
              v-model="selectedSkillId"
              clearable
              placeholder="不使用 Skills"
              size="small"
              :loading="skillsLoading"
              style="width: 220px"
              :disabled="!selectedDataSourceId || analyzing"
              @change="previewSelectedSkillPlan"
            >
              <el-option
                v-for="skill in skills"
                :key="skill.id"
                :label="skill.valid === false ? `${skill.name}（需修复）` : skill.name"
                :value="skill.id"
                :disabled="skill.valid === false"
              />
              <template #empty>
                <div class="select-empty" :class="{ error: skillsLoadError }">
                  {{ skillsLoading ? '正在加载 Skills…' : (skillsLoadError || '当前数据源暂无 Skills') }}
                </div>
              </template>
            </el-select>
            <el-button size="small" :disabled="analyzing" @click="openSkillDialog()">
              <el-icon><MagicStick /></el-icon>
              配置 Skills
            </el-button>
          </div>
          <div class="data-source-selector">
            <span class="label">数据源：</span>
            <el-select v-model="selectedDataSourceId" placeholder="选择数据源" size="small" style="width: 200px" :disabled="analyzing" @change="onDataSourceChange">
              <el-option
                v-for="ds in dataSources"
                :key="ds.id"
                :label="ds.name"
                :value="ds.id"
              />
            </el-select>
            <el-button size="small" type="primary" :disabled="analyzing" @click="showDataSourceDialog">
              <el-icon><Setting /></el-icon>
              配置
            </el-button>
          </div>
        </div>

        <!-- 内容区 -->
        <div class="content-area">
          <!-- 左侧：用户交互区 -->
          <div class="chat-panel">
            <div class="chat-area custom-scroll" ref="chatArea">
              <!-- 初始推荐问题 -->
              <div v-if="messages.length === 0" class="empty-state">
                <div class="tags-section">
                  <div class="suggest-cards">
                      <div
                        v-for="(item, index) in allSuggestions"
                        :key="index"
                        class="suggest-card"
                        :style="{ '--card-color': item.color }"
                        :class="{ disabled: analyzing }"
                        @click="selectQuestion(item.text)"
                      >
                        <div class="suggest-icon">
                          <el-icon :size="20">
                            <component :is="item.icon" />
                          </el-icon>
                        </div>
                        <div class="suggest-content">
                          <div class="suggest-title">{{ item.text }}</div>
                          <div class="suggest-desc">{{ item.desc }}</div>
                        </div>
                        <el-icon class="suggest-arrow"><ArrowRight /></el-icon>
                      </div>
                    </div>
                </div>
              </div>
              
              <!-- 消息列表 -->
              <div v-else class="message-list">
                <div
                  v-for="(msg, index) in messages"
                  :key="index"
                  :class="['message', msg.role]"
                >
                  <div class="message-avatar">
                    <el-avatar :size="40">
                      {{ msg.role === 'user' ? '我' : 'AI' }}
                    </el-avatar>
                  </div>
                  <div class="message-content">
                    <!-- 结果展示区（SQL + 数据表格）放在建议前面 -->
                    <div v-if="msg.result" class="result-section">
                      <div v-if="msg.result.type === 'skill_query'" class="skill-query-result">
                        <div class="result-header skill-result-header">
                          <div>
                            <h5>Skills 查询结果：{{ msg.result.skillName }}</h5>
                            <p v-if="msg.result.skillDescription">{{ msg.result.skillDescription }}</p>
                          </div>
                          <div class="skill-result-summary">
                            <el-tag :type="getStatusTagType(msg.result.executionSummary?.status)">
                              {{ getStatusLabel(msg.result.executionSummary?.status) }}
                            </el-tag>
                            <span>
                              成功 {{ msg.result.executionSummary?.successfulSteps ?? 0 }} / {{ msg.result.executionSummary?.totalSteps ?? (msg.result.queryResults?.length || 0) }}
                            </span>
                            <span v-if="msg.result.executionSummary?.emptySteps">空结果 {{ msg.result.executionSummary.emptySteps }}</span>
                            <span v-if="msg.result.executionSummary?.skippedSteps">跳过 {{ msg.result.executionSummary.skippedSteps }}</span>
                            <span v-if="msg.result.executionSummary?.truncatedSteps">截断 {{ msg.result.executionSummary.truncatedSteps }}</span>
                            <span v-if="msg.result.executionSummary?.durationMs">
                              {{ formatDuration(msg.result.executionSummary.durationMs) }}
                            </span>
                          </div>
                        </div>
                        <div
                          v-for="item in msg.result.queryResults"
                          :key="item.order"
                          class="skill-result-item"
                        >
                          <div class="skill-result-title">
                            <span class="skill-order">{{ item.order }}</span>
                            <div>
                              <strong>{{ item.datasetName }}</strong>
                              <p>{{ item.instruction }}</p>
                            </div>
                            <el-tag v-if="item.error" type="danger" size="small">失败</el-tag>
                            <el-tag v-else-if="item.skipped || item.status === 'skipped'" type="info" size="small">已跳过</el-tag>
                            <el-tag v-else-if="item.semanticSuccess === false" type="warning" size="small">未满足结果要求</el-tag>
                            <el-tag v-else type="success" size="small">
                              {{ formatRowCountSummary(item) }}
                            </el-tag>
                            <el-tag v-if="isResultTruncated(item)" type="warning" size="small">结果已截断</el-tag>
                            <span v-if="item.durationMs !== undefined" class="skill-result-duration">
                              {{ formatDuration(item.durationMs) }}
                            </span>
                          </div>
                          <el-alert v-if="item.error" :title="item.error" type="error" :closable="false" show-icon />
                          <el-alert
                            v-else-if="item.skipped || item.status === 'skipped'"
                            :title="item.skipReason || '本步骤已按策略跳过'"
                            type="info"
                            :closable="false"
                            show-icon
                          />
                          <el-alert
                            v-else-if="item.semanticSuccess === false"
                            :title="item.semanticMessage || '查询已执行，但结果未满足本步骤的有效性要求'"
                            type="warning"
                            :closable="false"
                            show-icon
                          />
                          <div v-if="item.sql" class="sql-section">
                            <h6>执行 SQL</h6>
                            <pre class="sql-code">{{ item.sql }}</pre>
                          </div>
                          <div v-if="item.rows && item.rows.length" class="data-section">
                            <h6>
                              数据结果（{{ formatRowCountSummary(item) }}<span v-if="isResultTruncated(item)">，已截断</span>）
                            </h6>
                            <el-table :data="item.rows" size="small" max-height="320" border stripe>
                              <el-table-column
                                v-for="column in Object.keys(item.rows[0] || {})"
                                :key="column"
                                :prop="column"
                                :label="column"
                                min-width="110"
                                show-overflow-tooltip
                              />
                            </el-table>
                          </div>
                          <el-empty
                            v-else-if="!item.error && !(item.skipped || item.status === 'skipped')"
                            :image-size="56"
                            description="本步骤返回 0 行数据"
                          />
                        </div>
                        <div v-if="msg.result.final_answer" class="summary-section">
                          <h6>Skills 综合评估</h6>
                          <div v-html="renderMarkdown(msg.result.final_answer)"></div>
                        </div>
                      </div>

                      <div v-if="msg.result.type === 'air_superiority'" class="air-superiority-result">
                        <div class="result-header">
                          <h5>制空权分析结果<span v-if="msg.result.region"> - {{ msg.result.region }}</span></h5>
                        </div>
                        <div v-for="(qr, idx) in msg.result.results" :key="idx" class="query-result-item">
                          <p class="query-result-title">{{ qr.group }} - {{ qr.label }}</p>
                          <div v-if="qr.sql" class="result-block">
                            <p class="block-label">SQL语句</p>
                            <p style="white-space: pre-wrap;">{{ qr.sql }}</p>
                          </div>
                          <div v-if="qr.rows && qr.rows.length > 0" class="result-block">
                            <p class="block-label">数据结果</p>
                            <p style="white-space: pre-wrap;">{{ formatRowsAsText(qr.columns, qr.rows) }}</p>
                          </div>
                          <p v-if="!qr.sql && (!qr.rows || qr.rows.length === 0)" class="no-data">暂无数据</p>
                          <div v-if="qr.insight" class="result-block">
                            <p class="block-label">分析洞察</p>
                            <p>{{ qr.insight }}</p>
                          </div>
                        </div>
                        <div v-if="msg.result.need_conclusion && msg.result.final_answer" class="summary-section">
                          <h6>综合评估</h6>
                          <p>{{ msg.result.final_answer }}</p>
                        </div>
                      </div>

                      <div v-if="msg.result.type === 'combat_effectiveness'" class="combat-result">
                        <div class="result-header">
                          <h5>作战效能评估结果</h5>
                        </div>
                        <div v-for="(r, idx) in msg.result.results" :key="idx" class="query-result-item">
                          <p class="query-result-title">{{ r.group }} - {{ r.label }}</p>
                          <div v-if="r.sql" class="result-block">
                            <p class="block-label">SQL语句</p>
                            <p style="white-space: pre-wrap;">{{ r.sql }}</p>
                          </div>
                          <div v-if="r.rows && r.rows.length > 0" class="result-block">
                            <p class="block-label">数据结果</p>
                            <p style="white-space: pre-wrap;">{{ formatRowsAsText(r.columns, r.rows) }}</p>
                          </div>
                          <p v-if="!r.sql && (!r.rows || r.rows.length === 0)" class="no-data">暂无数据</p>
                          <div v-if="r.insight" class="result-block">
                            <p class="block-label">分析洞察</p>
                            <p>{{ r.insight }}</p>
                          </div>
                        </div>
                        <div v-if="msg.result.need_conclusion && msg.result.final_answer" class="summary-section">
                          <h6>综合评估</h6>
                          <p>{{ msg.result.final_answer }}</p>
                        </div>
                      </div>
                      
                      <div v-if="msg.result.type === 'indicator_calculation'" class="indicator-result">
                        <div class="result-header">
                          <h5>指标计算结果</h5>
                        </div>
                        <div class="sql-section">
                          <h6>生成的SQL</h6>
                          <pre class="sql-code">{{ msg.result.generatedSql }}</pre>
                        </div>
                        <div v-if="msg.result.queryResult" class="data-section">
                          <h6>查询结果</h6>
                          <el-table :data="msg.result.queryResult.sampleData" style="width: 100%" size="small">
                            <el-table-column
                              v-for="(_value, key) in msg.result.queryResult.sampleData[0]"
                              :key="key"
                              :prop="String(key)"
                              :label="msg.result.queryResult.columns ? msg.result.queryResult.columns[Object.keys(msg.result.queryResult.sampleData[0]).indexOf(String(key))] : String(key)"
                            />
                          </el-table>
                        </div>
                        <div v-if="msg.result.statistics" class="statistics-section">
                          <h6>统计汇总</h6>
                          <div class="stats-grid">
                            <div class="stat-item">
                              <span class="stat-label">总任务数</span>
                              <span class="stat-value">{{ msg.result.statistics.totalMissions }}</span>
                            </div>
                            <div class="stat-item">
                              <span class="stat-label">成功数</span>
                              <span class="stat-value">{{ msg.result.statistics.totalSuccess }}</span>
                            </div>
                            <div class="stat-item highlight">
                              <span class="stat-label">总成功率</span>
                              <span class="stat-value">{{ msg.result.statistics.overallRate }}</span>
                            </div>
                          </div>
                        </div>
                      </div>
                      
                      <div v-if="msg.result.type === 'general' || msg.result.type === 'data_query'" class="general-result">
                        <!-- 执行的SQL -->
                        <div v-if="msg.result.generatedSql" class="sql-section">
                          <h6>生成的SQL</h6>
                          <pre class="sql-code">{{ msg.result.generatedSql }}</pre>
                        </div>
                        <!-- 图表可视化（仅当 chartConfig 有效时显示） -->
                        <div v-if="msg.result.chartConfig && msg.result.chartConfig.vizType !== 'table' && msg.result.rawResults && msg.result.rawResults.length > 0" class="chart-section">
                          <div class="chart-header">
                            <h6>{{ msg.result.chartConfig.chartTitle || '数据可视化' }}</h6>
                            <el-radio-group v-model="chartViewMode" size="small">
                              <el-radio-button value="chart">图表</el-radio-button>
                              <el-radio-button value="table">表格</el-radio-button>
                            </el-radio-group>
                          </div>
                          <div v-show="chartViewMode === 'chart'" class="chart-container">
                            <v-chart :option="buildChartOption(msg.result.chartConfig, msg.result.rawResults)" style="height: 360px" autoresize />
                          </div>
                          <div v-show="chartViewMode === 'table'" class="data-section">
                            <el-table :data="msg.result.rawResults" style="width: 100%" size="small" max-height="400" border stripe>
                              <el-table-column
                                v-for="col in Object.keys(msg.result.rawResults[0] || {})"
                                :key="col"
                                :prop="col"
                                :label="col"
                                min-width="100"
                                show-overflow-tooltip
                              />
                            </el-table>
                          </div>
                        </div>
                        <!-- 数据表格（无图表时） -->
                        <div v-else-if="msg.result.rawResults && msg.result.rawResults.length > 0" class="data-section">
                          <h6>查询结果（共 {{ msg.result.totalRows || msg.result.rawResults.length }} 行）</h6>
                          <el-table :data="msg.result.rawResults" style="width: 100%" size="small" max-height="400" border stripe>
                            <el-table-column
                              v-for="col in Object.keys(msg.result.rawResults[0] || {})"
                              :key="col"
                              :prop="col"
                              :label="col"
                              min-width="100"
                              show-overflow-tooltip
                            />
                          </el-table>
                        </div>
                        <!-- 数据为空提示 -->
                        <div v-if="msg.result.rawResults && msg.result.rawResults.length === 0" class="data-empty">
                          查询执行成功，但未返回数据
                        </div>
                        <!-- 结论（仅 need_conclusion=true 时显示） -->
                        <div v-if="msg.result.need_conclusion && msg.result.final_answer" class="summary-section">
                          <h6>评估结论</h6>
                          <p>{{ msg.result.final_answer }}</p>
                        </div>
                      </div>
                      
                      <div v-if="msg.result.knowledgeReference && msg.result.knowledgeReference.length > 0" class="references-section">
                        <h6>参考资料</h6>
                        <ul>
                          <li v-for="(ref, idx) in msg.result.knowledgeReference" :key="idx">{{ ref }}</li>
                        </ul>
                      </div>
                    </div>
                    <!-- 分析建议（2-3条） -->
                    <div class="message-text" v-html="renderMarkdown(msg.content)"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <!-- 执行过程侧边栏 -->
          <div v-if="showExecutionPanel" class="execution-panel" :style="{ width: executionPanelWidth + 'px' }">
            <div class="resize-handle" @mousedown="startResize"></div>
            <div class="panel-header">
              <div class="panel-title">
                <span>{{ executionPanelTitle }}</span>
                <small v-if="displayedExecutionSkillName">{{ displayedExecutionSkillName }}</small>
              </div>
              <div class="panel-header-actions">
                <el-tag
                  v-if="rootExecutionStep"
                  size="small"
                  effect="plain"
                  :type="getStatusTagType(rootExecutionStep.status)"
                >
                  {{ getStatusLabel(rootExecutionStep.status) }}
                </el-tag>
                <el-icon class="panel-close" @click="showExecutionPanel = false" title="收起"><Close /></el-icon>
              </div>
            </div>
            <div class="execution-content custom-scroll">
              <div v-if="executionSteps.length === 0 && !analyzing" class="empty-execution">
                <el-icon :size="32" color="#d1d5db"><Cpu /></el-icon>
                <p>暂无执行步骤</p>
              </div>
              <div v-else class="steps-list">
                <div
                  v-for="step in executionSteps"
                  :key="step.step"
                  :class="['inline-step', getStepStatusClass(step.status), { 'is-sub-step': Boolean(step.parentStep) }]"
                >
                  <div class="inline-step-header">
                    <span class="inline-step-icon">
                      <el-icon v-if="step.status === 'completed'"><CircleCheck /></el-icon>
                      <el-icon v-else-if="step.status === 'in_progress'"><Loading class="is-loading" /></el-icon>
                      <el-icon v-else-if="step.status === 'error'"><CircleClose /></el-icon>
                      <el-icon v-else-if="step.status === 'partial'"><WarningFilled /></el-icon>
                      <el-icon v-else><Clock /></el-icon>
                    </span>
                    <span class="inline-step-title">
                      {{ step.skillStep ? step.description : `步骤 ${step.step}: ${step.description}` }}
                    </span>
                  </div>
                  <div class="inline-step-detail">{{ step.detail }}</div>
                  <div v-if="step.phase === 'dataset_query' && !step.subStep" class="inline-step-policy">
                    {{ step.dependsOnPrevious ? `依赖前序（失败：${getPolicyLabel(step.onDependencyFailure)}）` : '独立步骤' }}；
                    {{ step.requireNonEmpty ? `要求非空（空结果：${getPolicyLabel(step.onEmpty)}）` : '允许空结果' }}
                  </div>
                  <div v-if="step.subStep || step.phase" class="inline-step-phase">
                    <span>{{ step.subStep ? `子步骤 · ${getPhaseLabel(step.phase)}` : getPhaseLabel(step.phase) }}</span>
                  </div>
                  <div v-if="step.durationMs !== undefined || step.rowCount !== undefined || step.returnedRows !== undefined || step.displayedRows !== undefined" class="inline-step-meta">
                    <span v-if="step.rowCount !== undefined || step.returnedRows !== undefined || step.displayedRows !== undefined">
                      {{ formatRowCountSummary(step) }}<span v-if="step.truncated">（已截断）</span>
                    </span>
                    <span v-if="step.durationMs !== undefined">耗时 {{ formatDuration(step.durationMs) }}</span>
                  </div>
                  <el-progress
                    v-if="step.status === 'in_progress'"
                    class="inline-step-progress"
                    :percentage="step.progress || 0"
                    :show-text="false"
                    :stroke-width="3"
                  />
                  <details v-if="step.thinking" class="inline-step-thinking">
                    <summary>查看执行详情</summary>
                    <pre>{{ step.thinking }}</pre>
                  </details>
                </div>
              </div>
            </div>
          </div>
          <!-- 收起状态下的展开按钮 -->
          <div v-else class="execution-panel-toggle" @click="showExecutionPanel = true" title="展开系统执行过程">
            <el-icon><ArrowRight /></el-icon>
            <span class="toggle-text">执行过程</span>
          </div>
        </div>

        <!-- 底部输入区 -->
        <div class="input-area">
          <div class="input-wrapper">
            <el-input
              v-model="inputMessage"
              type="textarea"
              :rows="3"
              :disabled="analyzing"
              placeholder="输入您的评估需求，如：分析XXX区域的红蓝双方制空权优势对比..."
              @keyup.enter.ctrl="sendMessage"
            />
            <div class="input-actions">
              <el-button v-if="analyzing" type="danger" plain @click="cancelAnalysis()">
                停止分析
              </el-button>
              <el-button type="primary" @click="sendMessage" :disabled="analyzing">
                <el-icon><Promotion /></el-icon>
                {{ analyzing ? '分析中...' : '发送' }}
              </el-button>
            </div>
          </div>
          
          <!-- 工具按钮 -->
          <div class="tools-bar">
            <div
              v-for="tool in tools"
              :key="tool.id"
              :class="['tool-item', { 'current': tool.current }]"
              @click="navigateToTool(tool.path)"
            >
              <div class="tool-icon">
                <el-icon :size="16" :color="tool.current ? 'white' : tool.color">
                  <component :is="tool.icon" />
                </el-icon>
              </div>
              <span class="tool-name">{{ tool.name }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- 数据源配置对话框 -->
      <el-dialog v-model="dataSourceDialogVisible" title="数据源配置" width="600px" @closed="resetPendingDataSource">
        <div class="data-source-list">
          <div
            v-for="ds in dataSources"
            :key="ds.id"
            :class="['ds-item', { active: ds.id === pendingDataSourceId }]"
            @click="selectPendingDataSource(ds)"
          >
            <div class="ds-name">{{ ds.name }}</div>
            <div class="ds-meta">
              <el-tag size="small">{{ ds.type }}</el-tag>
              <el-tag :type="ds.status === 'available' ? 'success' : 'info'" size="small">
                {{ ds.status === 'available' ? '可用' : '不可用' }}
              </el-tag>
            </div>
          </div>
        </div>
        <template #footer>
          <el-button @click="cancelDataSourceDialog">取消</el-button>
          <el-button type="primary" :loading="dataSourceSwitching" :disabled="!pendingDataSourceId" @click="confirmDataSource">确定</el-button>
        </template>
      </el-dialog>

      <!-- Skills 顺序查询配置 -->
      <el-dialog v-model="skillDialogVisible" title="Skills 查询流程配置" width="820px" destroy-on-close>
        <div class="skill-dialog-toolbar">
          <el-select
            v-model="editingSkillId"
            clearable
            placeholder="新建 Skill"
            style="width: 260px"
            @change="loadSkillForEdit"
          >
            <el-option v-for="skill in skills" :key="skill.id" :label="skill.name" :value="skill.id" />
          </el-select>
          <el-button type="primary" plain @click="resetSkillForm">新建 Skill</el-button>
          <el-button v-if="editingSkillId" type="danger" plain @click="removeSkill">删除</el-button>
        </div>

        <el-form label-position="top" class="skill-form">
          <el-form-item label="Skill 名称" required>
            <el-input v-model="skillForm.name" maxlength="100" show-word-limit placeholder="例如：装备保障综合评估" />
          </el-form-item>
          <el-form-item label="执行目标">
            <el-input
              v-model="skillForm.description"
              type="textarea"
              :rows="2"
              maxlength="1000"
              show-word-limit
              placeholder="告诉大模型这个 Skills 流程最终要完成什么评估"
            />
          </el-form-item>
          <el-form-item label="数据集查询顺序" required>
            <div class="skill-steps-editor">
              <el-alert
                title="系统将严格按从上到下的顺序执行；后续步骤会收到前序步骤的真实查询结果，全部完成后再由大模型输出综合结论。"
                type="info"
                :closable="false"
                show-icon
              />
              <div v-for="(step, index) in skillForm.steps" :key="step.localId" class="skill-step-editor">
                <span class="skill-step-index">{{ index + 1 }}</span>
                <div class="skill-step-fields">
                  <el-select
                    v-model="step.datasetId"
                    placeholder="选择要查询的数据集"
                    filterable
                    :loading="skillDatasetsLoading"
                    style="width: 100%"
                    @change="syncSkillDatasetName(step)"
                  >
                    <el-option
                      v-for="dataset in skillDatasets"
                      :key="dataset.id"
                      :label="`${dataset.name} (${dataset.tableName || '未关联表'})`"
                      :value="dataset.id"
                    />
                    <template #empty>
                      <div class="select-empty" :class="{ error: skillDatasetsLoadError }">
                        {{ skillDatasetsLoading ? '正在加载数据集…' : (skillDatasetsLoadError || '当前数据源暂无可查询数据集') }}
                      </div>
                    </template>
                  </el-select>
                  <el-input
                    v-model="step.instruction"
                    type="textarea"
                    :rows="2"
                    maxlength="2000"
                    show-word-limit
                    placeholder="本步骤查询要求，例如：先统计各型号装备的可用数量"
                  />
                  <div class="skill-step-policies">
                    <el-checkbox
                      v-model="step.dependsOnPrevious"
                      :disabled="index === 0"
                      @change="index === 0 && (step.dependsOnPrevious = false)"
                    >依赖前序结果</el-checkbox>
                    <label v-if="step.dependsOnPrevious">
                      前序失败时
                      <el-select v-model="step.onDependencyFailure" size="small" style="width: 110px">
                        <el-option label="跳过本步" value="skip" />
                        <el-option label="停止流程" value="stop" />
                        <el-option label="继续执行" value="continue" />
                      </el-select>
                    </label>
                    <el-checkbox v-model="step.requireNonEmpty">要求结果非空</el-checkbox>
                    <label v-if="step.requireNonEmpty">
                      空结果时
                      <el-select v-model="step.onEmpty" size="small" style="width: 110px">
                        <el-option label="继续执行" value="continue" />
                        <el-option label="空结果跳过本步" value="skip" />
                        <el-option label="停止流程" value="stop" />
                      </el-select>
                    </label>
                  </div>
                </div>
                <div class="skill-step-actions">
                  <el-button text :disabled="index === 0" @click="moveSkillStep(index, -1)">
                    <el-icon><ArrowUp /></el-icon>
                  </el-button>
                  <el-button text :disabled="index === skillForm.steps.length - 1" @click="moveSkillStep(index, 1)">
                    <el-icon><ArrowDown /></el-icon>
                  </el-button>
                  <el-button text type="danger" @click="deleteSkillStep(index)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <el-button class="add-skill-step" plain @click="addSkillStep">
                <el-icon><Plus /></el-icon> 添加数据集查询步骤
              </el-button>
            </div>
          </el-form-item>
        </el-form>

        <template #footer>
          <el-button @click="skillDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingSkill" @click="saveSkill">保存 Skill</el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Collection,
  Box,
  Document,
  Setting,
  Promotion,
  CircleCheck,
  CircleClose,
  WarningFilled,
  Clock,
  ChatDotRound,
  Loading,
  Cpu,
  Plus,
  Delete,
  ArrowRight,
  ArrowUp,
  ArrowDown,
  MagicStick,
  PieChart as ElPieChart
} from '@element-plus/icons-vue'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, PieChart, LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, TitleComponent } from 'echarts/components'
import VChart from 'vue-echarts'

use([CanvasRenderer, BarChart, PieChart, LineChart, GridComponent, TooltipComponent, LegendComponent, TitleComponent] as any)

const router = useRouter()

// localStorage 持久化 key
const LS_SESSION_ID = 'solution_session_id'
const LS_HISTORY_LIST = 'solution_history_list'
const LS_SESSION_MSGS = 'solution_session_msgs'

const parseStoredJson = <T,>(key: string, fallback: T): T => {
  try {
    const raw = localStorage.getItem(key)
    return raw ? JSON.parse(raw) as T : fallback
  } catch (error) {
    console.warn(`[SolutionEvaluation] 忽略损坏的本地数据：${key}`, error)
    return fallback
  }
}

const cloneSerializable = <T,>(value: T): T => JSON.parse(JSON.stringify(value)) as T

const orderExecutionSteps = (steps: Array<any>): Array<any> => {
  const snapshot = cloneSerializable(Array.isArray(steps) ? steps : [])
  const roots = snapshot.filter((step: any) => !step.parentStep)
  const ordered: Array<any> = []
  const consumed = new Set<any>()
  roots.forEach((root: any) => {
    ordered.push(root)
    consumed.add(root)
    snapshot
      .filter((step: any) => step.parentStep === root.step)
      .forEach((child: any) => {
        ordered.push(child)
        consumed.add(child)
      })
  })
  snapshot.filter((step: any) => !consumed.has(step)).forEach((step: any) => ordered.push(step))
  return ordered
}

// 工具配置
const tools = [
  {
    id: 1,
    name: '智能问答',
    icon: ChatDotRound,
    color: '#409eff',
    path: '/qa',
    current: false
  },
  {
    id: 2,
    name: '指标分析',
    icon: ElPieChart,
    color: '#67c23a',
    path: '/indicator',
    current: false
  },
  {
    id: 3,
    name: '评估分析',
    icon: Document,
    color: '#e6a23c',
    path: '/evaluation',
    current: true
  }
]

// 跳转工具
const navigateToTool = (path: string) => {
  if (analyzing.value) cancelAnalysis('页面已切换，当前分析已取消')
  router.push(path)
}

// 状态
const inputMessage = ref('')
const analyzing = ref(false)
const messages = ref<Array<any>>([])
const historyList = ref<Array<any>>(parseStoredJson<Array<any>>(LS_HISTORY_LIST, []))
const sessionMessages = ref<Record<string, Array<any>>>(parseStoredJson<Record<string, Array<any>>>(LS_SESSION_MSGS, {}))
const sessionId = ref(localStorage.getItem(LS_SESSION_ID) || '')

console.log('[SolutionEvaluation] component loaded')

// 简单 markdown 渲染（处理 **加粗**、换行、列表）
function renderMarkdown(text: string): string {
  if (!text) return ''
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n/g, '<br/>')
    .replace(/^(\d+)\.\s(.+)$/gm, '<div class="md-list-item"><span class="md-num">$1.</span> $2</div>')
    .replace(/<br\/>(\d+)\.\s/g, '<br/><span class="md-num">$1.</span> ')
  return html
}

const dataSources = ref<Array<any>>([])
const selectedDataSourceId = ref<string | null>(null)
const selectedDataSourceName = ref<string>('')
const dataSourceDialogVisible = ref(false)
const pendingDataSourceId = ref<string | null>(null)
const dataSourceSwitching = ref(false)
const showExecutionPanel = ref(true)
const chartViewMode = ref('chart')
const executionPanelWidth = ref(460)
const isResizing = ref(false)
const executionSteps = ref<Array<any>>([])
const displayedExecutionSkillName = ref('')
const skills = ref<Array<any>>([])
const skillDatasets = ref<Array<any>>([])
const skillsLoading = ref(false)
const skillsLoadError = ref('')
const skillDatasetsLoading = ref(false)
const skillDatasetsLoadError = ref('')
const selectedSkillId = ref<string>('')
const skillDialogVisible = ref(false)
const editingSkillId = ref<string>('')
const savingSkill = ref(false)
let skillStepSequence = 0
let metadataLoadSequence = 0
let requestSequence = 0
let pendingRestoredSkillId = ''
interface EvaluationRequestContext {
  id: string
  controller: AbortController
  steps: Array<any>
  aiMessage: any
  query: string
  requestedSessionId: string
  resolvedSessionId: string
  skillId: string
  skillName: string
  resultReceived: boolean
  terminalError: string
}
let activeRequest: EvaluationRequestContext | null = null

const newSkillStep = (dependsOnPrevious = false) => ({
  localId: `skill-step-${Date.now()}-${skillStepSequence++}`,
  datasetId: '',
  datasetName: '',
  instruction: '',
  dependsOnPrevious,
  onDependencyFailure: 'skip',
  requireNonEmpty: true,
  onEmpty: 'continue'
})

const skillForm = ref<any>({
  name: '',
  description: '',
  steps: [newSkillStep(false)]
})

const selectedSkill = computed(() => (
  skills.value.find((item: any) => item.id === selectedSkillId.value) || null
))
const selectedSkillName = computed(() => selectedSkill.value?.name || '')
const rootExecutionStep = computed(() => (
  executionSteps.value.find((step: any) => step.step === 'skill') || null
))
const executionPanelTitle = computed(() => (
  executionSteps.value.some((step: any) => step.skillStep)
    ? 'Skills 执行流程'
    : '系统执行过程'
))

const getStatusLabel = (status?: string) => ({
  pending: '等待执行',
  in_progress: '执行中',
  completed: '已完成',
  partial: '部分成功',
  error: '失败',
  skipped: '已跳过'
}[status || ''] || '等待执行')

const getStatusTagType = (status?: string) => {
  if (status === 'completed') return 'success'
  if (status === 'partial') return 'warning'
  if (status === 'error') return 'danger'
  if (status === 'in_progress') return 'primary'
  return 'info'
}

const getPolicyLabel = (policy?: string) => ({
  stop: '停止流程',
  skip: '标记跳过',
  continue: '继续执行'
}[policy || ''] || '继续执行')

const getPhaseLabel = (phase?: string) => ({
  skill: 'Skill 流程',
  dataset_query: '数据集查询',
  dataset_discovery: '发现数据集',
  structure_load: '读取数据结构',
  structure_loading: '读取数据结构',
  indicator_load: '加载指标',
  indicator_loading: '加载指标',
  sql_generation: '生成 SQL',
  scope_validation: '范围校验',
  sql_execution: '执行 SQL',
  summary: '综合汇总'
}[phase || ''] || phase || '执行步骤')

const formatDuration = (durationMs: number) => {
  if (!Number.isFinite(durationMs)) return '-'
  if (durationMs < 1000) return `${Math.max(0, Math.round(durationMs))} ms`
  return `${(durationMs / 1000).toFixed(durationMs < 10000 ? 1 : 0)} 秒`
}

const getReturnedRowCount = (item: any): number => {
  if (item?.returnedRows !== null && item?.returnedRows !== undefined) {
    const explicit = Number(item.returnedRows)
    if (Number.isFinite(explicit) && explicit >= 0) return explicit
  }
  if (item?.rowCount !== null && item?.rowCount !== undefined) {
    const rowCount = Number(item.rowCount)
    if (Number.isFinite(rowCount) && rowCount >= 0) return rowCount
  }
  return Array.isArray(item?.rows) ? item.rows.length : 0
}

const getDisplayedRowCount = (item: any): number => {
  if (item?.displayedRows !== null && item?.displayedRows !== undefined) {
    const explicit = Number(item.displayedRows)
    if (Number.isFinite(explicit) && explicit >= 0) return explicit
  }
  if (Array.isArray(item?.rows)) return item.rows.length
  return getReturnedRowCount(item)
}

const getTotalRowCount = (item: any): number | undefined => {
  if (item?.totalRows !== null && item?.totalRows !== undefined) {
    const explicit = Number(item.totalRows)
    if (Number.isFinite(explicit) && explicit >= 0) return explicit
  }
  return undefined
}

const getMinimumTotalRowCount = (item: any): number | undefined => {
  if (item?.minimumTotalRows !== null && item?.minimumTotalRows !== undefined) {
    const explicit = Number(item.minimumTotalRows)
    if (Number.isFinite(explicit) && explicit >= 0) return explicit
  }
  return isResultTruncated(item) ? getReturnedRowCount(item) : undefined
}

const isResultTruncated = (item: any): boolean => {
  if (typeof item?.truncated === 'boolean') return item.truncated
  const total = getTotalRowCount(item)
  return total !== undefined && total > getReturnedRowCount(item)
}

const formatRowCountSummary = (item: any): string => {
  const parts = [`展示 ${getDisplayedRowCount(item)} 行`, `已读取 ${getReturnedRowCount(item)} 行`]
  const total = getTotalRowCount(item)
  if (total !== undefined) {
    parts.push(`总计 ${total} 行`)
  } else if (isResultTruncated(item)) {
    const minimum = getMinimumTotalRowCount(item)
    if (minimum !== undefined) parts.push(`至少 ${minimum} 行`)
  }
  return parts.join(' / ')
}

const buildSkillPlan = (skill: any) => {
  if (!skill) return []
  const steps = skill.steps || []
  return [
    {
      step: 'skill',
      description: `Skills 执行：${skill.name}`,
      status: 'pending',
      detail: `等待按顺序执行 ${steps.length} 个数据集查询步骤`,
      progress: 0,
      skillStep: true,
      phase: 'skill',
      skillId: skill.id,
      skillName: skill.name,
      totalSteps: steps.length
    },
    ...steps.map((step: any, index: number) => ({
      step: `skill.${index + 1}`,
      description: `查询数据集 ${index + 1}/${steps.length}：${step.datasetName || step.datasetId}`,
      status: 'pending',
      detail: step.instruction || '根据用户问题查询该数据集',
      progress: 0,
      skillStep: true,
      phase: 'dataset_query',
      skillId: skill.id,
      skillName: skill.name,
      order: index + 1,
      totalSteps: steps.length,
      datasetId: step.datasetId,
      datasetName: step.datasetName,
      dependsOnPrevious: index === 0 ? false : (step.dependsOnPrevious ?? true),
      onDependencyFailure: step.onDependencyFailure || 'skip',
      requireNonEmpty: step.requireNonEmpty ?? true,
      onEmpty: step.onEmpty || 'continue'
    })),
    {
      step: 'skill.summary',
      description: '汇总 Skills 查询结果',
      status: 'pending',
      detail: '等待全部数据集查询完成后生成最终结论',
      progress: 0,
      skillStep: true,
      phase: 'summary',
      skillId: skill.id,
      skillName: skill.name,
      totalSteps: steps.length
    }
  ]
}

const previewSelectedSkillPlan = () => {
  if (analyzing.value) return
  executionSteps.value = buildSkillPlan(selectedSkill.value)
  displayedExecutionSkillName.value = selectedSkillName.value
  if (selectedSkill.value) showExecutionPanel.value = true
}

// 拖拽调整面板宽度
const startResize = (e: MouseEvent) => {
  isResizing.value = true
  const startX = e.clientX
  const startWidth = executionPanelWidth.value
  const onMouseMove = (ev: MouseEvent) => {
    if (!isResizing.value) return
    const delta = startX - ev.clientX
    executionPanelWidth.value = Math.min(700, Math.max(300, startWidth + delta))
  }
  const onMouseUp = () => {
    isResizing.value = false
    document.removeEventListener('mousemove', onMouseMove)
    document.removeEventListener('mouseup', onMouseUp)
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
  }
  document.addEventListener('mousemove', onMouseMove)
  document.addEventListener('mouseup', onMouseUp)
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
}

// 持久化辅助函数
const persistState = () => {
  try {
    localStorage.setItem(LS_SESSION_ID, sessionId.value)
    localStorage.setItem(LS_HISTORY_LIST, JSON.stringify(historyList.value))
    localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(sessionMessages.value))
  } catch (error) {
    // localStorage 空间有限。保留执行流程和结论，仅压缩历史结果明细后再保存。
    console.warn('[SolutionEvaluation] 完整历史保存失败，改为保存压缩快照', error)
    try {
      const compacted = cloneSerializable(sessionMessages.value)
      Object.values(compacted).forEach((items: Array<any>) => {
        items.forEach((message: any) => {
          message.result?.queryResults?.forEach((result: any) => {
            if (Array.isArray(result.rows) && result.rows.length > 20) {
              result.rows = result.rows.slice(0, 20)
              result.historyTruncated = true
              result.truncated = true
            }
          })
        })
      })
      localStorage.setItem(LS_SESSION_MSGS, JSON.stringify(compacted))
    } catch (fallbackError) {
      console.error('[SolutionEvaluation] 历史快照保存失败', fallbackError)
    }
  }
}

// 制空权分析示例
const airSuperiorityExamples = [
  {
    text: '分析A区域的红蓝双方制空权优势对比',
    desc: '区域空中优势对比分析',
    icon: 'Aim',
    color: '#3b82f6'
  },
  {
    text: '评估B区域的空中优势情况',
    desc: '区域制空能力评估',
    icon: 'Guide',
    color: '#ef4444'
  },
  {
    text: '对比红蓝双方的制空能力',
    desc: '双方制空能力综合对比',
    icon: 'TrendCharts',
    color: '#8b5cf6'
  }
]

// 指标计算示例
const indicatorExamples = [
  {
    text: '计算本月任务完成率指标',
    desc: '任务完成率统计分析',
    icon: 'DataAnalysis',
    color: '#10b981'
  },
  {
    text: '查询各区域作战效能指标',
    desc: '区域效能指标分布查询',
    icon: 'Histogram',
    color: '#f59e0b'
  },
  {
    text: '统计武器系统作战成功率',
    desc: '武器系统效能统计',
    icon: 'Coin',
    color: '#ec4899'
  }
]

const allSuggestions = [
  ...airSuperiorityExamples,
  ...indicatorExamples
]

// 导航
const goTo = (path: string) => {
  if (analyzing.value) cancelAnalysis('页面已切换，当前分析已取消')
  router.push(path)
}

// 选择推荐问题
const selectQuestion = (question: string) => {
  if (analyzing.value) {
    ElMessage.warning('当前分析尚未结束，请等待完成或先停止分析')
    return
  }
  inputMessage.value = question
  sendMessage()
}

// 数据源对话框仅修改临时值，确定之前不会影响当前查询上下文。
const selectPendingDataSource = (ds: any) => {
  if (analyzing.value) return
  pendingDataSourceId.value = ds.id
}

// 下拉框切换数据源时同步名称
const onDataSourceChange = async (val: string) => {
  if (analyzing.value) return
  const loadId = ++metadataLoadSequence
  const found = dataSources.value.find((ds: any) => ds.id === val)
  selectedDataSourceName.value = found?.name || ''
  selectedSkillId.value = ''
  executionSteps.value = []
  displayedExecutionSkillName.value = ''
  await Promise.all([loadSkills(val, loadId), loadSkillDatasets(val, loadId)])
}

const resetPendingDataSource = () => {
  pendingDataSourceId.value = selectedDataSourceId.value
}

const showDataSourceDialog = () => {
  if (analyzing.value) return
  resetPendingDataSource()
  dataSourceDialogVisible.value = true
}

const cancelDataSourceDialog = () => {
  resetPendingDataSource()
  dataSourceDialogVisible.value = false
}

const confirmDataSource = async () => {
  if (analyzing.value || !pendingDataSourceId.value) return
  const nextId = pendingDataSourceId.value
  dataSourceSwitching.value = true
  try {
    if (nextId !== selectedDataSourceId.value) {
      selectedDataSourceId.value = nextId
      await onDataSourceChange(nextId)
    }
    dataSourceDialogVisible.value = false
    ElMessage.success('数据源已更新')
  } finally {
    dataSourceSwitching.value = false
  }
}

const loadSkills = async (
  databaseId: string | null = selectedDataSourceId.value,
  loadId = metadataLoadSequence
) => {
  skillsLoadError.value = ''
  if (!databaseId) {
    skills.value = []
    return
  }
  skillsLoading.value = true
  try {
    const response = await api.get(`/evaluation/skills?database_id=${encodeURIComponent(databaseId)}`)
    if (databaseId !== selectedDataSourceId.value || loadId !== metadataLoadSequence) return
    skills.value = response.skills || []
    if (pendingRestoredSkillId) {
      selectedSkillId.value = skills.value.some((item: any) => (
        item.id === pendingRestoredSkillId && item.valid !== false
      ))
        ? pendingRestoredSkillId
        : ''
      pendingRestoredSkillId = ''
    }
    if (selectedSkillId.value && !skills.value.some((item: any) => (
      item.id === selectedSkillId.value && item.valid !== false
    ))) {
      selectedSkillId.value = ''
      executionSteps.value = []
      displayedExecutionSkillName.value = ''
    }
  } catch (error: any) {
    if (databaseId !== selectedDataSourceId.value || loadId !== metadataLoadSequence) return
    console.error('Load skills error:', error)
    skills.value = []
    skillsLoadError.value = error?.serverMessage || 'Skills 加载失败，请检查服务连接'
  } finally {
    if (databaseId === selectedDataSourceId.value && loadId === metadataLoadSequence) {
      skillsLoading.value = false
    }
  }
}

const loadSkillDatasets = async (
  databaseId: string | null = selectedDataSourceId.value,
  loadId = metadataLoadSequence
) => {
  skillDatasetsLoadError.value = ''
  if (!databaseId) {
    skillDatasets.value = []
    return
  }
  skillDatasetsLoading.value = true
  try {
    const response = await api.get(`/evaluation/datasets?database_id=${encodeURIComponent(databaseId)}`)
    if (databaseId !== selectedDataSourceId.value || loadId !== metadataLoadSequence) return
    skillDatasets.value = response.datasets || []
  } catch (error: any) {
    if (databaseId !== selectedDataSourceId.value || loadId !== metadataLoadSequence) return
    console.error('Load skill datasets error:', error)
    skillDatasets.value = []
    skillDatasetsLoadError.value = error?.serverMessage || '数据集加载失败，请检查服务连接'
  } finally {
    if (databaseId === selectedDataSourceId.value && loadId === metadataLoadSequence) {
      skillDatasetsLoading.value = false
    }
  }
}

const resetSkillForm = () => {
  editingSkillId.value = ''
  skillForm.value = { name: '', description: '', steps: [newSkillStep(false)] }
}

const loadSkillForEdit = (skillId: string) => {
  if (!skillId) {
    resetSkillForm()
    return
  }
  const skill = skills.value.find((item: any) => item.id === skillId)
  if (!skill) return
  skillForm.value = {
    name: skill.name || '',
    description: skill.description || '',
    steps: (skill.steps || []).map((step: any, index: number) => ({
      ...newSkillStep(index > 0),
      ...step,
      dependsOnPrevious: index === 0 ? false : (step.dependsOnPrevious ?? true),
      onDependencyFailure: step.onDependencyFailure || 'skip',
      requireNonEmpty: step.requireNonEmpty ?? true,
      onEmpty: step.onEmpty || 'continue'
    }))
  }
  if (!skillForm.value.steps.length) skillForm.value.steps = [newSkillStep(false)]
}

const openSkillDialog = async (skillId = selectedSkillId.value) => {
  if (!selectedDataSourceId.value) {
    ElMessage.warning('请先选择数据源')
    return
  }
  await Promise.all([loadSkills(), loadSkillDatasets()])
  skillDialogVisible.value = true
  if (skillId && skills.value.some((item: any) => item.id === skillId)) {
    editingSkillId.value = skillId
    loadSkillForEdit(skillId)
  } else {
    resetSkillForm()
  }
}

const addSkillStep = () => {
  if (skillForm.value.steps.length >= 20) {
    ElMessage.warning('单个 Skill 最多支持 20 个查询步骤')
    return
  }
  skillForm.value.steps.push(newSkillStep(skillForm.value.steps.length > 0))
}

const deleteSkillStep = (index: number) => {
  skillForm.value.steps.splice(index, 1)
  if (!skillForm.value.steps.length) addSkillStep()
  if (skillForm.value.steps[0]) skillForm.value.steps[0].dependsOnPrevious = false
}

const moveSkillStep = (index: number, offset: number) => {
  const target = index + offset
  if (target < 0 || target >= skillForm.value.steps.length) return
  const [item] = skillForm.value.steps.splice(index, 1)
  skillForm.value.steps.splice(target, 0, item)
  if (skillForm.value.steps[0]) skillForm.value.steps[0].dependsOnPrevious = false
}

const syncSkillDatasetName = (step: any) => {
  const dataset = skillDatasets.value.find((item: any) => item.id === step.datasetId)
  step.datasetName = dataset?.name || ''
}

const saveSkill = async () => {
  const name = skillForm.value.name.trim()
  if (!name) {
    ElMessage.warning('请输入 Skill 名称')
    return
  }
  const invalidStep = skillForm.value.steps.find((step: any) => !step.datasetId || !step.instruction.trim())
  if (invalidStep) {
    ElMessage.warning('请为每个步骤选择数据集并填写查询指令')
    return
  }

  const payload = {
    name,
    description: skillForm.value.description.trim(),
    databaseId: selectedDataSourceId.value,
    steps: skillForm.value.steps.map((step: any, index: number) => ({
      datasetId: step.datasetId,
      datasetName: step.datasetName,
      instruction: step.instruction.trim(),
      dependsOnPrevious: index === 0 ? false : Boolean(step.dependsOnPrevious),
      onDependencyFailure: step.onDependencyFailure || 'skip',
      requireNonEmpty: step.requireNonEmpty !== false,
      onEmpty: step.onEmpty || 'continue'
    }))
  }

  savingSkill.value = true
  try {
    const response = editingSkillId.value
      ? await api.put(`/evaluation/skills/${editingSkillId.value}`, payload)
      : await api.post('/evaluation/skills', payload)
    selectedSkillId.value = response.skill.id
    await loadSkills()
    editingSkillId.value = response.skill.id
    loadSkillForEdit(response.skill.id)
    previewSelectedSkillPlan()
    skillDialogVisible.value = false
    ElMessage.success('Skill 已保存，可直接开始顺序查询')
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '保存 Skill 失败')
  } finally {
    savingSkill.value = false
  }
}

const removeSkill = async () => {
  if (!editingSkillId.value) return
  try {
    await ElMessageBox.confirm('删除后无法恢复，确定删除这个 Skill 吗？', '删除 Skill', { type: 'warning' })
    const deletingId = editingSkillId.value
    await api.delete(`/evaluation/skills/${deletingId}`)
    const deletingCurrentPlan = selectedSkillId.value === deletingId
      || executionSteps.value.some((step: any) => step.skillId === deletingId)
    if (selectedSkillId.value === deletingId) selectedSkillId.value = ''
    if (deletingCurrentPlan) {
      executionSteps.value = []
      displayedExecutionSkillName.value = ''
    }
    await loadSkills()
    resetSkillForm()
    ElMessage.success('Skill 已删除')
  } catch (error: any) {
    if (error !== 'cancel' && error !== 'close') {
      ElMessage.error(error?.serverMessage || '删除 Skill 失败')
    }
  }
}

// 格式化时间
const formatTime = (time: string) => {
  const date = new Date(time)
  return date.toLocaleString()
}

// 获取步骤状态类名
const getStepStatusClass = (status: string) => {
  const statusMap: Record<string, string> = {
    'completed': 'completed',
    'in_progress': 'in-progress',
    'pending': 'pending',
    'partial': 'partial',
    'error': 'error',
    'skipped': 'skipped'
  }
  return statusMap[status] || 'pending'
}

// 将 rows 统一转为二维数组格式（兼容对象/{col:val} 和数组/[val] 两种后端返回）
const normalizeRows = (columns: any[], rows: any[]): any[][] => {
  if (!rows || rows.length === 0) return []
  const first = rows[0]
  // 首行是数组 → 已经是二维数组格式
  if (Array.isArray(first)) return rows
  // 首行是对象 → 按 columns 顺序提取值转为数组
  return rows.map((r: any) => columns.map((col: string) => r[col]))
}

// 行列数据转可读文本
const formatRowsAsText = (columns: any[], rows: any[]) => {
  if (!columns || !rows || rows.length === 0) return ''
  const arr = normalizeRows(columns, rows)
  const lines = arr.map((row: any) => columns.map((col, i) => `${col}=${row[i]}`).join('，'))
  return lines.map((line, i) => `${i + 1}. ${line}`).join('\n')
}

// 根据 chartConfig + 全量 rawResults 构建 ECharts option
const buildChartOption = (chartConfig: any, rawResults: any[]): any => {
  if (!chartConfig || !rawResults || rawResults.length === 0) return undefined
  const vizType = chartConfig.vizType || 'bar'
  const xAxisField = chartConfig.xAxis || Object.keys(rawResults[0])[0]
  const yAxisFields = chartConfig.yAxis && chartConfig.yAxis.length > 0
    ? chartConfig.yAxis
    : Object.keys(rawResults[0]).slice(1)

  if (vizType === 'table') return undefined

  const categories = rawResults.map((r: any) => String(r[xAxisField] ?? ''))

  if (vizType === 'pie') {
    const firstY = yAxisFields[0]
    return {
      title: { text: chartConfig.chartTitle || '', left: 'center', textStyle: { fontSize: 14 } },
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { orient: 'vertical', left: 'left', top: 30 },
      series: [{
        type: 'pie',
        radius: ['40%', '65%'],
        center: ['55%', '55%'],
        data: rawResults.map((r: any) => ({
          name: String(r[xAxisField] ?? ''),
          value: Number(r[firstY]) || 0
        })),
        itemStyle: { borderRadius: 6, borderColor: '#fff', borderWidth: 2 }
      }]
    }
  }

  // bar / line
  const series = yAxisFields.map((field: string) => ({
    name: field,
    type: vizType,
    data: rawResults.map((r: any) => Number(r[field]) || 0),
    barMaxWidth: 40,
    smooth: vizType === 'line'
  }))

  return {
    title: { text: chartConfig.chartTitle || '', left: 'center', textStyle: { fontSize: 14 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { data: yAxisFields, top: 30 },
    grid: { left: '3%', right: '4%', bottom: '3%', top: 60, containLabel: true },
    xAxis: { type: 'category', data: categories, axisLabel: { rotate: categories.length > 6 ? 30 : 0 } },
    yAxis: { type: 'value' },
    series
  }
}

const isCurrentRequest = (request: EvaluationRequestContext) => activeRequest?.id === request.id

const settleExecutionFailure = (request: EvaluationRequestContext, reason: string) => {
  let hasRoot = false
  let hasActive = false
  request.steps.forEach((step: any) => {
    if (step.step === 'skill' || step.step === 'request.error') {
      hasRoot = true
      step.status = 'error'
      step.progress = 100
      step.detail = reason
      return
    }
    if (step.status === 'in_progress') {
      hasActive = true
      step.status = 'error'
      step.progress = 100
      step.detail = reason
    } else if (step.status === 'pending') {
      step.status = 'skipped'
      step.detail = `未执行：${reason}`
    }
  })
  if (!hasRoot && !hasActive) {
    request.steps.push({
      step: 'request.error',
      description: '评估请求',
      detail: reason,
      status: 'error',
      progress: 100
    })
  }
  request.aiMessage.executionSteps = request.steps
  if (isCurrentRequest(request)) executionSteps.value = request.steps
}

const bindRequestSession = (request: EvaluationRequestContext, responseSessionId?: string) => {
  if (request.requestedSessionId && responseSessionId && request.requestedSessionId !== responseSessionId) {
    throw new Error('服务端返回的会话标识与当前请求不一致')
  }
  request.resolvedSessionId = request.requestedSessionId || responseSessionId || request.resolvedSessionId
  if (!request.resolvedSessionId) return
  if (isCurrentRequest(request) && !request.requestedSessionId) {
    sessionId.value = request.resolvedSessionId
  }
}

const persistRequestSnapshot = (request: EvaluationRequestContext) => {
  const targetSessionId = request.resolvedSessionId || request.requestedSessionId
  if (!targetSessionId) return
  request.aiMessage.executionSteps = cloneSerializable(request.steps)
  request.aiMessage.skillId = request.skillId
  request.aiMessage.skillName = request.skillName
  if (isCurrentRequest(request)) {
    sessionMessages.value[targetSessionId] = cloneSerializable(messages.value)
    saveHistory(targetSessionId, request.query)
    persistState()
  }
}

const cancelAnalysis = (reason = '用户已停止分析') => {
  const request = activeRequest
  if (!request || request.resultReceived) return
  request.terminalError = reason
  settleExecutionFailure(request, reason)
  request.controller.abort(reason)
}

// 发送消息 - 使用 fetch API 实现流式读取
const sendMessage = async () => {
  if (analyzing.value || activeRequest) {
    ElMessage.warning('当前分析尚未结束，请等待完成或先停止分析')
    return
  }
  if (!inputMessage.value.trim()) {
    ElMessage.warning('请输入评估需求')
    return
  }
  if (selectedSkillId.value && !selectedDataSourceId.value) {
    ElMessage.warning('使用 Skills 前请先选择数据源')
    return
  }
  if (selectedSkillId.value && !selectedSkill.value) {
    ElMessage.warning('所选 Skill 已不存在，请重新选择')
    await loadSkills()
    return
  }

  const query = inputMessage.value.trim()
  const requestSkill = selectedSkill.value ? cloneSerializable(selectedSkill.value) : null
  const requestSteps = requestSkill ? buildSkillPlan(requestSkill) : []
  const requestId = `evaluation-${Date.now()}-${++requestSequence}`
  const requestedSessionId = sessionId.value
  const controller = new AbortController()

  inputMessage.value = ''
  executionSteps.value = requestSteps
  displayedExecutionSkillName.value = requestSkill?.name || ''
  if (requestSkill) showExecutionPanel.value = true
  analyzing.value = true

  messages.value.push({ role: 'user', content: query, requestId })
  const aiMessage: any = {
    role: 'assistant',
    content: '正在分析您的需求，请稍候...',
    result: null,
    requestId,
    skillId: requestSkill?.id || '',
    skillName: requestSkill?.name || '',
    executionSteps: requestSteps
  }
  messages.value.push(aiMessage)

  const request: EvaluationRequestContext = {
    id: requestId,
    controller,
    steps: requestSteps,
    aiMessage,
    query,
    requestedSessionId,
    resolvedSessionId: requestedSessionId,
    skillId: requestSkill?.id || '',
    skillName: requestSkill?.name || '',
    resultReceived: false,
    terminalError: ''
  }
  activeRequest = request

  const handleStreamLine = (rawLine: string) => {
    if (!isCurrentRequest(request)) return
    let line = rawLine.trim()
    if (!line || line.startsWith(':')) return
    if (line.startsWith('data:')) line = line.slice(5).trim()
    if (!line) return

    let data: any
    try {
      data = JSON.parse(line)
    } catch (error) {
      console.error('Stream JSON parse error:', error, line)
      throw new Error('响应流包含无法解析的数据，执行结果可能不完整')
    }

    if (data.type === 'step') {
      if (!data.step || data.step.step === undefined) throw new Error('响应流中的执行步骤格式无效')
      const step = data.step
      const existingIndex = request.steps.findIndex((item: any) => item.step === step.step)
      if (existingIndex >= 0) {
        request.steps.splice(existingIndex, 1, { ...request.steps[existingIndex], ...step })
      } else if (step.parentStep) {
        const parentIndex = request.steps.findIndex((item: any) => item.step === step.parentStep)
        if (parentIndex >= 0) {
          let insertIndex = parentIndex + 1
          while (insertIndex < request.steps.length && request.steps[insertIndex].parentStep === step.parentStep) {
            insertIndex += 1
          }
          request.steps.splice(insertIndex, 0, step)
        } else {
          request.steps.push(step)
        }
      } else {
        request.steps.push(step)
      }
      request.aiMessage.executionSteps = request.steps
      executionSteps.value = request.steps
      aiMessage.content = '正在分析...'
      return
    }

    if (data.type === 'result') {
      if (request.resultReceived) throw new Error('服务端重复返回最终结果')
      bindRequestSession(request, data.session_id)
      const result = data.result || {}
      const answerText = result.final_answer || result.summary || result.answer || '分析完成'
      aiMessage.content = (result.need_conclusion === false || result.type === 'skill_query') ? '' : answerText
      aiMessage.result = result
      request.resultReceived = true
      persistRequestSnapshot(request)
      scrollToBottom()
      return
    }

    if (data.type === 'error') {
      throw new Error(data.message || '服务端执行分析失败')
    }
  }

  try {
    const token = localStorage.getItem('token')
    const headers: Record<string, string> = { 'Content-Type': 'application/json' }
    if (token) headers.Authorization = `Bearer ${token}`

    const response = await fetch('/api/evaluation/analyze/stream', {
      method: 'POST',
      headers,
      signal: controller.signal,
      body: JSON.stringify({
        query,
        session_id: requestedSessionId || undefined,
        dataSourceId: selectedDataSourceId.value || '',
        database_name: selectedDataSourceName.value,
        skillId: requestSkill?.id || ''
      })
    })

    if (!response.ok) {
      let detail = ''
      try {
        const body = await response.text()
        if (body) {
          try {
            const parsed = JSON.parse(body)
            detail = parsed.message || parsed.detail || ''
          } catch {
            detail = body.slice(0, 300)
          }
        }
      } catch {
        // 保留 HTTP 状态作为错误信息。
      }
      throw new Error(detail || `服务请求失败（HTTP ${response.status}）`)
    }

    const reader = response.body?.getReader()
    if (!reader) throw new Error('浏览器无法读取服务端响应流')

    const decoder = new TextDecoder('utf-8', { fatal: false })
    let buffer = ''
    const processBuffer = () => {
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() || ''
      lines.forEach(handleStreamLine)
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      processBuffer()
    }
    buffer += decoder.decode()
    // 流的最后一条 NDJSON 记录可能没有换行符，必须显式处理剩余缓冲区。
    if (buffer.trim()) {
      const remaining = buffer
      buffer = ''
      remaining.split(/\r?\n/).forEach(handleStreamLine)
    }

    if (!request.resultReceived) {
      throw new Error('响应流已结束，但服务端没有返回最终结果')
    }
  } catch (error: any) {
    const isAbort = error?.name === 'AbortError' || controller.signal.aborted
    const reason = request.terminalError
      || (isAbort ? String(controller.signal.reason || '分析已取消') : (error?.message || '分析失败，请稍后重试'))
    request.terminalError = reason
    settleExecutionFailure(request, reason)
    aiMessage.content = reason
    aiMessage.result = null
    if (!controller.signal.aborted) controller.abort(reason)
    persistRequestSnapshot(request)
    if (isCurrentRequest(request)) {
      if (isAbort) ElMessage.warning(reason)
      else ElMessage.error(`分析失败：${reason}`)
    }
    console.error('Evaluation error:', error)
  } finally {
    if (isCurrentRequest(request)) {
      activeRequest = null
      analyzing.value = false
    }
  }
}

// 滚动聊天区域到底部
const scrollToBottom = () => {
  nextTick(() => {
    const chatArea = document.querySelector('.chat-area') as HTMLElement
    if (chatArea) {
      chatArea.scrollTop = chatArea.scrollHeight
    }
  })
}

const scrollExecutionToActive = () => {
  nextTick(() => {
    const execContent = document.querySelector('.execution-content') as HTMLElement
    if (!execContent) return
    const activeSteps = execContent.querySelectorAll('.inline-step.in-progress')
    const activeStep = activeSteps.item(activeSteps.length - 1) as HTMLElement | null
    if (activeStep) {
      activeStep.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    } else if (rootExecutionStep.value?.status && rootExecutionStep.value.status !== 'pending') {
      execContent.scrollTop = execContent.scrollHeight
    } else {
      execContent.scrollTop = 0
    }
  })
}

// 监听消息和步骤变化，自动滚动
watch(() => messages.value.length, () => scrollToBottom())
watch(
  () => executionSteps.value.map((step: any) => `${step.step}:${step.status}:${step.progress}`).join('|'),
  () => scrollExecutionToActive()
)

const restoreLocalHistory = (id: string): boolean => {
  const localMessages = sessionMessages.value[id]
  if (!localMessages) return false
  messages.value = cloneSerializable(localMessages)
  sessionId.value = id
  const latestExecution = [...messages.value]
    .reverse()
    .find((message: any) => message.role === 'assistant' && Array.isArray(message.executionSteps) && message.executionSteps.length)
  executionSteps.value = latestExecution ? orderExecutionSteps(latestExecution.executionSteps) : []
  displayedExecutionSkillName.value = latestExecution?.skillName || ''
  const restoredSkillId = latestExecution?.skillId || ''
  const restoredSkillExists = restoredSkillId && skills.value.some((skill: any) => skill.id === restoredSkillId)
  selectedSkillId.value = restoredSkillExists ? restoredSkillId : ''
  pendingRestoredSkillId = restoredSkillId && !skills.value.length ? restoredSkillId : ''
  if (executionSteps.value.length) showExecutionPanel.value = true
  persistState()
  return true
}

// 加载历史记录：优先恢复服务端保存的结构化结果和执行流程，本地缓存作为离线兜底。
const loadHistory = async (item: any) => {
  if (analyzing.value) {
    ElMessage.warning('分析期间不能切换历史会话，请等待完成或先停止分析')
    return
  }
  try {
    const response = await api.get(`/evaluation/session/${encodeURIComponent(item.id)}`)
    const snapshot = response.session
    if (!snapshot) throw new Error('服务端未返回会话快照')

    const result = snapshot.result && Object.keys(snapshot.result).length ? snapshot.result : null
    const executionSnapshot = Array.isArray(snapshot.executionSteps) ? snapshot.executionSteps : []
    const restoredSkillId = snapshot.skillId || ''
    const restoredSkill = skills.value.find((skill: any) => skill.id === restoredSkillId)
    selectedSkillId.value = restoredSkill ? restoredSkillId : ''
    pendingRestoredSkillId = restoredSkillId && !skills.value.length ? restoredSkillId : ''
    displayedExecutionSkillName.value = restoredSkill?.name || result?.skillName || ''
    executionSteps.value = orderExecutionSteps(executionSnapshot)
    messages.value = [
      { role: 'user', content: snapshot.question || item.title || '' },
      {
        role: 'assistant',
        content: (result?.type === 'skill_query' ? '' : (snapshot.final_answer || '')),
        result,
        skillId: restoredSkillId,
        skillName: displayedExecutionSkillName.value,
      executionSteps: orderExecutionSteps(executionSnapshot)
      }
    ]
    sessionId.value = item.id
    sessionMessages.value[item.id] = cloneSerializable(messages.value)
    if (executionSteps.value.length) showExecutionPanel.value = true
    persistState()
    ElMessage.success('已加载历史记录')
  } catch (error) {
    console.warn('Load server session failed, using local cache:', error)
    if (restoreLocalHistory(item.id)) {
      ElMessage.warning('服务端未能恢复该记录，已使用本地缓存')
    } else {
      selectedSkillId.value = ''
      executionSteps.value = []
      displayedExecutionSkillName.value = ''
      ElMessage.warning('该历史记录没有可恢复的内容')
    }
  }
}

const loadServerHistory = async () => {
  try {
    const response = await api.get('/evaluation/history')
    const serverHistory = Array.isArray(response.history) ? response.history : []
    const localById = new Map(historyList.value.map((item: any) => [item.id, item]))
    historyList.value = [
      ...serverHistory.map((item: any) => ({ ...localById.get(item.id), ...item })),
      ...historyList.value.filter((item: any) => !serverHistory.some((serverItem: any) => serverItem.id === item.id))
    ]
    persistState()
  } catch (error) {
    console.warn('Load evaluation history failed, keeping local cache:', error)
  }
}

const newSession = () => {
  if (analyzing.value) {
    ElMessage.warning('分析期间不能创建新会话，请等待完成或先停止分析')
    return
  }
  sessionId.value = ''
  messages.value = []
  executionSteps.value = []
  displayedExecutionSkillName.value = ''
  persistState()
  ElMessage.success('已创建新会话')
}

const deleteHistory = async (id: string) => {
  if (analyzing.value) {
    ElMessage.warning('分析期间不能删除会话')
    return
  }
  try {
    await api.delete(`/evaluation/session/${encodeURIComponent(id)}`)
  } catch (error: any) {
    ElMessage.error(error?.serverMessage || '删除服务端会话失败')
    return
  }
  delete sessionMessages.value[id]
  historyList.value = historyList.value.filter(item => item.id !== id)
  if (sessionId.value === id) {
    sessionId.value = ''
    messages.value = []
    executionSteps.value = []
    displayedExecutionSkillName.value = ''
  }
  persistState()
  ElMessage.success('已删除会话')
}

const saveHistory = (id: string, question: string) => {
  const exists = historyList.value.find(item => item.id === id)
  if (!exists) {
    historyList.value.unshift({
      id: id,
      title: question.length > 20 ? question.substring(0, 20) + '...' : question,
      time: new Date().toLocaleString()
    })
  } else {
    exists.title = question.length > 20 ? question.substring(0, 20) + '...' : question
    exists.time = new Date().toLocaleString()
    const index = historyList.value.indexOf(exists)
    if (index > 0) {
      historyList.value.splice(index, 1)
      historyList.value.unshift(exists)
    }
  }
  persistState()
}

// 初始化数据
const initData = async () => {
  try {
    const dsResp = await api.get('/evaluation/data-sources')
    
    if (dsResp.dataSources) {
      dataSources.value = dsResp.dataSources
      if (dataSources.value.length > 0) {
        selectedDataSourceId.value = dataSources.value[0].id
        selectedDataSourceName.value = dataSources.value[0].name || ''
        await Promise.all([loadSkills(), loadSkillDatasets()])
      }
    }
  } catch (error) {
    console.error('Init data error:', error)
    ElMessage.warning('部分数据加载失败，请检查服务是否启动')
  }
}

onMounted(() => {
  // 恢复上次会话的消息
  if (sessionId.value && sessionMessages.value[sessionId.value]) {
    messages.value = cloneSerializable(sessionMessages.value[sessionId.value])
    const latestExecution = [...messages.value]
      .reverse()
      .find((message: any) => message.role === 'assistant' && Array.isArray(message.executionSteps) && message.executionSteps.length)
    if (latestExecution) {
      executionSteps.value = orderExecutionSteps(latestExecution.executionSteps)
      displayedExecutionSkillName.value = latestExecution.skillName || ''
      pendingRestoredSkillId = latestExecution.skillId || ''
      showExecutionPanel.value = true
    }
  }
  void loadServerHistory()
  initData()
})

onBeforeUnmount(() => {
  if (activeRequest && !activeRequest.resultReceived) {
    cancelAnalysis('页面已关闭，当前分析已取消')
  }
})
</script>

<style scoped>
.solution-container {
  display: flex;
  height: 100%;
  background: transparent;
}

.sidebar {
  width: 260px;
  flex-shrink: 0;
  padding: 16px 12px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.sidebar-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 0;
}

.sidebar-section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0;
  padding: 0 8px;
}

.sidebar-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  letter-spacing: 0.5px;
  margin-bottom: 0;
}

.new-session-btn {
  height: 32px !important;
  font-size: 13px !important;
  font-weight: 500 !important;
  padding: 0 12px !important;
  border-radius: 8px !important;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
}

.nav-item:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-primary);
}

.history-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-height: none;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  color: var(--text-secondary);
}

.history-item:hover {
  background: rgba(0, 0, 0, 0.04);
  color: var(--text-primary);
}

.history-item.active {
  background: rgba(59, 130, 246, 0.08);
  color: var(--primary-600);
  border: none;
}

.history-item-main {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
  min-width: 0;
}

.history-item .el-icon {
  font-size: 16px;
  flex-shrink: 0;
  color: var(--text-muted);
}

.history-item.active .el-icon {
  color: var(--primary-500);
}

.history-delete-btn {
  opacity: 0;
  transition: opacity 0.2s;
  flex-shrink: 0;
}

.history-item:hover .history-delete-btn {
  opacity: 1;
}

.history-item-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.history-item-title {
  font-size: 13px;
  font-weight: 500;
  color: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.history-item-time {
  font-size: 11px;
  color: var(--text-muted);
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  gap: 0;
  background: var(--bg-card);
  border-left: none;
  border-right: none;
  border-radius: 0;
  box-shadow: none;
}

.top-bar {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  padding: 14px 24px;
  border-bottom: none;
  background: transparent;
  flex-shrink: 0;
}

.data-source-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.skill-selector {
  display: flex;
  align-items: center;
  gap: 10px;
}

.label {
  font-size: 13px;
  color: var(--text-secondary);
  font-weight: 500;
}

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
  gap: 0;
}

.chat-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  border-right: none;
  padding: 0;
  gap: 0;
}

.chat-area {
  flex: 1;
  overflow-y: auto;
  padding: 24px 20px;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-start;
  padding-top: 80px;
  height: 100%;
  color: var(--text-muted);
  gap: 0;
}

.empty-state > .el-icon {
  color: var(--gray-200) !important;
}

.empty-state p {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
}

.tags-section {
  margin-top: 0;
  width: 100%;
  max-width: 720px;
  padding: 0 20px;
}

.tag-group {
  margin-bottom: 0;
}

.tag-group h4 {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-tertiary);
  margin-bottom: 16px;
  text-align: center;
  letter-spacing: 0.5px;
}

.suggest-cards {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 12px;
}

.suggest-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  background: var(--gray-50);
  border: 1px solid var(--border-light);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.suggest-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--card-color);
  opacity: 0;
  transition: opacity 0.2s;
}

.suggest-card:hover {
  background: white;
  border-color: color-mix(in srgb, var(--card-color) 30%, white);
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.06);
}

.suggest-card:hover::before {
  opacity: 1;
}

.suggest-icon {
  flex-shrink: 0;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: color-mix(in srgb, var(--card-color) 12%, white);
  color: var(--card-color);
  transition: all 0.2s;
}

.suggest-card:hover .suggest-icon {
  background: var(--card-color);
  color: white;
  transform: scale(1.05);
}

.suggest-content {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.suggest-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  line-height: 1.4;
  transition: color 0.2s;
}

.suggest-card:hover .suggest-title {
  color: var(--card-color);
}

.suggest-desc {
  font-size: 11px;
  color: var(--text-muted);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.suggest-arrow {
  flex-shrink: 0;
  font-size: 14px;
  color: var(--text-muted);
  opacity: 0;
  transform: translateX(-4px);
  transition: all 0.2s;
}

.suggest-card:hover .suggest-arrow {
  opacity: 1;
  transform: translateX(0);
  color: var(--card-color);
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.message {
  display: flex;
  gap: 1rem;
}

.message.user {
  flex-direction: row-reverse;
}

.message-content {
  max-width: 90%;
}

.message-text {
  padding: 1rem;
  border-radius: 0.75rem;
  line-height: 1.8;
  font-size: 1.05rem;
}

.message.user .message-text {
  background: #409eff;
  color: white;
}

.message.assistant .message-text {
  background: white;
  border: 1px solid #e2e8f0;
  color: #374151;
}

.assistant .message-text strong {
  color: #374151;
  font-weight: 600;
}

.md-list-item {
  margin-bottom: 0.35rem;
  padding-left: 0.5rem;
}

.md-num {
  font-weight: 600;
  color: #409eff;
}

.result-section {
  margin-top: 1rem;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 0.5rem;
}

.result-header {
  margin-bottom: 1rem;
  padding-bottom: 0.5rem;
  border-bottom: 2px solid #409eff;
}

.result-header h5 {
  margin: 0;
  color: #374151;
}

.skill-result-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.skill-result-header p {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 13px;
}

.skill-result-summary {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  color: #6b7280;
  font-size: 12px;
}

.skill-result-duration {
  margin-left: auto;
  color: #9ca3af;
  font-size: 12px;
  white-space: nowrap;
}

.skill-result-item {
  margin-bottom: 14px;
  padding: 14px;
  background: #fff;
  border: 1px solid #dbeafe;
  border-radius: 10px;
}

.skill-result-title {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-bottom: 12px;
}

.skill-result-title > div {
  flex: 1;
}

.skill-result-title p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 12px;
}

.skill-order,
.skill-step-index {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #fff;
  background: #409eff;
  font-weight: 700;
  font-size: 13px;
}

.skill-query-result .sql-code {
  margin: 0 0 12px;
  padding: 12px;
  overflow-x: auto;
  border-radius: 8px;
  color: #e5e7eb;
  background: #1f2937;
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
}

.skill-query-result h6 {
  margin: 12px 0 8px;
  color: #374151;
}

.query-result-item {
  margin-bottom: 1rem;
  padding: 0.75rem;
  background: white;
  border-radius: 0.5rem;
  border: 1px solid #e5e7eb;
}

.query-result-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
  margin-bottom: 0.5rem;
}

.query-result-insight {
  font-size: 13px;
  color: #6b7280;
  line-height: 1.6;
  margin-bottom: 0.75rem;
  padding: 0.5rem 0.75rem;
  background: #f0f9ff;
  border-radius: 6px;
  border-left: 3px solid #409eff;
}

.summary-section {
  margin-top: 0.5rem;
  padding: 1rem;
  background: linear-gradient(135deg, #f0f9ff, #e0f2fe);
  border-radius: 0.5rem;
  border: 1px solid #bae6fd;
}

.summary-section h6 {
  margin: 0 0 0.5rem;
  color: #0369a1;
  font-size: 14px;
}

.summary-section p {
  margin: 0;
  color: #075985;
  line-height: 1.8;
  font-size: 14px;
}

.no-data {
  text-align: center;
  padding: 1.5rem;
  color: #9ca3af;
  font-size: 13px;
}

.air-superiority-result .score-display {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 2rem;
  margin: 1.5rem 0;
}

.air-superiority-result .team {
  text-align: center;
}

.air-superiority-result .team.red .team-score {
  background: linear-gradient(135deg, #fef2f2, #fee2e2);
  color: #dc2626;
  border: 2px solid #fecaca;
}

.air-superiority-result .team.blue .team-score {
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
  color: #2563eb;
  border: 2px solid #bfdbfe;
}

.air-superiority-result .team-name {
  font-size: 1.2rem;
  font-weight: 600;
  margin-bottom: 0.5rem;
}

.air-superiority-result .team-score {
  font-size: 3rem;
  font-weight: 700;
  width: 120px;
  height: 120px;
  line-height: 120px;
  border-radius: 50%;
}

.air-superiority-result .vs {
  font-size: 1.5rem;
  color: #64748b;
  font-weight: 600;
}

.air-superiority-result .advantage-banner {
  text-align: center;
  padding: 1rem;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  color: white;
  border-radius: 0.5rem;
  font-size: 1.2rem;
  font-weight: 600;
  margin-bottom: 1rem;
}

.air-superiority-result .advantage-banner .winner {
  margin-right: 0.5rem;
}

.air-superiority-result .analysis-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
  margin-bottom: 1rem;
}

.air-superiority-result .detail-section,
.air-superiority-result .recommendations {
  background: white;
  padding: 1rem;
  border-radius: 0.5rem;
}

.air-superiority-result .detail-section h6,
.air-superiority-result .recommendations h6 {
  margin: 0 0 0.5rem;
  color: #374151;
}

.air-superiority-result .detail-section ul {
  list-style: disc;
  padding-left: 1.5rem;
  margin: 0;
  color: #64748b;
}

.air-superiority-result .recommendations {
  grid-column: 1 / -1;
}

.air-superiority-result .recommendations p {
  margin: 0;
  color: #64748b;
}

.air-superiority-result .factors-section h6,
.indicator-result .sql-section h6,
.indicator-result .data-section h6,
.indicator-result .statistics-section h6,
.references-section h6 {
  margin: 1rem 0 0.5rem;
  color: #374151;
}

.indicator-result .sql-code {
  background: #1f2937;
  color: #e5e7eb;
  padding: 1rem;
  border-radius: 0.5rem;
  overflow-x: auto;
  font-family: 'Courier New', monospace;
  font-size: 0.9rem;
  line-height: 1.6;
}

.indicator-result .statistics-section {
  background: white;
  padding: 1rem;
  border-radius: 0.5rem;
}

.indicator-result .stats-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1rem;
}

.indicator-result .stat-item {
  text-align: center;
  padding: 1rem;
  background: #f8fafc;
  border-radius: 0.5rem;
}

.indicator-result .stat-item.highlight {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.indicator-result .stat-label {
  display: block;
  font-size: 0.85rem;
  margin-bottom: 0.5rem;
}

.indicator-result .stat-value {
  display: block;
  font-size: 1.5rem;
  font-weight: 700;
}

.references-section ul {
  list-style: disc;
  padding-left: 1.5rem;
  color: #64748b;
}

.execution-panel-toggle {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 32px;
  flex-shrink: 0;
  background: #fafafa;
  border-left: 1px solid #e2e8f0;
  border-right: 1px solid #e2e8f0;
  cursor: pointer;
  color: #9ca3af;
  transition: background 0.2s, color 0.2s;
  writing-mode: vertical-rl;
}
.execution-panel-toggle .el-icon {
  writing-mode: horizontal-tb;
  font-size: 16px;
}
.execution-panel-toggle .toggle-text {
  font-size: 13px;
  letter-spacing: 2px;
  user-select: none;
}
.execution-panel-toggle:hover {
  background: #f0f7ff;
  color: #409eff;
}

.execution-panel {
  min-width: 300px;
  max-width: 700px;
  background: #fafafa;
  display: flex;
  flex-direction: column;
  border-left: 1px solid #e2e8f0;
  flex-shrink: 0;
  position: relative;
}
.resize-handle {
  position: absolute;
  top: 0;
  left: -4px;
  width: 8px;
  height: 100%;
  cursor: col-resize;
  z-index: 10;
  background: transparent;
  transition: background 0.2s;
}
.resize-handle:hover,
.resize-handle:active {
  background: rgba(64, 158, 255, 0.35);
}
.panel-header {
  padding: 12px 16px;
  border-bottom: 1px solid #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  font-size: 14px;
  color: #1f2937;
  background: #fff;
}
.panel-title {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.panel-title small {
  max-width: 260px;
  overflow: hidden;
  color: #6b7280;
  font-size: 11px;
  font-weight: 400;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.panel-header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.panel-close {
  cursor: pointer;
  color: #9ca3af;
}
.panel-close:hover {
  color: #374151;
}
.execution-content {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}
.empty-execution {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: #9ca3af;
  gap: 8px;
  font-size: 13px;
}

/* 内联执行步骤样式 */
.execution-inline {
  margin-bottom: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
  background: #f9fafb;
}
.inline-step {
  padding: 8px 12px;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  word-break: break-word;
  overflow-wrap: break-word;
}
.inline-step:last-child {
  border-bottom: none;
}
.inline-step-header {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}
.inline-step-icon {
  display: flex;
  align-items: center;
  flex-shrink: 0;
  margin-top: 1px;
}
.inline-step-title {
  font-weight: 500;
  color: #1f2937;
  flex: 1;
  min-width: 0;
}
.inline-step-detail {
  color: #6b7280;
  font-size: 12px;
  padding-left: 24px;
}
.inline-step-thinking {
  margin-top: 4px;
  padding: 8px 10px;
  background: #f3f4f6;
  border-radius: 4px;
  font-size: 12px;
  color: #6b7280;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}
.inline-step-thinking summary {
  cursor: pointer;
  color: #4b5563;
  user-select: none;
}
.inline-step-thinking pre {
  margin: 8px 0 0;
  font: inherit;
  white-space: pre-wrap;
}
.inline-step-meta {
  display: flex;
  gap: 12px;
  padding-left: 24px;
  color: #9ca3af;
  font-size: 11px;
}
.inline-step-progress {
  padding-left: 24px;
}
.inline-step.in-progress .inline-step-icon {
  color: #409eff;
}
.inline-step.completed .inline-step-icon {
  color: #67c23a;
}
.inline-step.partial .inline-step-icon {
  color: #e6a23c;
}
.inline-step.error .inline-step-icon {
  color: #f56c6c;
}
.inline-step.pending {
  opacity: 0.72;
}

.input-area {
  flex-shrink: 0;
  padding: 16px 40px 24px;
  background: linear-gradient(to top, var(--bg-card) 60%, transparent);
  border: none;
  display: flex;
  flex-direction: column;
  gap: 0;
}

.tools-bar {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  flex-wrap: wrap;
  margin-bottom: 1rem;
}

.tools-bar .tool-item {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 1rem;
  background: #f5f7fa;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.tools-bar .tool-item:hover {
  background: #eff6ff;
  border-color: #409eff;
}

.tools-bar .tool-item.current {
  background: #409eff;
  border-color: #409eff;
  cursor: default;
}

.tools-bar .tool-icon {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.8);
  display: flex;
  align-items: center;
  justify-content: center;
}

.tools-bar .tool-item.current .tool-icon {
  background: rgba(255, 255, 255, 0.2);
}

.tools-bar .tool-name {
  color: #606266;
  font-size: 0.85rem;
  font-weight: 500;
}

.tools-bar .tool-item.current .tool-name {
  color: white;
}

.input-wrapper {
  position: relative;
  max-width: 1000px;
  margin: 0 auto;
  width: 100%;
}

.input-wrapper :deep(.el-textarea__inner) {
  border-radius: 16px !important;
  border-color: var(--border-normal) !important;
  padding: 16px 100px 16px 20px !important;
  font-size: 15px !important;
  line-height: 1.6 !important;
  transition: all 0.2s !important;
  background: var(--gray-50) !important;
  resize: none;
}

.input-wrapper :deep(.el-textarea__inner:hover) {
  border-color: var(--primary-400) !important;
  background: white !important;
}

.input-wrapper :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-500) !important;
  background: white !important;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1) !important;
}

.input-actions {
  position: absolute;
  bottom: 14px;
  right: 16px;
  display: flex;
  justify-content: flex-end;
}

.input-actions .el-button {
  height: 38px;
  padding: 0 22px;
  border-radius: 10px;
  font-weight: 500;
}

.data-source-list {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.ds-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1rem;
  border: 1px solid #e2e8f0;
  border-radius: 0.5rem;
  cursor: pointer;
  transition: all 0.2s;
}

.ds-item:hover {
  border-color: #409eff;
}

.ds-item.active {
  border-color: #409eff;
  background: #eff6ff;
}

.ds-name {
  font-weight: 600;
  color: #374151;
}

.ds-meta {
  display: flex;
  gap: 0.5rem;
}

.skill-dialog-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid #e5e7eb;
}

.skill-steps-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.skill-step-editor {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid #dbeafe;
  border-radius: 10px;
  background: #f8fbff;
}

.skill-step-fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.skill-step-policies {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px 16px;
  padding: 8px 10px;
  border-radius: 8px;
  background: #f1f5f9;
  color: #475569;
  font-size: 12px;
}

.skill-step-policies label {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}

.inline-step-phase {
  display: inline-block;
  margin-top: 6px;
  padding: 2px 7px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4f46e5;
  font-size: 11px;
}

.inline-step-policy {
  margin-top: 5px;
  color: #64748b;
  font-size: 11px;
}

.inline-step.is-sub-step {
  margin-left: 18px;
  border-left: 3px solid #c7d2fe;
}

.select-empty {
  padding: 10px 12px;
  color: #909399;
  text-align: center;
}

.select-empty.error {
  color: #f56c6c;
}

.history-item-main.disabled,
.suggest-card.disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.skill-step-actions {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.skill-step-actions .el-button + .el-button {
  margin-left: 0;
}

.add-skill-step {
  align-self: flex-start;
}

.is-loading {
  animation: rotating 2s linear infinite;
}

@keyframes rotating {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

/* 图表可视化区域 */
.chart-section {
  background: #fff;
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 16px;
  border: 1px solid #e5e7eb;
}
.chart-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.chart-header h6 {
  margin: 0;
  font-size: 14px;
  color: #374151;
}
.chart-container {
  width: 100%;
  min-height: 360px;
}
</style>
