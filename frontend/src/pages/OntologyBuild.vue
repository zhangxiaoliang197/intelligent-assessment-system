<template>
  <Layout>
    <div class="ontology-build">
      <!-- 顶部 Header -->
      <div class="build-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回本体首页</el-button>
          <h2>文档构建：{{ job?.name || '加载中...' }}</h2>
          <el-tag :type="getStatusType(job?.status)" size="small" v-if="job">
            {{ getStatusText(job?.status) }}
          </el-tag>
        </div>
      </div>

      <!-- 状态栏：真实进度时间线 + 步骤条 -->
      <div class="status-bar" v-if="job">
        <!-- 运行中：当前阶段文案 + 百分比（取自后端 progress，无假动画） -->
        <div class="status-progress" v-if="isRunning">
          <el-icon class="is-loading" :size="16"><Loading /></el-icon>
          <span class="status-text">{{ progressMessage }}</span>
          <el-progress
            :percentage="currentProgressPercent"
            :stroke-width="4"
            class="slim-progress"
            :show-text="false"
          />
          <span class="status-percent">{{ currentProgressPercent }}%</span>
          <span class="status-hint">后台运行中，可随时离开</span>
        </div>

        <!-- 阶段时间线：4 个 LLM 阶段的真实状态（progress_stages 驱动） -->
        <div class="stage-timeline" v-if="hasStageTimeline">
          <div
            v-for="s in stageTimeline"
            :key="s.stage"
            :class="['stage-item', `stage-${s.status}`]"
          >
            <span class="stage-dot">
              <el-icon v-if="s.status === 'running'" class="is-loading"><Loading /></el-icon>
              <el-icon v-else-if="s.status === 'done'"><Check /></el-icon>
              <el-icon v-else-if="s.status === 'failed'"><Close /></el-icon>
              <span v-else class="stage-num">{{ s.stage }}</span>
            </span>
            <span class="stage-name">{{ s.name }}</span>
            <span class="stage-time" v-if="s.elapsed">{{ s.elapsed }}</span>
          </div>
        </div>

        <!-- 步骤指示（5 阶段） -->
        <el-steps :active="currentStep" finish-status="success" align-center class="build-steps">
          <el-step title="上传文档" :status="getStepStatus(0)" />
          <el-step title="提取概念" :status="getStepStatus(1)" />
          <el-step title="提取实体" :status="getStepStatus(2)" />
          <el-step title="关系建模" :status="getStepStatus(3)" />
          <el-step title="验证报告" :status="getStepStatus(4)" />
        </el-steps>
      </div>

      <!-- 错误提示 -->
      <el-alert
        v-if="job?.error_message"
        :title="'构建出错：' + job.error_message"
        type="error"
        :closable="false"
        show-icon
        style="margin-bottom: 1rem"
      />

      <!-- 步骤内容区 -->
      <div class="step-content" v-loading="loading">
        <!-- Step 0: 上传文档 + 元模型确认 + 粒度 + 阶段提示词 -->
        <div v-if="currentStep === 0" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>文档信息</h3>
                <el-tag type="success" v-if="job?.meta_confirmed">已确认</el-tag>
              </div>
            </template>
            <el-descriptions :column="2" border>
              <el-descriptions-item label="本体名称">{{ job?.name }}</el-descriptions-item>
              <el-descriptions-item label="源文档">{{ job?.source_filename }}</el-descriptions-item>
              <el-descriptions-item label="字符数">{{ job?.char_count?.toLocaleString() }}</el-descriptions-item>
              <el-descriptions-item label="创建时间">{{ formatTime(job?.create_time) }}</el-descriptions-item>
              <el-descriptions-item label="描述" :span="2">{{ job?.description || '暂无描述' }}</el-descriptions-item>
            </el-descriptions>
          </el-card>

          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>确认元模型</h3>
                <el-tag type="info" size="small">AI 已根据文档内容推荐以下元模型，您可以编辑确认</el-tag>
              </div>
            </template>

            <div class="meta-columns">
              <!-- 左侧：实体类型 -->
              <div class="meta-column">
                <div class="meta-column-header">
                  <h4>实体类型</h4>
                  <el-tag size="small" type="info">{{ metaForm.entityTypes.length }} 个</el-tag>
                </div>
                <div class="type-list">
                  <div v-for="(t, idx) in metaForm.entityTypes" :key="idx" class="type-item">
                    <el-input v-model="t.name" placeholder="类型名" size="small" class="type-name-input" />
                    <el-color-picker v-model="t.color" size="small" />
                    <el-button size="small" link type="danger" @click="metaForm.entityTypes.splice(idx, 1)">
                      <el-icon><Close /></el-icon>
                    </el-button>
                  </div>
                </div>
                <el-button size="small" class="add-type-btn" @click="metaForm.entityTypes.push({ name: '', color: '#5470c6' })">
                  <el-icon><Plus /></el-icon> 添加实体类型
                </el-button>
              </div>

              <!-- 右侧：关系类型 -->
              <div class="meta-column">
                <div class="meta-column-header">
                  <h4>关系类型</h4>
                  <el-tag size="small" type="info">{{ metaForm.relationTypes.length }} 个</el-tag>
                </div>
                <div class="type-list">
                  <div v-for="(t, idx) in metaForm.relationTypes" :key="idx" class="type-item">
                    <el-input v-model="t.name" placeholder="关系名" size="small" class="type-name-input" />
                    <el-button size="small" link type="danger" @click="metaForm.relationTypes.splice(idx, 1)">
                      <el-icon><Close /></el-icon>
                    </el-button>
                  </div>
                </div>
                <el-button size="small" class="add-type-btn" @click="metaForm.relationTypes.push({ name: '' })">
                  <el-icon><Plus /></el-icon> 添加关系类型
                </el-button>
              </div>
            </div>

            <!-- 粒度预设 + 阶段提示词（控制后续 LLM 提取粗细与重点） -->
            <div class="granularity-section">
              <div class="granularity-row">
                <span class="granularity-label">提取粒度：</span>
                <el-radio-group v-model="metaForm.granularity" size="small" :disabled="job?.meta_confirmed">
                  <el-radio-button value="coarse">粗（5-10 概念）</el-radio-button>
                  <el-radio-button value="medium">中（10-20 概念）</el-radio-button>
                  <el-radio-button value="fine">细（20-40 概念）</el-radio-button>
                </el-radio-group>
              </div>
              <div class="stage-hints-grid">
                <div v-for="n in [1, 2, 3, 4]" :key="n" class="stage-hint-item">
                  <span class="stage-hint-label">{{ stageHintLabels[n] }}：</span>
                  <el-input
                    v-model="metaForm.stageHints[n]"
                    size="small"
                    :placeholder="`为阶段${n}补充提示词（可选）`"
                    :disabled="job?.meta_confirmed"
                  />
                </div>
              </div>
            </div>

            <div class="step-actions">
              <el-button @click="goBack">取消</el-button>
              <el-button
                type="primary"
                :loading="submitting"
                :disabled="job?.meta_confirmed"
                @click="doConfirmMeta"
              >
                {{ job?.meta_confirmed ? '已确认' : '确认元模型' }}
              </el-button>
            </div>
          </el-card>
        </div>

        <!-- Step 1: 提取概念（类型层） -->
        <div v-if="currentStep === 1" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>提取概念</h3>
                <el-tag type="info" size="small">
                  {{ isExtractingConcepts ? 'AI 正在提取，可实时编辑已提取部分' : 'AI 已提取以下概念，可编辑确认' }}
                </el-tag>
              </div>
            </template>

            <!-- 分批提取中途失败，可断点续作 -->
            <div v-if="isStep1Resumable" class="extract-section">
              <el-alert
                :title="`第 ${job.step1_failed_batch + 1}/${job.step1_batches_total} 批提取失败，已成功 ${job.step1_batches_done} 批`"
                type="warning"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>{{ job?.error_message || '部分批次提取失败' }}</p>
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续提取概念"重试，无需修改任何配置。</p>
                  <p>点击"继续提取概念"从失败批次续跑，已成功批次不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractConcepts">
                  继续提取概念
                </el-button>
              </div>
            </div>

            <!-- 未开始提取 -->
            <div v-else-if="!isExtractingConcepts && !concepts.length" class="extract-section">
              <el-alert
                title="点击按钮开始提取概念"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将根据已确认的元模型，从文档内容中提取概念（抽象类型定义，如「公司」「人物」），每个概念会标注原文出处。</p>
                  <p>长文档会分批提取，每批完成后实时显示在下方表格中，您可边提取边编辑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractConcepts">
                  开始提取概念
                </el-button>
              </div>
            </div>

            <!-- 提取中/已完成审核：实时表格 -->
            <div v-else class="concepts-section">
              <el-alert
                v-if="isExtractingConcepts"
                :title="batch1ProgressText"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-alert
                v-else
                title="概念提取完成，请审核确认"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-table :data="concepts" stripe style="width: 100%">
                <el-table-column prop="name" label="名称" width="130">
                  <template #default="scope">
                    <el-input v-model="scope.row.name" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="entity_type" label="元模型类型" width="130">
                  <template #default="scope">
                    <el-select v-model="scope.row.entity_type" size="small">
                      <el-option
                        v-for="t in metaForm.entityTypes"
                        :key="t.name"
                        :label="t.name"
                        :value="t.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="description" label="描述" min-width="180">
                  <template #default="scope">
                    <el-input v-model="scope.row.description" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="property_schema" label="属性骨架（JSON）" min-width="220">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.propertySchemaStr"
                      size="small"
                      type="textarea"
                      :rows="2"
                      placeholder='[{"name":"属性名","category":"metric","unit":"%"}]'
                    />
                  </template>
                </el-table-column>
                <el-table-column prop="source_snippet" label="原文出处" min-width="200">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.source_snippet"
                      size="small"
                      type="textarea"
                      :rows="2"
                      placeholder="从原文摘录"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" fixed="right">
                  <template #default="scope">
                    <el-button size="small" link type="danger" @click="concepts.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="concepts.push({ name: '', entity_type: metaForm.entityTypes[0]?.name || '', description: '', property_schema: [], propertySchemaStr: '[]', source_snippet: '' })">
                  + 添加概念
                </el-button>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep1Done || job?.step1_confirmed"
                  @click="doConfirmConcepts"
                >
                  {{ job?.step1_confirmed ? '已确认' : (aiStep1Done ? '确认概念清单' : 'AI 提取中（可先编辑已提取部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 2: 提取实体+属性（实例层） -->
        <div v-if="currentStep === 2" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>提取实体+属性</h3>
                <el-tag type="info" size="small">
                  {{ isExtractingEntities ? 'AI 正在提取，可实时编辑已生成部分' : 'AI 已提取以下实体，可编辑确认' }}
                </el-tag>
              </div>
            </template>

            <!-- 实体提取分批中途失败，可断点续作 -->
            <div v-if="isStep2Resumable" class="build-section">
              <el-alert
                :title="`第 ${job.step2_failed_batch + 1}/${job.step2_batches_total} 批提取失败，已成功 ${job.step2_batches_done} 批`"
                type="warning"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>{{ job?.error_message || '部分批次提取失败' }}</p>
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续提取实体"重试，无需修改任何配置。</p>
                  <p>点击"继续提取实体"从失败批次续跑，已成功批次不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractEntities">
                  继续提取实体
                </el-button>
              </div>
            </div>

            <!-- 未开始提取 -->
            <div v-else-if="!isExtractingEntities && !entities.length" class="build-section">
              <el-alert
                title="点击按钮开始提取实体"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将根据概念清单，从文档提取具体实体（人名、公司名、地名等），并按概念的属性骨架填充属性。指标型数据（如资产负债率）会作为属性填入实体。</p>
                  <p>长文档会分批提取，每批完成后实时显示在下方表格中。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractEntities">
                  开始提取实体
                </el-button>
              </div>
            </div>

            <!-- 提取中/已完成审核 -->
            <div v-else class="structure-section">
              <el-alert
                v-if="isExtractingEntities"
                :title="batch2ProgressText"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-alert
                v-else
                title="实体提取完成，请审核并勾选主要实体"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <h4>实体列表（{{ entities.length }} 个）</h4>
              <el-table :data="entities" stripe style="width: 100%; margin-bottom: 1.5rem">
                <el-table-column prop="name" label="名称" width="130">
                  <template #default="scope">
                    <el-input v-model="scope.row.name" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="instance_of" label="所属概念" width="130">
                  <template #default="scope">
                    <el-select v-model="scope.row.instance_of" size="small">
                      <el-option
                        v-for="c in concepts"
                        :key="c.name"
                        :label="c.name"
                        :value="c.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="is_primary_candidate" label="主要候选" width="90" align="center">
                  <template #default="scope">
                    <el-tag v-if="scope.row.is_primary_candidate" type="warning" size="small">候选</el-tag>
                  </template>
                </el-table-column>
                <el-table-column prop="properties" label="属性（JSON）" min-width="220">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.propertiesStr"
                      size="small"
                      type="textarea"
                      :rows="2"
                      placeholder='[{"name":"属性名","value":"值","category":"metric","unit":"%"}]'
                    />
                  </template>
                </el-table-column>
                <el-table-column prop="source_snippet" label="原文出处" min-width="180">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.source_snippet"
                      size="small"
                      type="textarea"
                      :rows="2"
                      placeholder="从原文摘录"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" fixed="right">
                  <template #default="scope">
                    <el-button size="small" link type="danger" @click="entities.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="entities.push({ name: '', instance_of: concepts[0]?.name || '', is_primary_candidate: false, propertiesStr: '[]', source_snippet: '' })">
                  + 添加实体
                </el-button>
              </div>

              <!-- 主要实体勾选（多本体拆分依据） -->
              <div class="primary-section" v-if="job?.primary_entity_candidates?.length">
                <h4>主要实体勾选（用于多本体实例化）</h4>
                <el-checkbox-group v-model="primarySelected">
                  <el-checkbox
                    v-for="name in job.primary_entity_candidates"
                    :key="name"
                    :value="name"
                    :label="name"
                  />
                </el-checkbox-group>
                <p class="primary-hint">未勾选时，系统将取第一个候选作为唯一主要实体（退化为单本体）。</p>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep2Done || job?.step2_confirmed"
                  @click="doConfirmEntities"
                >
                  {{ job?.step2_confirmed ? '已确认' : (aiStep2Done ? '确认实体清单' : 'AI 提取中（可先编辑已生成部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 3: 关系建模 -->
        <div v-if="currentStep === 3" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>关系建模</h3>
                <el-tag type="info" size="small">
                  {{ isBuildingRelations ? 'AI 正在建模，可实时编辑已生成部分' : 'AI 已建立以下关系，可编辑确认' }}
                </el-tag>
              </div>
            </template>

            <!-- 关系建模分组中途失败，可断点续作 -->
            <div v-if="isStep3Resumable" class="build-section">
              <el-alert
                :title="job.step3_groups_done < job.step3_groups_total
                  ? `第 ${job.step3_failed_group + 1}/${job.step3_groups_total} 组建模失败，已成功 ${job.step3_groups_done} 组`
                  : '跨组关系补充失败'"
                type="warning"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>{{ job?.error_message || '部分建模步骤失败' }}</p>
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续建模"重试，无需修改任何配置。</p>
                  <p>点击"继续建模"从断点续跑，已成功步骤不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doBuildRelations">
                  继续建模
                </el-button>
              </div>
            </div>

            <!-- 未开始建模 -->
            <div v-else-if="!isBuildingRelations && !relations.length" class="build-section">
              <el-alert
                title="点击按钮开始关系建模"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将在已确认的实体间建立语义关系。实体较多时分组建模，每组完成后实时显示在下方表格中。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doBuildRelations">
                  开始关系建模
                </el-button>
              </div>
            </div>

            <!-- 建模中/已完成审核 -->
            <div v-else class="structure-section">
              <el-alert
                v-if="isBuildingRelations"
                :title="group3ProgressText"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-alert
                v-else
                title="关系建模完成，请审核确认"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <h4>关系列表（{{ relations.length }} 条）</h4>
              <el-table :data="relations" stripe style="width: 100%; margin-bottom: 1.5rem">
                <el-table-column prop="source" label="源实体" width="140">
                  <template #default="scope">
                    <el-select v-model="scope.row.source" size="small" filterable>
                      <el-option
                        v-for="e in entities"
                        :key="e.name"
                        :label="e.name"
                        :value="e.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="relation_type" label="关系类型" width="130">
                  <template #default="scope">
                    <el-select v-model="scope.row.relation_type" size="small">
                      <el-option
                        v-for="t in metaForm.relationTypes"
                        :key="t.name"
                        :label="t.name"
                        :value="t.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="target" label="目标实体" width="140">
                  <template #default="scope">
                    <el-select v-model="scope.row.target" size="small" filterable>
                      <el-option
                        v-for="e in entities"
                        :key="e.name"
                        :label="e.name"
                        :value="e.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="weight" label="权重" width="110">
                  <template #default="scope">
                    <el-input-number v-model="scope.row.weight" size="small" :min="0" :max="1" :step="0.1" controls-position="right" />
                  </template>
                </el-table-column>
                <el-table-column prop="source_snippet" label="原文出处" min-width="200">
                  <template #default="scope">
                    <el-input
                      v-model="scope.row.source_snippet"
                      size="small"
                      type="textarea"
                      :rows="2"
                      placeholder="从原文摘录"
                    />
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="70" fixed="right">
                  <template #default="scope">
                    <el-button size="small" link type="danger" @click="relations.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>

              <div class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="relations.push({ source: entities[0]?.name || '', target: '', relation_type: metaForm.relationTypes[0]?.name || '', weight: 1.0, source_snippet: '' })">
                  + 添加关系
                </el-button>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep3Done || job?.step3_confirmed"
                  @click="doConfirmRelations"
                >
                  {{ job?.step3_confirmed ? '已确认' : (aiStep3Done ? '确认关系清单' : 'AI 建模中（可先编辑已生成部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 4: 验证 + 报告 -->
        <div v-if="currentStep === 4" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>验证 + 报告</h3>
                <el-tag type="info" size="small">
                  {{ isVerifying ? 'AI 正在做自检验证...' : (job?.step4_verification ? '验证完成' : '可启动验证') }}
                </el-tag>
              </div>
            </template>

            <!-- 验证中 -->
            <div v-if="isVerifying" class="waiting-section">
              <el-alert
                title="AI 正在做自检验证，检查实体/属性/关系是否可溯源..."
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>后台任务正在运行，请耐心等待。您可以随时离开此页面，稍后回来继续。</p>
                </template>
              </el-alert>
            </div>

            <!-- 未启动验证 -->
            <div v-else-if="!job?.step4_verification && job?.status !== 'completed'" class="generate-section">
              <el-alert
                title="点击按钮启动 LLM 自检验证"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将逐项检查实体/属性/关系是否可溯源到原文，标记存疑项，并生成一份结构化简报。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doVerify">
                  启动验证
                </el-button>
              </div>
            </div>

            <!-- 验证完成 -->
            <div v-else-if="job?.step4_verification" class="verify-section">
              <el-alert
                :title="`验证完成：${job.step4_verification.verified_count || 0} 项通过，${job.step4_verification.suspect_count || 0} 项存疑`"
                :type="(job.step4_verification.suspect_count || 0) > 0 ? 'warning' : 'success'"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />

              <!-- 存疑项列表 -->
              <div v-if="job.step4_verification.suspects?.length" class="suspects-block">
                <h4>存疑项（{{ job.step4_verification.suspects.length }} 条）</h4>
                <el-table :data="job.step4_verification.suspects" stripe size="small" style="width: 100%; margin-bottom: 1.5rem">
                  <el-table-column prop="item_type" label="类型" width="90" />
                  <el-table-column prop="item_id" label="标识" width="160" />
                  <el-table-column prop="reason" label="存疑原因" min-width="280" />
                </el-table>
              </div>

              <!-- 简报 -->
              <div v-if="job.step4_report" class="report-block">
                <h4>生成简报</h4>
                <div class="report-content">{{ job.step4_report }}</div>
              </div>

              <!-- 确认生成最终本体 -->
              <div class="step-actions" v-if="job?.status !== 'completed'">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="job?.step4_confirmed"
                  @click="doConfirmVerification"
                >
                  {{ job?.step4_confirmed ? '本体已生成' : '确认并生成最终本体' }}
                </el-button>
              </div>

              <!-- 已完成 -->
              <div v-else class="complete-content">
                <el-icon class="success-icon"><CircleCheck /></el-icon>
                <h3>本体构建成功！</h3>
                <el-descriptions :column="2" border style="margin: 1.5rem 0">
                  <el-descriptions-item label="本体名称">{{ job?.name }}</el-descriptions-item>
                  <el-descriptions-item label="状态">
                    <el-tag type="success">已完成</el-tag>
                  </el-descriptions-item>
                  <el-descriptions-item label="实体数量">{{ entities.length }}</el-descriptions-item>
                  <el-descriptions-item label="关系数量">{{ relations.length }}</el-descriptions-item>
                </el-descriptions>
                <div class="step-actions" style="justify-content: center">
                  <el-button type="primary" @click="viewOntology">查看本体详情</el-button>
                  <el-button @click="goBack">返回首页</el-button>
                </div>
              </div>
            </div>
          </el-card>
        </div>
      </div>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, CircleCheck, Loading, Close, Plus, Check } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'
import {
  getBuildJob,
  getBuildProgress,
  confirmMeta as confirmMetaApi,
  extractConcepts as extractConceptsApi,
  confirmConcepts as confirmConceptsApi,
  extractEntities as extractEntitiesApi,
  confirmEntities as confirmEntitiesApi,
  buildRelations as buildRelationsApi,
  confirmRelations as confirmRelationsApi,
  verifyOntology as verifyOntologyApi,
  confirmVerification as confirmVerificationApi,
  streamBuildJob
} from '@/services/ontologyBuild'

const route = useRoute()
const router = useRouter()
const jobId = route.params.jobId as string

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)

const job = ref<any>(null)
const concepts = ref<any[]>([])
const entities = ref<any[]>([])
const relations = ref<any[]>([])

const metaForm = ref({
  entityTypes: [] as any[],
  relationTypes: [] as any[],
  granularity: 'medium' as 'coarse' | 'medium' | 'fine',
  stageHints: { 1: '', 2: '', 3: '', 4: '' } as Record<number, string>
})

const stageHintLabels: Record<number, string> = {
  1: '概念提取提示',
  2: '实体提取提示',
  3: '关系建模提示',
  4: '验证提示'
}

// 主要实体勾选（多本体实例化依据）
const primarySelected = ref<string[]>([])

// AI 各阶段完成标记（收到 SSE step_done 后置 true，启用"确认"按钮）
const aiStep1Done = ref(false)
const aiStep2Done = ref(false)
const aiStep3Done = ref(false)

// 轮询定时器（Step4 验证用轮询；SSE 不可用时降级）
let pollTimer: ReturnType<typeof setInterval> | null = null
let sseAbort: (() => void) | null = null
let streamRetryCount = 0
const STREAM_MAX_RETRY = 3

// ── 计算属性 ──
// running_step 语义：1=概念, 2=实体, 3=关系, 4=验证, -1=空闲
const currentStep = computed(() => {
  if (!job.value) return 0
  if (job.value.status === 'completed' || job.value.step4_confirmed) return 4
  if (job.value.step3_confirmed) return 4   // 进入验证阶段
  if (job.value.step2_confirmed) return 3   // 关系建模
  if (job.value.step1_confirmed) return 2   // 实体提取
  if (job.value.meta_confirmed) return 1    // 概念提取
  return 0
})

const isRunning = computed(() => {
  const rs = job.value?.running_step
  return rs !== undefined && rs >= 1 && rs <= 4
})
const isExtractingConcepts = computed(() => job.value?.running_step === 1)
const isExtractingEntities = computed(() => job.value?.running_step === 2)
const isBuildingRelations = computed(() => job.value?.running_step === 3)
const isVerifying = computed(() => job.value?.running_step === 4)

const progressMessage = computed(() => {
  if (!job.value) return ''
  const msgs: Record<number, string> = {
    1: job.value.progress_message || '正在提取概念...',
    2: job.value.progress_message || '正在提取实体+属性...',
    3: job.value.progress_message || '正在建模关系...',
    4: job.value.progress_message || '正在验证+生成报告...'
  }
  return msgs[job.value.running_step] || job.value.progress_message || ''
})

const currentProgressPercent = computed(() => job.value?.progress ?? 0)

// 空响应错误：LLM 服务端偶发无响应（非配置/代码问题），提示用户重试即可
const isEmptyResponseError = computed(() =>
  !!job.value?.error_message && job.value.error_message.includes('空响应')
)

// ── 阶段时间线（progress_stages 真实进度）──
const hasStageTimeline = computed(() => {
  const stages = job.value?.progress_stages || []
  return stages.length > 0
})

const stageTimeline = computed(() => {
  const defaultStages = [
    { stage: 1, name: '概念提取', status: 'pending', elapsed: '' },
    { stage: 2, name: '实体提取', status: 'pending', elapsed: '' },
    { stage: 3, name: '关系建模', status: 'pending', elapsed: '' },
    { stage: 4, name: '验证报告', status: 'pending', elapsed: '' }
  ]
  const real = job.value?.progress_stages || []
  const map: Record<number, any> = {}
  for (const s of real) map[s.stage] = s
  return defaultStages.map(a => {
    const s = map[a.stage]
    if (!s) return a
    return {
      stage: a.stage,
      name: s.name || a.name,
      status: s.status || 'pending',
      elapsed: _calcElapsed(s.started_at, s.finished_at)
    }
  })
})

function _calcElapsed(start?: string, end?: string): string {
  if (!start) return ''
  const s = new Date(start).getTime()
  if (isNaN(s)) return ''
  const e = end ? new Date(end).getTime() : Date.now()
  const sec = Math.max(0, Math.round((e - s) / 1000))
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m${sec % 60}s`
}

// ── 实时进度文案 ──
const batch1ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在提取概念...'
  const done = concepts.value.length
  if (j.step1_batches_total > 1) {
    return `AI 正在提取概念（第 ${j.step1_batches_done + 1}/${j.step1_batches_total} 批），已提取 ${done} 个`
  }
  return `AI 正在提取概念，已提取 ${done} 个`
})

const batch2ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在提取实体...'
  const done = entities.value.length
  if (j.step2_batches_total > 1) {
    return `AI 正在提取实体（第 ${j.step2_batches_done + 1}/${j.step2_batches_total} 批），已提取 ${done} 个`
  }
  return `AI 正在提取实体，已提取 ${done} 个`
})

const group3ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在建模关系...'
  const done = relations.value.length
  if (j.step3_groups_total > 1) {
    return `AI 正在建模关系（第 ${j.step3_groups_done + 1}/${j.step3_groups_total} 组），已生成 ${done} 条`
  }
  return `AI 正在建模关系，已生成 ${done} 条`
})

// ── 断点续作 ──
const isStep1Resumable = computed(() =>
  !!job.value
  && job.value.step1_batches_total > 0
  && job.value.step1_batches_done < job.value.step1_batches_total
  && job.value.step1_failed_batch >= 0
  && !job.value.step1_confirmed
)
const isStep2Resumable = computed(() =>
  !!job.value
  && !job.value.step2_confirmed
  && job.value.step2_batches_total > 0
  && job.value.step2_batches_done < job.value.step2_batches_total
  && job.value.step2_failed_batch >= 0
)
const isStep3Resumable = computed(() =>
  !!job.value
  && !job.value.step3_confirmed
  && job.value.step3_groups_total > 0
  && (
    (job.value.step3_groups_done < job.value.step3_groups_total && job.value.step3_failed_group >= 0)
    || (job.value.step3_groups_done === job.value.step3_groups_total
        && !job.value.step3_cross_group_done && job.value.step3_cross_group_failed)
  )
)

// ── 步骤条状态 ──
const getStepStatus = (step: number): 'wait' | 'process' | 'finish' | 'error' => {
  if (!job.value) return 'wait'
  if (job.value.error_message && step === currentStep.value) return 'error'
  if (step < currentStep.value) return 'finish'
  if (step === currentStep.value) return 'process'
  return 'wait'
}

// ── 数据加载 ──
const loadJob = async () => {
  try {
    const res: any = await getBuildJob(jobId)
    job.value = res.data

    // 恢复元模型 + 粒度 + 阶段提示词
    if (job.value.meta_entity_types?.length) {
      metaForm.value.entityTypes = JSON.parse(JSON.stringify(job.value.meta_entity_types))
    }
    if (job.value.meta_relation_types?.length) {
      metaForm.value.relationTypes = JSON.parse(JSON.stringify(job.value.meta_relation_types))
    }
    if (job.value.granularity) {
      metaForm.value.granularity = job.value.granularity
    }
    if (job.value.stage_hints && typeof job.value.stage_hints === 'object') {
      metaForm.value.stageHints = { 1: '', 2: '', 3: '', 4: '', ...job.value.stage_hints }
    }

    // 恢复概念清单
    if (job.value.step1_concepts?.length) {
      concepts.value = job.value.step1_concepts.map((c: any) => ({
        ...c,
        // property_schema 可能是数组，转为可编辑 JSON 串
        propertySchemaStr: JSON.stringify(c.property_schema || [], null, 0)
      }))
    } else {
      concepts.value = []
    }

    // 恢复实体清单
    if (job.value.step2_entities?.length) {
      entities.value = job.value.step2_entities.map((e: any) => ({
        ...e,
        propertiesStr: JSON.stringify(e.properties || [], null, 0)
      }))
    } else {
      entities.value = []
    }

    // 恢复关系清单
    if (job.value.step3_relations?.length) {
      relations.value = JSON.parse(JSON.stringify(job.value.step3_relations))
    } else {
      relations.value = []
    }

    // 恢复主要实体勾选
    if (job.value.primary_entity_selected?.length) {
      primarySelected.value = [...job.value.primary_entity_selected]
    } else if (job.value.primary_entity_candidates?.length) {
      // 默认勾选全部候选，方便用户
      primarySelected.value = [...job.value.primary_entity_candidates]
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载任务失败')
  }
}

// ── 轮询进度（Step4 验证用；SSE 降级时也用）──
const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const res: any = await getBuildProgress(jobId)
      const p = res.data
      if (job.value) {
        _applyProgress(p)
        // 后台任务完成（running_step 回到 -1）或出错时，重新加载并停止轮询
        if (p.running_step === -1) {
          await loadJob()
          stopPolling()
        }
      }
    } catch {
      // 静默失败，继续轮询
    }
  }, 2000)
}

const stopPolling = () => {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

/** 把 progress 端点返回的字段同步到 job（轮询/SSE 共用） */
const _applyProgress = (p: any) => {
  if (!job.value) return
  job.value.running_step = p.running_step
  job.value.progress = p.progress
  job.value.progress_message = p.progress_message
  job.value.error_message = p.error_message
  job.value.step = p.step
  job.value.status = p.status
  job.value.meta_confirmed = p.meta_confirmed
  job.value.step1_confirmed = p.step1_confirmed
  job.value.step2_confirmed = p.step2_confirmed
  job.value.step3_confirmed = p.step3_confirmed
  job.value.step4_confirmed = p.step4_confirmed
  job.value.ontology_id = p.ontology_id
  // 分批/分组状态
  job.value.step1_batches_total = p.step1_batches_total
  job.value.step1_batches_done = p.step1_batches_done
  job.value.step1_failed_batch = p.step1_failed_batch
  job.value.step2_batches_total = p.step2_batches_total
  job.value.step2_batches_done = p.step2_batches_done
  job.value.step2_failed_batch = p.step2_failed_batch
  job.value.step3_groups_total = p.step3_groups_total
  job.value.step3_groups_done = p.step3_groups_done
  job.value.step3_failed_group = p.step3_failed_group
  job.value.step3_cross_group_done = p.step3_cross_group_done
  job.value.step3_cross_group_failed = p.step3_cross_group_failed
  // 验证结果 + 主要实体
  job.value.step4_verification = p.step4_verification
  job.value.step4_report = p.step4_report
  job.value.primary_entity_candidates = p.primary_entity_candidates
  job.value.primary_entity_selected = p.primary_entity_selected
  // 真实进度时间线
  job.value.progress_stages = p.progress_stages
}

// ── SSE 实时订阅（Step1/Step2/Step3 批次级增量推送）──
// Step1/Step2 都发 batch_done 事件，按 data.concepts / data.entities 区分
// Step3 发 group_done / cross_group_done 事件

/** 名称归一化（与后端 _normalize_name 一致）：用于按名称去重 */
const _normName = (name: string) =>
  (name || '').trim().replace(/（/g, '(').replace(/）/g, ')').replace(/\u3000/g, ' ')

/** 关系三元组去重 key */
const _relKey = (r: any) => `${_normName(r.source)}|${r.relation_type}|${_normName(r.target)}`

const startStream = () => {
  console.log('[Stream] startStream, jobId=', jobId)
  stopStream()
  stopPolling()
  streamRetryCount = 0
  sseAbort = streamBuildJob(jobId, {
    onBatchDone: (d) => {
      // batch_done 同时服务于 Step1（concepts）和 Step2（entities），按字段区分
      if (Array.isArray(d.concepts)) {
        // Step1：概念按名称去重追加
        const existing = new Set(concepts.value.map(c => _normName(c.name)).filter(Boolean))
        const fresh = (d.concepts || []).filter((c: any) => {
          const n = _normName(c.name)
          if (!n || existing.has(n)) return false
          existing.add(n)
          return true
        }).map((c: any) => ({
          ...c,
          propertySchemaStr: JSON.stringify(c.property_schema || [], null, 0)
        }))
        concepts.value.push(...fresh)
        if (job.value) {
          job.value.step1_batches_done = d.batches_done
          job.value.step1_batches_total = d.batches_total
        }
      } else if (Array.isArray(d.entities)) {
        // Step2：实体按名称去重追加
        const existing = new Set(entities.value.map(e => _normName(e.name)).filter(Boolean))
        const fresh = (d.entities || []).filter((e: any) => {
          const n = _normName(e.name)
          if (!n || existing.has(n)) return false
          existing.add(n)
          return true
        }).map((e: any) => ({
          ...e,
          propertiesStr: JSON.stringify(e.properties || [], null, 0)
        }))
        entities.value.push(...fresh)
        if (job.value) {
          job.value.step2_batches_done = d.batches_done
          job.value.step2_batches_total = d.batches_total
        }
      }
    },
    onGroupDone: (d) => {
      // Step3：关系按三元组去重追加
      const existRel = new Set(relations.value.map(_relKey))
      const freshRel = (d.relations || []).filter((r: any) => {
        const k = _relKey(r)
        if (existRel.has(k)) return false
        existRel.add(k)
        return true
      })
      relations.value.push(...freshRel)
      if (job.value) {
        job.value.step3_groups_done = d.groups_done
        job.value.step3_groups_total = d.groups_total
      }
    },
    onCrossGroupDone: (d) => {
      const existRel = new Set(relations.value.map(_relKey))
      const freshRel = (d.relations || []).filter((r: any) => {
        const k = _relKey(r)
        if (existRel.has(k)) return false
        existRel.add(k)
        return true
      })
      relations.value.push(...freshRel)
    },
    onStepDone: (d) => {
      // AI 全部完成，启用对应"确认"按钮
      if (d.step === 1) {
        aiStep1Done.value = true
        if (job.value) job.value.running_step = -1
        ElMessage.success(`概念提取完成，共 ${d.total ?? concepts.value.length} 个`)
      } else if (d.step === 2) {
        aiStep2Done.value = true
        if (job.value) job.value.running_step = -1
        // 用最终合并结果覆盖（含主要实体候选）
        if (Array.isArray(d.entities)) {
          entities.value = d.entities.map((e: any) => ({
            ...e,
            propertiesStr: JSON.stringify(e.properties || [], null, 0)
          }))
        }
        if (Array.isArray(d.primary_entity_candidates) && job.value) {
          job.value.primary_entity_candidates = d.primary_entity_candidates
          // 默认勾选全部候选
          if (!primarySelected.value.length) {
            primarySelected.value = [...d.primary_entity_candidates]
          }
        }
        ElMessage.success(`实体提取完成，共 ${entities.value.length} 个`)
      } else if (d.step === 3) {
        aiStep3Done.value = true
        if (job.value) job.value.running_step = -1
        if (Array.isArray(d.relations)) {
          relations.value = JSON.parse(JSON.stringify(d.relations))
        }
        ElMessage.success(`关系建模完成，共 ${relations.value.length} 条`)
      } else if (d.step === 4) {
        if (job.value) {
          job.value.running_step = -1
          if (d.verification) job.value.step4_verification = d.verification
          if (d.report !== undefined) job.value.step4_report = d.report
        }
        ElMessage.success('验证完成')
      }
    },
    onError: (d) => {
      if (d.reconnect) {
        console.log('[Stream] onError reconnect, retryCount=', streamRetryCount)
        retryStream()
      } else {
        if (d.message) ElMessage.error(d.message)
        if (job.value) {
          job.value.error_message = d.message
          job.value.running_step = -1
        }
        startPolling()
      }
    },
    onState: (s) => {
      if (s === 'open') streamRetryCount = 0
    }
  })
}

const stopStream = () => {
  if (sseAbort) {
    sseAbort()
    sseAbort = null
  }
}

/** 断线重连：最多 3 次，仍失败回退轮询 */
const retryStream = () => {
  if (streamRetryCount >= STREAM_MAX_RETRY) {
    ElMessage.warning('实时连接不稳定，已切换到轮询模式')
    startPolling()
    return
  }
  streamRetryCount++
  setTimeout(() => {
    startStream()
  }, 3000)
}

// ── 步骤操作 ──
const doConfirmMeta = async () => {
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('entity_types', JSON.stringify(metaForm.value.entityTypes.filter((t: any) => t.name)))
    fd.append('relation_types', JSON.stringify(metaForm.value.relationTypes.filter((t: any) => t.name)))
    fd.append('granularity', metaForm.value.granularity)
    // 只传非空的阶段提示词
    const hints: Record<string, string> = {}
    for (const k of Object.keys(metaForm.value.stageHints)) {
      const v = (metaForm.value.stageHints as any)[k]
      if (v && String(v).trim()) hints[k] = String(v).trim()
    }
    fd.append('stage_hints', JSON.stringify(hints))

    await confirmMetaApi(jobId, fd)
    ElMessage.success('元模型已确认，可执行概念提取')
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doExtractConcepts = async () => {
  try {
    await extractConceptsApi(jobId)
    if (job.value) {
      job.value.running_step = 1
      job.value.progress_message = '正在准备文档...'
    }
    aiStep1Done.value = false
    ElMessage.info('概念提取已在后台开始，可实时查看提取结果')
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

const doConfirmConcepts = async () => {
  submitting.value = true
  try {
    // 解析 propertySchemaStr 回数组
    const parsed = concepts.value.map(c => {
      let schema: any = []
      try {
        schema = JSON.parse(c.propertySchemaStr || '[]')
      } catch {
        schema = []
      }
      const { propertySchemaStr, ...rest } = c
      return { ...rest, property_schema: schema }
    })
    await confirmConceptsApi(jobId, parsed)
    ElMessage.success('概念清单已确认，可执行实体提取')
    stopStream()
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doExtractEntities = async () => {
  try {
    await extractEntitiesApi(jobId)
    if (job.value) {
      job.value.running_step = 2
      job.value.progress_message = '正在提取实体+属性...'
    }
    aiStep2Done.value = false
    ElMessage.info('实体提取已在后台开始，可实时查看提取结果')
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

const doConfirmEntities = async () => {
  submitting.value = true
  try {
    const parsedEntities = entities.value.map(e => {
      let props: any = []
      try {
        const parsed = JSON.parse(e.propertiesStr || '[]')
        props = Array.isArray(parsed) ? parsed : []
      } catch {
        props = []
      }
      const { propertiesStr, ...rest } = e
      return { ...rest, properties: props }
    })
    await confirmEntitiesApi(jobId, parsedEntities, primarySelected.value)
    ElMessage.success('实体清单已确认，可执行关系建模')
    stopStream()
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doBuildRelations = async () => {
  try {
    await buildRelationsApi(jobId)
    if (job.value) {
      job.value.running_step = 3
      job.value.progress_message = '正在建模关系...'
    }
    aiStep3Done.value = false
    ElMessage.info('关系建模已在后台开始，可实时查看建模结果')
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动建模失败')
  }
}

const doConfirmRelations = async () => {
  submitting.value = true
  try {
    await confirmRelationsApi(jobId, relations.value)
    ElMessage.success('关系清单已确认，可执行验证')
    stopStream()
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doVerify = async () => {
  try {
    await verifyOntologyApi(jobId)
    if (job.value) {
      job.value.running_step = 4
      job.value.progress_message = '正在验证+生成报告...'
    }
    ElMessage.info('验证已在后台开始，您可以离开页面')
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动验证失败')
  }
}

const doConfirmVerification = async () => {
  submitting.value = true
  try {
    await confirmVerificationApi(jobId)
    ElMessage.success('本体已生成')
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '生成失败')
  } finally {
    submitting.value = false
  }
}

// ── 导航 ──
const viewOntology = () => {
  if (job.value?.ontology_id) {
    router.push(`/ontology/${job.value.ontology_id}`)
  } else {
    goBack()
  }
}

const goBack = () => {
  stopPolling()
  stopStream()
  router.push('/ontology')
}

// ── 辅助函数 ──
const getStatusType = (status: string) => {
  const typeMap: Record<string, 'success' | 'warning' | 'info' | 'danger'> = {
    'completed': 'success',
    'draft': 'warning',
    'abandoned': 'info'
  }
  return typeMap[status] || 'info'
}

const getStatusText = (status: string) => {
  const textMap: Record<string, string> = {
    'completed': '已完成',
    'draft': '草稿',
    'abandoned': '已废弃'
  }
  return textMap[status] || status
}

const formatTime = (time: string) => {
  if (!time) return ''
  try {
    return new Date(time).toLocaleString('zh-CN')
  } catch {
    return time
  }
}

// ── 生命周期 ──
onMounted(async () => {
  loading.value = true
  await loadJob()
  loading.value = false

  // 恢复 AI 完成标记（断线重连/刷新页面恢复场景：已提取但未确认）
  if (job.value?.step1_concepts?.length && !job.value?.step1_confirmed) {
    aiStep1Done.value = true
  }
  if (job.value?.step2_entities?.length && !job.value?.step2_confirmed) {
    aiStep2Done.value = true
  }
  if (job.value?.step3_relations?.length && !job.value?.step3_confirmed) {
    aiStep3Done.value = true
  }

  // 若有后台任务在运行：Step1/2/3 用 SSE 实时推送，Step4（验证）用轮询
  const rs = job.value?.running_step
  if (rs >= 1 && rs <= 3) {
    startStream()
  } else if (rs === 4) {
    startPolling()
  }
})

onUnmounted(() => {
  stopStream()
  stopPolling()
})
</script>

<style scoped>
.ontology-build {
  height: 100%;
  padding: 1.5rem;
  overflow-y: auto;
}

.build-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.875rem;
}

.header-left h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.35rem;
  font-weight: 600;
}

.status-bar {
  background: white;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 1.25rem;
}

.status-progress {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
}

.status-text {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-primary);
}

.slim-progress {
  flex: 1;
  margin: 0;
}

.status-percent {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--primary-500);
  min-width: 32px;
  text-align: right;
}

.status-hint {
  font-size: 0.8rem;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* 阶段时间线：4 个 LLM 阶段的真实状态 */
.stage-timeline {
  display: flex;
  gap: 1.5rem;
  margin-bottom: 1rem;
  padding: 0.75rem 0;
  border-bottom: 1px dashed var(--border-color, #e4e7ed);
  flex-wrap: wrap;
}

.stage-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.82rem;
}

.stage-dot {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  border-radius: 50%;
  background: var(--bg-secondary, #f0f2f5);
  color: var(--text-secondary, #909399);
  font-size: 0.7rem;
}

.stage-item.stage-running .stage-dot {
  background: var(--primary-100, #ecf5ff);
  color: var(--primary-500, #409eff);
}

.stage-item.stage-done .stage-dot {
  background: var(--success-100, #f0f9eb);
  color: var(--success-500, #67c23a);
}

.stage-item.stage-failed .stage-dot {
  background: var(--el-color-danger-light-9, #fef0f0);
  color: var(--el-color-danger, #f56c6c);
}

.stage-name {
  color: var(--text-secondary, #606266);
}

.stage-item.stage-running .stage-name,
.stage-item.stage-done .stage-name {
  color: var(--text-primary);
  font-weight: 500;
}

.stage-time {
  font-size: 0.72rem;
  color: var(--text-secondary, #909399);
}

.build-steps {
  margin: 0;
}

.step-content {
  min-height: 300px;
}

.step-panel {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

.step-card {
  border-radius: 10px;
}

.step-card :deep(.el-card__body) {
  padding: 1.5rem;
}

.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.step-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-bottom: 1.25rem;
}

@media (max-width: 768px) {
  .meta-columns {
    grid-template-columns: 1fr;
  }
}

.meta-column {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  padding: 1.25rem;
  border: 1px solid var(--border-color, #e4e7ed);
}

.meta-column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  padding-bottom: 0.75rem;
  border-bottom: 2px solid var(--primary-500, #409eff);
}

.meta-column-header h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.type-list {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin-bottom: 1rem;
  min-height: 80px;
}

.type-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  background: white;
  padding: 0.625rem 0.75rem;
  border-radius: 6px;
  border: 1px solid var(--border-color, #e4e7ed);
  transition: all 0.2s;
}

.type-item:hover {
  border-color: var(--primary-500, #409eff);
  box-shadow: 0 2px 4px rgba(64, 158, 255, 0.1);
}

.type-name-input {
  flex: 1;
}

.add-type-btn {
  width: 100%;
  border-style: dashed;
}

/* 粒度 + 阶段提示词 */
.granularity-section {
  margin-bottom: 1.25rem;
  padding: 1rem 1.25rem;
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e4e7ed);
}

.granularity-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.granularity-label {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}

.stage-hints-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.75rem 1.25rem;
}

@media (max-width: 768px) {
  .stage-hints-grid {
    grid-template-columns: 1fr;
  }
}

.stage-hint-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.stage-hint-label {
  font-size: 0.82rem;
  color: var(--text-secondary);
  white-space: nowrap;
  min-width: 96px;
}

.waiting-section,
.extract-section,
.build-section,
.generate-section {
  padding: 0.5rem 0;
}

.concepts-section,
.structure-section {
  padding: 0.5rem 0;
}

.concepts-section h4,
.structure-section h4 {
  margin: 1.5rem 0 0.75rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

/* 主要实体勾选 */
.primary-section {
  margin: 1.5rem 0;
  padding: 1rem 1.25rem;
  background: var(--el-color-warning-light-9, #fdf6ec);
  border-radius: 8px;
  border: 1px solid var(--el-color-warning-light-7, #f5dab1);
}

.primary-section h4 {
  margin: 0 0 0.75rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.primary-hint {
  margin: 0.5rem 0 0 0;
  font-size: 0.78rem;
  color: var(--text-secondary);
}

/* 验证报告 */
.verify-section {
  padding: 0.5rem 0;
}

.suspects-block h4,
.report-block h4 {
  margin: 1rem 0 0.75rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

.report-block {
  margin: 1.5rem 0;
}

.report-content {
  padding: 1rem 1.25rem;
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e4e7ed);
  white-space: pre-wrap;
  font-size: 0.88rem;
  line-height: 1.7;
  color: var(--text-primary);
  max-height: 480px;
  overflow-y: auto;
}

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1.5rem;
}

/* LLM 服务端偶发无响应的专属提示 */
.llm-hint {
  margin: 0.25rem 0;
  color: var(--el-color-warning);
  font-weight: 600;
}

.complete-content {
  text-align: center;
  padding: 2rem 1.5rem;
}

.success-icon {
  font-size: 3.5rem;
  color: var(--success-500);
  margin-bottom: 1rem;
}

.complete-content h3 {
  margin: 0 0 0.75rem 0;
  font-size: 1.35rem;
  font-weight: 600;
  color: var(--text-primary);
}
</style>
