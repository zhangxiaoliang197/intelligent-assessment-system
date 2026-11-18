/**
 * @fileoverview Ontology Metrics Dashboard panel.
 *
 * Gathers structural counts from the data graph via rdfManager.getOntologyStats
 * (a direct N3 store query in the worker — no Comunica / SPARQL dependency),
 * then renders compact stat cards, a per-namespace breakdown table, and a set
 * of OQuaRE-flavored quality heuristics. The pure ratio math lives in
 * utils/ontologyMetrics so it stays unit-testable; this component only does
 * the gathering and presentation.
 *
 * NOTE: the "quality" ratios are simple heuristics, NOT a certified OQuaRE
 * assessment — the UI labels them as such.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  BarChart3,
  RefreshCw,
  Loader2,
  Gauge,
  Boxes,
  Link2,
  Tag,
  Users,
  Database,
} from 'lucide-react';
import { rdfManager } from '../../utils/rdfManager';
import {
  computeOntologyMetrics,
  formatRatio,
  formatPercent,
  type OntologyRawCounts,
} from '../../utils/ontologyMetrics';
import { cn } from '../../lib/utils';

const DATA_GRAPH = 'urn:vg:data';
const INFERRED_GRAPH = 'urn:vg:inferred';

/** Per-prefix subject count for the namespace breakdown table. */
interface NamespaceRow {
  prefix: string;
  uri: string;
  subjects: number;
}

