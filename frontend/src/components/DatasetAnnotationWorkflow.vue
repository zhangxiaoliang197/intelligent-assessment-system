<template>
  <el-dialog
    v-model="visible"
    :title="`数据集注解：${datasetTitle}`"
    width="92%"
    top="4vh"
    destroy-on-close
    class="wf-dialog"
    @closed="reset"
  >
    <!-- 步骤条：3 步，第 1 步可跳过 -->
    <el-steps :active="step" simple class="wf-steps">
      <el-step title="识别" description="可选，AI 建议" />
      <el-step title="注解" description="按需填写" />
      <el-step title="校验保存" />
    </el-steps>

    <div class="wf-meta">
      <span>数据源：<b>{{ databaseName }}</b></span>
      <span>数据表：<b>{{ dataset?.tableName || '-' }}</b></span>
      <span>字段：<b>{{ columns.length }}</b></span>
      <span>当前状态：<b>{{ validatedText }}</b></span>
      <el-tag v-if="structureError" type="warning" size="small">{{ structureError }}</el-tag>
    </div>

    <!-- ── 步骤 1：识别（可选）── -->
    <div v-show="step === 0" class="wf-body">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="打开弹框不会自动调用 AI；需要建议时请手动点击「生成建议」。不生成也可以直接进入下一步手工填写。"
      />
      <div class="wf-toolbar">
        <el-button size="small" :loading="loading" @click="loadStructure">刷新表结构</el-button>
        <el-button size="small" type="primary" :loading="draftGenerating" @click="generateDrafts">
          生成建议
        </el-button>
        <el-button size="small" @click="step = 1">跳过识别</el-button>
        <span class="wf-hint">建议只写入本地表单，不会直接生效</span>
      </div>

      <el-table :data="columns" size="small" stripe max-height="240" class="wf-table">
        <el-table-column prop="columnName" label="字段" width="170" />
        <el-table-column prop="dataType" label="类型" width="120" />
        <el-table-column prop="comment" label="数据库注释" min-width="200" />
        <el-table-column label="当前角色" width="120">
          <template #default="{ row }">{{ roleLabel(row.role) || '未设置' }}</template>
        </el-table-column>
      </el-table>

      <div class="wf-section-title">
        AI 建议
        <span class="wf-hint" v-if="!drafts.length">暂无建议，点上方「生成建议」</span>
      </div>

      <el-empty v-if="!drafts.length" description="暂无待审草稿" :image-size="60" />
      <div v-for="item in drafts" :key="item.id" :class="['wf-card', { 'wf-card-ignored': ignoredIds.includes(item.id) }]">
        <div class="wf-card-head">
          <el-tag size="small" effect="plain" :type="item.scope === 'dataset' ? 'warning' : 'info'">
            {{ item.scope === 'dataset' ? '数据集级' : `字段 ${item.columnName}` }}
          </el-tag>
          <el-tag v-if="adoptedIds.includes(item.id)" size="small" type="success">已采纳</el-tag>
          <el-tag v-if="ignoredIds.includes(item.id)" size="small" type="info">已忽略</el-tag>
          <span class="wf-hint">来源 {{ item.source }}｜模型 {{ item.model || '-' }}</span>
          <div class="wf-card-actions">
            <el-button size="small" type="success" plain :disabled="hasIssues(item) || ignoredIds.includes(item.id)"
                       @click="adoptDraft(item)">采纳</el-button>
            <el-button size="small" plain :disabled="ignoredIds.includes(item.id)"
                       @click="ignoreDraft(item)">忽略</el-button>
          </div>
        </div>
        <div class="wf-card-body">
          <div v-for="(line, idx) in draftSummary(item)" :key="idx" class="wf-line">・{{ line }}</div>
          <div v-if="draftSamples(item).length" class="wf-line wf-hint">
            真实取值：{{ draftSamples(item).join('、') }}
          </div>
          <div v-if="hasIssues(item)" class="wf-error">
            <div v-for="(issue, idx) in parseList(item.issuesJson)" :key="idx">✕ {{ issue }}</div>
          </div>
          <div v-for="(warn, idx) in parseList(item.warningsJson)" :key="'w' + idx" class="wf-warn">! {{ warn }}</div>
        </div>
        <el-collapse class="wf-json">
          <el-collapse-item title="技术详情（JSON）">
            <pre>{{ prettyJson(item.draftJson) }}</pre>
          </el-collapse-item>
        </el-collapse>
      </div>
    </div>

    <!-- ── 步骤 2：注解 ── -->
    <div v-show="step === 1" class="wf-body wf-two-col">
      <div class="wf-left">
        <div class="wf-toolbar">
          <el-radio-group v-model="fieldFilter" size="small">
            <el-radio-button label="focus">需关注</el-radio-button>
            <el-radio-button label="all">全部字段</el-radio-button>
          </el-radio-group>
          <span class="wf-hint">默认只列已设置、有建议或有告警的字段</span>
        </div>
        <el-table :data="visibleColumns" size="small" stripe max-height="440" class="wf-table">
          <el-table-column label="字段" width="150">
            <template #default="{ row }">
              <div>{{ row.columnName }}</div>
              <div class="wf-hint">{{ row.comment }}</div>
            </template>
          </el-table-column>
          <el-table-column label="角色" width="150">
            <template #default="{ row }">
              <el-select v-model="row.role" size="small" clearable placeholder="未设置"
                         style="width:100%" @change="markDirty(row)">
                <el-option v-for="r in ROLE_OPTIONS" :key="r.value" :label="r.label" :value="r.value" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="值映射/别名" width="130">
            <template #default="{ row }">
              <el-button size="small" text type="primary" @click="openMapping(row)">
                编辑<template v-if="Object.keys(row.values).length">（{{ Object.keys(row.values).length }}）</template>
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="符号" width="120">
            <template #default="{ row }">
              <el-select v-model="row.symbol" size="small" clearable placeholder="默认" style="width:100%"
                         @change="markDirty(row)">
                <el-option v-for="s in SYMBOL_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="单位" width="90">
            <template #default="{ row }">
              <el-input v-model="row.unit" size="small" placeholder="如 km" @change="markDirty(row)" />
            </template>
          </el-table-column>
          <el-table-column label="提示" min-width="160">
            <template #default="{ row }">
              <div v-for="(warn, idx) in columnWarnings(row)" :key="idx" class="wf-warn">! {{ warn }}</div>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!visibleColumns.length" description="没有需要关注的字段，可切换「全部字段」" :image-size="60" />
      </div>

      <div class="wf-right">
        <div class="wf-section-title">数据集语义</div>
        <el-form label-width="92px" size="small">
          <el-form-item label="实体大类">
            <el-select v-model="semanticForm.entityKind" clearable placeholder="未设置" style="width:100%">
              <el-option v-for="k in ENTITY_KIND_OPTIONS" :key="k.value" :label="k.label" :value="k.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="默认符号">
            <el-select v-model="semanticForm.symbolDefault" clearable placeholder="未设置" style="width:100%">
              <el-option v-for="s in SYMBOL_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
            </el-select>
          </el-form-item>

          <template v-if="showGeo || showAllConfig">
            <el-form-item label="经度列">
              <el-select v-model="semanticForm.lngColumn" clearable placeholder="选择经度字段" style="width:100%">
                <el-option v-for="c in geoCandidates" :key="c.columnName" :label="columnLabel(c)" :value="c.columnName" />
              </el-select>
            </el-form-item>
            <el-form-item label="纬度列">
              <el-select v-model="semanticForm.latColumn" clearable placeholder="选择纬度字段" style="width:100%">
                <el-option v-for="c in latCandidates" :key="c.columnName" :label="columnLabel(c)" :value="c.columnName" />
              </el-select>
            </el-form-item>
            <el-form-item label="半径列">
              <el-select v-model="semanticForm.radiusColumn" clearable placeholder="可选" style="width:100%">
                <el-option v-for="c in columns" :key="c.columnName" :label="columnLabel(c)" :value="c.columnName" />
              </el-select>
            </el-form-item>
          </template>

          <template v-if="showTime || showAllConfig">
            <el-form-item label="事件时间">
              <el-select v-model="semanticForm.eventTimeColumn" clearable placeholder="选择事件时间列" style="width:100%">
                <el-option v-for="c in timeCandidates" :key="c.columnName" :label="columnLabel(c)" :value="c.columnName" />
              </el-select>
            </el-form-item>
          </template>

          <template v-if="showTrack || showAllConfig">
            <el-form-item label="航迹拆分键">
              <el-select v-model="semanticForm.trackGroupKey" multiple clearable placeholder="实体编号 + 任务编号"
                         style="width:100%">
                <el-option v-for="c in idCandidates" :key="c.columnName" :label="columnLabel(c)" :value="c.columnName" />
              </el-select>
            </el-form-item>
          </template>

          <el-form-item label="配置范围">
            <el-switch v-model="showAllConfig" size="small" active-text="显示全部项" inactive-text="仅显示推荐项" />
          </el-form-item>
          <el-form-item v-if="!showGeo && !showAllConfig" label="坐标">
            <span class="wf-hint">未发现坐标候选列，可打开「显示全部项」手动选择</span>
          </el-form-item>
        </el-form>

        <div class="wf-preview">
          <div class="wf-section-title">配置预览</div>
          <div v-if="semanticForm.lngColumn && semanticForm.latColumn" class="wf-line">
            地图：按坐标标点（{{ semanticForm.lngColumn }} / {{ semanticForm.latColumn }}）
          </div>
          <div v-else class="wf-line wf-hint">未配置坐标，页面不会出现地图</div>
          <div v-if="semanticForm.eventTimeColumn" class="wf-line">
            时间轴：按 {{ semanticForm.eventTimeColumn }} 聚合
          </div>
          <div v-if="semanticForm.entityKind" class="wf-line">
            实体：{{ entityKindLabel(semanticForm.entityKind) }}
          </div>
        </div>
      </div>
    </div>

    <!-- ── 步骤 3：校验与保存 ── -->
    <div v-show="step === 2" class="wf-body">
      <div class="wf-toolbar">
        <el-button size="small" :loading="validating" @click="validateAnnotations">校验</el-button>
        <span class="wf-hint">校验不通过的结构错误会阻止保存</span>
      </div>

      <el-alert v-if="expired" type="warning" :closable="false" show-icon
                title="表结构自上次校验后已变化，建议复核注解" />
      <div v-for="(err, idx) in validateErrors" :key="'e' + idx" class="wf-error">✕ {{ err }}</div>
      <div v-for="(warn, idx) in validateWarnings" :key="'w' + idx" class="wf-warn">! {{ warn }}</div>

      <div class="wf-section-title">保存前差异</div>
      <div class="wf-line">
        字段：修改 {{ diff.changed }} 个、新增 {{ diff.added }} 个、清除 {{ diff.cleared }} 个；
        数据集语义：{{ diff.semanticChanged ? '有变更' : '未变更' }}
      </div>
      <div v-if="adoptedIds.length" class="wf-line wf-warn">
        本次采纳了 {{ adoptedIds.length }} 条 AI 建议，保存时会先通过对应草稿
      </div>

      <el-collapse class="wf-json">
        <el-collapse-item title="技术详情（JSON）">
          <div class="wf-hint">数据集语义（保存时将写入）：</div>
          <pre>{{ prettyJson(buildDatasetSemantic()) }}</pre>
          <div class="wf-hint" style="margin-top:8px">字段语义：</div>
          <pre>{{ fieldJsonPreview }}</pre>
          <el-input v-model="datasetJsonDraft" type="textarea" :rows="4" placeholder="可编辑数据集语义 JSON 后点「按 JSON 应用」" />
          <el-button size="small" style="margin-top:6px" @click="applyDatasetJson">按 JSON 应用</el-button>
        </el-collapse-item>
      </el-collapse>
    </div>

    <!-- 值映射编辑弹窗 -->
    <el-dialog v-model="mappingVisible" :title="`值映射：${mappingColumn?.columnName || ''}`" width="560px"
               append-to-body>
      <div class="wf-hint" style="margin-bottom:8px">
        原始值必须来自真实数据；含义用于页面展示与筛选。左列可编辑，右列必填。
      </div>
      <div v-if="mappingColumn?.sampled?.length" class="wf-samples">
        真实采样：
        <el-tag v-for="v in mappingColumn.sampled" :key="v" size="small" class="wf-sample-tag"
                @click="addMappingRow(v)">{{ v }}</el-tag>
      </div>
      <el-table :data="mappingRows" size="small" max-height="260">
        <el-table-column label="原始值" width="200">
          <template #default="{ row }">
            <el-input v-model="row.raw" size="small" placeholder="如 红方" />
          </template>
        </el-table-column>
        <el-table-column label="含义" min-width="180">
          <template #default="{ row }">
            <el-input v-model="row.label" size="small" placeholder="如 我方" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70">
          <template #default="{ $index }">
            <el-button size="small" text type="danger" @click="mappingRows.splice($index, 1)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="wf-toolbar" style="margin-top:8px">
        <el-button size="small" @click="mappingRows.push({ raw: '', label: '' })">新增一行</el-button>
        <el-button v-for="preset in MAPPING_PRESETS" :key="preset" size="small" plain
                   @click="addMappingRow(preset)">{{ preset }}</el-button>
      </div>
      <template #footer>
        <el-button size="small" @click="mappingVisible = false">取消</el-button>
        <el-button size="small" type="primary" @click="applyMapping">确定</el-button>
      </template>
    </el-dialog>

    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button v-if="step > 0" @click="step -= 1">上一步</el-button>
      <el-button v-if="step < 2" type="primary" @click="step += 1">下一步</el-button>
      <el-button v-if="step === 2" type="primary" :loading="saving" @click="saveAll">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
