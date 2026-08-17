<template>
  <Layout>
    <div class="ontology-build">
      <!-- 顶部 Header -->
      <div class="build-header">
        <div class="header-left">
          <el-button @click="goBack" :icon="ArrowLeft">返回</el-button>
          <h2>文档构建：{{ job?.name || '加载中...' }}</h2>
          <el-tag v-if="job" :type="getStatusType(job.status)" size="small">
            {{ getStatusText(job.status) }}
          </el-tag>
          <el-tag v-if="job?.ontology_id" type="success" size="small">已生成本体</el-tag>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" @click="refreshAll">刷新</el-button>
          <el-button @click="docCollapsed = !docCollapsed">
            {{ docCollapsed ? '展开原文' : '收起原文' }}
          </el-button>
        </div>
      </div>

      <!-- 状态栏：步骤条（含阶段耗时，可回看已确认步骤） -->
      <div class="status-bar" v-if="job">
        <el-steps :active="currentStep" finish-status="process" process-status="process" align-center class="build-steps">
          <el-step
            title="文档解析"
            :status="getStepStatus(0)"
            :class="{ 'step-clickable': stepClickable(0) }"
            @click="jumpToStep(0)"
          >
            <template #description>{{ stepDesc(0) }}</template>
          </el-step>
          <el-step
            title="本体提取"
            :status="getStepStatus(1)"
            :class="{ 'step-clickable': stepClickable(1) }"
            @click="jumpToStep(1)"
          >
            <template #description>{{ stepDesc(1) }}</template>
          </el-step>
          <el-step
            title="实体提取"
            :status="getStepStatus(2)"
            :class="{ 'step-clickable': stepClickable(2) }"
            @click="jumpToStep(2)"
          >
            <template #description>{{ stepDesc(2) }}</template>
          </el-step>
          <el-step
            title="分析验证"
            :status="getStepStatus(3)"
            :class="{ 'step-clickable': stepClickable(3) }"
            @click="jumpToStep(3)"
          >
            <template #description>{{ stepDesc(3) }}</template>
          </el-step>
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

      <!-- 工作台：左原文 / 右审阅 -->
      <div class="workspace" v-if="job" :style="workspaceGridStyle" :class="{ resizing: isResizing }">
        <!-- 左：原文 + 出处高亮 -->
        <aside class="doc-pane" v-if="!docCollapsed">
          <div class="doc-pane-header">
            <span class="doc-title">
              <el-icon><Document /></el-icon>
              {{ job.source_filename || '原文' }}
            </span>
            <span class="doc-chars">{{ job.char_count?.toLocaleString() }} 字</span>
          </div>
          <div class="doc-toolbar">
            <el-input
              v-model="docSearch"
              size="small"
              placeholder="搜索原文"
              clearable
              @keyup.enter="searchDoc"
              @clear="searchDoc"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-button size="small" type="primary" plain @click="searchDoc">查找</el-button>
          </div>
          <div class="doc-nav" v-if="docMatches.length || highlightRange">
            <el-button size="small" link :disabled="!docMatches.length" @click="gotoPrevMatch">
              上一处
            </el-button>
            <span class="doc-match-count" v-if="docMatches.length">
              {{ docMatchIndex + 1 }}/{{ docMatches.length }}
            </span>
            <el-button size="small" link :disabled="!docMatches.length" @click="gotoNextMatch">
              下一处
            </el-button>
            <el-button size="small" link @click="clearHighlight">清除高亮</el-button>
          </div>
          <div class="doc-text">
            <template v-if="docRenderParts.length">
              <template v-for="(part, i) in docRenderParts" :key="i">
                <span v-if="part.mark" :ref="setMarkRef" class="doc-hl">{{ part.text }}</span>
                <span v-else>{{ part.text }}</span>
              </template>
            </template>
            <el-empty v-else description="暂无原文内容" :image-size="80" />
          </div>
        </aside>

        <!-- 拖拽分隔条：调整原文面板宽度（双击还原 380px） -->
        <div
          v-if="!docCollapsed"
          class="doc-resizer"
          @mousedown.prevent="startResize"
          @dblclick="resetDocWidth"
        ></div>

        <!-- 右：分步审阅 -->
        <section class="review-pane" v-loading="loading">
          <!-- Step 0：文档解析 + 配置 -->
          <div v-if="displayStep === 0" class="step-panel">
            <!-- 阶段 0：文档解析 -->
            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>文档解析</h3>
                    <el-tag v-if="isParsing" type="primary" size="small">解析中</el-tag>
                    <el-tag v-else-if="job?.char_count" type="success" size="small">解析完成</el-tag>
                    <el-tag v-else type="info" size="small">待解析</el-tag>
                  </div>
                </div>
              </template>
              <div v-if="isParsing" class="parse-progress">
                <el-icon class="is-loading" :size="16"><Loading /></el-icon>
                <span>{{ job?.progress_message || '正在解析文档...' }}</span>
              </div>
              <div v-else-if="job?.error_message && !job?.char_count" class="parse-error">
                <el-alert
                  :title="'文档解析失败：' + job.error_message"
                  type="error"
                  :closable="false"
                  show-icon
                >
                  <template #default>
                    <el-button size="small" type="primary" @click="doParseDocument">重新解析</el-button>
                  </template>
                </el-alert>
              </div>
              <div v-else-if="job?.char_count" class="parse-done">
                <p>已解析「{{ job.source_filename }}」，共 <strong>{{ job.char_count?.toLocaleString() }}</strong> 字。</p>
                <p v-if="(job.estimated_step1_batches || 0) > 1 || (job.estimated_step2_batches || 0) > 1" class="batch-hint">
                  文档较长，将分批并行处理：
                  <template v-if="(job.estimated_step1_batches || 0) > 1">
                    本体提取 <strong>{{ job.estimated_step1_batches }}</strong> 批
                  </template>
                  <template v-if="(job.estimated_step1_batches || 0) > 1 && (job.estimated_step2_batches || 0) > 1">、</template>
                  <template v-if="(job.estimated_step2_batches || 0) > 1">
                    实体提取 <strong>{{ job.estimated_step2_batches }}</strong> 批
                  </template>
                </p>
                <p v-else class="batch-hint">文档长度适中，无需分批处理。</p>
              </div>
              <div v-else class="parse-pending">
                <p>文档尚未解析。</p>
              </div>
            </el-card>

            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>文档信息</h3>
                    <el-tag v-if="job?.meta_confirmed" type="success" size="small">配置已确认</el-tag>
                  </div>
                </div>
              </template>
              <el-descriptions :column="2" border>
                <el-descriptions-item label="本体名称">{{ job.name }}</el-descriptions-item>
                <el-descriptions-item label="源文档">{{ job.source_filename }}</el-descriptions-item>
                <el-descriptions-item label="字符数">{{ job.char_count?.toLocaleString() }}</el-descriptions-item>
                <el-descriptions-item label="创建时间">{{ formatTime(job.create_time) }}</el-descriptions-item>
                <el-descriptions-item label="描述" :span="2">{{ job.description || '暂无描述' }}</el-descriptions-item>
              </el-descriptions>
            </el-card>

            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>构建配置</h3>
                    <el-tag type="info" size="small">粒度 / 本体模型</el-tag>
                  </div>
                </div>
              </template>
              <div class="granularity-section">
                <div class="granularity-row">
                  <span class="granularity-label">提取粒度：</span>
                  <el-radio-group v-model="metaForm.granularity" size="small" :disabled="job?.meta_confirmed">
                    <el-radio-button value="coarse">粗（少量实体类型）</el-radio-button>
                    <el-radio-button value="medium">中（适中）</el-radio-button>
                    <el-radio-button value="fine">细（精细）</el-radio-button>
                  </el-radio-group>
                </div>
                <div class="granularity-row template-row">
                  <span class="granularity-label">载入本体模型：</span>
                  <el-select
                    v-model="metaForm.templateId"
                    size="small"
                    clearable
                    placeholder="不载入本体模型（从零推荐）"
                    :disabled="job?.meta_confirmed"
                    style="width: 240px"
                    @change="onTemplateChange"
                  >
                    <el-option
                      v-for="t in templates"
                      :key="t.id"
                      :label="`${t.name}${t.is_builtin ? '（内置）' : ''}`"
                      :value="t.id"
                    />
                  </el-select>
                  <span v-if="metaForm.templateId" class="template-hint">
                    载入后强制大模型按该本体模型提取实体类型 / 实体 / 关系
                  </span>
                </div>
              </div>
            </el-card>

            <!-- 初始类型约束：来自载入本体模型或 AI 预生成，确认配置前可编辑调整 -->
            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>初始类型约束</h3>
                    <el-tag type="info" size="small">
                      {{ metaForm.templateId ? '来自载入的本体模型' : 'AI 预生成，提取前可调整' }}
                    </el-tag>
                  </div>
                  <el-button size="small" link @click="constraintOpen = !constraintOpen">
                    {{ constraintOpen ? '收起' : '编辑' }}
                  </el-button>
                </div>
              </template>
              <template v-if="constraintOpen">
                <div class="meta-block">
                  <h4>实体类型（{{ constraintEntityTypes.length }}）</h4>
                  <div v-for="(t, idx) in constraintEntityTypes" :key="idx" class="meta-type-row">
                    <span class="meta-index">{{ idx + 1 }}</span>
                    <el-input v-model="t.name" size="small" placeholder="类型名" style="width: 220px" />
                    <el-color-picker v-model="t.color" size="small" />
                    <el-button
                      size="small"
                      link
                      type="danger"
                      :icon="Delete"
                      @click="constraintEntityTypes.splice(idx, 1)"
                    >
                      删除
                    </el-button>
                  </div>
                  <el-button
                    size="small"
                    :icon="Plus"
                    @click="constraintEntityTypes.push({ name: '', color: '#5470c6' })"
                  >
                    添加实体类型
                  </el-button>
                </div>
                <div class="meta-block">
                  <h4>关系类型（{{ constraintRelationTypes.length }}）</h4>
                  <div class="meta-tags">
                    <el-tag
                      v-for="(r, idx) in constraintRelationTypes"
                      :key="idx"
                      closable
                      size="small"
                      effect="plain"
                      @close="constraintRelationTypes.splice(idx, 1)"
                    >
                      {{ r.name || '未命名' }}
                    </el-tag>
                  </div>
                  <div class="meta-add-row">
                    <el-input
                      v-model="newConstraintRelationType"
                      size="small"
                      placeholder="新关系类型"
                      style="width: 160px"
                      @keyup.enter="addConstraintRelationType"
                    />
                    <el-button size="small" :icon="Plus" @click="addConstraintRelationType">添加</el-button>
                  </div>
                </div>
              </template>
              <p v-else class="form-hint" style="margin: 0">
                初始类型约束已就绪（默认折叠），点击右上角「编辑」可调整实体类型与关系类型。
              </p>
            </el-card>

            <div v-if="!job?.meta_confirmed" class="stage-input-area">
              <div class="stage-input-wrapper">
                <el-input
                  v-model="stageNote0"
                  type="textarea"
                  :rows="2"
                  placeholder="补充说明（可选）"
                />
                <div class="stage-input-actions">
                  <el-button
                    type="primary"
                    :loading="submitting"
                    :disabled="job?.meta_confirmed || isParsing || !job?.char_count"
                    @click="doConfirmMeta"
                  >
                    确认并开始本体提取
                  </el-button>
                </div>
              </div>
            </div>
          </div>

          <!-- Step 1：实体类型审阅 -->
          <div v-else-if="displayStep === 1" class="step-panel">
            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>本体提取</h3>
                    <el-tag type="info" size="small">
                      {{ isExtractingEntityTypes
                        ? 'AI 正在提取，可实时查看已生成部分'
                        : (entityTypes.length ? 'AI 已提取，可编辑或删除后确认' : '提取已启动，请稍候...') }}
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
                    重新生成
                  </el-button>
                </div>
              </template>

              <div v-if="isStep1Resumable" class="resume-section">
                <el-alert
                  :title="`第 ${job.step1_failed_batch + 1}/${job.step1_batches_total} 批提取失败，已成功 ${job.step1_batches_done} 批`"
                  type="warning"
                  :closable="false"
                  show-icon
                >
                  <template #default>
                    <p>{{ job?.error_message || '部分批次提取失败' }}</p>
                    <p v-if="isEmptyResponseError">LLM 服务端偶发无响应，请点击"继续提取"重试，无需修改任何配置。</p>
                    <p>点击"继续提取本体"从失败批次续跑，已成功批次不会重跑。</p>
                  </template>
                </el-alert>
                <div class="step-actions">
                  <el-button type="primary" :disabled="isRunning" @click="doExtractEntityTypes">
                    继续提取本体
                  </el-button>
                </div>
              </div>

              <div v-else class="review-section">
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
                  :title="`本体提取完成：${entityTypes.length} 个类型、${entityTypeRelations.length} 条类型间关系`"
                  type="success"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 1rem"
                />

                <div class="review-block">
                  <div class="review-block-head">
                    <h4>实体类型层级（{{ keptEntityTypes.length }} 个）</h4>
                    <el-button
                      v-if="entityTypeTree.length"
                      size="small"
                      link
                      @click="toggleAllTypeTree"
                    >
                      {{ allTypeTreeExpanded ? '全部收起' : '全部展开' }}
                    </el-button>
                  </div>

                  <el-tree
                    ref="typeTreeRef"
                    :data="entityTypeTree"
                    node-key="name"
                    :expand-on-click-node="false"
                    :props="{ label: 'name', children: 'children' }"
                  >
                    <template #default="{ data }">
                      <div class="et-tree-node">
                        <span class="et-tree-dot" :style="{ background: data.color || '#5470c6' }"></span>
                        <span class="et-tree-name">{{ data.name || '(未命名)' }}</span>
                        <el-tag v-if="data.parent_entity_type_name" size="small" type="info">
                          父：{{ data.parent_entity_type_name }}
                        </el-tag>
                        <el-tag v-if="data.property_schema?.length" size="small" type="success" effect="plain">
                          {{ data.property_schema.length }} 属性
                        </el-tag>
                        <el-tooltip
                          v-if="data.description"
                          :content="data.description"
                          placement="top"
                          :show-after="300"
                        >
                          <span class="et-tree-desc">{{ data.description }}</span>
                        </el-tooltip>
                        <span class="et-tree-actions">
                          <el-button size="small" link :icon="Edit" @click.stop="openTypeEditor(data)" />
                          <el-button size="small" link type="danger" :icon="Delete" @click.stop="removeType(data)" />
                        </span>
                      </div>
                    </template>
                  </el-tree>
                  <el-button size="small" :icon="Plus" style="margin-top: 0.5rem" @click="openTypeEditor()">
                    添加实体类型
                  </el-button>
                </div>

                <div class="review-block">
                  <h4>类型间关系（{{ keptEntityTypeRelations.length }} 条）</h4>
                  <el-table :data="keptEntityTypeRelations" stripe size="small" style="width: 100%">
                    <el-table-column prop="source_type" label="源类型" width="160" />
                    <el-table-column prop="relation_type" label="关系类型" width="150" />
                    <el-table-column prop="target_type" label="目标类型" width="160" />
                    <el-table-column prop="description" label="说明" min-width="160" show-overflow-tooltip />
                    <el-table-column label="操作" width="100" fixed="right">
                      <template #default="scope">
                        <el-button size="small" link :icon="Edit" @click="openETRelationEditor(scope.row)" />
                        <el-button size="small" link type="danger" :icon="Delete" @click="removeEntityTypeRelation(scope.row)" />
                      </template>
                    </el-table-column>
                  </el-table>
                  <el-button size="small" :icon="Plus" style="margin-top: 0.5rem" @click="openETRelationEditor()">
                    添加类型间关系
                  </el-button>
                </div>

                <div v-if="!job?.step1_confirmed">
                  <div class="stage-input-area">
                    <div class="stage-input-wrapper">
                      <el-input
                        v-model="stageFeedback[1]"
                        type="textarea"
                        :rows="2"
                        :placeholder="stageFeedbackLabels[1] + '（填写后点击发送将重新生成）'"
                      />
                      <div class="stage-input-actions">
                        <el-button
                          type="primary"
                          :icon="Promotion"
                          :loading="submitting"
                          :disabled="!aiStep1Done || job?.step1_confirmed || !stageFeedback[1]?.trim()"
                          @click="sendFeedback(1)"
                        >
                          发送
                        </el-button>
                      </div>
                    </div>
                  </div>
                  <div class="stage-confirm-area">
                    <el-button
                      type="success"
                      :loading="submitting"
                      :disabled="!aiStep1Done || job?.step1_confirmed || !keptEntityTypes.length"
                      @click="confirmEntityTypesAndStartNext"
                    >
                      确认通过，进入下一阶段
                    </el-button>
                  </div>
                </div>
              </div>
            </el-card>
          </div>

          <!-- Step 2：实体 + 关系审阅 -->
          <div v-else-if="displayStep === 2" class="step-panel">
            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>实体 + 关系提取</h3>
                    <el-tag type="info" size="small">
                      {{ isExtractingEntities
                        ? 'AI 正在提取，可实时查看已生成部分'
                        : (entities.length || relations.length ? 'AI 已提取，可编辑或删除后确认' : '提取已启动，请稍候...') }}
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
                    重新生成
                  </el-button>
                </div>
              </template>

              <div v-if="isStep2Resumable" class="resume-section">
                <el-alert
                  :title="`第 ${job.step2_failed_batch + 1}/${job.step2_batches_total} 批提取失败，已成功 ${job.step2_batches_done} 批`"
                  type="warning"
                  :closable="false"
                  show-icon
                >
                  <template #default>
                    <p>{{ job?.error_message || '部分批次提取失败' }}</p>
                    <p v-if="isEmptyResponseError">LLM 服务端偶发无响应，请点击"继续提取"重试，无需修改任何配置。</p>
                    <p>点击"继续提取"从失败批次续跑，已成功批次不会重跑。</p>
                  </template>
                </el-alert>
                <div class="step-actions">
                  <el-button type="primary" :disabled="isRunning" @click="doExtractEntities">
                    继续提取
                  </el-button>
                </div>
              </div>

              <div v-else class="review-section">
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
                  :title="`实体+关系提取完成：${entities.length} 个实体、${relations.length} 条关系`"
                  type="success"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 1rem"
                />

                <div class="review-block">
                  <div class="entity-view-controls">
                    <h4 style="margin: 0">实体列表（{{ keptEntities.length }} 个）</h4>
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
                          <el-table-column type="expand">
                            <template #default="scope">
                              <div class="entity-expand">
                                <div class="entity-expand-row">
                                  <span class="entity-expand-label">全部属性</span>
                                  <div class="prop-chips">
                                    <el-tag
                                      v-for="(p, i) in scope.row.properties || []"
                                      :key="i"
                                      size="small"
                                      type="info"
                                      effect="plain"
                                    >
                                      {{ p.name }}: {{ p.value }}{{ p.unit || '' }}
                                    </el-tag>
                                    <el-text v-if="!scope.row.properties?.length" type="info" size="small">无属性</el-text>
                                  </div>
                                </div>
                                <div v-if="scope.row.description" class="entity-expand-row">
                                  <span class="entity-expand-label">描述</span>{{ scope.row.description }}
                                </div>
                                <div v-if="scope.row.source_snippet" class="entity-expand-row">
                                  <span class="entity-expand-label">原文出处</span>{{ scope.row.source_snippet }}
                                </div>
                              </div>
                            </template>
                          </el-table-column>
                          <el-table-column prop="name" label="名称" width="150">
                            <template #default="scope">
                              <span class="entity-name-cell">{{ scope.row.name }}</span>
                            </template>
                          </el-table-column>
                          <el-table-column label="属性" min-width="180">
                            <template #default="scope">
                              <div class="prop-chips">
                                <el-tag
                                  v-for="(p, i) in (scope.row.properties || []).slice(0, 2)"
                                  :key="i"
                                  size="small"
                                  type="info"
                                  effect="plain"
                                >
                                  {{ p.name }}: {{ p.value }}{{ p.unit || '' }}
                                </el-tag>
                                <el-tag
                                  v-if="(scope.row.properties || []).length > 2"
                                  size="small"
                                  type="info"
                                  effect="plain"
                                >
                                  +{{ (scope.row.properties || []).length - 2 }} 项
                                </el-tag>
                                <el-text v-if="!scope.row.properties?.length" type="info" size="small">无属性</el-text>
                              </div>
                            </template>
                          </el-table-column>
                          <el-table-column label="原文出处" min-width="150">
                            <template #default="scope">
                              <div class="source-cell">
                                <el-tooltip
                                  v-if="scope.row.source_snippet"
                                  :content="scope.row.source_snippet"
                                  placement="top"
                                  :show-after="300"
                                  :enterable="false"
                                >
                                  <el-text type="info" size="small" class="source-snippet">
                                    {{ scope.row.source_snippet }}
                                  </el-text>
                                </el-tooltip>
                                <el-text v-else type="info" size="small">无出处</el-text>
                                <el-button
                                  v-if="scope.row.source_snippet"
                                  size="small"
                                  link
                                  :icon="View"
                                  @click="locateSnippet(scope.row.source_snippet)"
                                >
                                  定位原文
                                </el-button>
                              </div>
                            </template>
                          </el-table-column>
                          <el-table-column label="操作" width="100" fixed="right">
                            <template #default="scope">
                              <el-button size="small" link :icon="Edit" @click="openEntityEditor(scope.row)" />
                              <el-button size="small" link type="danger" :icon="Delete" @click="removeEntity(scope.row)" />
                            </template>
                          </el-table-column>
                        </el-table>
                        <el-button size="small" :icon="Plus" style="margin-top: 0.5rem" @click="addEntityToType(g.typeName)">
                          添加实体到此类型
                        </el-button>
                      </el-collapse-item>
                    </el-collapse>
                  </div>

                  <el-table v-else :data="keptEntities" stripe size="small" style="width: 100%; margin-bottom: 1rem">
                    <el-table-column type="expand">
                      <template #default="scope">
                        <div class="entity-expand">
                          <div class="entity-expand-row">
                            <span class="entity-expand-label">全部属性</span>
                            <div class="prop-chips">
                              <el-tag
                                v-for="(p, i) in scope.row.properties || []"
                                :key="i"
                                size="small"
                                type="info"
                                effect="plain"
                              >
                                {{ p.name }}: {{ p.value }}{{ p.unit || '' }}
                              </el-tag>
                              <el-text v-if="!scope.row.properties?.length" type="info" size="small">无属性</el-text>
                            </div>
                          </div>
                          <div v-if="scope.row.description" class="entity-expand-row">
                            <span class="entity-expand-label">描述</span>{{ scope.row.description }}
                          </div>
                          <div v-if="scope.row.source_snippet" class="entity-expand-row">
                            <span class="entity-expand-label">原文出处</span>{{ scope.row.source_snippet }}
                          </div>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column prop="name" label="名称" width="140" />
                    <el-table-column label="所属类型" width="150">
                      <template #default="scope">
                        <span class="entity-type-cell" :style="{ color: entityTypeColor(scope.row.instance_of) }">
                          {{ scope.row.instance_of }}
                        </span>
                      </template>
                    </el-table-column>
                    <el-table-column label="属性" min-width="180">
                      <template #default="scope">
                        <div class="prop-chips">
                          <el-tag
                            v-for="(p, i) in (scope.row.properties || []).slice(0, 2)"
                            :key="i"
                            size="small"
                            type="info"
                            effect="plain"
                          >
                            {{ p.name }}: {{ p.value }}{{ p.unit || '' }}
                          </el-tag>
                          <el-tag
                            v-if="(scope.row.properties || []).length > 2"
                            size="small"
                            type="info"
                            effect="plain"
                          >
                            +{{ (scope.row.properties || []).length - 2 }} 项
                          </el-tag>
                          <el-text v-if="!scope.row.properties?.length" type="info" size="small">无属性</el-text>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="原文出处" min-width="150">
                      <template #default="scope">
                        <div class="source-cell">
                          <el-tooltip
                            v-if="scope.row.source_snippet"
                            :content="scope.row.source_snippet"
                            placement="top"
                            :show-after="300"
                            :enterable="false"
                          >
                            <el-text type="info" size="small" class="source-snippet">
                              {{ scope.row.source_snippet }}
                            </el-text>
                          </el-tooltip>
                          <el-text v-else type="info" size="small">无出处</el-text>
                          <el-button
                            v-if="scope.row.source_snippet"
                            size="small"
                            link
                            :icon="View"
                            @click="locateSnippet(scope.row.source_snippet)"
                          >
                            定位原文
                          </el-button>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="操作" width="100" fixed="right">
                      <template #default="scope">
                        <el-button size="small" link :icon="Edit" @click="openEntityEditor(scope.row)" />
                        <el-button size="small" link type="danger" :icon="Delete" @click="removeEntity(scope.row)" />
                      </template>
                    </el-table-column>
                  </el-table>
                  <div v-if="entityViewMode === 'flat'" class="step-actions" style="margin-top: 0">
                    <el-button size="small" :icon="Plus" @click="openEntityEditor()">添加实体</el-button>
                  </div>
                </div>

                <div class="review-block">
                  <h4><el-icon><Connection /></el-icon> 关系列表（{{ keptRelations.length }} 条）</h4>
                  <el-table :data="keptRelations" stripe size="small" style="width: 100%">
                    <el-table-column prop="source" label="源实体" width="150" />
                    <el-table-column prop="relation_type" label="关系类型" width="140" />
                    <el-table-column prop="target" label="目标实体" width="150" />
                    <el-table-column label="原文出处" min-width="160">
                      <template #default="scope">
                        <div class="source-cell">
                          <el-text type="info" size="small" class="source-snippet">
                            {{ scope.row.source_snippet || '无出处' }}
                          </el-text>
                          <el-button
                            v-if="scope.row.source_snippet"
                            size="small"
                            link
                            :icon="View"
                            @click="locateSnippet(scope.row.source_snippet)"
                          >
                            定位原文
                          </el-button>
                        </div>
                      </template>
                    </el-table-column>
                    <el-table-column label="操作" width="100" fixed="right">
                      <template #default="scope">
                        <el-button size="small" link :icon="Edit" @click="openRelationEditor(scope.row)" />
                        <el-button size="small" link type="danger" :icon="Delete" @click="removeRelation(scope.row)" />
                      </template>
                    </el-table-column>
                  </el-table>
                  <el-button size="small" :icon="Plus" style="margin-top: 0.5rem" @click="openRelationEditor()">
                    添加关系
                  </el-button>
                </div>

                <div v-if="!job?.step2_confirmed">
                  <div class="stage-input-area">
                    <div class="stage-input-wrapper">
                      <el-input
                        v-model="stageFeedback[2]"
                        type="textarea"
                        :rows="2"
                        :placeholder="stageFeedbackLabels[2] + '（填写后点击发送将重新生成）'"
                      />
                      <div class="stage-input-actions">
                        <el-button
                          type="primary"
                          :icon="Promotion"
                          :loading="submitting"
                          :disabled="!aiStep2Done || job?.step2_confirmed || !stageFeedback[2]?.trim()"
                          @click="sendFeedback(2)"
                        >
                          发送
                        </el-button>
                      </div>
                    </div>
                  </div>
                  <div class="stage-confirm-area">
                    <el-button
                      type="success"
                      :loading="submitting"
                      :disabled="!aiStep2Done || job?.step2_confirmed || !keptEntities.length"
                      @click="confirmEntitiesAndStartVerify"
                    >
                      确认通过，进入下一阶段
                    </el-button>
                  </div>
                </div>
              </div>
            </el-card>
          </div>

          <!-- Step 3：验证 -->
          <div v-else-if="displayStep === 3" class="step-panel">
            <el-card class="step-card">
              <template #header>
                <div class="step-header">
                  <div class="step-header-title">
                    <h3>验证</h3>
                    <el-tag type="info" size="small">
                      {{ isVerifying ? 'AI 正在做自检验证...' : (job?.step3_verification ? '验证完成' : '可启动验证') }}
                    </el-tag>
                  </div>
                  <el-button
                    v-if="job?.step3_verification"
                    size="small"
                    type="warning"
                    plain
                    :icon="Refresh"
                    :disabled="isRunning || submitting"
                    @click="openRework(3)"
                  >
                    重新生成
                  </el-button>
                </div>
              </template>

              <div v-if="isVerifying" class="waiting-section">
                <el-alert
                  title="AI 正在核查实体/属性/关系是否可溯源..."
                  type="info"
                  :closable="false"
                  show-icon
                />
              </div>

              <div v-else-if="!job?.step3_verification && job?.status !== 'completed'" class="generate-section">
                <el-alert
                  title="AI 将核查实体/属性/关系是否可溯源，标记存疑项"
                  type="info"
                  :closable="false"
                  show-icon
                />
                <div class="step-actions">
                  <el-button type="primary" :disabled="isRunning" @click="doVerify">
                    启动验证
                  </el-button>
                </div>
              </div>

              <div v-else-if="job?.step3_verification" class="verify-section">
                <el-alert
                  :title="`验证完成：${job.step3_verification.verified_count || 0} 项通过，${job.step3_verification.suspect_count || 0} 项存疑`"
                  :type="(job.step3_verification.suspect_count || 0) > 0 ? 'warning' : 'success'"
                  :closable="false"
                  show-icon
                  style="margin-bottom: 1rem"
                />

                <div v-if="job.step3_verification.suspects?.length" class="suspects-block">
                  <h4>存疑项（{{ job.step3_verification.suspects.length }} 条）</h4>
                  <el-table :data="job.step3_verification.suspects" stripe size="small" style="width: 100%; margin-bottom: 1.5rem">
                    <el-table-column prop="item_type" label="类型" width="100" />
                    <el-table-column prop="item_id" label="标识" width="180" />
                    <el-table-column prop="reason" label="存疑原因" min-width="280" />
                  </el-table>
                </div>

                <div v-if="job?.status !== 'completed' && !job?.step3_confirmed">
                  <div class="stage-input-area">
                    <div class="stage-input-wrapper">
                      <el-input
                        v-model="stageFeedback[3]"
                        type="textarea"
                        :rows="2"
                        :placeholder="stageFeedbackLabels[3] + '（填写后点击发送将重新生成）'"
                      />
                      <div class="stage-input-actions">
                        <el-button
                          type="primary"
                          :icon="Promotion"
                          :loading="submitting"
                          :disabled="job?.step3_confirmed || !stageFeedback[3]?.trim()"
                          @click="sendFeedback(3)"
                        >
                          发送
                        </el-button>
                      </div>
                    </div>
                  </div>
                  <div class="stage-confirm-area">
                    <el-button
                      type="success"
                      :loading="submitting"
                      :disabled="job?.step3_confirmed"
                      @click="doConfirmVerification"
                    >
                      确认并生成最终本体
                    </el-button>
                  </div>
                </div>
              </div>
            </el-card>
          </div>

          <!-- 已完成 -->
          <div v-else class="step-panel">
            <el-card class="step-card">
              <div class="complete-content">
                <el-icon class="success-icon"><CircleCheck /></el-icon>
                <h3>本体构建成功！</h3>
                <el-descriptions :column="2" border style="margin: 1.5rem 0">
                  <el-descriptions-item label="本体名称">{{ job?.name }}</el-descriptions-item>
                  <el-descriptions-item label="实体类型">{{ entityTypes.length }} 个</el-descriptions-item>
                  <el-descriptions-item label="实体数量">{{ entities.length }}</el-descriptions-item>
                  <el-descriptions-item label="属性数量">{{ totalPropertyCount }}</el-descriptions-item>
                  <el-descriptions-item label="关系数量">{{ relations.length }}</el-descriptions-item>
                  <el-descriptions-item label="构建耗时">{{ buildDuration }}</el-descriptions-item>
                </el-descriptions>
                <div class="step-actions" style="justify-content: center">
                  <el-button type="primary" @click="viewOntology">查看本体详情</el-button>
                  <el-button @click="goBack">返回首页</el-button>
                </div>
              </div>
            </el-card>
          </div>
        </section>
      </div>

      <!-- 实体类型编辑对话框 -->
      <el-dialog
        v-model="typeEditor.visible"
        :title="typeEditor.mode === 'add' ? '添加实体类型' : '编辑实体类型'"
        width="720px"
        :close-on-click-modal="false"
      >
        <el-form label-width="110px">
          <el-form-item label="类型名称" required>
            <el-input v-model="typeEditor.name" placeholder="如：公司、人物、财务指标" />
          </el-form-item>
          <el-form-item label="父类型">
            <el-select
              v-model="typeEditor.parent_entity_type_name"
              clearable
              filterable
              placeholder="顶层类型"
              style="width: 100%"
            >
              <el-option
                v-for="t in entityTypes.filter(x => x.name !== typeEditor.name)"
                :key="t.name"
                :label="t.name"
                :value="t.name"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="颜色">
            <el-color-picker v-model="typeEditor.color" />
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="typeEditor.description" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="属性骨架">
            <div class="schema-editor">
              <el-table :data="typeEditor.schema" size="small" border>
                <el-table-column label="属性名" min-width="120">
                  <template #default="s"><el-input v-model="s.row.name" size="small" placeholder="属性名" /></template>
                </el-table-column>
                <el-table-column label="分类" width="110">
                  <template #default="s">
                    <el-select v-model="s.row.category" size="small">
                      <el-option label="文本" value="text" />
                      <el-option label="数值" value="metric" />
                      <el-option label="时间" value="date" />
                      <el-option label="枚举" value="enum" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="数据类型" width="110">
                  <template #default="s"><el-input v-model="s.row.data_type" size="small" placeholder="string" /></template>
                </el-table-column>
                <el-table-column label="单位" width="90">
                  <template #default="s"><el-input v-model="s.row.unit" size="small" placeholder="%" /></template>
                </el-table-column>
                <el-table-column label="说明" min-width="140">
                  <template #default="s"><el-input v-model="s.row.description" size="small" placeholder="可选" /></template>
                </el-table-column>
                <el-table-column label="操作" width="60">
                  <template #default="s">
                    <el-button size="small" link type="danger" :icon="Delete" @click="typeEditor.schema.splice(s.$index, 1)" />
                  </template>
                </el-table-column>
              </el-table>
              <el-button
                size="small"
                :icon="Plus"
                style="margin-top: 0.5rem"
                @click="typeEditor.schema.push({ name: '', category: 'text', data_type: 'string', unit: '', description: '' })"
              >
                添加属性
              </el-button>
            </div>
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="typeEditor.visible = false">取消</el-button>
          <el-button type="primary" @click="saveType">保存</el-button>
        </template>
      </el-dialog>

      <!-- 实体编辑对话框 -->
      <el-dialog
        v-model="entityEditor.visible"
        :title="entityEditor.index >= 0 ? '编辑实体' : '添加实体'"
        width="760px"
        :close-on-click-modal="false"
      >
        <el-form label-width="110px">
          <el-form-item label="实体名称" required>
            <el-input v-model="entityEditor.name" placeholder="如：贵州茅台" />
          </el-form-item>
          <el-form-item label="所属类型" required>
            <el-select v-model="entityEditor.instance_of" filterable style="width: 100%">
              <el-option v-for="t in keptEntityTypes" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="属性">
            <div class="schema-editor">
              <el-table :data="entityEditor.properties" size="small" border>
                <el-table-column label="属性名" min-width="120">
                  <template #default="s"><el-input v-model="s.row.name" size="small" placeholder="属性名" /></template>
                </el-table-column>
                <el-table-column label="值" min-width="150">
                  <template #default="s"><el-input v-model="s.row.value" size="small" placeholder="值" /></template>
                </el-table-column>
                <el-table-column label="分类" width="100">
                  <template #default="s">
                    <el-select v-model="s.row.category" size="small">
                      <el-option label="文本" value="text" />
                      <el-option label="数值" value="metric" />
                      <el-option label="时间" value="date" />
                      <el-option label="枚举" value="enum" />
                    </el-select>
                  </template>
                </el-table-column>
                <el-table-column label="单位" width="80">
                  <template #default="s"><el-input v-model="s.row.unit" size="small" placeholder="%" /></template>
                </el-table-column>
                <el-table-column label="操作" width="60">
                  <template #default="s">
                    <el-button size="small" link type="danger" :icon="Delete" @click="entityEditor.properties.splice(s.$index, 1)" />
                  </template>
                </el-table-column>
              </el-table>
              <el-button
                size="small"
                :icon="Plus"
                style="margin-top: 0.5rem"
                @click="entityEditor.properties.push({ name: '', value: '', category: 'text', unit: '' })"
              >
                添加属性
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="原文出处">
            <div class="source-edit">
              <el-input
                v-model="entityEditor.source_snippet"
                type="textarea"
                :rows="2"
                placeholder="从原文摘录支持该实体的片段"
              />
              <el-button
                v-if="entityEditor.source_snippet"
                size="small"
                :icon="View"
                @click="locateSnippet(entityEditor.source_snippet)"
              >
                定位原文
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="描述">
            <el-input v-model="entityEditor.description" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="entityEditor.visible = false">取消</el-button>
          <el-button type="primary" @click="saveEntity">保存</el-button>
        </template>
      </el-dialog>

      <!-- 关系编辑对话框 -->
      <el-dialog
        v-model="relationEditor.visible"
        :title="relationEditor.index >= 0 ? '编辑关系' : '添加关系'"
        width="600px"
        :close-on-click-modal="false"
      >
        <el-form label-width="110px">
          <el-form-item label="源实体" required>
            <el-select v-model="relationEditor.source" filterable style="width: 100%">
              <el-option v-for="e in keptEntities" :key="e.name" :label="e.name" :value="e.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型" required>
            <el-input v-model="relationEditor.relation_type" placeholder="如：投资 / 任职" />
          </el-form-item>
          <el-form-item label="目标实体" required>
            <el-select v-model="relationEditor.target" filterable style="width: 100%">
              <el-option v-for="e in keptEntities" :key="e.name" :label="e.name" :value="e.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="权重">
            <el-input-number v-model="relationEditor.weight" :min="0" :max="1" :step="0.1" controls-position="right" />
          </el-form-item>
          <el-form-item label="原文出处">
            <div class="source-edit">
              <el-input
                v-model="relationEditor.source_snippet"
                type="textarea"
                :rows="2"
                placeholder="从原文摘录支持该关系的片段"
              />
              <el-button
                v-if="relationEditor.source_snippet"
                size="small"
                :icon="View"
                @click="locateSnippet(relationEditor.source_snippet)"
              >
                定位原文
              </el-button>
            </div>
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="relationEditor.description" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="relationEditor.visible = false">取消</el-button>
          <el-button type="primary" @click="saveRelation">保存</el-button>
        </template>
      </el-dialog>

      <!-- 类型间关系编辑对话框 -->
      <el-dialog
        v-model="etRelationEditor.visible"
        :title="etRelationEditor.index >= 0 ? '编辑类型间关系' : '添加类型间关系'"
        width="560px"
        :close-on-click-modal="false"
      >
        <el-form label-width="110px">
          <el-form-item label="源类型" required>
            <el-select v-model="etRelationEditor.source_type" filterable style="width: 100%">
              <el-option v-for="t in keptEntityTypes" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="关系类型" required>
            <el-input v-model="etRelationEditor.relation_type" placeholder="如：包含 / 属于" />
          </el-form-item>
          <el-form-item label="目标类型" required>
            <el-select v-model="etRelationEditor.target_type" filterable style="width: 100%">
              <el-option v-for="t in keptEntityTypes" :key="t.name" :label="t.name" :value="t.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="说明">
            <el-input v-model="etRelationEditor.description" type="textarea" :rows="2" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="etRelationEditor.visible = false">取消</el-button>
          <el-button type="primary" @click="saveETRelation">保存</el-button>
        </template>
      </el-dialog>

      <!-- 重新生成对话框（补充要求后重跑当前步骤） -->
      <el-dialog
        v-model="reworkDialogVisible"
        :title="`重新生成 step${reworkTargetStep}`"
        width="560px"
        :close-on-click-modal="false"
      >
        <el-alert
          :title="`重新生成将清空 step${reworkTargetStep} 的现有结果并重新调用 LLM，后续已确认的步骤也需重新执行。`"
          type="warning"
          :closable="false"
          show-icon
          style="margin-bottom: 1rem"
        />
        <el-form label-width="100px">
          <el-form-item label="补充要求">
            <el-input
              v-model="reworkPrompt"
              type="textarea"
              :rows="5"
              :placeholder="reworkPlaceholders[reworkTargetStep] || '请输入对当前步骤的补充要求'"
            />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="reworkDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="reworkSubmitting" @click="doRework">
            <el-icon><Promotion /></el-icon>
            发送
          </el-button>
        </template>
      </el-dialog>
    </div>
  </Layout>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft, CircleCheck, Loading, Refresh,
  Search, Document, Plus, Edit, Delete, View, Connection, Promotion
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Layout from '@/components/Layout.vue'
import api from '@/services/api'
import {
  getBuildJob,
  getBuildProgress,
  confirmMeta as confirmMetaApi,
  streamBuildJob,
  parseBuildJob
} from '@/services/ontologyBuild'
import { reworkBuildStep } from '@/services/ontology'
import { getMetaModelList, getMetaModel } from '@/services/ontologyMetaModel'

