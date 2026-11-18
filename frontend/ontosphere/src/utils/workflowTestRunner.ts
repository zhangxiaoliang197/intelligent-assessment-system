import { useOntologyStore } from '../stores/ontologyStore';

const PROV_NS = 'http://www.w3.org/ns/prov#';
const RDF_NS = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#';
const RDFS_NS = 'http://www.w3.org/2000/01/rdf-schema#';
const PPLAN_NS = 'http://purl.org/net/p-plan#';
const DATA_GRAPH = 'urn:vg:data';
const WORKFLOWS_GRAPH = 'urn:vg:workflows';

export interface CheckResult {
  name: string;
  passed: boolean;
  detail: string;
}

export interface ValidationResult {
  valid: boolean;
  checks: CheckResult[];
  errors: string[];
}

async function getWorker() {
  const rdfManager = useOntologyStore.getState().getRdfManager();
  if (!rdfManager) throw new Error('RDF manager not available');
  const worker = (rdfManager as any).worker;
  if (!worker) throw new Error('RDF manager worker not available');
  return worker;
}

async function findQuads(worker: any, opts: { subject?: string; predicate?: string; object?: string; graphName: string }) {
  const params: any = { graphName: opts.graphName };
  if (opts.subject) params.subject = opts.subject;
  if (opts.predicate) params.predicate = opts.predicate;
  if (opts.object) params.object = { termType: 'NamedNode', value: opts.object };
  return (await worker.call('getQuads', params)) ?? [];
}

export async function validateWorkflowExecution(activityIri: string): Promise<ValidationResult> {
  const checks: CheckResult[] = [];
  const errors: string[] = [];

  let worker: any;
  try {
    worker = await getWorker();
  } catch (err) {
    return { valid: false, checks: [], errors: [(err as Error).message] };
  }

  // Check 1: Activity exists in data graph
  const activityTypeQuads = await findQuads(worker, {
    subject: activityIri,
    predicate: `${RDF_NS}type`,
    graphName: DATA_GRAPH,
  });
  const isActivity = activityTypeQuads.some((q: any) =>
    q.object.value === `${PROV_NS}Activity` || q.object.value === `${PPLAN_NS}Activity`
  );
  checks.push({
    name: 'activity-exists',
    passed: isActivity,
    detail: isActivity ? `Found activity ${activityIri}` : `${activityIri} is not a prov:Activity in data graph`,
  });
  if (!isActivity) errors.push(`Activity not found: ${activityIri}`);

  // Check 2: Has prov:used linking to code resource
  const usedQuads = await findQuads(worker, {
    subject: activityIri,
    predicate: `${PROV_NS}used`,
    graphName: DATA_GRAPH,
  });
  checks.push({
    name: 'has-used-resources',
    passed: usedQuads.length > 0,
    detail: `Found ${usedQuads.length} prov:used resources`,
  });
  if (usedQuads.length === 0) errors.push('No prov:used resources found');

  // Check 3: Code resource has valid prov:atLocation
  let codeUrl = '';
  let requirementsUrl = '';
  for (const quad of usedQuads) {
    const resourceIri = quad.object.value;

    // Search both graphs
    let locQuads = await findQuads(worker, { subject: resourceIri, predicate: `${PROV_NS}atLocation`, graphName: WORKFLOWS_GRAPH });
    if (locQuads.length === 0) {
      locQuads = await findQuads(worker, { subject: resourceIri, predicate: `${PROV_NS}atLocation`, graphName: DATA_GRAPH });
    }
    if (locQuads.length === 0) continue;
    const location = locQuads[0].object.value;

    let typeQuads = await findQuads(worker, { subject: resourceIri, predicate: `${RDF_NS}type`, graphName: WORKFLOWS_GRAPH });
    if (typeQuads.length === 0) {
      typeQuads = await findQuads(worker, { subject: resourceIri, predicate: `${RDF_NS}type`, graphName: DATA_GRAPH });
    }
    const types: string[] = typeQuads.map((q: any) => q.object.value);
    const isCode = types.some((t: string) => t.includes('SoftwareSourceCode') || t.includes('Code'));

    if (isCode) {
      codeUrl = location;
    } else {
      let labelQuads = await findQuads(worker, { subject: resourceIri, predicate: `${RDFS_NS}label`, graphName: WORKFLOWS_GRAPH });
      if (labelQuads.length === 0) {
        labelQuads = await findQuads(worker, { subject: resourceIri, predicate: `${RDFS_NS}label`, graphName: DATA_GRAPH });
      }
      const labelText = labelQuads[0]?.object?.value?.toLowerCase() ?? resourceIri.toLowerCase();
      if (labelText.includes('requirement')) requirementsUrl = location;
    }
  }

  checks.push({
    name: 'code-url-found',
    passed: !!codeUrl,
    detail: codeUrl ? `Code URL: ${codeUrl}` : 'No code URL found in used resources',
  });
  if (!codeUrl) errors.push('No code URL found — ensure catalog is loaded');

  // Check 4: Code URL reachable
  if (codeUrl) {
    try {
      const resp = await fetch(codeUrl, { method: 'HEAD' });
      checks.push({
        name: 'code-url-reachable',
        passed: resp.ok,
        detail: resp.ok ? `Code URL reachable (${resp.status})` : `Code URL returned ${resp.status}`,
      });
      if (!resp.ok) errors.push(`Code URL not reachable: ${codeUrl} (${resp.status})`);
    } catch (err) {
      checks.push({ name: 'code-url-reachable', passed: false, detail: `Fetch failed: ${(err as Error).message}` });
      errors.push(`Code URL fetch failed: ${codeUrl}`);
    }
  }

  // Check 5: Requirements URL reachable (if present)
  if (requirementsUrl) {
    try {
      const resp = await fetch(requirementsUrl, { method: 'HEAD' });
      checks.push({
        name: 'requirements-url-reachable',
        passed: resp.ok,
        detail: resp.ok ? `Requirements URL reachable (${resp.status})` : `Requirements URL returned ${resp.status}`,
      });
      if (!resp.ok) errors.push(`Requirements URL not reachable: ${requirementsUrl}`);
    } catch (err) {
      checks.push({ name: 'requirements-url-reachable', passed: false, detail: `Fetch failed: ${(err as Error).message}` });
    }
  }

  // Check 6: Template step exists in workflows graph
  const stepQuads = await findQuads(worker, {
    subject: activityIri,
    predicate: `${PPLAN_NS}correspondsToStep`,
    graphName: DATA_GRAPH,
  });
  if (stepQuads.length > 0) {
    const stepIri = stepQuads[0].object.value;
    const stepExists = await findQuads(worker, {
      subject: stepIri,
      predicate: `${RDF_NS}type`,
      graphName: WORKFLOWS_GRAPH,
    });
    checks.push({
      name: 'template-step-exists',
      passed: stepExists.length > 0,
      detail: stepExists.length > 0 ? `Template step found: ${stepIri}` : `Template step not found in workflows graph: ${stepIri}`,
    });
    if (stepExists.length === 0) errors.push(`Template step missing from workflows graph: ${stepIri}`);
  }

  return { valid: errors.length === 0, checks, errors };
}

// Expose on window for dev console access
if (typeof window !== 'undefined') {
  (window as any).__vgTestWorkflow = validateWorkflowExecution;
}