// 数据集注解工作流：3 步（识别可跳过）→ 注解 → 校验保存。
// 打开时不自动调用 AI；AI 建议只写入本地表单，不直接生效。
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/services/api'

const props = defineProps<{
  modelValue: boolean
  dataset: any
  databases?: any[]
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', value: boolean): void
  (e: 'saved'): void
}>()

// ── 常量：与 semantic-schema.json 保持一致 ──
const ROLE_OPTIONS = [
  { label: '标识', value: 'id' },
  { label: '名称', value: 'name' },
  { label: '时间', value: 'time' },
  { label: '经度', value: 'lng' },
  { label: '纬度', value: 'lat' },
  { label: '半径', value: 'radius' },
  { label: '序号', value: 'seq' },
  { label: '度量', value: 'measure' },
  { label: '维度', value: 'dimension' },
  { label: '状态', value: 'status' },
  { label: '高度', value: 'altitude' },
  { label: '速度', value: 'speed' },
  { label: '航向', value: 'heading' },
]

const SYMBOL_OPTIONS = [
  { label: '战斗机', value: 'fighter' }, { label: '预警机', value: 'awacs' },
  { label: '侦察机', value: 'recon' }, { label: '轰炸机', value: 'bomber' },
  { label: '基地', value: 'base' }, { label: '防空阵地', value: 'sam' },
  { label: '雷达', value: 'radar' }, { label: '岸舰阵地', value: 'coastal' },
  { label: '指挥所', value: 'flag' }, { label: '仓库', value: 'depot' },
  { label: '油库', value: 'fuel' }, { label: '港口', value: 'anchor' },
  { label: '机场跑道', value: 'runway' }, { label: '通信塔', value: 'tower' },
  { label: '打击', value: 'boom' }, { label: '摧毁', value: 'cross' },
  { label: '侦察发现', value: 'magnifier' }, { label: '范围', value: 'ring' },
  { label: '圆点', value: 'dot' },
]