const route = useRoute()
const router = useRouter()
const jobId = route.params.jobId as string

type ReviewStatus = 'pending' | 'approved' | 'rejected'

// ── 响应式状态 ──
const loading = ref(false)
const submitting = ref(false)

const job = ref<any>(null)
const entityTypes = ref<any[]>([])          // v3: step1_entity_types（含 review 审阅状态）
const entityTypeRelations = ref<any[]>([])  // v3: step1_entity_type_relations
const entities = ref<any[]>([])             // v3: step2_entities
const relations = ref<any[]>([])            // v3: step2_relations
const templates = ref<any[]>([])            // step0 可选本体模型

// 初始类型约束（step1 提取前可编辑，作为 LLM 提取的起点；同步到 job.meta_entity_types）
const constraintEntityTypes = ref<any[]>([])
const constraintRelationTypes = ref<any[]>([])
const newConstraintRelationType = ref('')
const constraintOpen = ref(false)   // 约束编辑区默认折叠
let constraintInitialized = false
watch(job, (j) => {
  // 仅当解析完成后 AI 推荐本体模型（meta_*）就绪时才初始化初始类型约束，
  // 避免「文档解析」阶段 job 首次加载 meta 为空时过早置位，导致解析后无法回填。
  if (!constraintInitialized && j && (j.meta_entity_types?.length || j.meta_relation_types?.length)) {
    constraintEntityTypes.value = JSON.parse(JSON.stringify(j.meta_entity_types || []))
    constraintRelationTypes.value = JSON.parse(JSON.stringify(j.meta_relation_types || []))
    constraintInitialized = true
  }
}, { immediate: true })

