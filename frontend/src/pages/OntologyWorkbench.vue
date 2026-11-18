<template>
  <OntologyDetail v-if="route.query.jobId" />
  <main v-else class="native-workbench">
    <header class="project-bar">
      <button class="home-button" aria-label="返回本体管理" @click="router.push('/ontology/library')"><ArrowLeft :size="18" /></button>
      <span class="brand-mark"><Orbit :size="23" /></span>
      <div class="project-name"><span>天智智能评估系统 <i>/</i> 动态本体</span><h1>{{ model?.name || '正在载入本体' }}</h1></div>
      <span :class="['sync-state', { dirty }]" role="status"><b></b>{{ dirty ? '未保存修改' : '已保存' }}</span>
      <div class="project-actions">
        <button @click="about = true"><CircleHelp :size="15" />使用说明</button>
        <button :disabled="!ready || loading" @click="openHistory"><History :size="15" />版本记录</button>
        <button :disabled="!ready || loading || saving" @click="reload"><RotateCcw :size="15" />重新载入</button>
        <button class="primary" :disabled="!ready || loading || saving" @click="save"><Save :size="15" />{{ saving ? '正在保存…' : '保存本体' }}</button>
      </div>
    </header>
    <section class="editor-stage" aria-label="Ontosphere 原生本体编辑器">
      <iframe ref="frame" :key="identifier" title="Ontosphere 原生编辑器" :src="editorUrl" allow="cross-origin-isolated" />
      <div v-if="loading || failure" class="loading-cover"><Orbit :size="40" :class="{ spinning: !failure }" /><h2>{{ failure ? '本体载入失败' : '正在打开 Ontosphere' }}</h2><p>{{ failure || '启动 RDF 工作线程与本体画布' }}</p><button v-if="failure" @click="retry">重新尝试</button></div>
    </section>
    <section v-if="model?.is_demo && scenario" class="exercise-strip" aria-label="推演回合">
      <div class="exercise-label"><span class="example-badge">内置样例</span><strong>回合回放</strong><small>四个时间节点</small></div>
      <div class="turn-track"><button v-for="item in scenario.turns" :key="item.index" :class="['turn', { active: turn === item.index }]" :disabled="loading || !!acting || saving" @click="changeTurn(item.index)"><span class="turn-dot">{{ item.index + 1 }}</span><span><small>{{ item.time }} · 回合 {{ item.index }}</small><strong>{{ item.title }}</strong></span></button></div>
      <div class="exercise-metrics"><span>就绪率<strong>{{ selectedTurn?.readiness }}<small>%</small></strong></span><span>协同度<strong>{{ selectedTurn?.coordination }}</strong></span><span>任务进度<strong>{{ selectedTurn?.progress }}<small>%</small></strong></span></div>
      <div class="exercise-tools"><button :disabled="loading || !!acting" @click="reason"><Sparkles :size="14" />OWL 推理</button><button :disabled="loading || !!acting" @click="validate"><ListChecks :size="14" />约束验证</button></div>
    </section>
    <footer class="workbench-footer"><span><b class="online-dot"></b>{{ acting || selectedTurn?.description || '编辑节点、建立关系，保存后同步到评估系统' }}</span><span>{{ model?.triple_count || 0 }} 条断言 · RDF / OWL 2 DL <a href="https://github.com/ThHanke/ontosphere/tree/6bdcb78b531b2300d047fbcdd10246fc62611cb9" target="_blank" rel="noopener">Ontosphere 1.8.1 ↗</a></span></footer>
    <el-drawer v-model="historyVisible" title="版本记录" size="430px" :append-to-body="true"><p class="drawer-note">恢复操作会先载入所选版本。检查画布后，点击“保存本体”生成新版本。</p><el-empty v-if="!history.length" description="保存修改后将在这里保留历史快照" /><div v-for="item in history" :key="item.id" class="history-item"><strong>{{ versionNote(item.note) }}</strong><p>{{ new Date(item.time).toLocaleString('zh-CN') }}</p><el-button size="small" @click="restore(item)">载入这个版本</el-button></div></el-drawer>
    <el-dialog v-model="about" title="Ontosphere 原生本体工作台" width="650px" :append-to-body="true">
      <p>当前画布直接使用 Ontosphere 1.8.1 的源码、Reactodia 编辑器和 Konclude WASM 推理引擎。左侧工具栏提供数据导入、RDF 编辑、SPARQL、命名空间与配置；顶部保留原项目的布局、聚类、折叠与 ABox / TBox 切换。</p>
      <ol class="guide-list"><li><b>ABox 实例图：</b>选择装备查看属性，双击节点展开邻接关系；选中后使用编辑与连线操作修改本体。</li><li><b>TBox 本体图：</b>查看装备分类、属性定义、等价类和 OWL 限制。就绪装备由状态值自动分类，编组能力由“至少编配一个就绪装备”推导。</li><li><b>推演回放：</b>底部选择四个回合，观察装备状态、任务进度和评估来源事件变化。回合数据载入为草稿，保存后进入版本记录。</li><li><b>推理与验证：</b>运行 OWL 推理后查看原生推理报告与新增关系。约束验证检查任务进度、装备状态和评估溯源。</li><li><b>保存与导出：</b>项目顶部“保存本体”和画布中的“保存” 都会保存 RDF、命名空间与画布位置；原生导出保留多图数据集。</li></ol>
      <p v-if="model?.is_demo" class="drawer-note">内置样例包含 8 台装备、2 个协作小组、3 个协作单元和 3 项任务。</p><a href="https://github.com/ThHanke/ontosphere" target="_blank" rel="noopener">查看原项目与 Apache-2.0 许可 ↗</a>
    </el-dialog>
    <el-dialog v-model="resultVisible" :title="resultTitle" width="620px" :append-to-body="true"><pre class="result-content">{{ resultText }}</pre></el-dialog>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, CircleHelp, History, ListChecks, Orbit, RotateCcw, Save, Sparkles } from 'lucide-vue-next'