// 实体大类：原有 4 类 + 新增 6 类
const ENTITY_KIND_OPTIONS = [
  { label: '空中目标', value: 'air' },
  { label: '基地', value: 'base' },
  { label: '地面设施', value: 'ground_facility' },
  { label: '部队单位', value: 'unit' },
  { label: '人员', value: 'person' },
  { label: '组织机构', value: 'organization' },
  { label: '任务/行动', value: 'task' },
  { label: '区域', value: 'area' },
  { label: '物资/装备', value: 'resource' },
  { label: '其他', value: 'other' },
]

// 画像内部类型 → 注解可选值（避免把 platform_air 等内部值写进注解）
const KIND_COMPAT: Record<string, string> = {
  platform_air: 'air', platform_ground: 'other', platform_sea: 'other',
  facility: 'ground_facility', sensor: 'ground_facility',
  unit: 'unit', person: 'person', organization: 'organization',
  task: 'task', area: 'area', resource: 'resource',
  event: 'other', target: 'other', threat: 'other', other: 'other',
  air: 'air', base: 'base', ground_facility: 'ground_facility',
}

const MAPPING_PRESETS = ['红方', '蓝方', '我方', '敌方', '中立', '未知']

interface ColumnRow {
  columnName: string
  dataType: string
  comment: string
  isPrimaryKey: boolean
  isNullable: boolean
  annotation: string
  businessMeaning: string
  dataCategory: string
  role: string
  symbol: string
  unit: string
  values: Record<string, string>
  synonyms: Record<string, string>
  rawSemantic: Record<string, any>
  rawSemanticText: string
  dirty: boolean
  sampled: string[]
}

