<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { BrainCircuit, Boxes, ChevronDown, DatabaseZap, GitMerge, Plus, Sparkles, Workflow, Zap } from 'lucide-vue-next';
import { causalApi } from '@/services/causalApi';
import { useOntologyStore } from '@/stores/ontology';

const router = useRouter();
const store = useOntologyStore();
const seeding = ref(false);
const seedStatus = ref('');
const lifecycleOpen = ref(true);
const tasksOpen = ref(true);

const metrics = computed(() => [
  { label: '原始事实节点', value: store.dynamicStatistics.assertedNodeCount, icon: Boxes, tone: 'blue' },
  { label: '规则派生节点', value: store.dynamicStatistics.derivedNodeCount, icon: Sparkles, tone: 'violet' },
  { label: '启用推理规则', value: store.dynamicStatistics.ruleCount, icon: Zap, tone: 'blue' },
  { label: '待消歧候选', value: store.dynamicStatistics.pendingResolutionCount, icon: GitMerge, tone: 'amber' },
  { label: 'Agent 待审批', value: store.dynamicStatistics.pendingProposalCount, icon: BrainCircuit, tone: 'amber' },
]);

async function seedDataset() {
  seeding.value = true;
  seedStatus.value = '正在写入 Word 原始事实，并清理上一轮派生节点与生命周期记录…';
  try {
    const result = await causalApi.seedMilitaryDataset();
    await store.reloadAll();
    seedStatus.value = `初始化完成：${result.entities} 个实体、${result.actions} 个行动事实。动态高阶节点不会由 Seed 预写，将由规则引擎运行时“长出”。`;
  } catch (error) {
    seedStatus.value = `初始化失败：${error instanceof Error ? error.message : '请检查 API / Neo4j / OpenSearch'}`;
  } finally { seeding.value = false; }
}

onMounted(() => void store.reloadAll());
</script>

<template>
  <div class="space-y-5">
    <section class="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
      <div>
        <p class="text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">Dynamic Ontology Workspace</p>
        <h2 class="mt-1 text-2xl font-semibold tracking-tight text-slate-950">本体管理</h2>
        <p class="mt-2 max-w-4xl text-sm leading-6 text-slate-500">Word 只负责提供 ASSERTED 底层事实；高阶事件由确定性规则运行时派生，重复实体通过消歧融合消融，DeepSeek Agent 仅提交待人工批准的本体扩充建议。</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button :disabled="seeding" class="inline-flex items-center gap-2 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2.5 text-sm font-semibold text-blue-700" @click="seedDataset"><DatabaseZap class="h-4 w-4" />{{ seeding ? '初始化中…' : '初始化 Word 事实' }}</button>
        <button class="inline-flex items-center gap-2 rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold text-white" @click="router.push('/ontology/aegis-maneuver-causal')"><Plus class="h-4 w-4" />进入动态本体</button>
      </div>
    </section>

    <div v-if="seedStatus" class="rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700">{{ seedStatus }}</div>

    <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
      <article v-for="metric in metrics" :key="metric.label" class="aegis-card flex items-center gap-4 p-5">
        <div class="flex h-11 w-11 items-center justify-center rounded-xl" :class="metric.tone === 'violet' ? 'bg-violet-50 text-violet-600' : metric.tone === 'amber' ? 'bg-amber-50 text-amber-600' : 'bg-blue-50 text-blue-600'"><component :is="metric.icon" class="h-5 w-5" /></div>
        <div><p class="text-xs text-slate-500">{{ metric.label }}</p><p class="mt-1 text-2xl font-semibold text-slate-950">{{ metric.value }}</p></div>
      </article>
    </section>

    <section class="aegis-card min-h-[520px] overflow-hidden">
      <div class="flex items-center justify-between border-b border-slate-100 px-6 py-5"><div><h3 class="text-base font-semibold text-slate-900">动态本体生命周期</h3><p class="mt-1 text-xs text-slate-500">图结构本身会在规则、消歧与 Agent 审批驱动下产生、融合与扩充。</p></div><button class="rounded-lg border border-slate-200 p-2 text-slate-500" @click="lifecycleOpen=!lifecycleOpen"><ChevronDown class="h-4 w-4 transition" :class="{'rotate-180':!lifecycleOpen}" /></button></div>
      <div v-if="lifecycleOpen" class="grid gap-4 p-6">
        <div class="rounded-xl border border-violet-100 bg-violet-50/50 p-5 min-h-[118px]"><div class="flex items-center gap-2 font-semibold text-violet-800"><Sparkles class="h-4 w-4" />规则派生 · 长出</div><p class="mt-2 text-xs leading-5 text-violet-700/80">底层 ActionNode 满足规则后才 MERGE 新的 DerivedEvent，并记录 ruleId、confidence、sourceNodeIds 与 OntologyMutation。</p></div>
        <div class="rounded-xl border border-amber-100 bg-amber-50/50 p-5 min-h-[118px]"><div class="flex items-center gap-2 font-semibold text-amber-800"><GitMerge class="h-4 w-4" />消歧融合 · 消失</div><p class="mt-2 text-xs leading-5 text-amber-700/80">相同 canonicalKey / fingerprint 的实例进入候选。低置信度只建 POSSIBLY_SAME_AS；人工确认后 APOC mergeNodes，旧节点消融且关系继承。</p></div>
        <div class="rounded-xl border border-blue-100 bg-blue-50/50 p-5 min-h-[118px]"><div class="flex items-center gap-2 font-semibold text-blue-800"><BrainCircuit class="h-4 w-4" />Agent · 扩充</div><p class="mt-2 text-xs leading-5 text-blue-700/80">DeepSeek 检查“现有本体是否无法表达重复结构”，只生成 NEW_CLASS / NEW_RELATION / NEW_RULE Proposal，批准后才进入 ACTIVE。</p></div>
      </div>
    </section>

    <section class="aegis-card overflow-hidden">
      <div class="flex items-center justify-between border-b border-slate-100 px-5 py-4"><div><h3 class="text-sm font-semibold text-slate-900">本体项目</h3><p class="mt-1 text-xs text-slate-500">机动目标打击因果溯源结构化数据集</p></div><button class="rounded-lg border border-slate-200 p-2 text-slate-500" @click="tasksOpen=!tasksOpen"><ChevronDown class="h-4 w-4 transition" :class="{'rotate-180':!tasksOpen}" /></button></div>
      <div v-if="tasksOpen" class="p-5">
        <div class="flex flex-col justify-between gap-4 rounded-xl border border-slate-100 bg-slate-50/70 p-5 lg:flex-row lg:items-center"><div><div class="flex items-center gap-2"><Workflow class="h-4 w-4 text-blue-600" /><h4 class="font-semibold text-slate-900">机动目标打击动态本体</h4><span class="rounded-full bg-emerald-50 px-2 py-1 text-[10px] text-emerald-700">ACTIVE</span></div><p class="mt-2 max-w-4xl text-xs leading-5 text-slate-500">基础层：9 个独立作战实体 + 22 个源行动事实；动态层：OntologyRule / DerivedEvent / ResolutionCandidate / OntologyProposal / OntologyMutation。</p></div><button class="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white" @click="router.push('/ontology/aegis-maneuver-causal')">打开本体</button></div>
      </div>
    </section>
  </div>
</template>
