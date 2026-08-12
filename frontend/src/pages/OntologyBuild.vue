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

        <!-- 阶段时间线：3 个 LLM 阶段的真实状态（progress_stages 驱动） -->
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

        <!-- 步骤指示（v3 四阶段） -->
        <el-steps :active="currentStep" finish-status="success" align-center class="build-steps">
          <el-step title="配置" :status="getStepStatus(0)" />
          <el-step title="实体类型" :status="getStepStatus(1)" />
          <el-step title="实体+关系" :status="getStepStatus(2)" />
          <el-step title="验证报告" :status="getStepStatus(3)" />
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
        <!-- Step 0: 配置（粒度 + 阶段提示词 + 可选模板） -->
        <div v-if="currentStep === 0" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <h3>文档信息</h3>
                <el-tag type="success" v-if="job?.meta_confirmed">配置已确认</el-tag>
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
                <h3>构建配置</h3>
                <el-tag type="info" size="small">粒度 / 阶段提示词 / 可选模板</el-tag>
              </div>
            </template>

            <div class="granularity-section">
              <!-- 提取粒度 -->
              <div class="granularity-row">
                <span class="granularity-label">提取粒度：</span>
                <el-radio-group v-model="metaForm.granularity" size="small" :disabled="job?.meta_confirmed">
                  <el-radio-button value="coarse">粗（少量实体类型）</el-radio-button>
                  <el-radio-button value="medium">中（适中）</el-radio-button>
                  <el-radio-button value="fine">细（精细）</el-radio-button>
                </el-radio-group>
              </div>

              <!-- 可选模板 -->
              <div class="granularity-row template-row">
                <span class="granularity-label">使用模板：</span>
                <el-select
                  v-model="metaForm.templateId"
                  size="small"
                  clearable
                  placeholder="不使用模板"
                  :disabled="job?.meta_confirmed"
                  style="width: 240px"
                >
                  <el-option
                    v-for="t in templates"
                    :key="t.id"
                    :label="`${t.name}${t.is_builtin ? '（内置）' : ''}`"
                    :value="t.id"
                  />
                </el-select>
                <el-radio-group
                  v-if="metaForm.templateId"
                  v-model="metaForm.templateMode"
                  size="small"
                  :disabled="job?.meta_confirmed"
                  style="margin-left: 0.75rem"
                >
                  <el-radio-button value="skip_step1">跳过实体类型提取</el-radio-button>
                  <el-radio-button value="soft_constraint">软约束（参考）</el-radio-button>
                </el-radio-group>
                <el-tag v-if="metaForm.templateId" size="small" type="info" style="margin-left: 0.5rem">
                  {{ metaForm.templateMode === 'skip_step1' ? '直接使用模板实体类型' : 'AI 参考模板提取' }}
                </el-tag>
              </div>

              <!-- 阶段提示词（3 个阶段） -->
              <div class="stage-hints-grid">
                <div v-for="n in [1, 2, 3]" :key="n" class="stage-hint-item">
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
                {{ job?.meta_confirmed ? '已确认' : '确认配置' }}
              </el-button>
            </div>
          </el-card>
        </div>

        <!-- Step 1: 实体类型提取（EntityType 层级 + property_schema + 类型间关系） -->
        <div v-if="currentStep === 1" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <div class="step-header-title">
                  <h3>实体类型提取</h3>
                  <el-tag type="info" size="small">
                    {{ isExtractingEntityTypes
                      ? 'AI 正在提取，可实时编辑已生成部分'
                      : (entityTypes.length ? 'AI 已提取以下实体类型，可编辑确认' : '可启动 AI 提取') }}
                  </el-tag>
                </div>
                <el-button
                  v-if="entityTypes.length || job?.step1_confirmed"
                  size="small"
                  type="warning"
                  plain
                  :icon="Refresh"
                  :disabled="isRunning || submitting"
                  @click="openRework(1)"
                >
                  返工重建
                </el-button>
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
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续提取"重试，无需修改任何配置。</p>
                  <p>点击"继续提取实体类型"从失败批次续跑，已成功批次不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractEntityTypes">
                  继续提取实体类型
                </el-button>
              </div>
            </div>

            <!-- 未开始提取 -->
            <div v-else-if="!isExtractingEntityTypes && !entityTypes.length" class="extract-section">
              <el-alert
                title="点击按钮启动实体类型提取"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将从文档提取 EntityType 层级（含父类型 parent_entity_type_name）、属性骨架 property_schema，以及类型间关系 EntityTypeRelation。</p>
                  <p v-if="metaForm.templateId && metaForm.templateMode === 'skip_step1'" class="llm-hint">
                    已选择模板「{{ selectedTemplateName }}」并设为"跳过实体类型提取"，将直接使用模板中的实体类型，无需调用 LLM。
                  </p>
                  <p v-else-if="metaForm.templateId" class="llm-hint">
                    已选择模板「{{ selectedTemplateName }}」作为软约束，AI 提取时会参考模板。
                  </p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractEntityTypes">
                  {{ (metaForm.templateId && metaForm.templateMode === 'skip_step1') ? '从模板加载实体类型' : '开始提取实体类型' }}
                </el-button>
              </div>
            </div>

            <!-- 提取中/已完成审核 -->
            <div v-else class="entity-types-section">
              <el-alert
                v-if="isExtractingEntityTypes"
                :title="batch1ProgressText"
                type="info"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />
              <el-alert
                v-else
                title="实体类型提取完成，请审核确认"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />

              <!-- 实体类型树（按 parent_entity_type_name 层级） -->
              <div class="entity-types-block">
                <h4>实体类型层级（{{ entityTypes.length }} 个）</h4>
                <el-tree
                  :data="entityTypeTree"
                  node-key="name"
                  default-expand-all
                  :expand-on-click-node="false"
                  :props="{ label: 'name', children: 'children' }"
                >
                  <template #default="{ data }">
                    <div class="et-tree-node">
                      <span class="et-tree-dot" :style="{ background: data.color || '#5470c6' }"></span>
                      <span class="et-tree-name">{{ data.name || '(未命名)' }}</span>
                      <el-tag size="small" type="info" v-if="data.parent_entity_type_name">
                        父：{{ data.parent_entity_type_name }}
                      </el-tag>
                      <span class="et-tree-desc" v-if="data.description">{{ data.description }}</span>
                      <el-button size="small" link type="danger" @click.stop="removeEntityType(data)">
                        删除
                      </el-button>
                    </div>
                  </template>
                </el-tree>
              </div>

              <!-- 属性骨架表格 -->
              <div class="property-schema-block">
                <h4>属性骨架（property_schema）</h4>
                <el-table :data="entityTypes" stripe size="small" style="width: 100%">
                  <el-table-column prop="name" label="类型名" width="140">
                    <template #default="scope">
                      <el-input v-model="scope.row.name" size="small" />
                    </template>
                  </el-table-column>
                  <el-table-column prop="color" label="颜色" width="70">
                    <template #default="scope">
                      <el-color-picker v-model="scope.row.color" size="small" />
                    </template>
                  </el-table-column>
                  <el-table-column prop="parent_entity_type_name" label="父类型" width="140">
                    <template #default="scope">
                      <el-select
                        v-model="scope.row.parent_entity_type_name"
                        size="small"
                        clearable
                        placeholder="顶层类型"
                      >
                        <el-option
                          v-for="t in entityTypes.filter(x => x.name !== scope.row.name)"
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
                  <el-table-column prop="property_schema" label="属性骨架（JSON）" min-width="260">
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
                  <el-table-column label="操作" width="70" fixed="right">
                    <template #default="scope">
                      <el-button size="small" link type="danger" @click="entityTypes.splice(scope.$index, 1)">
                        删除
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div class="step-actions" style="margin-top: 0.5rem">
                  <el-button size="small" @click="addEntityType">
                    + 添加实体类型
                  </el-button>
                </div>
              </div>

              <!-- 类型间关系列表 -->
              <div class="entity-type-relations-block">
                <h4>类型间关系（{{ entityTypeRelations.length }} 条）</h4>
                <el-table :data="entityTypeRelations" stripe size="small" style="width: 100%">
                  <el-table-column prop="source_type" label="源类型" width="160">
                    <template #default="scope">
                      <el-select v-model="scope.row.source_type" size="small" filterable>
                        <el-option
                          v-for="t in entityTypes"
                          :key="t.name"
                          :label="t.name"
                          :value="t.name"
                        />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column prop="relation_type" label="关系类型" width="160">
                    <template #default="scope">
                      <el-input v-model="scope.row.relation_type" size="small" placeholder="如：包含/属于" />
                    </template>
                  </el-table-column>
                  <el-table-column prop="target_type" label="目标类型" width="160">
                    <template #default="scope">
                      <el-select v-model="scope.row.target_type" size="small" filterable>
                        <el-option
                          v-for="t in entityTypes"
                          :key="t.name"
                          :label="t.name"
                          :value="t.name"
                        />
                      </el-select>
                    </template>
                  </el-table-column>
                  <el-table-column prop="description" label="说明" min-width="200">
                    <template #default="scope">
                      <el-input v-model="scope.row.description" size="small" />
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="70" fixed="right">
                    <template #default="scope">
                      <el-button size="small" link type="danger" @click="entityTypeRelations.splice(scope.$index, 1)">
                        删除
                      </el-button>
                    </template>
                  </el-table-column>
                </el-table>
                <div class="step-actions" style="margin-top: 0.5rem">
                  <el-button size="small" @click="entityTypeRelations.push({ source_type: entityTypes[0]?.name || '', relation_type: '', target_type: '', description: '' })">
                    + 添加类型间关系
                  </el-button>
                </div>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep1Done || job?.step1_confirmed"
                  @click="doConfirmEntityTypes"
                >
                  {{ job?.step1_confirmed ? '已确认' : (aiStep1Done ? '确认实体类型' : 'AI 提取中（可先编辑已生成部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 2: 实体 + 关系提取 -->
        <div v-if="currentStep === 2" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <div class="step-header-title">
                  <h3>实体 + 关系提取</h3>
                  <el-tag type="info" size="small">
                    {{ isExtractingEntities
                      ? 'AI 正在提取，可实时编辑已生成部分'
                      : (entities.length || relations.length ? 'AI 已提取以下实体与关系，可编辑确认' : '可启动 AI 提取') }}
                  </el-tag>
                </div>
                <el-button
                  v-if="entities.length || relations.length || job?.step2_confirmed"
                  size="small"
                  type="warning"
                  plain
                  :icon="Refresh"
                  :disabled="isRunning || submitting"
                  @click="openRework(2)"
                >
                  返工重建
                </el-button>
              </div>
            </template>

            <!-- 提取中途失败，可断点续作 -->
            <div v-if="isStep2Resumable" class="build-section">
              <el-alert
                :title="`第 ${job.step2_failed_batch + 1}/${job.step2_batches_total} 批提取失败，已成功 ${job.step2_batches_done} 批`"
                type="warning"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>{{ job?.error_message || '部分批次提取失败' }}</p>
                  <p v-if="isEmptyResponseError" class="llm-hint">LLM 服务端偶发无响应，请点击"继续提取"重试，无需修改任何配置。</p>
                  <p>点击"继续提取"从失败批次续跑，已成功批次不会重跑。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractEntities">
                  继续提取
                </el-button>
              </div>
            </div>

            <!-- 未开始提取 -->
            <div v-else-if="!isExtractingEntities && !entities.length && !relations.length" class="build-section">
              <el-alert
                title="点击按钮启动实体+关系提取"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将基于已确认的实体类型，从文档提取具体 Entity 实例（按 property_schema 填充属性）和 Relation 实例间关系。</p>
                  <p>长文档会分批提取，每批完成后实时显示在下方表格中。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doExtractEntities">
                  开始提取
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
                title="实体+关系提取完成，请审核确认"
                type="success"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />

              <!-- 实体列表（按类型分组 el-collapse） -->
              <div class="entity-view-controls">
                <h4 style="margin: 0">实体列表（{{ entities.length }} 个，{{ entityTypeGroups.length }} 个类型）</h4>
                <el-radio-group v-model="entityViewMode" size="small">
                  <el-radio-button value="grouped">按类型分组</el-radio-button>
                  <el-radio-button value="flat">平铺表格</el-radio-button>
                </el-radio-group>
                <el-button
                  v-if="entityViewMode === 'grouped'"
                  size="small"
                  link
                  @click="toggleAllEntityTypes"
                >
                  {{ allEntityTypesExpanded ? '全部收起' : '全部展开' }}
                </el-button>
              </div>

              <!-- 分组视图 -->
              <div v-if="entityViewMode === 'grouped'" class="entity-grouped-view">
                <el-collapse v-model="expandedEntityTypeNames">
                  <el-collapse-item
                    v-for="g in entityTypeGroups"
                    :key="g.typeName"
                    :name="g.typeName"
                  >
                    <template #title>
                      <span class="concept-dot" :style="{ background: g.color || '#5470c6' }"></span>
                      <span class="concept-name">{{ g.typeName }}</span>
                      <el-tag size="small" type="info">{{ g.entities.length }} 个实体</el-tag>
                    </template>
                    <el-table :data="g.entities" stripe size="small" style="width: 100%">
                      <el-table-column prop="name" label="名称" width="160">
                        <template #default="scope">
                          <el-input v-model="scope.row.name" size="small" />
                        </template>
                      </el-table-column>
                      <el-table-column prop="properties" label="属性（JSON）" min-width="260">
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
                      <el-table-column prop="source_snippet" label="原文出处" min-width="160">
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
                      <el-table-column label="操作" width="70">
                        <template #default="scope">
                          <el-button size="small" link type="danger" @click="removeEntityFromGroup(g, scope.$index)">
                            删除
                          </el-button>
                        </template>
                      </el-table-column>
                    </el-table>
                    <el-button size="small" @click="addEntityToType(g.typeName)" style="margin-top: 0.5rem">
                      + 添加实体到此类型
                    </el-button>
                  </el-collapse-item>
                </el-collapse>
              </div>

              <!-- 平铺视图 -->
              <el-table v-else :data="entities" stripe style="width: 100%; margin-bottom: 1.5rem">
                <el-table-column prop="name" label="名称" width="140">
                  <template #default="scope">
                    <el-input v-model="scope.row.name" size="small" />
                  </template>
                </el-table-column>
                <el-table-column prop="instance_of" label="所属类型" width="160">
                  <template #default="scope">
                    <el-select v-model="scope.row.instance_of" size="small" filterable>
                      <el-option
                        v-for="t in entityTypes"
                        :key="t.name"
                        :label="t.name"
                        :value="t.name"
                      />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column prop="properties" label="属性（JSON）" min-width="260">
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

              <div v-if="entityViewMode === 'flat'" class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="entities.push({ name: '', instance_of: entityTypes[0]?.name || '', propertiesStr: '[]', source_snippet: '' })">
                  + 添加实体
                </el-button>
              </div>

              <!-- 关系列表 -->
              <h4 style="margin-top: 1.5rem">关系列表（{{ relations.length }} 条）</h4>
              <el-table :data="relations" stripe size="small" style="width: 100%; margin-bottom: 1rem">
                <el-table-column prop="source" label="源实体" width="160">
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
                <el-table-column prop="relation_type" label="关系类型" width="140">
                  <template #default="scope">
                    <el-input v-model="scope.row.relation_type" size="small" placeholder="如：投资/任职" />
                  </template>
                </el-table-column>
                <el-table-column prop="target" label="目标实体" width="160">
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
                <el-table-column prop="weight" label="权重" width="100">
                  <template #default="scope">
                    <el-input-number v-model="scope.row.weight" size="small" :min="0" :max="1" :step="0.1" controls-position="right" />
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
                    <el-button size="small" link type="danger" @click="relations.splice(scope.$index, 1)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
              <div class="step-actions" style="margin-top: 0">
                <el-button size="small" @click="relations.push({ source: entities[0]?.name || '', target: '', relation_type: '', weight: 1.0, source_snippet: '' })">
                  + 添加关系
                </el-button>
              </div>

              <div class="step-actions">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="!aiStep2Done || job?.step2_confirmed"
                  @click="doConfirmEntities"
                >
                  {{ job?.step2_confirmed ? '已确认' : (aiStep2Done ? '确认实体+关系' : 'AI 提取中（可先编辑已生成部分）...') }}
                </el-button>
              </div>
            </div>
          </el-card>
        </div>

        <!-- Step 3: 验证 + 报告 -->
        <div v-if="currentStep === 3" class="step-panel">
          <el-card class="step-card">
            <template #header>
              <div class="step-header">
                <div class="step-header-title">
                  <h3>验证 + 报告</h3>
                  <el-tag type="info" size="small">
                    {{ isVerifying ? 'AI 正在做自检验证...' : (job?.step3_verification ? '验证完成' : '可启动验证') }}
                  </el-tag>
                </div>
                <el-button
                  v-if="job?.step3_verification || job?.step3_report"
                  size="small"
                  type="warning"
                  plain
                  :icon="Refresh"
                  :disabled="isRunning || submitting"
                  @click="openRework(3)"
                >
                  返工重建
                </el-button>
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
            <div v-else-if="!job?.step3_verification && job?.status !== 'completed'" class="generate-section">
              <el-alert
                title="点击按钮启动 LLM 自检验证"
                type="info"
                :closable="false"
                show-icon
              >
                <template #default>
                  <p>AI 将逐项检查实体/属性/关系是否可溯源到原文，标记存疑项，并生成一份 markdown 结构化简报。</p>
                </template>
              </el-alert>
              <div class="step-actions">
                <el-button type="primary" :disabled="isRunning" @click="doVerify">
                  启动验证
                </el-button>
              </div>
            </div>

            <!-- 验证完成 -->
            <div v-else-if="job?.step3_verification" class="verify-section">
              <el-alert
                :title="`验证完成：${job.step3_verification.verified_count || 0} 项通过，${job.step3_verification.suspect_count || 0} 项存疑`"
                :type="(job.step3_verification.suspect_count || 0) > 0 ? 'warning' : 'success'"
                :closable="false"
                show-icon
                style="margin-bottom: 1rem"
              />

              <!-- 存疑项列表 -->
              <div v-if="job.step3_verification.suspects?.length" class="suspects-block">
                <h4>存疑项（{{ job.step3_verification.suspects.length }} 条）</h4>
                <el-table :data="job.step3_verification.suspects" stripe size="small" style="width: 100%; margin-bottom: 1.5rem">
                  <el-table-column prop="item_type" label="类型" width="90" />
                  <el-table-column prop="item_id" label="标识" width="160" />
                  <el-table-column prop="reason" label="存疑原因" min-width="280" />
                </el-table>
              </div>

              <!-- 简报 -->
              <div v-if="job.step3_report" class="report-block">
                <h4>生成简报（markdown）</h4>
                <div class="report-content">{{ job.step3_report }}</div>
              </div>

              <!-- 确认生成最终本体 -->
              <div class="step-actions" v-if="job?.status !== 'completed'">
                <el-button @click="goBack">取消</el-button>
                <el-button
                  type="primary"
                  :loading="submitting"
                  :disabled="job?.step3_confirmed"
                  @click="doConfirmVerification"
                >
                  {{ job?.step3_confirmed ? '本体已生成' : '确认并生成最终本体' }}
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

      <!-- 返工对话框（v3 新增：每步可重新调用 LLM 重建） -->
      <el-dialog
        v-model="reworkDialogVisible"
        :title="`返工 step${reworkTargetStep} — 重新调用 LLM 重建`"
        width="560px"
        :close-on-click-modal="false"
      >
        <el-alert
          :title="`返工将清空 step${reworkTargetStep} 的现有结果并重新调用 LLM 重建，后续已确认的步骤也需要重新执行。`"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 1rem"
        />
        <el-form label-width="100px">
          <el-form-item label="新提示词">
            <el-input
              v-model="reworkPrompt"
              type="textarea"
              :rows="5"
              :placeholder="reworkPlaceholders[reworkTargetStep] || '请输入对当前步骤的补充说明或修改要求'"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="reworkDialogVisible = false">取消</el-button>
          <el-button
            type="primary"
            :loading="reworkSubmitting"
            @click="doRework"
          >
            开始返工
          </el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, CircleCheck, Loading, Close, Check, Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'
import {
  getBuildJob,
  getBuildProgress,
  confirmMeta as confirmMetaApi,
  streamBuildJob
} from '@/services/ontologyBuild'
import { reworkBuildStep } from '@/services/ontology'
import { getTemplateList } from '@/services/ontologyTemplate'

const route = useRoute()
const router = useRouter()
const jobId = route.params.jobId as string

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)

const job = ref<any>(null)
const entityTypes = ref<any[]>([])          // v3: step1_entity_types（含 parent_entity_type_name / property_schema）
const entityTypeRelations = ref<any[]>([])  // v3: step1_entity_type_relations
const entities = ref<any[]>([])             // v3: step2_entities（含 properties 属性赋值）
const relations = ref<any[]>([])            // v3: step2_relations
const templates = ref<any[]>([])            // step0 可选模板列表

// ── 实体视图：按类型分组（默认折叠隐藏实体实例）/ 平铺表格 ──
const entityViewMode = ref<'grouped' | 'flat'>('grouped')
const expandedEntityTypeNames = ref<string[]>([])

// ── step0 配置表单（v3：粒度 + 阶段提示词 + 可选模板） ──
const metaForm = ref({
  granularity: 'medium' as 'coarse' | 'medium' | 'fine',
  stageHints: { 1: '', 2: '', 3: '' } as Record<number, string>,
  templateId: '' as string,
  templateMode: 'soft_constraint' as 'skip_step1' | 'soft_constraint'
})

const stageHintLabels: Record<number, string> = {
  1: '实体类型提示',
  2: '实体+关系提示',
  3: '验证提示'
}

const selectedTemplateName = computed(() => {
  const t = templates.value.find(t => t.id === metaForm.value.templateId)
  return t?.name || ''
})

// AI 各阶段完成标记（收到 SSE step_done 后置 true，启用"确认"按钮）
const aiStep1Done = ref(false)
const aiStep2Done = ref(false)

// 轮询定时器（step3 验证用轮询；SSE 不可用时降级）
let pollTimer: ReturnType<typeof setInterval> | null = null
let sseAbort: (() => void) | null = null
let streamRetryCount = 0
const STREAM_MAX_RETRY = 3

// ── 返工对话框状态（v3 新增） ──
const reworkDialogVisible = ref(false)
const reworkTargetStep = ref(1)
const reworkPrompt = ref('')
const reworkSubmitting = ref(false)
const reworkPlaceholders: Record<number, string> = {
  1: '例如：增加"风险事件"实体类型；细化财务指标的属性骨架',
  2: '例如：补充关联交易实体；只保留前 20 大股东的关联关系',
  3: '例如：重点关注资产负债率与现金流是否可溯源'
}

// ── 实体类型树（按 parent_entity_type_name 构建层级） ──
const entityTypeTree = computed(() => {
  const map = new Map<string, any>()
  const nodes = entityTypes.value.map(t => ({
    ...t,
    children: [] as any[]
  }))
  for (const n of nodes) map.set(n.name, n)
  const roots: any[] = []
  for (const n of nodes) {
    const parentName = n.parent_entity_type_name
    if (parentName && map.has(parentName)) {
      map.get(parentName).children.push(n)
    } else {
      roots.push(n)
    }
  }
  return roots
})

// ── 实体按类型分组（v3 step2 展示） ──
const entityTypeGroups = computed(() => {
  const groups: any[] = []
  for (const t of entityTypes.value) {
    const list = entities.value.filter(e => e.instance_of === t.name)
    if (list.length) {
      groups.push({ typeName: t.name, color: t.color, entities: list })
    }
  }
  // 未分类实体：instance_of 不在实体类型清单中
  const known = new Set(entityTypes.value.map(t => t.name))
  const unclassified = entities.value.filter(e => !known.has(e.instance_of))
  if (unclassified.length) {
    groups.push({ typeName: '未分类', color: '#909399', entities: unclassified })
  }
  return groups
})

const allEntityTypesExpanded = computed(
  () => entityTypeGroups.value.length > 0
    && entityTypeGroups.value.every(g => expandedEntityTypeNames.value.includes(g.typeName))
)

const toggleAllEntityTypes = () => {
  if (allEntityTypesExpanded.value) {
    expandedEntityTypeNames.value = []
  } else {
    expandedEntityTypeNames.value = entityTypeGroups.value.map(g => g.typeName)
  }
}

const addEntityType = () => {
  entityTypes.value.push({
    name: '',
    description: '',
    color: '#5470c6',
    property_schema: [],
    propertySchemaStr: '[]',
    parent_entity_type_name: ''
  })
}

const removeEntityType = (data: any) => {
  const idx = entityTypes.value.findIndex(t => t === data || t.name === data.name)
  if (idx >= 0) entityTypes.value.splice(idx, 1)
}

const addEntityToType = (typeName: string) => {
  entities.value.push({
    name: '', instance_of: typeName,
    propertiesStr: '[]', source_snippet: ''
  })
}

const removeEntityFromGroup = (group: any, index: number) => {
  const entity = group.entities[index]
  const idx = entities.value.indexOf(entity)
  if (idx >= 0) entities.value.splice(idx, 1)
}

// ── 计算属性 ──
// v3 step 状态映射：0=待开始, 1=实体类型, 2=实体+关系, 3=验证报告, 4=已完成
const currentStep = computed(() => {
  if (!job.value) return 0
  if (job.value.status === 'completed' || job.value.step3_confirmed) return 4
  if (job.value.step2_confirmed) return 3   // 进入验证阶段
  if (job.value.step1_confirmed) return 2   // 实体+关系提取
  if (job.value.meta_confirmed) return 1    // 实体类型提取
  return 0
})

// v3 running_step：-1=空闲, 1=实体类型提取, 2=实体+关系, 3=验证
const isRunning = computed(() => {
  const rs = job.value?.running_step
  return rs !== undefined && rs >= 1 && rs <= 3
})
const isExtractingEntityTypes = computed(() => job.value?.running_step === 1)
const isExtractingEntities = computed(() => job.value?.running_step === 2)
const isVerifying = computed(() => job.value?.running_step === 3)

const progressMessage = computed(() => {
  if (!job.value) return ''
  const msgs: Record<number, string> = {
    1: job.value.progress_message || '正在提取实体类型...',
    2: job.value.progress_message || '正在提取实体+关系...',
    3: job.value.progress_message || '正在验证+生成报告...'
  }
  return msgs[job.value.running_step] || job.value.progress_message || ''
})

const currentProgressPercent = computed(() => job.value?.progress ?? 0)

// 空响应错误：LLM 服务端偶发无响应（非配置/代码问题），提示用户重试即可
const isEmptyResponseError = computed(() =>
  !!job.value?.error_message && job.value.error_message.includes('空响应')
)

// ── 阶段时间线（progress_stages 真实进度，3 个 LLM 阶段） ──
const hasStageTimeline = computed(() => {
  const stages = job.value?.progress_stages || []
  return stages.length > 0
})

const stageTimeline = computed(() => {
  const defaultStages = [
    { stage: 1, name: '实体类型', status: 'pending', elapsed: '' },
    { stage: 2, name: '实体+关系', status: 'pending', elapsed: '' },
    { stage: 3, name: '验证报告', status: 'pending', elapsed: '' }
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
  if (!j) return 'AI 正在提取实体类型...'
  const done = entityTypes.value.length
  if (j.step1_batches_total > 1) {
    return `AI 正在提取实体类型（第 ${j.step1_batches_done + 1}/${j.step1_batches_total} 批），已提取 ${done} 个`
  }
  return `AI 正在提取实体类型，已提取 ${done} 个`
})

const batch2ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在提取实体+关系...'
  const done = entities.value.length
  if (j.step2_batches_total > 1) {
    return `AI 正在提取实体+关系（第 ${j.step2_batches_done + 1}/${j.step2_batches_total} 批），已提取 ${done} 个实体/${relations.value.length} 条关系`
  }
  return `AI 正在提取实体+关系，已提取 ${done} 个实体/${relations.value.length} 条关系`
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

    // 恢复配置：粒度 + 阶段提示词 + 模板
    if (job.value.granularity) {
      metaForm.value.granularity = job.value.granularity
    }
    if (job.value.stage_hints && typeof job.value.stage_hints === 'object') {
      metaForm.value.stageHints = { 1: '', 2: '', 3: '', ...job.value.stage_hints }
    }
    if (job.value.template_id) {
      metaForm.value.templateId = job.value.template_id
      metaForm.value.templateMode = job.value.template_mode || 'soft_constraint'
    }

    // 恢复实体类型清单（v3: step1_entity_types）
    if (job.value.step1_entity_types?.length) {
      entityTypes.value = job.value.step1_entity_types.map((t: any) => ({
        ...t,
        propertySchemaStr: JSON.stringify(t.property_schema || [], null, 0)
      }))
    } else {
      entityTypes.value = []
    }

    // 恢复实体类型间关系（v3: step1_entity_type_relations）
    if (job.value.step1_entity_type_relations?.length) {
      entityTypeRelations.value = JSON.parse(JSON.stringify(job.value.step1_entity_type_relations))
    } else {
      entityTypeRelations.value = []
    }

    // 恢复实体清单（v3: step2_entities）
    if (job.value.step2_entities?.length) {
      entities.value = job.value.step2_entities.map((e: any) => ({
        ...e,
        propertiesStr: JSON.stringify(e.properties || [], null, 0)
      }))
    } else {
      entities.value = []
    }

    // 恢复关系清单（v3: step2_relations，原 step3_relations 已合并到 step2）
    if (job.value.step2_relations?.length) {
      relations.value = JSON.parse(JSON.stringify(job.value.step2_relations))
    } else {
      relations.value = []
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载任务失败')
  }
}

// 加载模板列表（step0 可选）
const loadTemplates = async () => {
  try {
    const res: any = await getTemplateList()
    templates.value = res.data || []
  } catch {
    // 静默失败：模板为可选配置，加载失败不阻断主流程
  }
}

// ── 轮询进度（step3 验证用；SSE 降级时也用） ──
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
  job.value.ontology_id = p.ontology_id
  // 分批状态
  job.value.step1_batches_total = p.step1_batches_total
  job.value.step1_batches_done = p.step1_batches_done
  job.value.step1_failed_batch = p.step1_failed_batch
  job.value.step2_batches_total = p.step2_batches_total
  job.value.step2_batches_done = p.step2_batches_done
  job.value.step2_failed_batch = p.step2_failed_batch
  // 验证结果（v3: step3_verification / step3_report）
  job.value.step3_verification = p.step3_verification
  job.value.step3_report = p.step3_report
  // 真实进度时间线
  job.value.progress_stages = p.progress_stages
}

// ── SSE 实时订阅（step1/step2 批次级增量推送） ──
// step1 推 batch_done 携带 entity_types / entity_type_relations
// step2 推 batch_done 携带 entities / relations
// step_done 在每步 AI 全部完成时触发，覆盖最终结果

/** 名称归一化（与后端 _normalize_name 一致）：用于按名称去重 */
const _normName = (name: string) =>
  (name || '').trim().replace(/（/g, '(').replace(/）/g, ')').replace(/\u3000/g, ' ')

/** 关系三元组去重 key */
const _relKey = (r: any) => `${_normName(r.source)}|${r.relation_type}|${_normName(r.target)}`

/** 类型间关系三元组去重 key */
const _etRelKey = (r: any) =>
  `${_normName(r.source_type)}|${r.relation_type}|${_normName(r.target_type)}`

const startStream = () => {
  console.log('[Stream] startStream, jobId=', jobId)
  stopStream()
  stopPolling()
  streamRetryCount = 0
  sseAbort = streamBuildJob(jobId, {
    onBatchDone: (d) => {
      // step1：实体类型按名称去重追加
      if (Array.isArray(d.entity_types)) {
        const existing = new Set(entityTypes.value.map(t => _normName(t.name)).filter(Boolean))
        const fresh = (d.entity_types || []).filter((t: any) => {
          const n = _normName(t.name)
          if (!n || existing.has(n)) return false
          existing.add(n)
          return true
        }).map((t: any) => ({
          ...t,
          propertySchemaStr: JSON.stringify(t.property_schema || [], null, 0)
        }))
        entityTypes.value.push(...fresh)
        if (job.value) {
          job.value.step1_batches_done = d.batches_done
          job.value.step1_batches_total = d.batches_total
        }
      }
      // step1：类型间关系增量追加
      if (Array.isArray(d.entity_type_relations)) {
        const existRel = new Set(entityTypeRelations.value.map(_etRelKey))
        const fresh = (d.entity_type_relations || []).filter((r: any) => {
          const k = _etRelKey(r)
          if (existRel.has(k)) return false
          existRel.add(k)
          return true
        })
        entityTypeRelations.value.push(...fresh)
      }
      // step2：实体按名称去重追加
      if (Array.isArray(d.entities)) {
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
      // step2：关系增量追加
      if (Array.isArray(d.relations)) {
        const existRel = new Set(relations.value.map(_relKey))
        const fresh = (d.relations || []).filter((r: any) => {
          const k = _relKey(r)
          if (existRel.has(k)) return false
          existRel.add(k)
          return true
        })
        relations.value.push(...fresh)
      }
    },
    onStepDone: (d) => {
      // AI 全部完成，启用对应"确认"按钮，并用后端权威数据覆盖
      if (d.step === 1) {
        aiStep1Done.value = true
        if (job.value) job.value.running_step = -1
        if (Array.isArray(d.entity_types)) {
          entityTypes.value = d.entity_types.map((t: any) => ({
            ...t,
            propertySchemaStr: JSON.stringify(t.property_schema || [], null, 0)
          }))
        }
        if (Array.isArray(d.entity_type_relations)) {
          entityTypeRelations.value = JSON.parse(JSON.stringify(d.entity_type_relations))
        }
        ElMessage.success(`实体类型提取完成，共 ${entityTypes.value.length} 个`)
      } else if (d.step === 2) {
        aiStep2Done.value = true
        if (job.value) job.value.running_step = -1
        if (Array.isArray(d.entities)) {
          entities.value = d.entities.map((e: any) => ({
            ...e,
            propertiesStr: JSON.stringify(e.properties || [], null, 0)
          }))
        }
        if (Array.isArray(d.relations)) {
          relations.value = JSON.parse(JSON.stringify(d.relations))
        }
        ElMessage.success(`实体+关系提取完成，共 ${entities.value.length} 个实体/${relations.value.length} 条关系`)
      } else if (d.step === 3) {
        if (job.value) {
          job.value.running_step = -1
          if (d.verification) job.value.step3_verification = d.verification
          if (d.report !== undefined) job.value.step3_report = d.report
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
// step0：确认配置（粒度 + 阶段提示词 + 模板）
const doConfirmMeta = async () => {
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('granularity', metaForm.value.granularity)
    // 阶段提示词（只传非空）
    const hints: Record<string, string> = {}
    for (const k of Object.keys(metaForm.value.stageHints)) {
      const v = (metaForm.value.stageHints as any)[k]
      if (v && String(v).trim()) hints[k] = String(v).trim()
    }
    fd.append('stage_hints', JSON.stringify(hints))
    // 模板配置（可选）
    if (metaForm.value.templateId) {
      fd.append('template_id', metaForm.value.templateId)
      fd.append('template_mode', metaForm.value.templateMode)
    }

    await confirmMetaApi(jobId, fd)
    ElMessage.success('配置已确认，可执行实体类型提取')
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

// step1：启动实体类型提取（POST /ontology/build/{jobId}/step1）
const doExtractEntityTypes = async () => {
  try {
    await api.post(`/ontology/build/${jobId}/step1`)
    if (job.value) {
      job.value.running_step = 1
      job.value.progress_message = '正在准备文档...'
    }
    aiStep1Done.value = false
    ElMessage.info('实体类型提取已在后台开始，可实时查看提取结果')
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

// step1：确认实体类型 + 类型间关系（PUT /ontology/build/{jobId}/step1）
const doConfirmEntityTypes = async () => {
  submitting.value = true
  try {
    // 解析 propertySchemaStr 回数组
    const parsedTypes = entityTypes.value.map(t => {
      let schema: any = []
      try {
        schema = JSON.parse(t.propertySchemaStr || '[]')
      } catch {
        schema = []
      }
      const { propertySchemaStr, ...rest } = t
      return { ...rest, property_schema: schema }
    })
    const fd = new FormData()
    fd.append('entity_types', JSON.stringify(parsedTypes))
    fd.append('entity_type_relations', JSON.stringify(entityTypeRelations.value))
    await api.put(`/ontology/build/${jobId}/step1`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('实体类型已确认，可执行实体+关系提取')
    stopStream()
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

// step2：启动实体+关系提取（POST /ontology/build/{jobId}/step2）
const doExtractEntities = async () => {
  try {
    await api.post(`/ontology/build/${jobId}/step2`)
    if (job.value) {
      job.value.running_step = 2
      job.value.progress_message = '正在提取实体+关系...'
    }
    aiStep2Done.value = false
    ElMessage.info('实体+关系提取已在后台开始，可实时查看提取结果')
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

// step2：确认实体 + 关系（PUT /ontology/build/{jobId}/step2）
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
    const fd = new FormData()
    fd.append('entities', JSON.stringify(parsedEntities))
    fd.append('relations', JSON.stringify(relations.value))
    await api.put(`/ontology/build/${jobId}/step2`, fd, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('实体+关系已确认，可执行验证')
    stopStream()
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

// step3：启动验证（POST /ontology/build/{jobId}/step3）
const doVerify = async () => {
  try {
    await api.post(`/ontology/build/${jobId}/step3`)
    if (job.value) {
      job.value.running_step = 3
      job.value.progress_message = '正在验证+生成报告...'
    }
    ElMessage.info('验证已在后台开始，您可以离开页面')
    startPolling()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动验证失败')
  }
}

// step3：确认验证结果，生成正式本体（PUT /ontology/build/{jobId}/step3）
const doConfirmVerification = async () => {
  submitting.value = true
  try {
    await api.put(`/ontology/build/${jobId}/step3`)
    ElMessage.success('本体已生成')
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '生成失败')
  } finally {
    submitting.value = false
  }
}

// ── 返工（v3 新增） ──
const openRework = (step: number) => {
  reworkTargetStep.value = step
  reworkPrompt.value = ''
  reworkDialogVisible.value = true
}

const doRework = async () => {
  reworkSubmitting.value = true
  try {
    const fd = new FormData()
    fd.append('prompt', reworkPrompt.value || '')
    await reworkBuildStep(jobId, reworkTargetStep.value, fd)
    ElMessage.success(`step${reworkTargetStep.value} 返工已开始，结果将被替换`)
    reworkDialogVisible.value = false
    // 返工后该步结果被替换：重新加载任务状态，并按 running_step 启动 SSE/轮询
    await loadJob()
    const rs = job.value?.running_step
    if (rs >= 1 && rs <= 2) {
      // step1/step2 返工走 SSE
      aiStep1Done.value = rs < 1
      aiStep2Done.value = rs < 2
      // 清空当前步缓存（后端会重新生成）
      if (rs === 1) {
        entityTypes.value = []
        entityTypeRelations.value = []
      } else if (rs === 2) {
        entities.value = []
        relations.value = []
      }
      startStream()
    } else if (rs === 3) {
      // step3 返工走轮询
      job.value.step3_verification = null
      job.value.step3_report = null
      startPolling()
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '返工失败')
  } finally {
    reworkSubmitting.value = false
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
  // 模板列表与任务详情可并行加载
  await Promise.all([loadJob(), loadTemplates()])
  loading.value = false

  // 恢复 AI 完成标记（断线重连/刷新页面恢复场景：已提取但未确认）
  if (job.value?.step1_entity_types?.length && !job.value?.step1_confirmed) {
    aiStep1Done.value = true
  }
  if (job.value?.step2_entities?.length && !job.value?.step2_confirmed) {
    aiStep2Done.value = true
  }

  // 若有后台任务在运行：step1/step2 用 SSE 实时推送，step3（验证）用轮询
  const rs = job.value?.running_step
  if (rs >= 1 && rs <= 2) {
    startStream()
  } else if (rs === 3) {
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

/* 阶段时间线：3 个 LLM 阶段的真实状态 */
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

.step-header-title {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.step-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 600;
  color: var(--text-primary);
}

/* 粒度 + 模板 + 阶段提示词 */
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
  flex-wrap: wrap;
}

.template-row {
  flex-wrap: wrap;
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

.entity-types-section,
.structure-section {
  padding: 0.5rem 0;
}

.entity-types-section h4,
.structure-section h4 {
  margin: 1.5rem 0 0.75rem 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
}

/* 实体类型树 */
.entity-types-block {
  margin-bottom: 1.5rem;
}

.entity-types-block :deep(.el-tree) {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  padding: 0.75rem;
  border: 1px solid var(--border-color, #e4e7ed);
}

.entity-types-block :deep(.el-tree-node__content) {
  height: auto;
  min-height: 32px;
  padding: 0.25rem 0;
}

.et-tree-node {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  padding: 0.25rem 0;
  flex-wrap: wrap;
}

.et-tree-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.et-tree-name {
  font-weight: 600;
  color: var(--text-primary);
}

.et-tree-desc {
  color: var(--text-secondary);
  font-size: 0.8rem;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.property-schema-block,
.entity-type-relations-block {
  margin-bottom: 1.5rem;
}

/* 实体视图控制栏 */
.entity-view-controls {
  display: flex;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1rem;
  flex-wrap: wrap;
}

/* 实体分组视图 */
.entity-grouped-view {
  margin-bottom: 1.5rem;
}

.entity-grouped-view .concept-dot {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 0.5rem;
  flex-shrink: 0;
}

.entity-grouped-view .concept-name {
  font-weight: 600;
  margin-right: 0.4rem;
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