// ── 基础状态 ──
const step = ref(0)
const loading = ref(false)
const structureError = ref('')
const columns = ref<ColumnRow[]>([])
const datasetTitle = computed(() => props.dataset?.name || props.dataset?.tableName || '')
const databaseName = computed(() => {
  const db = (props.databases || []).find((d: any) => d.id === props.dataset?.databaseId)
  return db?.name || props.dataset?.databaseId || '未关联'
})
const validatedText = computed(() => {
  const at = props.dataset?.annotationValidatedAt
  return at ? `已校验 ${String(at).replace('T', ' ').slice(5, 16)}` : '未校验'
})

const visible = computed({
  get: () => props.modelValue,
  set: (value: boolean) => emit('update:modelValue', value),
})

// ── 数据集语义表单 ──
const semanticForm = reactive({
  entityKind: '',
  symbolDefault: '',
  eventTimeColumn: '',
  trackGroupKey: [] as string[],
  lngColumn: '',
  latColumn: '',
  radiusColumn: '',
})
const rawDatasetSemantic = ref<Record<string, any>>({})
const rawDatasetText = ref('')
const datasetJsonDraft = ref('')
const showAllConfig = ref(false)

// ── 字段筛选 ──
const fieldFilter = ref<'focus' | 'all'>('focus')

// ── AI 草稿 ──
const drafts = ref<any[]>([])
const adoptedIds = ref<string[]>([])
const ignoredIds = ref<string[]>([])
const draftGenerating = ref(false)

// ── 校验与保存 ──
const validating = ref(false)
const saving = ref(false)
const validateErrors = ref<string[]>([])
const validateWarnings = ref<string[]>([])
const expired = ref(false)

// ── 值映射弹窗 ──
const mappingVisible = ref(false)
const mappingColumn = ref<ColumnRow | null>(null)
const mappingRows = ref<Array<{ raw: string; label: string }>>([])