import OntologyDetail from './OntologyDetail.vue'
import api from '@/services/api'
import { workbenchHistory } from '@/services/ontologyWorkbench'
const route = useRoute(), router = useRouter()
const identifier = computed(() => String(route.params.id))
const frame = ref<HTMLIFrameElement>(), model = ref<any>(), scenario = ref<any>()
const ready = ref(false), loading = ref(true), saving = ref(false), dirty = ref(false), failure = ref(''), acting = ref('')
const historyVisible = ref(false), history = ref<any[]>([]), about = ref(false), turn = ref(0)
const resultVisible = ref(false), resultTitle = ref(''), resultText = ref('')
const selectedTurn = computed(() => scenario.value?.turns?.[turn.value])
function versionNote(note: string) {
  if (!model.value?.is_demo) return note
  const legacy = /^青岚推演 · 回合 ([0-3]) · (?:编组就绪|链路变化|保障协同|推演复盘)$/.exec(note)
  const recordedTurn = legacy && scenario.value?.turns?.[Number(legacy[1])]
  return recordedTurn ? `回合 ${recordedTurn.index} · ${recordedTurn.title}` : note
}
const editorUrl = '/ontosphere/?assessment=1&ontologies=&loadImports=false&workflowCatalog=off&theme=light'
const channel = 'assessment-ontosphere-v1'
let initialized = false, serial = 0, changed = 0
const pending = new Map<string, { resolve: (v: any) => void; reject: (e: Error) => void; timer: ReturnType<typeof setTimeout> }>()
const path = () => `/ontology/${encodeURIComponent(identifier.value)}/workbench/editor`
const message = (error: any) => error?.response?.data?.detail?.message || error?.response?.data?.detail || error?.message || String(error)
function rpc(method: string, data?: any): Promise<any> {
  return new Promise((resolve, reject) => {
    if (!ready.value || !frame.value?.contentWindow) { reject(new Error('编辑器尚未就绪')); return }
    const id = `editor-${++serial}`
    const timer = setTimeout(() => { pending.delete(id); reject(new Error('编辑器操作超时，请检查画布状态后重试')) }, 180000)
    pending.set(id, { resolve, reject, timer })
    // Vue reactive proxies cannot cross postMessage's structured-clone boundary.
    frame.value.contentWindow.postMessage(JSON.parse(JSON.stringify({ channel, type: 'request', id, method, data })), location.origin)
  })
}
async function boot() {
  if (!ready.value || !model.value || initialized) return
  initialized = true
  try { await rpc('load', { ...model.value, shapes: model.value.is_demo ? scenario.value?.shapes : undefined }); turn.value = model.value.layouts?.host?.turn ?? 0; dirty.value = false }
  catch (error) { failure.value = message(error) }
  finally { loading.value = false }
}
function receive(event: MessageEvent) {
  if (event.origin !== location.origin || event.source !== frame.value?.contentWindow || event.data?.channel !== channel) return
  const { type, data, id } = event.data
  if (type === 'ready') { ready.value = true; void boot() }
  if (type === 'dirty' && !loading.value) { dirty.value = true; changed++ }
  if (type === 'save-request' && !saving.value && !loading.value) void save()
  if (type === 'response') { const task = pending.get(id); if (!task) return; clearTimeout(task.timer); pending.delete(id); if (data.success) task.resolve(data.value); else task.reject(new Error(data.error)) }
}
async function fetchModel() {
  try { model.value = (await api.get(path())).data; if (model.value.is_demo) scenario.value = (await api.get('/ontology/examples/wargame/turns/0')).data; await boot() }
  catch (error) { failure.value = message(error); loading.value = false }
}
async function discard() {
  if (!dirty.value) return true
  try { await ElMessageBox.confirm('当前草稿有未保存修改。继续将载入所选数据。', '切换本体数据', { confirmButtonText: '继续载入', cancelButtonText: '返回编辑', type: 'warning' }); return true } catch { return false }
}
async function reload() { if (!await discard()) return; loading.value = true; failure.value = ''; initialized = false; await fetchModel() }
function retry() { location.reload() }
async function save() {
  if (saving.value) return
  saving.value = true
  try {
    const data = await rpc('export'), exportedAt = changed
    model.value = (await api.put(path(), { ...data, layouts: { ...data.layouts, host: { turn: turn.value } }, expected_revision: model.value.revision, note: model.value.is_demo ? `回合 ${turn.value} · ${selectedTurn.value?.title}` : 'Ontosphere 原生画布编辑' }, { timeout: 60000 })).data
    dirty.value = changed !== exportedAt; ElMessage.success('本体、RDF 数据集与画布布局已保存')
  } catch (error) { ElMessage.error(message(error)) } finally { saving.value = false }
}
async function changeTurn(index: number) {
  if (index === turn.value || !await discard()) return
  loading.value = true
  try { const data = (await api.get(`/ontology/examples/wargame/turns/${index}`)).data; await rpc('load', data); turn.value = index; dirty.value = true; changed++; model.value.triple_count = data.triple_count }
  catch (error) { ElMessage.error(message(error)) } finally { loading.value = false }
}
async function reason() {
  acting.value = '正在使用 Konclude 运行 OWL 2 DL 推理…'
  try { await rpc('tool', { name: 'runReasoning', args: { reasonerBackend: 'konclude' } }); ElMessage.success('OWL 推理已完成，可在原生推理报告中查看推导结果') }
  catch (error) { ElMessage.error(message(error)) } finally { acting.value = '' }
}
async function validate() {
  acting.value = '正在验证装备状态、任务进度与评估溯源…'
  try { const result = await rpc('tool', { name: 'validateGraph', args: {} }); resultTitle.value = result.conforms ? 'SHACL 验证通过' : 'SHACL 验证结果'; resultText.value = result.conforms ? '当前回合的装备状态、任务进度和评估溯源均符合约束。' : JSON.stringify(result.violations, null, 2); resultVisible.value = true }
  catch (error) { ElMessage.error(message(error)) } finally { acting.value = '' }
}
async function openHistory() { try { history.value = await workbenchHistory(identifier.value); historyVisible.value = true } catch (error) { ElMessage.error(message(error)) } }
async function restore(item: any) {
  if (!await discard()) return
  loading.value = true
  try { const data = (await api.post(`${path()}/preview`, { document: item.document })).data; await rpc('load', { ...data, shapes: scenario.value?.shapes }); turn.value = data.layouts?.host?.turn ?? 0; model.value.triple_count = data.triple_count; dirty.value = true; changed++; historyVisible.value = false; ElMessage.success('历史版本已载入草稿，保存后生效') }
  catch (error) { ElMessage.error(message(error)) } finally { loading.value = false }
}
const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty.value) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(async () => !dirty.value || discard())
onMounted(() => { if (route.query.jobId) return; window.addEventListener('message', receive); window.addEventListener('beforeunload', beforeUnload); void fetchModel() })
onBeforeUnmount(() => { window.removeEventListener('message', receive); window.removeEventListener('beforeunload', beforeUnload); for (const task of pending.values()) { clearTimeout(task.timer); task.reject(new Error('编辑器已关闭')) } pending.clear() })
</script>