/** step1 提取前判断约束是否有修改 */
const constraintDirty = computed(() =>
  JSON.stringify(constraintEntityTypes.value) !== JSON.stringify(job.value?.meta_entity_types || []) ||
  JSON.stringify(constraintRelationTypes.value) !== JSON.stringify(job.value?.meta_relation_types || [])
)

// 实体视图：按类型分组 / 平铺
const entityViewMode = ref<'grouped' | 'flat'>('grouped')
const expandedEntityTypeNames = ref<string[]>([])

// 原文面板
const docCollapsed = ref(false)
const docWidth = ref(460)            // 原文面板宽度，可拖拽调整（最小 280px，最大半个屏幕）
const isResizing = ref(false)        // 拖拽中禁用 grid 过渡动画
const MIN_DOC_WIDTH = 280            // 原文面板最小宽度
/** 原文面板最大宽度：占半个屏幕，保证宽屏下可充分放大 */
const maxDocWidth = () => Math.max(MIN_DOC_WIDTH, Math.floor(window.innerWidth * 0.5))
const workspaceGridStyle = computed(() =>
  docCollapsed.value
    ? 'grid-template-columns: minmax(0, 1fr)'
    : `grid-template-columns: ${docWidth.value}px 6px minmax(0, 1fr)`
)
const resetDocWidth = () => { docWidth.value = 460 }