// ── 工具函数 ──
function safeParse(raw: any): Record<string, any> {
  if (!raw) return {}
  if (typeof raw === 'object') return raw as Record<string, any>
  try {
    const parsed = JSON.parse(String(raw))
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function parseList(raw: any): string[] {
  if (Array.isArray(raw)) return raw.map((item) => String(item))
  if (!raw) return []
  try {
    const parsed = JSON.parse(String(raw))
    return Array.isArray(parsed) ? parsed.map((item) => String(item)) : []
  } catch {
    return [String(raw)]
  }
}

function prettyJson(raw: any): string {
  const data = typeof raw === 'string' ? safeParse(raw) : raw
  return JSON.stringify(data ?? {}, null, 2)
}

function roleLabel(role: string): string {
  return ROLE_OPTIONS.find((item) => item.value === role)?.label || role || ''
}

function symbolLabel(symbol: string): string {
  return SYMBOL_OPTIONS.find((item) => item.value === symbol)?.label || symbol || ''
}

function entityKindLabel(kind: string): string {
  return ENTITY_KIND_OPTIONS.find((item) => item.value === kind)?.label || kind || ''
}

function columnLabel(col: ColumnRow): string {
  return col.comment ? `${col.columnName}（${col.comment}）` : col.columnName
}

function normalizeKind(kind: any): string {
  const value = String(kind || '').trim()
  return KIND_COMPAT[value] || (ENTITY_KIND_OPTIONS.some((item) => item.value === value) ? value : '')
}

function reset() {
  step.value = 0
  loading.value = false
  structureError.value = ''
  columns.value = []
  drafts.value = []
  adoptedIds.value = []
  ignoredIds.value = []
  validateErrors.value = []
  validateWarnings.value = []
  expired.value = false
  showAllConfig.value = false
  fieldFilter.value = 'focus'
  mappingVisible.value = false
  mappingColumn.value = null
  mappingRows.value = []
  Object.assign(semanticForm, {
    entityKind: '', symbolDefault: '', eventTimeColumn: '',
    trackGroupKey: [], lngColumn: '', latColumn: '', radiusColumn: '',
  })
  rawDatasetSemantic.value = {}
  rawDatasetText.value = ''
  datasetJsonDraft.value = ''
}

// ── 初始化：加载结构 + 已生效注解 + 待审草稿（不调用 AI）──
async function init() {
  reset()
  if (!props.dataset?.id) return
  const parsed = safeParse(props.dataset.semanticJson)
  rawDatasetSemantic.value = parsed
  rawDatasetText.value = props.dataset.semanticJson || ''
  datasetJsonDraft.value = props.dataset.semanticJson || ''
  const geometry = parsed.geometry && typeof parsed.geometry === 'object' ? parsed.geometry : {}
  Object.assign(semanticForm, {
    entityKind: normalizeKind(parsed.entityKind),
    symbolDefault: parsed.symbolDefault || '',
    eventTimeColumn: parsed.eventTimeColumn || '',
    trackGroupKey: Array.isArray(parsed.trackGroupKey) ? parsed.trackGroupKey.map(String) : [],
    lngColumn: geometry.lngColumn || '',
    latColumn: geometry.latColumn || '',
    radiusColumn: geometry.radiusColumn || '',
  })
  await loadStructure()
  await loadDrafts()
}

async function loadStructure() {
  if (!props.dataset?.id) return
  loading.value = true
  structureError.value = ''
  try {
    const res = await api.get(`/admin/dataset/${props.dataset.id}/structure`)
    if (res?.success && Array.isArray(res.columns) && res.columns.length) {
      columns.value = res.columns.map((c: any) => toColumnRow(c))
    } else {
      structureError.value = res?.message || '未能读取表结构，请检查数据库连接'
      columns.value = []
    }
  } catch (e: any) {
    structureError.value = e?.response?.data?.message || e?.serverMessage || '读取表结构失败'
    columns.value = []
  } finally {
    // 已生效字段注解回填（即使结构读取失败也尝试）
    try {
      const fa = await api.get(`/admin/dataset/${props.dataset.id}/fields`)
      applyFields(fa?.fields || [])
    } catch { /* 字段注解加载失败不阻断 */ }
    loading.value = false
  }
}

function toColumnRow(c: any): ColumnRow {
  return {
    columnName: String(c.columnName || c.name || ''),
    dataType: String(c.dataType || c.columnType || ''),
    comment: String(c.comment || c.columnComment || ''),
    isPrimaryKey: !!c.isPrimaryKey,
    isNullable: c.isNullable !== false,
    annotation: '',
    businessMeaning: '',
    dataCategory: '',
    role: '',
    symbol: '',
    unit: '',
    values: {},
    synonyms: {},
    rawSemantic: {},
    rawSemanticText: '',
    dirty: false,
    sampled: [],
  }
}

function applyFields(fields: any[]) {
  fields.forEach((fa: any) => {
    const col = columns.value.find((c) => c.columnName === fa.columnName)
      || columns.value.find((c) => c.columnName.toLowerCase() === String(fa.columnName || '').toLowerCase())
    if (!col) return
    col.annotation = fa.annotation || ''
    col.businessMeaning = fa.businessMeaning || ''
    col.dataCategory = fa.dataCategory || ''
    const parsed = safeParse(fa.semanticJson)
    col.rawSemantic = parsed
    col.rawSemanticText = fa.semanticJson || ''
    col.role = String(parsed.role || '')
    col.symbol = String(parsed.symbol || '')
    col.unit = String(parsed.unit || '')
    col.values = parsed.values && typeof parsed.values === 'object' ? { ...parsed.values } : {}
    col.synonyms = parsed.synonyms && typeof parsed.synonyms === 'object' ? { ...parsed.synonyms } : {}
    col.dirty = false
  })
}

async function loadDrafts() {
  if (!props.dataset?.id) return
  try {
    const res = await api.get(`/admin/dataset/${props.dataset.id}/annotations/drafts`, {
      params: { status: 'draft' },
    })
    drafts.value = res?.items || []
    // 采样值回填到字段行，供值映射弹窗使用
    drafts.value.forEach((item: any) => {
      if (item.scope !== 'field' || !item.columnName) return
      const col = columns.value.find((c) => c.columnName === item.columnName)
      if (!col) return
      const samples = parseList(item.sampledJson)
      if (samples.length) col.sampled = samples
    })
  } catch {
    drafts.value = []
  }
}

async function generateDrafts() {
  if (!props.dataset?.id) return
  draftGenerating.value = true
  try {
    const res = await api.post(`/admin/dataset/${props.dataset.id}/annotations/draft/generate`, {})
    if (res?.success) {
      ElMessage.success(res.message || '建议已生成')
      if (Array.isArray(res.notes) && res.notes.length) {
        ElMessage.warning({ message: res.notes.join('；'), duration: 6000 })
      }
      await loadDrafts()
    }
  } catch (e: any) {
    ElMessage.error('生成建议失败：' + (e?.serverMessage || e?.message || '未知错误'))
  } finally {
    draftGenerating.value = false
  }
}

// ── AI 建议可读化 ──
function draftSummary(item: any): string[] {
  const data = safeParse(item.draftJson)
  if (item.scope === 'dataset') {
    const lines: string[] = []
    if (data.entityKind) lines.push(`实体大类：${entityKindLabel(normalizeKind(data.entityKind)) || data.entityKind}`)
    const geometry = data.geometry || {}
    if (geometry.lngColumn && geometry.latColumn) {
      lines.push(`坐标列：${geometry.lngColumn}（经度）/ ${geometry.latColumn}（纬度）`)
    }
    if (data.eventTimeColumn) lines.push(`事件时间：${data.eventTimeColumn}`)
    if (Array.isArray(data.trackGroupKey) && data.trackGroupKey.length) {
      lines.push(`航迹拆分键：${data.trackGroupKey.join(' + ')}`)
    }
    if (data.symbolDefault) lines.push(`默认符号：${symbolLabel(data.symbolDefault)}`)
    return lines.length ? lines : ['未给出可识别的数据集语义']
  }
  const lines: string[] = []
  if (data.role) lines.push(`角色：${roleLabel(data.role)}`)
  if (data.values && typeof data.values === 'object') {
    lines.push('值映射：' + Object.entries(data.values).map(([k, v]) => `${k}→${v}`).join('、'))
  }
  if (data.synonyms && typeof data.synonyms === 'object') {
    lines.push('别名：' + Object.keys(data.synonyms).join('、'))
  }
  if (data.symbol) lines.push(`符号：${symbolLabel(data.symbol)}`)
  return lines.length ? lines : ['未给出可识别的字段语义']
}

function draftSamples(item: any): string[] {
  return parseList(item.sampledJson)
}

function hasIssues(item: any): boolean {
  return parseList(item.issuesJson).length > 0
}

function adoptDraft(item: any) {
  const data = safeParse(item.draftJson)
  if (item.scope === 'dataset') {
    const kind = normalizeKind(data.entityKind)
    if (kind) semanticForm.entityKind = kind
    if (data.symbolDefault) semanticForm.symbolDefault = String(data.symbolDefault)
    if (data.eventTimeColumn) semanticForm.eventTimeColumn = String(data.eventTimeColumn)
    if (Array.isArray(data.trackGroupKey)) semanticForm.trackGroupKey = data.trackGroupKey.map(String)
    const geometry = data.geometry || {}
    if (geometry.lngColumn) semanticForm.lngColumn = String(geometry.lngColumn)
    if (geometry.latColumn) semanticForm.latColumn = String(geometry.latColumn)
    if (geometry.radiusColumn) semanticForm.radiusColumn = String(geometry.radiusColumn)
  } else {
    const col = columns.value.find((c) => c.columnName === item.columnName)
    if (!col) {
      ElMessage.warning(`字段 ${item.columnName} 不在当前表结构中，已跳过`)
      return
    }
    if (data.role) col.role = String(data.role)
    if (data.symbol) col.symbol = String(data.symbol)
    if (data.unit) col.unit = String(data.unit)
    if (data.values && typeof data.values === 'object') col.values = { ...data.values }
    if (data.synonyms && typeof data.synonyms === 'object') col.synonyms = { ...data.synonyms }
    col.dirty = true
  }
  if (!adoptedIds.value.includes(item.id)) adoptedIds.value.push(item.id)
  ignoredIds.value = ignoredIds.value.filter((id) => id !== item.id)
}

function ignoreDraft(item: any) {
  if (!ignoredIds.value.includes(item.id)) ignoredIds.value.push(item.id)
  adoptedIds.value = adoptedIds.value.filter((id) => id !== item.id)
}

// ── 字段与按能力裁剪 ──
function markDirty(row: any) {
  row.dirty = true
}

const visibleColumns = computed(() => {
  if (fieldFilter.value === 'all') return columns.value
  return columns.value.filter((c) =>
    c.role || c.symbol || c.unit || Object.keys(c.values).length || Object.keys(c.synonyms).length
    || c.dirty || c.sampled.length || columnWarnings(c).length)
})

function containsAny(text: string, words: string[]): boolean {
  return words.some((word) => text.includes(word))
}

const geoCandidates = computed(() => columns.value.filter((c) =>
  /(lng|lon|经度|东经|jd|横坐标)/i.test(`${c.columnName} ${c.comment}`)))
const latCandidates = computed(() => columns.value.filter((c) =>
  /(lat|纬度|北纬|wd|纵坐标)/i.test(`${c.columnName} ${c.comment}`)))
const timeCandidates = computed(() => columns.value.filter((c) =>
  /(date|time|时间|日期|时刻)/i.test(`${c.dataType} ${c.columnName} ${c.comment}`)))
const idCandidates = computed(() => columns.value.filter((c) =>
  c.isPrimaryKey || /(^|_)id$|编号|标识|编码/i.test(`${c.columnName} ${c.comment}`)))
const showGeo = computed(() => geoCandidates.value.length > 0 && latCandidates.value.length > 0)
const showTime = computed(() => timeCandidates.value.length > 0)
const showTrack = computed(() => idCandidates.value.length >= 2)

function columnWarnings(row: any): string[] {
  const warnings: string[] = []
  const text = `${row.columnName} ${row.comment}`.toLowerCase()
  if (row.role === 'time' && containsAny(text, ['服役', '成立', '创建', '出生', 'commission', 'create', 'found'])) {
    warnings.push('疑似档案时间，不建议作为事件时间')
  }
  if (row.role === 'dimension' && containsAny(text, ['说明', '备注', '描述', '摘要', 'note', 'remark', 'desc'])) {
    warnings.push('说明性文本不建议作为维度')
  }
  if (row.values?.['红方'] === 'blue' || row.values?.['蓝方'] === 'red') {
    warnings.push('红蓝映射方向可能与语义色相反，请确认')
  }
  if (row.values?.['我方'] === 'hostile' || row.values?.['敌方'] === 'friendly') {
    warnings.push('我敌映射方向可能相反，请确认')
  }
  return warnings
}

// ── 值映射 ──
function openMapping(row: any) {
  mappingColumn.value = row
  mappingRows.value = Object.entries(row.values || {}).map(([raw, label]) => ({ raw, label: String(label) }))
  if (!mappingRows.value.length) mappingRows.value = [{ raw: '', label: '' }]
  mappingVisible.value = true
}

function addMappingRow(raw: string) {
  if (mappingRows.value.some((row) => row.raw === raw)) return
  const empty = mappingRows.value.find((row) => !row.raw)
  if (empty) {
    empty.raw = raw
  } else {
    mappingRows.value.push({ raw, label: raw })
  }
}

function applyMapping() {
  if (!mappingColumn.value) return
  const values: Record<string, string> = {}
  mappingRows.value.forEach((row) => {
    const raw = row.raw.trim()
    const label = row.label.trim()
    if (raw && label) values[raw] = label
  })
  mappingColumn.value.values = values
  mappingColumn.value.dirty = true
  mappingVisible.value = false
}

// ── 语义组装与差异 ──
function buildFieldSemanticSnapshot(row: ColumnRow): string {
  const known = ['role', 'symbol', 'unit', 'values', 'synonyms']
  const out: Record<string, any> = { ...row.rawSemantic }
  known.forEach((key) => delete out[key])
  if (row.role) out.role = row.role
  if (row.symbol) out.symbol = row.symbol
  if (row.unit.trim()) out.unit = row.unit.trim()
  if (Object.keys(row.values).length) out.values = { ...row.values }
  if (Object.keys(row.synonyms).length) out.synonyms = { ...row.synonyms }
  return Object.keys(out).length ? JSON.stringify(out) : ''
}

function buildDatasetSemantic(): string {
  const out: Record<string, any> = { ...rawDatasetSemantic.value }
  ;['entityKind', 'symbolDefault', 'eventTimeColumn', 'trackGroupKey', 'geometry'].forEach((key) => delete out[key])
  if (semanticForm.entityKind) out.entityKind = semanticForm.entityKind
  if (semanticForm.symbolDefault) out.symbolDefault = semanticForm.symbolDefault
  if (semanticForm.eventTimeColumn) out.eventTimeColumn = semanticForm.eventTimeColumn
  if (semanticForm.trackGroupKey.length) out.trackGroupKey = [...semanticForm.trackGroupKey]
  if (semanticForm.lngColumn && semanticForm.latColumn) {
    const geometry: Record<string, string> = {
      lngColumn: semanticForm.lngColumn,
      latColumn: semanticForm.latColumn,
    }
    if (semanticForm.radiusColumn) geometry.radiusColumn = semanticForm.radiusColumn
    out.geometry = geometry
  }
  return Object.keys(out).length ? JSON.stringify(out) : ''
}

const diff = computed(() => {
  let changed = 0, added = 0, cleared = 0
  columns.value.forEach((row) => {
    const before = row.rawSemanticText || ''
    const after = buildFieldSemanticSnapshot(row)
    if (before === after) return
    if (!before && after) added += 1
    else if (before && !after) cleared += 1
    else changed += 1
  })
  return {
    changed, added, cleared,
    semanticChanged: buildDatasetSemantic() !== (rawDatasetText.value || ''),
  }
})

const fieldJsonPreview = computed(() => {
  const out: Record<string, any> = {}
  columns.value.forEach((row) => {
    const json = buildFieldSemanticSnapshot(row)
    if (json) out[row.columnName] = safeParse(json)
  })
  return JSON.stringify(out, null, 2)
})

function applyDatasetJson() {
  const parsed = safeParse(datasetJsonDraft.value)
  if (datasetJsonDraft.value.trim() && !Object.keys(parsed).length) {
    ElMessage.error('JSON 解析失败，请检查格式')
    return
  }
  rawDatasetSemantic.value = parsed
  rawDatasetText.value = datasetJsonDraft.value
  const geometry = parsed.geometry || {}
  Object.assign(semanticForm, {
    entityKind: normalizeKind(parsed.entityKind),
    symbolDefault: parsed.symbolDefault || '',
    eventTimeColumn: parsed.eventTimeColumn || '',
    trackGroupKey: Array.isArray(parsed.trackGroupKey) ? parsed.trackGroupKey.map(String) : [],
    lngColumn: geometry.lngColumn || '',
    latColumn: geometry.latColumn || '',
    radiusColumn: geometry.radiusColumn || '',
  })
  ElMessage.success('已按 JSON 回填表单')
}

// ── 校验与保存 ──
async function validateAnnotations() {
  if (!props.dataset?.id) return
  validating.value = true
  try {
    const res = await api.post(`/admin/dataset/${props.dataset.id}/annotations/validate`, {})
    validateErrors.value = Array.isArray(res?.errors) ? res.errors.map(String) : []
    validateWarnings.value = Array.isArray(res?.warnings) ? res.warnings.map(String) : []
    expired.value = !!res?.expired
    if (!validateErrors.value.length) ElMessage.success('校验通过')
  } catch (e: any) {
    ElMessage.error('校验失败：' + (e?.serverMessage || e?.message || '未知错误'))
  } finally {
    validating.value = false
  }
}

async function saveAll() {
  if (!props.dataset?.id) return
  if (validateErrors.value.length) {
    ElMessage.error('存在结构错误，请先修正或重新校验')
    return
  }
  saving.value = true
  try {
    // 1) 先通过本次采纳的 AI 草稿（写入正式注解）
    for (const draftId of adoptedIds.value) {
      await api.post(`/admin/annotations/draft/${draftId}/approve`, {})
    }
    // 2) 保存字段注解（全量替换；语义以当前表单为准）
    if (columns.value.length) {
      const payload = columns.value.map((row) => ({
        columnName: row.columnName,
        columnType: row.dataType,
        isPrimaryKey: row.isPrimaryKey,
        isNullable: row.isNullable,
        columnComment: row.comment,
        annotation: row.annotation || '',
        businessMeaning: row.businessMeaning || '',
        dataCategory: row.dataCategory || '',
        semanticJson: buildFieldSemanticSnapshot(row),
      }))
      await api.post(`/admin/dataset/${props.dataset.id}/fields`, payload)
    }
    // 3) 保存数据集级语义
    await api.put(`/admin/dataset/${props.dataset.id}/semantic`, {
      semanticJson: buildDatasetSemantic(),
    })
    ElMessage.success('注解已保存并生效')
    emit('saved')
    visible.value = false
  } catch (e: any) {
    const errors = e?.response?.data?.errors ?? e?.errors
    const detail = Array.isArray(errors) && errors.length ? `\n${errors.join('\n')}` : ''
    await ElMessageBox.alert(
      `${e?.response?.data?.message || e?.serverMessage || e?.message || '保存失败'}${detail}`,
      '保存失败',
      { confirmButtonText: '知道了', type: 'error' },
    ).catch(() => { /* 关闭提示不算异常 */ })
  } finally {
    saving.value = false
  }
}

watch(() => props.modelValue, (value) => {
  if (value) init()
})
</script>

<style scoped>
.wf-dialog :deep(.el-dialog__body) {
  padding-top: 8px;
}
.wf-steps {
  margin-bottom: 10px;
}
.wf-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
  padding: 8px 10px;
  margin-bottom: 10px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 12px;
  color: #475569;
}
.wf-body {
  min-height: 360px;
}
.wf-two-col {
  display: grid;
  grid-template-columns: minmax(0, 1.6fr) minmax(300px, 1fr);
  gap: 16px;
}
.wf-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 10px 0;
  flex-wrap: wrap;
}
.wf-hint {
  color: #94a3b8;
  font-size: 12px;
}
.wf-section-title {
  margin: 14px 0 8px;
  font-weight: 600;
  color: #1e293b;
  font-size: 13px;
}
.wf-table {
  width: 100%;
}
.wf-card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 10px;
  background: #fff;
}
.wf-card-ignored {
  opacity: 0.55;
}
.wf-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.wf-card-actions {
  margin-left: auto;
}
.wf-card-body {
  margin-top: 8px;
  font-size: 13px;
  color: #334155;
}
.wf-line {
  line-height: 1.8;
}
.wf-error {
  color: #dc2626;
  font-size: 12px;
}
.wf-warn {
  color: #d97706;
  font-size: 12px;
}
.wf-json {
  margin-top: 8px;
}
.wf-json pre {
  margin: 0;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  background: #f8fafc;
  padding: 8px;
  border-radius: 4px;
}
.wf-preview {
  padding: 10px;
  background: #f8fafc;
  border: 1px dashed #cbd5e1;
  border-radius: 6px;
  margin-top: 8px;
}
.wf-samples {
  margin-bottom: 8px;
  font-size: 12px;
  color: #475569;
}
.wf-sample-tag {
  margin-right: 6px;
  cursor: pointer;
}
</style>