export function MetricsPanel() {
  const [counts, setCounts] = useState<OntologyRawCounts | null>(null);
  const [nsRows, setNsRows] = useState<NamespaceRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const gather = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const stats = await rdfManager.getOntologyStats();

      const next: OntologyRawCounts = {
        totalTriples: stats.totalTriples,
        classCount: stats.classCount,
        objectPropertyCount: stats.objectPropertyCount,
        datatypePropertyCount: stats.datatypePropertyCount,
        namedIndividualCount: stats.namedIndividualCount,
        subjectCount: stats.subjectCount,
        labeledClassCount: stats.labeledClassCount,
        assertedTriples: stats.assertedTriples,
        inferredTriples: stats.inferredTriples,
      };

      const rows: NamespaceRow[] = stats.namespaceBreakdown
        .filter((r) => r.subjects > 0)
        .sort((a, b) => b.subjects - a.subjects)
        .map((r) => ({ prefix: r.prefix || ':', uri: r.uri, subjects: r.subjects }));

      if (mounted.current) {
        setCounts(next);
        setNsRows(rows);
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      if (mounted.current) {
        setError(message);
        toast.error(`Metrics failed: ${message}`);
      }
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  // Gather on mount, and refresh when subjects change in the data graph.
  useEffect(() => {
    mounted.current = true;
    void gather();
    const handler = (
      _subjects: string[],
      _quads?: unknown,
      _snapshot?: unknown,
      meta?: Record<string, unknown> | null,
    ) => {
      const graphName = meta && typeof meta.graphName === 'string' ? meta.graphName : null;
      if (graphName === null || graphName === DATA_GRAPH || graphName === INFERRED_GRAPH) {
        void gather();
      }
    };
    rdfManager.onSubjectsChange(handler as never);
    return () => {
      mounted.current = false;
      rdfManager.offSubjectsChange(handler as never);
    };
  }, [gather]);

  const metrics = useMemo(
    () => (counts ? computeOntologyMetrics(counts) : null),
    [counts],
  );

  const isEmpty = !loading && !error && counts !== null && counts.totalTriples === 0;

  return (
    <div className="space-y-2.5 px-2 pb-1">
      <div className="flex items-center justify-between px-1">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <BarChart3 className="h-3.5 w-3.5" />
          Ontology metrics
        </span>
        <button
          type="button"
          onClick={() => void gather()}
          disabled={loading}
          aria-label="Refresh metrics"
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
        >
          {loading ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <RefreshCw className="h-3 w-3" />
          )}
          Refresh
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-[11px] text-destructive break-words"
        >
          {error}
        </div>
      )}

      {loading && !counts && (
        <div className="px-3 py-6 text-center text-sm text-muted-foreground">
          <Loader2 className="mx-auto mb-2 h-6 w-6 animate-spin opacity-60" />
          Computing metrics…
        </div>
      )}

      {isEmpty && (
        <div className="px-3 py-6 text-center">
          <BarChart3 className="mx-auto mb-2 h-8 w-8 text-muted-foreground/40" />
          <p className="mb-1 text-sm text-muted-foreground">No data yet</p>
          <p className="text-xs text-muted-foreground">Load data to see metrics.</p>
        </div>
      )}

      {counts && !isEmpty && (
        <>
          {/* Stat cards */}
          <div className="grid grid-cols-2 gap-1.5" aria-label="Ontology counts">
            <StatCard icon={Database} label="Triples" value={counts.totalTriples} />
            <StatCard icon={Users} label="Subjects" value={counts.subjectCount} />
            <StatCard icon={Boxes} label="Classes" value={counts.classCount} />
            <StatCard
              icon={Link2}
              label="Object props"
              value={counts.objectPropertyCount}
            />
            <StatCard
              icon={Tag}
              label="Datatype props"
              value={counts.datatypePropertyCount}
            />
            <StatCard
              icon={Users}
              label="Individuals"
              value={counts.namedIndividualCount}
            />
          </div>

          {/* Namespace breakdown */}
          <section aria-label="Per-namespace subject breakdown" className="space-y-1">
            <h3 className="px-1 text-[11px] font-medium text-muted-foreground">
              Subjects by namespace
            </h3>
            {nsRows.length === 0 ? (
              <p className="px-1 text-[11px] text-muted-foreground/80">
                No namespaced subjects found.
              </p>
            ) : (
              <div className="max-h-48 overflow-auto rounded-md border">
                <table className="w-full border-collapse text-[11px]">
                  <thead className="sticky top-0 bg-muted">
                    <tr>
                      <th
                        scope="col"
                        className="border-b px-2 py-1 text-left font-mono font-medium"
                      >
                        prefix
                      </th>
                      <th
                        scope="col"
                        className="border-b px-2 py-1 text-right font-medium"
                      >
                        subjects
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {nsRows.map((row) => (
                      <tr key={row.uri} className="odd:bg-muted/30">
                        <td
                          className="border-b px-2 py-1 font-mono"
                          title={row.uri}
                        >
                          {row.prefix}
                        </td>
                        <td className="border-b px-2 py-1 text-right tabular-nums">
                          {row.subjects}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Quality heuristics */}
          {metrics && (
            <section aria-label="Quality heuristics" className="space-y-1">
              <h3 className="flex items-center gap-1 px-1 text-[11px] font-medium text-muted-foreground">
                <Gauge className="h-3 w-3" />
                Quality heuristics
              </h3>
              <div className="space-y-0.5 rounded-md border px-2 py-1.5">
                <RatioRow
                  label="Avg properties / class"
                  value={formatRatio(metrics.avgPropertiesPerClass)}
                />
                <RatioRow
                  label="Class : property ratio"
                  value={formatRatio(metrics.classToPropertyRatio)}
                />
                <RatioRow
                  label="Classes with rdfs:label"
                  value={formatPercent(metrics.labeledClassRatio)}
                />
                <RatioRow
                  label="Inferred : asserted triples"
                  value={formatRatio(metrics.inferredToAssertedRatio)}
                />
              </div>
              <p className="px-1 text-[10px] leading-snug text-muted-foreground/80">
                Simple OQuaRE-flavored heuristics — directional signals, not a
                certified OQuaRE assessment.
              </p>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Database;
  label: string;
  value: number;
}) {
  return (
    <div
      className={cn(
        'flex flex-col gap-0.5 rounded-md border bg-card px-2 py-1.5',
      )}
    >
      <span className="flex items-center gap-1 text-[10px] text-muted-foreground">
        <Icon className="h-3 w-3" />
        {label}
      </span>
      <span className="text-base font-semibold tabular-nums text-foreground">
        {value.toLocaleString()}
      </span>
    </div>
  );
}

function RatioRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between text-[11px]">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-medium tabular-nums text-foreground">
        {value}
      </span>
    </div>
  );
}