/** 拖拽分隔条调整原文面板宽度 */
const startResize = (e: MouseEvent) => {
  const startX = e.clientX
  const startW = docWidth.value
  isResizing.value = true
  document.body.style.cursor = 'col-resize'
  document.body.style.userSelect = 'none'
  const onMove = (ev: MouseEvent) => {
    docWidth.value = Math.min(maxDocWidth(), Math.max(MIN_DOC_WIDTH, startW + ev.clientX - startX))
  }
  const onUp = () => {
    isResizing.value = false
    document.body.style.cursor = ''
    document.body.style.userSelect = ''
    window.removeEventListener('mousemove', onMove)
    window.removeEventListener('mouseup', onUp)
  }
  window.addEventListener('mousemove', onMove)
  window.addEventListener('mouseup', onUp)
}
const docSearch = ref('')
const docMatches = ref<{ start: number; end: number }[]>([])
const docMatchIndex = ref(0)
const highlightRange = ref<{ start: number; end: number } | null>(null)
const markEl = ref<HTMLElement | null>(null)

// step0 配置表单（载入本体模型即强制按本体模型提取）
const metaForm = ref({
  granularity: 'medium' as 'coarse' | 'medium' | 'fine',
  templateId: '' as string
})

// 完成后修改意见（确认时可填写，触发重新生成）
const stageFeedback = ref<Record<number, string>>({ 1: '', 2: '', 3: '' })