<style scoped>
.native-workbench{height:100dvh;display:flex;flex-direction:column;background:var(--bg-page);color:var(--text-primary);font-family:Inter,"Microsoft YaHei",sans-serif;overflow:hidden}.project-bar{height:65px;flex-shrink:0;display:flex;align-items:center;gap:13px;padding:0 22px;border-bottom:1px solid var(--border-normal);background:var(--bg-card)}.home-button,.project-actions button,.exercise-tools button{display:flex;align-items:center;justify-content:center;gap:7px;border:1px solid var(--border-normal);border-radius:6px;background:var(--bg-card);color:var(--text-secondary);cursor:pointer;white-space:nowrap}.home-button{width:31px;height:31px;background:transparent;border-color:transparent}.home-button:hover{background:var(--bg-hover)}.brand-mark{color:var(--primary-500);display:flex}.project-name{min-width:0}.project-name>span{font-size:10px;letter-spacing:1.5px;color:var(--text-tertiary)}.project-name i{font-style:normal;margin:0 8px;color:var(--text-muted)}.project-name h1{font-size:15px;margin:4px 0 0;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sync-state{font-size:11px;color:var(--success-600);display:flex;align-items:center;gap:6px;margin-left:12px;white-space:nowrap}.sync-state b,.online-dot{width:5px;height:5px;border-radius:50%;background:var(--success-500);display:inline-block}.sync-state.dirty{color:var(--warning-600)}.sync-state.dirty b{background:var(--warning-600)}.project-actions{margin-left:auto;display:flex;gap:8px}.project-actions button{height:32px;padding:0 12px;font-size:12px}.project-actions .primary{background:var(--primary-500);border-color:var(--primary-500);color:#fff}button:disabled{opacity:.45;cursor:default}.editor-stage{position:relative;flex:1;min-height:0;overflow:hidden}.editor-stage iframe{width:100%;height:100%;display:block;border:0;background:var(--bg-page)}.loading-cover{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:14px;background:rgba(248,250,252,.96);color:var(--primary-500);z-index:5}.loading-cover h2{color:var(--text-primary);font-size:18px;margin:8px 0 0}.loading-cover p{color:var(--text-tertiary);font-size:13px;max-width:650px}.loading-cover button{padding:8px 20px;border:1px solid var(--primary-500);background:var(--primary-500);color:white;border-radius:6px;cursor:pointer}.spinning{animation:spin 3s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.exercise-strip{display:flex;align-items:center;gap:22px;padding:15px 23px;border-top:1px solid var(--border-normal);background:var(--bg-card);flex-shrink:0}.exercise-label{display:grid;gap:4px;min-width:126px}.example-badge{color:var(--primary-600);font-size:10px;letter-spacing:2px}.exercise-label strong{font-size:16px;font-weight:600}.exercise-label small{color:var(--text-tertiary);font-size:10px}.turn-track{display:flex;flex:1;gap:8px}.turn{flex:1;display:flex;align-items:center;gap:10px;background:var(--bg-card);border:1px solid var(--border-normal);padding:11px 13px;text-align:left;border-radius:7px;color:var(--text-tertiary);cursor:pointer}.turn small{display:block;font-size:10px;margin-bottom:5px}.turn strong{font-size:12px;font-weight:500}.turn-dot{width:24px;height:24px;border:1px solid var(--border-strong);display:flex;align-items:center;justify-content:center;border-radius:50%;font-size:11px;flex-shrink:0}.turn.active{border-color:var(--primary-400);background:var(--primary-50);color:var(--primary-700)}.turn.active .turn-dot{background:var(--primary-500);border-color:var(--primary-400);color:white}.exercise-metrics{display:flex;gap:22px}.exercise-metrics>span{display:grid;gap:6px;font-size:10px;color:var(--text-tertiary)}.exercise-metrics strong{font-size:21px;color:var(--text-primary);font-weight:500;font-variant-numeric:tabular-nums}.exercise-metrics strong small{font-size:11px;color:var(--text-tertiary);margin-left:2px}.exercise-tools{display:grid;gap:7px}.exercise-tools button{height:28px;font-size:11px;padding:0 9px}.workbench-footer{height:29px;flex-shrink:0;display:flex;align-items:center;justify-content:space-between;padding:0 23px;background:var(--bg-page);border-top:1px solid var(--border-normal);color:var(--text-tertiary);font-size:10px;gap:20px}.workbench-footer>span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.online-dot{margin-right:7px}.workbench-footer a{color:var(--text-muted);margin-left:18px;text-decoration:none}.drawer-note{color:var(--text-tertiary);font-size:13px;line-height:1.7}.guide-list{padding-left:22px;line-height:1.9}.guide-list li{margin:12px 0}.history-item{padding:18px 0;border-bottom:1px solid var(--border-normal)}.history-item strong{font-size:14px}.history-item p{font-size:12px;color:var(--text-tertiary)}.result-content{white-space:pre-wrap;word-break:break-word;max-height:55vh;overflow:auto;font-size:13px;line-height:1.8}@media(max-width:1100px){.exercise-metrics{gap:12px}.exercise-strip{gap:12px;padding:12px}.turn{padding:10px 8px;gap:7px}.project-bar{padding:0 12px}.sync-state{display:none}.exercise-label{min-width:100px}.project-actions button{padding:0 8px}}@media(max-width:800px){.project-actions button:nth-child(1),.project-actions button:nth-child(3){display:none}.project-name h1{max-width:230px}.exercise-strip{flex-wrap:wrap}.exercise-label{display:none}.turn-track{width:100%;flex-basis:100%}.exercise-metrics{margin-right:auto;gap:30px}.exercise-metrics>span{display:flex;align-items:center}.exercise-metrics strong{font-size:16px}.exercise-tools{display:flex}.workbench-footer span:last-child{display:none}}
</style>
