/** Local integration of Ontosphere 1.8.1. Upstream editor and RDF engine are unchanged. */
import * as Reactodia from '@reactodia/workspace';
import { Parser } from 'n3';
import { rdfManager } from '@/utils/rdfManager';
import { getWorkspaceRefs, applyViewMode } from '@/mcp/workspaceContext';
import { isStartupComplete } from '@/utils/startupReady';
import { useOntologyStore } from '@/stores/ontologyStore';

export const embedded = new URLSearchParams(location.search).has('assessment');
const channel = 'assessment-ontosphere-v1';
const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));
const send = (type: string, data?: unknown, id?: string) => {
  if (embedded) window.parent.postMessage({ channel, type, data, id }, location.origin);
};
export function requestProjectSave() { send('save-request'); }

interface Hooks {
  commit: () => Promise<void>;
  clear: () => void;
  capture: () => Record<string, unknown>;
  restore: (layouts: Record<string, any>) => Promise<void>;
}

export function installAssessmentBridge(hooks: Hooks) {
  if (!embedded) return () => {};
  let disposed = false;
  let loading = false;
  let queue: Promise<unknown> = Promise.resolve();
  let editor: Reactodia.EditorController | undefined;
  const dirty = () => { if (!loading) send('dirty'); };
  rdfManager.onChange(dirty);
  const unNamespace = rdfManager.onNamespacesChange(dirty);

  async function tool(name: string, args: Record<string, unknown> = {}) {
    const fn = (window as any).__mcpTools?.[name];
    if (!fn) throw new Error(`Ontosphere 工具不可用：${name}`);
    const result = await fn(args);
    if (!result.success) throw new Error(result.error || `${name} 执行失败`);
    return result.data;
  }
  async function load(data: any) {
    loading = true;
    try {
      const { ctx } = getWorkspaceRefs();
      ctx.editor.setAuthoringState(Reactodia.AuthoringState.empty);
      ctx.model.history.reset();
      hooks.clear();
      rdfManager.clear();
      // Worker requests are ordered. Await a barrier before inserting the next dataset.
      await rdfManager.removeGraphAsync('urn:vg:data');
      rdfManager.setNamespaces(data.namespaces || {}, { replace: true });
      applyViewMode('abox');
      if (data.dataset) {
        const quads = new Parser({ format: 'N-Quads', blankNodePrefix: '' }).parse(data.dataset);
        const graphs = new Map<string, typeof quads>();
        for (const quad of quads) {
          const name = quad.graph.termType === 'DefaultGraph' ? 'urn:vg:data' : quad.graph.value;
          // Inferences must be regenerated for the selected facts, never restored as assertions.
          if (name === 'urn:vg:inferred') continue;
          const bucket = graphs.get(name) || [];
          bucket.push(quad); graphs.set(name, bucket);
        }
        for (const [name, adds] of graphs) await rdfManager.applyBatch({ adds }, name);
      } else if (data.turtle?.trim()) {
        await rdfManager.loadRDFIntoGraph(data.turtle, 'urn:vg:data', 'text/turtle');
      }
      if (data.shapes) {
        await rdfManager.removeGraphAsync('urn:vg:shapes');
        await tool('loadShacl', { turtle: data.shapes });
      }
      const currentResources = new Set<string>();
      if (data.turtle) {
        for (const quad of new Parser({ format: 'Turtle' }).parse(data.turtle)) {
          if (quad.subject.termType === 'NamedNode') currentResources.add(quad.subject.value);
          if (quad.object.termType === 'NamedNode') currentResources.add(quad.object.value);
        }
      }
      // The upstream subject reconciliation and automatic layout are debounced.
      await delay(750);
      const colors = ['#3b82f6', '#06b6d4', '#6366f1', '#10b981', '#f59e0b', '#64748b', '#0ea5e9', '#14b8a6'];
      useOntologyStore.getState().setNamespaceRegistry(rdfManager.getNamespaces().map((entry, index) => ({
        ...entry, namespace: entry.uri, color: colors[index % colors.length],
      })));
      if (data.layouts?.abox) await hooks.restore(data.layouts);
      else if (data.id === 'ont_demo_qinglan') {
        // A reproducible, readable seed layout for the example. All upstream layout
        // algorithms remain available, and saved user positions take precedence.
        const positions: Record<string, [number, number]> = {
          'force#Blue': [0, 50], 'force#Red': [0, 620],
          'unit#BlueTeam': [310, 190], 'unit#BlueSupport': [310, 480], 'unit#RedTeam': [310, 700],
          'equipment#C01': [620, 0], 'equipment#R01': [620, 120], 'equipment#R02': [620, 240],
          'equipment#G01': [620, 360], 'equipment#G02': [620, 480], 'equipment#L01': [620, 600],
          'equipment#C02': [0, 760], 'equipment#R03': [310, 840],
          'mission#Observe': [940, 40], 'mission#Coordinate': [940, 300], 'mission#Support': [940, 590],
          'assessment#Readiness': [1560, 40], 'assessment#Coordination': [1560, 260],
        };
        for (let i = 0; i < 4; i++) { positions[`event#E${i}`] = [1250, 60 + i * 220]; positions[`turn#T${i}`] = [1560, 440 + i * 130]; }
        for (const element of ctx.model.elements) {
          if (!(element instanceof Reactodia.EntityElement)) continue;
          const key = String(element.data.id).replace('https://example.org/qinglan/', '');
          if (positions[key]) element.setPosition({ x: positions[key][0], y: positions[key][1] });
        }
        await tool('fitCanvas');
      }
      else if (ctx.model.elements.length) await tool('runLayout', { algorithm: 'elk-force', spacing: 100 });
      // A layout can refer to nodes removed in the selected revision. Keep the
      // RDF facts authoritative and remove stale visual placeholders after import.
      if (currentResources.size) {
        for (const element of [...ctx.model.elements]) {
          if (element instanceof Reactodia.EntityElement && !String(element.data.id).startsWith('urn:vg:bnode:') && !currentResources.has(String(element.data.id))) ctx.model.removeElement(element.id);
        }
      }
      ctx.model.history.reset();
      // Restoring a diagram can stage Reactodia entityAdd events. Loading an
      // existing revision is not an authored edit and must not add rdf:types on Save.
      ctx.editor.setAuthoringState(Reactodia.AuthoringState.empty);
      await delay(200);
      return { elements: ctx.model.elements.length, isolated: crossOriginIsolated };
    } finally { loading = false; }
  }
  async function execute(method: string, data: any) {
    if (method === 'load') return load(data);
    if (method === 'export') {
      await hooks.commit();
      return { dataset: await rdfManager.exportToNQuads(), layouts: hooks.capture(),
        namespaces: Object.fromEntries(rdfManager.getNamespaces().map(e => [e.prefix, e.uri])) };
    }
    if (method === 'tool') { await hooks.commit(); return tool(data.name, data.args); }
    throw new Error(`未知编辑器操作：${method}`);
  }
  const receive = (event: MessageEvent) => {
    if (event.origin !== location.origin || event.source !== window.parent || event.data?.channel !== channel || event.data?.type !== 'request') return;
    const { id, method, data } = event.data;
    queue = queue.then(async () => {
      try { send('response', { success: true, value: await execute(method, data) }, id); }
      catch (error) { send('response', { success: false, error: String(error) }, id); }
    });
  };
  window.addEventListener('message', receive);
  const saveShortcut = (event: KeyboardEvent) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
      event.preventDefault(); requestProjectSave();
    }
  };
  window.addEventListener('keydown', saveShortcut, true);
  void (async () => {
    while (!disposed && !isStartupComplete()) await delay(100);
    if (disposed) return;
    editor = getWorkspaceRefs().ctx.editor;
    editor.events.on('changeAuthoringState', dirty);
    send('ready', { version: '1.8.1', isolated: crossOriginIsolated });
  })();
  return () => {
    disposed = true;
    window.removeEventListener('message', receive);
    window.removeEventListener('keydown', saveShortcut, true);
    rdfManager.offChange(dirty); unNamespace();
    editor?.events.off('changeAuthoringState', dirty);
  };
}