// step0 配置阶段的补充说明（可选）
const stageNote0 = ref('')

const stageFeedbackLabels: Record<number, string> = {
  1: '对实体类型结果的意见（可选）',
  2: '对实体+关系结果的意见（可选）',
  3: '对验证结果的意见（可选）'
}

// AI 各阶段完成标记
const aiStep1Done = ref(false)
const aiStep2Done = ref(false)

// 轮询 / SSE
let pollTimer: ReturnType<typeof setInterval> | null = null
let sseAbort: (() => void) | null = null
let streamRetryCount = 0
let retryTimer: ReturnType<typeof setTimeout> | null = null
// 组件是否已卸载：卸载后禁止再发起重连/订阅，避免在其它页面回放 step_done 重复弹提示
let disposed = false
const STREAM_MAX_RETRY = 3

// 返工
const reworkDialogVisible = ref(false)
const reworkTargetStep = ref(1)
const reworkPrompt = ref('')
const reworkSubmitting = ref(false)
const reworkPlaceholders: Record<number, string> = {
  1: '例如：增加"风险事件"实体类型；细化财务指标的属性骨架',
  2: '例如：补充关联交易实体；只保留前 20 大股东的关联关系',
  3: '例如：重点关注资产负债率与现金流是否可溯源'
}

// 编辑器对话框状态
const typeEditor = ref({
  visible: false,
  mode: 'add' as 'add' | 'edit',
  index: -1,
  name: '',
  description: '',
  color: '#5470c6',
  parent_entity_type_name: '',
  schema: [] as any[]
})
const entityEditor = ref({
  visible: false,
  index: -1,
  name: '',
  instance_of: '',
  properties: [] as any[],
  source_snippet: '',
  description: ''
})
const relationEditor = ref({
  visible: false,
  index: -1,
  source: '',
  relation_type: '',
  target: '',
  weight: 1,
  source_snippet: '',
  description: ''
})
const etRelationEditor = ref({
  visible: false,
  index: -1,
  source_type: '',
  relation_type: '',
  target_type: '',
  description: ''
})

// ── 数据列表（不再区分审阅状态，全部可编辑/删除）──
const keptEntityTypes = computed(() => entityTypes.value)
const keptEntityTypeRelations = computed(() => entityTypeRelations.value)
const keptEntities = computed(() => entities.value)
const keptRelations = computed(() => relations.value)

// ── 实体类型树 / 实体分组 ──
const entityTypeTree = computed(() => {
  const map = new Map<string, any>()
  const nodes = keptEntityTypes.value.map(t => ({ ...t, children: [] as any[] }))
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

// ── 实体类型树：展开控制 ──
const typeTreeRef = ref<any>()
const allTypeTreeExpanded = ref(false)
let typeTreeInitialized = false

watch(entityTypeTree, () => {
  if (!typeTreeInitialized && entityTypeTree.value.length) {
    // 首次加载仅展开根层，避免类型多时页面过长
    nextTick(() => {
      typeTreeRef.value?.store?.setExpandedKeys(entityTypeTree.value.map(r => r.name))
    })
    typeTreeInitialized = true
  }
}, { flush: 'post' })

const expandTypeTreeAll = (expand: boolean) => {
  const tree = typeTreeRef.value
  if (!tree) return
  if (expand) {
    tree.store.setExpandedKeys(keptEntityTypes.value.map(t => t.name))
    allTypeTreeExpanded.value = true
  } else {
    tree.store.setExpandedKeys([])
    allTypeTreeExpanded.value = false
  }
}
const toggleAllTypeTree = () => expandTypeTreeAll(!allTypeTreeExpanded.value)

const entityTypeGroups = computed(() => {
  const groups: any[] = []
  for (const t of keptEntityTypes.value) {
    const list = keptEntities.value.filter(e => e.instance_of === t.name)
    if (list.length) {
      groups.push({ typeName: t.name, color: t.color, entities: list })
    }
  }
  const known = new Set(keptEntityTypes.value.map(t => t.name))
  const unclassified = keptEntities.value.filter(e => !known.has(e.instance_of))
  if (unclassified.length) {
    groups.push({ typeName: '未分类', color: '#909399', entities: unclassified })
  }
  return groups
})

// 分组视图首次加载时默认全部展开，避免逐个展开
let groupsAutoExpanded = false
watch(entityTypeGroups, (groups) => {
  if (!groupsAutoExpanded && groups.length) {
    expandedEntityTypeNames.value = groups.map(g => g.typeName)
    groupsAutoExpanded = true
  }
}, { immediate: true })

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

const entityTypeColor = (name: string) =>
  entityTypes.value.find(t => t.name === name)?.color || '#5470c6'

// ── 步骤状态机 ──
const currentStep = computed(() => {
  if (!job.value) return 0
  if (job.value.status === 'completed' || job.value.step3_confirmed) return 4
  if (job.value.step2_confirmed) return 3
  if (job.value.step1_confirmed) return 2
  if (job.value.meta_confirmed) return 1
  return 0
})

// 展示步骤：步骤条可点击回看已确认步骤，真实进度仍由 currentStep 驱动
const viewStep = ref(0)
const displayStep = computed(() => viewStep.value)
watch(currentStep, (v) => { viewStep.value = v }, { immediate: true })

const stepClickable = (step: number) => step <= currentStep.value
const jumpToStep = (step: number) => {
  if (step <= currentStep.value) viewStep.value = step
}

const isRunning = computed(() => {
  const rs = job.value?.running_step
  return rs !== undefined && rs >= 0 && rs <= 3
})
const isExtractingEntityTypes = computed(() => job.value?.running_step === 1)
const isExtractingEntities = computed(() => job.value?.running_step === 2)
const isVerifying = computed(() => job.value?.running_step === 3)
// 阶段 0「文档解析」运行中
const isParsing = computed(() => job.value?.running_step === 0)

// 完成页统计：属性总数 / 构建耗时（create_time → update_time）
const totalPropertyCount = computed(() =>
  entities.value.reduce((s: number, e: any) => s + (e.properties?.length || 0), 0)
)
const buildDuration = computed(() => {
  const j = job.value
  if (!j?.create_time || !j?.update_time) return ''
  const t0 = new Date(j.create_time).getTime()
  const t1 = new Date(j.update_time).getTime()
  if (!isFinite(t0) || !isFinite(t1) || t1 < t0) return ''
  const sec = Math.round((t1 - t0) / 1000)
  if (sec < 60) return `${sec} 秒`
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return s ? `${m} 分 ${s} 秒` : `${m} 分钟`
})

const isEmptyResponseError = computed(() =>
  !!job.value?.error_message && job.value.error_message.includes('空响应')
)

// 各阶段真实状态（progress_stages），步骤条描述展示用
const stageInfo = computed<Record<number, any>>(() => {
  const map: Record<number, any> = {}
  for (const s of (job.value?.progress_stages || [])) map[s.stage] = s
  return map
})

/** 步骤条每步描述：已完成 → 耗时，运行中 → 运行中，其余为空 */
const stepDesc = (step: number): string => {
  const s = stageInfo.value[step]
  if (!s) return ''
  if (s.status === 'done') return `✓ ${_calcElapsed(s.started_at, s.finished_at)}`
  if (s.status === 'running') return '运行中'
  return ''
}

function _calcElapsed(start?: string, end?: string): string {
  if (!start) return ''
  const s = new Date(start).getTime()
  if (isNaN(s)) return ''
  const e = end ? new Date(end).getTime() : Date.now()
  const sec = Math.max(0, Math.round((e - s) / 1000))
  if (sec < 60) return `${sec}s`
  return `${Math.floor(sec / 60)}m${sec % 60}s`
}

const batch1ProgressText = computed(() => {
  const j = job.value
  if (!j) return 'AI 正在提取本体...'
  const done = entityTypes.value.length
  if (j.step1_batches_total > 1) {
    return `AI 正在提取本体（第 ${j.step1_batches_done + 1}/${j.step1_batches_total} 批），已提取 ${done} 个`
  }
  return `AI 正在提取本体，已提取 ${done} 个`
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

const getStepStatus = (step: number): 'wait' | 'process' | 'error' => {
  if (!job.value) return 'wait'
  if (job.value.error_message && step === currentStep.value) return 'error'
  if (step === currentStep.value) return 'process'
  return 'wait'
}

// ── 原文定位 / 高亮 ──
function _findRange(source: string, snippet: string): { start: number; end: number } | null {
  const q = (snippet || '').trim()
  if (!q || !source) return null
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+')
  const m = new RegExp(escaped, 'i').exec(source)
  return m ? { start: m.index, end: m.index + m[0].length } : null
}

const activeRange = computed(() =>
  highlightRange.value || (docMatches.value.length ? docMatches.value[docMatchIndex.value] : null)
)

const docRenderParts = computed(() => {
  const text = job.value?.source_text || ''
  const r = activeRange.value
  if (!r || r.start < 0 || r.end > text.length) return [{ text, mark: false }]
  return [
    { text: text.slice(0, r.start), mark: false },
    { text: text.slice(r.start, r.end), mark: true },
    { text: text.slice(r.end), mark: false }
  ]
})

const setMarkRef = (el: any) => {
  markEl.value = (el as HTMLElement) || null
}

watch(activeRange, async () => {
  await nextTick()
  if (markEl.value) markEl.value.scrollIntoView({ block: 'center', behavior: 'smooth' })
})

const searchDoc = () => {
  const source = job.value?.source_text || ''
  const q = (docSearch.value || '').trim()
  highlightRange.value = null
  if (!q) {
    docMatches.value = []
    docMatchIndex.value = 0
    return
  }
  const escaped = q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+')
  const re = new RegExp(escaped, 'gi')
  const matches: { start: number; end: number }[] = []
  let m: RegExpExecArray | null
  while ((m = re.exec(source)) !== null) {
    matches.push({ start: m.index, end: m.index + m[0].length })
    if (matches.length >= 200) break
    if (m[0].length === 0) re.lastIndex++
  }
  docMatches.value = matches
  docMatchIndex.value = 0
}

const gotoNextMatch = () => {
  if (!docMatches.value.length) return
  docMatchIndex.value = (docMatchIndex.value + 1) % docMatches.value.length
  highlightRange.value = null
}

const gotoPrevMatch = () => {
  if (!docMatches.value.length) return
  docMatchIndex.value = (docMatchIndex.value - 1 + docMatches.value.length) % docMatches.value.length
  highlightRange.value = null
}

const clearHighlight = () => {
  highlightRange.value = null
  docMatches.value = []
  docMatchIndex.value = 0
  docSearch.value = ''
}

const locateSnippet = (snippet: string) => {
  if (!job.value?.source_text) {
    ElMessage.info('任务暂无原文内容')
    return
  }
  const range = _findRange(job.value.source_text, snippet)
  if (!range) {
    ElMessage.warning('未在原文中找到该片段（可能已被改写）')
    return
  }
  docSearch.value = ''
  docMatches.value = []
  highlightRange.value = range
}

// ── 数据加载 ──
const loadJob = async () => {
  try {
    const res: any = await getBuildJob(jobId)
    job.value = res.data

    if (job.value.granularity) metaForm.value.granularity = job.value.granularity
    if (job.value.template_id) {
      metaForm.value.templateId = job.value.template_id
    }

    entityTypes.value = (job.value.step1_entity_types || []).map((t: any) => ({
      ...t,
      review: (job.value.step1_confirmed ? 'approved' : 'pending') as ReviewStatus
    }))
    entityTypeRelations.value = (job.value.step1_entity_type_relations || []).map((r: any) => ({
      ...r,
      review: (job.value.step1_confirmed ? 'approved' : 'pending') as ReviewStatus
    }))
    entities.value = (job.value.step2_entities || []).map((e: any) => ({
      ...e,
      review: (job.value.step2_confirmed ? 'approved' : 'pending') as ReviewStatus
    }))
    relations.value = (job.value.step2_relations || []).map((r: any) => ({
      ...r,
      review: (job.value.step2_confirmed ? 'approved' : 'pending') as ReviewStatus
    }))

    // 已载入本体模型且尚未确认配置：真实连接本体模型，用其 schema 回填初始类型约束
    if (job.value.template_id && !job.value.meta_confirmed) {
      await loadMetaModelIntoConstraints(job.value.template_id, true)
    }
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '加载任务失败')
  }
}

const loadTemplates = async () => {
  try {
    const res: any = await getMetaModelList()
    templates.value = res.items || res.data || []
  } catch {
    // 本体模型为可选配置，加载失败不阻断主流程
  }
}

// 真实连接本体模型：拉取本体模型详情，用其实体类型/关系类型回填初始约束
const loadMetaModelIntoConstraints = async (tplId: string, silent = false) => {
  try {
    const res: any = await getMetaModel(tplId)
    const tpl = res.data
    constraintEntityTypes.value = (tpl.entity_types || []).map((t: any) => ({
      name: t.name,
      color: t.color || '#5470c6'
    }))
    constraintRelationTypes.value = (tpl.relation_types || []).map((r: any) => ({ name: r.name }))
    constraintInitialized = true
    if (!silent) ElMessage.success(`已载入本体模型「${tpl.name}」`)
  } catch (e: any) {
    if (!silent) ElMessage.error(e.serverMessage || '载入本体模型失败')
  }
}

// 用户在构建配置中切换/清除本体模型
const onTemplateChange = async (val: string) => {
  if (!val) {
    // 清除本体模型：回退到 AI 推荐的初始约束
    constraintEntityTypes.value = JSON.parse(JSON.stringify(job.value?.meta_entity_types || []))
    constraintRelationTypes.value = JSON.parse(JSON.stringify(job.value?.meta_relation_types || []))
    constraintInitialized = true
    return
  }
  await loadMetaModelIntoConstraints(val)
}

// ── 轮询（step3 验证；SSE 降级时兜底） ──
const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(async () => {
    try {
      const res: any = await getBuildProgress(jobId)
      const p = res.data
      if (job.value) {
        _applyProgress(p)
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
  job.value.step1_batches_total = p.step1_batches_total
  job.value.step1_batches_done = p.step1_batches_done
  job.value.step1_failed_batch = p.step1_failed_batch
  job.value.step2_batches_total = p.step2_batches_total
  job.value.step2_batches_done = p.step2_batches_done
  job.value.step2_failed_batch = p.step2_failed_batch
  // 预估分批数（step0 解析后预计算，前端展示用）
  job.value.estimated_step1_batches = p.estimated_step1_batches
  job.value.estimated_step2_batches = p.estimated_step2_batches
  job.value.step3_verification = p.step3_verification
  job.value.progress_stages = p.progress_stages
}

// ── SSE 实时订阅 ──
const _normName = (name: string) =>
  (name || '').trim().replace(/（/g, '(').replace(/）/g, ')').replace(/\u3000/g, ' ')

const _relKey = (r: any) => `${_normName(r.source)}|${r.relation_type}|${_normName(r.target)}`
const _etRelKey = (r: any) =>
  `${_normName(r.source_type)}|${r.relation_type}|${_normName(r.target_type)}`

const startStream = () => {
  if (disposed) return
  stopStream()
  stopPolling()
  streamRetryCount = 0
  sseAbort = streamBuildJob(jobId, {
    onParseDone: (d) => {
      // 文档解析完成：断开 SSE 并刷新任务，展示解析结果
      stopStream()
      if (job.value) {
        job.value.running_step = -1
        // 预估分批数（SSE 事件携带，loadJob 也会从详情接口拿到）
        if (d.estimated_step1_batches) job.value.estimated_step1_batches = d.estimated_step1_batches
        if (d.estimated_step2_batches) job.value.estimated_step2_batches = d.estimated_step2_batches
      }
      ElMessage.success('文档解析完成')
      loadJob()
    },
    onBatchDone: (d) => {
      if (Array.isArray(d.entity_types)) {
        const existing = new Set(entityTypes.value.map(t => _normName(t.name)).filter(Boolean))
        const fresh = (d.entity_types || []).filter((t: any) => {
          const n = _normName(t.name)
          if (!n || existing.has(n)) return false
          existing.add(n)
          return true
        }).map((t: any) => ({ ...t, review: 'pending' as ReviewStatus }))
        entityTypes.value.push(...fresh)
        if (job.value) {
          job.value.step1_batches_done = d.batches_done
          job.value.step1_batches_total = d.batches_total
        }
      }
      if (Array.isArray(d.entity_type_relations)) {
        const existRel = new Set(entityTypeRelations.value.map(_etRelKey))
        const fresh = (d.entity_type_relations || []).filter((r: any) => {
          const k = _etRelKey(r)
          if (existRel.has(k)) return false
          existRel.add(k)
          return true
        }).map((r: any) => ({ ...r, review: 'pending' as ReviewStatus }))
        entityTypeRelations.value.push(...fresh)
      }
      if (Array.isArray(d.entities)) {
        const existing = new Set(entities.value.map(e => _normName(e.name)).filter(Boolean))
        const fresh = (d.entities || []).filter((e: any) => {
          const n = _normName(e.name)
          if (!n || existing.has(n)) return false
          existing.add(n)
          return true
        }).map((e: any) => ({ ...e, review: 'pending' as ReviewStatus }))
        entities.value.push(...fresh)
        if (job.value) {
          job.value.step2_batches_done = d.batches_done
          job.value.step2_batches_total = d.batches_total
        }
      }
      if (Array.isArray(d.relations)) {
        const existRel = new Set(relations.value.map(_relKey))
        const fresh = (d.relations || []).filter((r: any) => {
          const k = _relKey(r)
          if (existRel.has(k)) return false
          existRel.add(k)
          return true
        }).map((r: any) => ({ ...r, review: 'pending' as ReviewStatus }))
        relations.value.push(...fresh)
      }
    },
    onStepDone: (d) => {
      // 步骤已完成：立即断开 SSE，避免连接残留被后续事件/回放再次触发完成提示
      stopStream()
      if (d.step === 1) {
        aiStep1Done.value = true
        if (job.value) job.value.running_step = -1
        if (Array.isArray(d.entity_types)) {
          entityTypes.value = d.entity_types.map((t: any) => ({
            ...t,
            review: 'pending' as ReviewStatus
          }))
        }
        if (Array.isArray(d.entity_type_relations)) {
          entityTypeRelations.value = d.entity_type_relations.map((r: any) => ({
            ...r,
            review: 'pending' as ReviewStatus
          }))
        }
        ElMessage.success(`本体提取完成，共 ${entityTypes.value.length} 个`)
      } else if (d.step === 2) {
        aiStep2Done.value = true
        if (job.value) job.value.running_step = -1
        if (Array.isArray(d.entities)) {
          entities.value = d.entities.map((e: any) => ({
            ...e,
            review: 'pending' as ReviewStatus
          }))
        }
        if (Array.isArray(d.relations)) {
          relations.value = d.relations.map((r: any) => ({
            ...r,
            review: 'pending' as ReviewStatus
          }))
        }
        ElMessage.success(`实体+关系提取完成，共 ${entities.value.length} 个实体/${relations.value.length} 条关系`)
      } else if (d.step === 3) {
        if (job.value) {
          job.value.running_step = -1
          if (d.verification) job.value.step3_verification = d.verification
        }
        ElMessage.success('验证完成')
      }
    },
    onError: (d) => {
      if (d.reconnect) {
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
  if (retryTimer) {
    clearTimeout(retryTimer)
    retryTimer = null
  }
  if (sseAbort) {
    sseAbort()
    sseAbort = null
  }
}

const retryStream = () => {
  if (disposed) return
  if (streamRetryCount >= STREAM_MAX_RETRY) {
    ElMessage.warning('实时连接不稳定，已切换到轮询模式')
    startPolling()
    return
  }
  streamRetryCount++
  retryTimer = setTimeout(() => {
    retryTimer = null
    startStream()
  }, 3000)
}

// ── 步骤操作 ──
// 阶段 0「文档解析」：触发后台解析任务，并订阅 SSE 等待 parse_done
const doParseDocument = async () => {
  try {
    await parseBuildJob(jobId)
    if (job.value) {
      job.value.running_step = 0
      job.value.progress_message = '正在解析文档...'
      job.value.error_message = null
    }
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动文档解析失败')
  }
}

const doConfirmMeta = async () => {
  submitting.value = true
  try {
    const fd = new FormData()
    fd.append('granularity', metaForm.value.granularity)
    if (metaForm.value.templateId) {
      fd.append('template_id', metaForm.value.templateId)
      // 载入本体模型：强制大模型按该本体模型提取
      fd.append('template_mode', 'hard_constraint')
    }
    // 同步初始类型约束（step0 提取前可调整，作为 step1 提取的起点）
    const et = constraintEntityTypes.value
      .filter((t: any) => t.name && t.name.trim())
      .map((t: any) => ({ name: t.name.trim(), color: t.color }))
    const rt = constraintRelationTypes.value
      .filter((r: any) => r.name && r.name.trim())
      .map((r: any) => ({ name: r.name.trim() }))
    fd.append('entity_types', JSON.stringify(et))
    fd.append('relation_types', JSON.stringify(rt))
    // 配置阶段的补充说明（可选），存入 stage_hints["0"] 供后续参考
    if (stageNote0.value.trim()) {
      fd.append('stage_hints', JSON.stringify({ 0: stageNote0.value.trim() }))
    }
    await confirmMetaApi(jobId, fd)
    await loadJob()
    // 二合一：确认配置后立即开始本体提取，无需再单独点击「开始提取本体」
    await doExtractEntityTypes()
    ElMessage.success('配置已确认，本体提取已开始')
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

const doExtractEntityTypes = async () => {
  try {
    // 若初始类型约束有修改，先同步到本体模型再启动提取
    if (constraintDirty.value) {
      const mfd = new FormData()
      mfd.append('granularity', job.value?.granularity || metaForm.value.granularity)
      const et = constraintEntityTypes.value
        .filter((t: any) => t.name && t.name.trim())
        .map((t: any) => ({ name: t.name.trim(), color: t.color }))
      const rt = constraintRelationTypes.value
        .filter((r: any) => r.name && r.name.trim())
        .map((r: any) => ({ name: r.name.trim() }))
      mfd.append('entity_types', JSON.stringify(et))
      mfd.append('relation_types', JSON.stringify(rt))
      if (job.value?.template_id) {
        mfd.append('template_id', job.value.template_id)
        mfd.append('template_mode', 'hard_constraint')
      }
      await confirmMetaApi(jobId, mfd)
    }
    await api.post(`/ontology/build/${jobId}/step1`)
    if (job.value) {
      job.value.running_step = 1
      job.value.progress_message = '正在准备文档...'
    }
    aiStep1Done.value = false
    ElMessage.info('本体提取已在后台开始，可实时查看提取结果')
    startStream()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '启动提取失败')
  }
}

const doConfirmEntityTypes = async () => {
  submitting.value = true
  try {
    const types = keptEntityTypes.value.map((t: any) => {
      const { review, children, ...rest } = t
      void review
      void children
      return rest
    })
    const rels = keptEntityTypeRelations.value.map((r: any) => {
      const { review, ...rest } = r
      void review
      return rest
    })
    if (!types.length) {
      ElMessage.warning('请至少保留一个实体类型')
      return
    }
    const fd = new FormData()
    fd.append('entity_types', JSON.stringify(types))
    fd.append('entity_type_relations', JSON.stringify(rels))
    await api.put(`/ontology/build/${jobId}/step1`, fd)
    ElMessage.success('实体类型已确认，正在提取实体+关系')
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

const doConfirmEntities = async () => {
  submitting.value = true
  try {
    const parsedEntities = keptEntities.value.map((e: any) => {
      const { review, ...rest } = e
      void review
      return rest
    })
    const parsedRelations = keptRelations.value.map((r: any) => {
      const { review, ...rest } = r
      void review
      return rest
    })
    if (!parsedEntities.length) {
      ElMessage.warning('请至少保留一个实体')
      return
    }
    const fd = new FormData()
    fd.append('entities', JSON.stringify(parsedEntities))
    fd.append('relations', JSON.stringify(parsedRelations))
    await api.put(`/ontology/build/${jobId}/step2`, fd)
    ElMessage.success('实体+关系已确认，正在启动验证')
    stopStream()
    await loadJob()
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '确认失败')
  } finally {
    submitting.value = false
  }
}

// 二合一：确认实体类型后立即开始实体+关系提取，无需再单独点击「开始提取」
const confirmEntityTypesAndStartNext = async () => {
  await doConfirmEntityTypes()
  await doExtractEntities()
}

// 二合一：确认实体+关系后立即启动验证，无需再单独点击「启动验证」
const confirmEntitiesAndStartVerify = async () => {
  await doConfirmEntities()
  await doVerify()
}

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

// ── 返工 ──
const openRework = (step: number) => {
  reworkTargetStep.value = step
  reworkPrompt.value = ''
  reworkDialogVisible.value = true
}

const doRework = async () => {
  reworkSubmitting.value = true
  try {
    await triggerRework(reworkTargetStep.value, reworkPrompt.value || '')
    ElMessage.success(`step${reworkTargetStep.value} 重新生成已开始，结果将被替换`)
    reworkDialogVisible.value = false
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '重新生成失败')
  } finally {
    reworkSubmitting.value = false
  }
}

const triggerRework = async (step: number, promptText: string) => {
  const fd = new FormData()
  fd.append('prompt', promptText || '')
  await reworkBuildStep(jobId, step, fd)
  await loadJob()
  const rs = job.value?.running_step
  if (rs >= 1 && rs <= 2) {
    aiStep1Done.value = rs < 1
    aiStep2Done.value = rs < 2
    if (rs === 1) {
      entityTypes.value = []
      entityTypeRelations.value = []
    } else if (rs === 2) {
      entities.value = []
      relations.value = []
    }
    startStream()
  } else if (rs === 3) {
    job.value.step3_verification = null
    startPolling()
  }
}

// 发送修改意见给 AI 重新生成当前阶段结果（确认进入下一阶段已抽离为独立按钮）
const sendFeedback = async (step: 1 | 2 | 3) => {
  const feedback = (stageFeedback.value[step] || '').trim()
  if (!feedback) {
    ElMessage.warning('请输入修改意见')
    return
  }
  submitting.value = true
  try {
    await triggerRework(step, feedback)
    stageFeedback.value[step] = ''
    ElMessage.success(`已携带您的修改意见重新执行阶段 ${step}，请审阅新结果`)
  } catch (e: any) {
    ElMessage.error(e.serverMessage || '重新生成失败')
  } finally {
    submitting.value = false
  }
}

// ── 编辑器保存 ──
const addConstraintRelationType = () => {
  const name = newConstraintRelationType.value.trim()
  if (!name) return
  constraintRelationTypes.value.push({ name })
  newConstraintRelationType.value = ''
}

const openTypeEditor = (t?: any) => {
  if (t) {
    const idx = entityTypes.value.findIndex(x => x.name === t.name)
    typeEditor.value = {
      visible: true,
      mode: 'edit',
      index: idx,
      name: t.name || '',
      description: t.description || '',
      color: t.color || '#5470c6',
      parent_entity_type_name: t.parent_entity_type_name || '',
      schema: JSON.parse(JSON.stringify(t.property_schema || []))
    }
  } else {
    typeEditor.value = {
      visible: true,
      mode: 'add',
      index: -1,
      name: '',
      description: '',
      color: '#5470c6',
      parent_entity_type_name: '',
      schema: []
    }
  }
}

const saveType = () => {
  const name = typeEditor.value.name.trim()
  if (!name) {
    ElMessage.warning('请填写类型名称')
    return
  }
  const data = {
    name,
    description: typeEditor.value.description.trim(),
    color: typeEditor.value.color,
    parent_entity_type_name: typeEditor.value.parent_entity_type_name,
    property_schema: typeEditor.value.schema
  }
  if (typeEditor.value.mode === 'add') {
    entityTypes.value.push({ ...data, review: 'approved' as ReviewStatus })
  } else {
    Object.assign(entityTypes.value[typeEditor.value.index], data, { review: 'approved' as ReviewStatus })
  }
  typeEditor.value.visible = false
}

const removeType = (data: any) => {
  const idx = entityTypes.value.findIndex(t => t.name === data.name)
  if (idx >= 0) entityTypes.value.splice(idx, 1)
}

const removeEntity = (e: any) => {
  const idx = entities.value.indexOf(e)
  if (idx >= 0) entities.value.splice(idx, 1)
}

const removeRelation = (r: any) => {
  const idx = relations.value.indexOf(r)
  if (idx >= 0) relations.value.splice(idx, 1)
}

const openEntityEditor = (e?: any) => {
  if (e) {
    entityEditor.value = {
      visible: true,
      index: entities.value.indexOf(e),
      name: e.name || '',
      instance_of: e.instance_of || '',
      properties: JSON.parse(JSON.stringify(e.properties || [])),
      source_snippet: e.source_snippet || '',
      description: e.description || ''
    }
  } else {
    entityEditor.value = {
      visible: true,
      index: -1,
      name: '',
      instance_of: keptEntityTypes.value[0]?.name || '',
      properties: [],
      source_snippet: '',
      description: ''
    }
  }
}

const addEntityToType = (typeName: string) => {
  entityEditor.value = {
    visible: true,
    index: -1,
    name: '',
    instance_of: typeName,
    properties: [],
    source_snippet: '',
    description: ''
  }
}

const saveEntity = () => {
  const name = entityEditor.value.name.trim()
  if (!name) {
    ElMessage.warning('请填写实体名称')
    return
  }
  if (!entityEditor.value.instance_of) {
    ElMessage.warning('请选择所属类型')
    return
  }
  const data = {
    name,
    instance_of: entityEditor.value.instance_of,
    properties: entityEditor.value.properties,
    source_snippet: entityEditor.value.source_snippet.trim(),
    description: entityEditor.value.description.trim()
  }
  if (entityEditor.value.index >= 0) {
    Object.assign(entities.value[entityEditor.value.index], data, { review: 'approved' as ReviewStatus })
  } else {
    entities.value.push({ ...data, review: 'approved' as ReviewStatus })
  }
  entityEditor.value.visible = false
}

const openRelationEditor = (r?: any) => {
  if (r) {
    relationEditor.value = {
      visible: true,
      index: relations.value.indexOf(r),
      source: r.source || '',
      relation_type: r.relation_type || '',
      target: r.target || '',
      weight: typeof r.weight === 'number' ? r.weight : 1,
      source_snippet: r.source_snippet || '',
      description: r.description || ''
    }
  } else {
    relationEditor.value = {
      visible: true,
      index: -1,
      source: keptEntities.value[0]?.name || '',
      relation_type: '',
      target: '',
      weight: 1,
      source_snippet: '',
      description: ''
    }
  }
}

const saveRelation = () => {
  const { source, relation_type, target } = relationEditor.value
  if (!source || !target) {
    ElMessage.warning('请选择源实体与目标实体')
    return
  }
  if (!relation_type.trim()) {
    ElMessage.warning('请填写关系类型')
    return
  }
  const data = {
    source,
    relation_type: relation_type.trim(),
    target,
    weight: relationEditor.value.weight,
    source_snippet: relationEditor.value.source_snippet.trim(),
    description: relationEditor.value.description.trim()
  }
  if (relationEditor.value.index >= 0) {
    Object.assign(relations.value[relationEditor.value.index], data, { review: 'approved' as ReviewStatus })
  } else {
    relations.value.push({ ...data, review: 'approved' as ReviewStatus })
  }
  relationEditor.value.visible = false
}

const openETRelationEditor = (r?: any) => {
  if (r) {
    etRelationEditor.value = {
      visible: true,
      index: entityTypeRelations.value.indexOf(r),
      source_type: r.source_type || '',
      relation_type: r.relation_type || '',
      target_type: r.target_type || '',
      description: r.description || ''
    }
  } else {
    etRelationEditor.value = {
      visible: true,
      index: -1,
      source_type: keptEntityTypes.value[0]?.name || '',
      relation_type: '',
      target_type: '',
      description: ''
    }
  }
}

const saveETRelation = () => {
  const { source_type, relation_type, target_type } = etRelationEditor.value
  if (!source_type || !target_type) {
    ElMessage.warning('请选择源类型与目标类型')
    return
  }
  if (!relation_type.trim()) {
    ElMessage.warning('请填写关系类型')
    return
  }
  const data = {
    source_type,
    relation_type: relation_type.trim(),
    target_type,
    description: etRelationEditor.value.description.trim()
  }
  if (etRelationEditor.value.index >= 0) {
    Object.assign(entityTypeRelations.value[etRelationEditor.value.index], data, { review: 'approved' as ReviewStatus })
  } else {
    entityTypeRelations.value.push({ ...data, review: 'approved' as ReviewStatus })
  }
  etRelationEditor.value.visible = false
}

const removeEntityTypeRelation = (r: any) => {
  const idx = entityTypeRelations.value.indexOf(r)
  if (idx >= 0) entityTypeRelations.value.splice(idx, 1)
}

// ── 导航 / 刷新 ──
const viewOntology = () => {
  if (job.value?.ontology_id) {
    router.push(`/ontology/${job.value.ontology_id}`)
  } else {
    goBack()
  }
}

const refreshAll = async () => {
  loading.value = true
  stopStream()
  stopPolling()
  await loadJob()
  const rs = job.value?.running_step
  if (rs >= 1 && rs <= 2) {
    startStream()
  } else if (rs === 3) {
    startPolling()
  }
  loading.value = false
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
  // 窄屏默认收起原文面板，聚焦审阅区
  if (window.matchMedia('(max-width: 1280px)').matches) {
    docCollapsed.value = true
  }
  loading.value = true
  await Promise.all([loadJob(), loadTemplates()])
  loading.value = false

  if (job.value?.step1_entity_types?.length && !job.value?.step1_confirmed) {
    aiStep1Done.value = true
  }
  if (job.value?.step2_entities?.length && !job.value?.step2_confirmed) {
    aiStep2Done.value = true
  }

  const rs = job.value?.running_step
  if (rs >= 1 && rs <= 2) {
    startStream()
  } else if (rs === 3) {
    startPolling()
  } else if (rs === 0) {
    // 文档解析进行中（如刷新页面）：订阅 SSE 等待 parse_done
    startStream()
  } else if (!job.value?.source_text && !job.value?.meta_confirmed && !job.value?.error_message) {
    // 首次进入阶段 0：自动触发文档解析
    doParseDocument()
  }
})

onUnmounted(() => {
  disposed = true
  stopStream()
  stopPolling()
})
</script>

<style scoped>
.ontology-build {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 1.25rem;
  overflow: hidden;
}

.build-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1rem;
  flex-shrink: 0;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

.header-left h2 {
  margin: 0;
  color: var(--text-primary);
  font-size: 1.25rem;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.status-bar {
  padding: 0.9rem 1.25rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  margin-bottom: 1rem;
  flex-shrink: 0;
}

/* 步骤条：可点击回看已完成步骤 */
.step-clickable {
  cursor: pointer;
}

.step-clickable:hover :deep(.el-step__head) {
  transform: scale(1.04);
  transition: transform 0.15s ease;
}

.build-steps {
  margin: 0;
}

/* 步骤条数字：当前步骤蓝色，其余黑色（覆盖 Element 默认绿对勾/灰数字） */
.build-steps :deep(.el-step__head.is-process .el-step__icon) {
  background: var(--primary-500, #409eff);
  border-color: var(--primary-500, #409eff);
  color: #fff;
}
.build-steps :deep(.el-step__head.is-process .el-step__title) {
  color: var(--primary-500, #409eff);
}
.build-steps :deep(.el-step__head.is-wait .el-step__icon) {
  background: #fff;
  border-color: #c0c4cc;
  color: #303133;
}
.build-steps :deep(.el-step__head.is-wait .el-step__title) {
  color: #303133;
}

/* ── 工作台：左原文 / 右审阅 ── */
.workspace {
  flex: 1;
  min-height: 0;
  display: grid;
  gap: 0.5rem;
  transition: grid-template-columns 0.2s ease;
}

.workspace.resizing {
  transition: none;
  user-select: none;
  cursor: col-resize;
}

.doc-resizer {
  width: 6px;
  cursor: col-resize;
  border-radius: 3px;
  transition: background 0.15s ease;
}

.doc-resizer:hover,
.workspace.resizing .doc-resizer {
  background: var(--primary-300, #79bbff);
}

.doc-pane {
  min-height: 0;
  display: flex;
  flex-direction: column;
  background: white;
  border-radius: 10px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.doc-pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color, #e4e7ed);
}

.doc-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  font-size: 0.9rem;
  color: var(--text-primary);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-chars {
  font-size: 0.75rem;
  color: var(--text-secondary, #909399);
  white-space: nowrap;
}

.doc-toolbar {
  display: flex;
  gap: 0.5rem;
  padding: 0.6rem 1rem;
  border-bottom: 1px solid var(--border-color, #e4e7ed);
}

.doc-toolbar .el-input {
  flex: 1;
}

.doc-nav {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.35rem 1rem;
  border-bottom: 1px solid var(--border-color, #e4e7ed);
  background: var(--bg-secondary, #f8f9fb);
  font-size: 0.78rem;
}

.doc-match-count {
  color: var(--text-secondary, #606266);
  min-width: 40px;
  text-align: center;
}

.doc-text {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  font-size: 0.82rem;
  line-height: 1.9;
  color: var(--text-primary, #303133);
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--bg-secondary, #fafbfc);
}

.doc-hl {
  background: #ffe58f;
  border-radius: 3px;
  padding: 1px 2px;
  box-shadow: 0 0 0 2px rgba(255, 229, 143, 0.5);
}

.review-pane {
  min-height: 0;
  overflow-y: auto;
  padding-right: 2px;
}

.step-panel {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.step-card {
  border-radius: 10px;
}

/* 阶段 0 文档解析状态 */
.parse-progress {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: var(--primary-500, #409eff);
  font-size: 0.9rem;
}
.parse-done p,
.parse-pending p {
  margin: 0;
  color: #606266;
  font-size: 0.9rem;
}
.parse-done strong {
  color: #303133;
}
.batch-hint {
  margin-top: 0.25rem !important;
  color: #909399 !important;
  font-size: 0.85rem !important;
}

.step-card :deep(.el-card__body) {
  padding: 1.25rem;
}

.step-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
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

.step-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.75rem;
  margin-top: 1rem;
}

/* 确认按钮旁的待审提示 */
.pending-hint {
  font-size: 0.78rem;
  color: var(--el-color-warning, #e6a23c);
  align-self: center;
}

/* 配置 */
.granularity-section {
  padding: 1rem 1.25rem;
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e4e7ed);
}

.granularity-row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.9rem;
  flex-wrap: wrap;
}

.granularity-row:last-child {
  margin-bottom: 0;
}

.granularity-label {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}

.template-hint {
  font-size: 0.75rem;
  color: #e6a23c;
  white-space: nowrap;
}

.meta-block {
  margin-bottom: 1.25rem;
}

.meta-block:last-child {
  margin-bottom: 0;
}

.meta-block h4 {
  margin: 0 0 0.6rem;
  font-size: 0.92rem;
  font-weight: 600;
  color: var(--text-primary);
}

.meta-type-row {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 0.5rem;
}

.meta-index {
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: var(--bg-secondary, #f0f2f5);
  color: var(--text-secondary, #909399);
  font-size: 0.72rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.meta-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
}

.meta-add-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* 阶段底部输入条（指标分析样式）：意见输入 + 确认按钮一体 */
.stage-input-area {
  margin-top: 1.25rem;
}

.stage-input-wrapper {
  position: relative;
}

.stage-input-wrapper :deep(.el-textarea__inner) {
  border-radius: 16px;
  border-color: var(--border-normal);
  padding: 14px 120px 14px 18px;
  font-size: 15px;
  line-height: 1.6;
  transition: all 0.2s;
  background: var(--gray-50);
  resize: none;
}

.stage-input-wrapper :deep(.el-textarea__inner:hover) {
  border-color: var(--primary-400);
  background: white;
}

.stage-input-wrapper :deep(.el-textarea__inner:focus) {
  border-color: var(--primary-500);
  background: white;
  box-shadow: 0 0 0 4px rgba(59, 130, 246, 0.1);
}

.stage-input-actions {
  position: absolute;
  bottom: 14px;
  right: 16px;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  align-items: center;
}

.stage-input-actions .el-button {
  height: 38px;
  padding: 0 22px;
  border-radius: 10px;
  font-weight: 500;
  font-size: 14px;
}

/* 阶段确认按钮区（输入条下方独立按钮，确认通过进入下一阶段） */
.stage-confirm-area {
  margin-top: 0.75rem;
  display: flex;
  justify-content: flex-end;
}

.resume-section,
.waiting-section,
.generate-section,
.review-section,
.verify-section {
  padding: 0.25rem 0;
}

/* 审阅 */
.review-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1.25rem;
  padding: 0.7rem 1rem;
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  border: 1px solid var(--border-color, #e4e7ed);
}

.review-label {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text-primary);
  white-space: nowrap;
}

.review-count {
  font-size: 0.8rem;
  color: var(--text-secondary, #606266);
  white-space: nowrap;
}

.review-block {
  margin-bottom: 1.5rem;
}

.review-block h4 {
  margin: 0 0 0.7rem;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 0.35rem;
}

/* 审阅块标题行：标题 + 全部展开/收起 */
.review-block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.7rem;
}

.review-block-head h4 {
  margin: 0;
}

/* 批量操作栏：勾选树节点后出现 */
.batch-bar {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.6rem;
  padding: 0.45rem 0.75rem;
  background: var(--primary-100, #ecf5ff);
  border: 1px solid var(--primary-200, #b3d8ff);
  border-radius: 8px;
  font-size: 0.82rem;
}

.batch-label {
  font-weight: 500;
  color: var(--primary-500, #409eff);
  margin-right: auto;
}

.review-block :deep(.el-tree) {
  background: var(--bg-secondary, #f5f7fa);
  border-radius: 8px;
  padding: 0.75rem;
  border: 1px solid var(--border-color, #e4e7ed);
}

.review-block :deep(.el-tree-node__content) {
  height: auto;
  min-height: 32px;
  padding: 0.2rem 0;
}

.et-tree-node {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex: 1;
  min-width: 0;
  flex-wrap: wrap;
}

.et-tree-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.et-tree-name {
  font-weight: 500;
  color: var(--text-primary);
}

.et-tree-desc {
  font-size: 0.78rem;
  color: var(--text-secondary, #909399);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.et-tree-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 0.2rem;
  flex-shrink: 0;
}

.entity-view-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 0.75rem;
  flex-wrap: wrap;
}

.concept-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  margin-right: 0.4rem;
  display: inline-block;
}

.concept-name {
  font-weight: 500;
  margin-right: 0.5rem;
}

.prop-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.3rem;
}

/* 展开行：全部属性 / 描述 / 出处 */
.entity-expand {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.5rem 1.5rem 0.6rem 3rem;
  font-size: 0.82rem;
  line-height: 1.7;
}

.entity-expand-row {
  display: flex;
  align-items: flex-start;
  gap: 0.6rem;
}

.entity-expand-label {
  flex-shrink: 0;
  min-width: 64px;
  font-weight: 500;
  color: var(--text-secondary, #606266);
  padding-top: 1px;
}

.source-cell {
  display: flex;
  align-items: flex-start;
  gap: 0.3rem;
}

.source-snippet {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.entity-name-cell {
  font-weight: 500;
}

.entity-type-cell {
  font-weight: 500;
}

.rejected-block {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
  margin-top: 1rem;
  padding: 0.7rem 1rem;
  background: var(--el-color-danger-light-9, #fef0f0);
  border-radius: 8px;
  border: 1px dashed var(--el-color-danger-light-5, #fbc4c4);
}

.rejected-title {
  font-size: 0.82rem;
  font-weight: 500;
  color: var(--el-color-danger, #f56c6c);
}

.complete-content {
  text-align: center;
  padding: 2rem 0;
}

.complete-content h3 {
  margin: 0.75rem 0 0;
  font-size: 1.15rem;
  color: var(--text-primary);
}

.success-icon {
  font-size: 56px;
  color: var(--el-color-success, #67c23a);
}

.schema-editor {
  width: 100%;
}

.source-edit {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  align-items: flex-start;
}
</style>
