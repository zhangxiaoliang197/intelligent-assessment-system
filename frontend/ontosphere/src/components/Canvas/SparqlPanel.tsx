import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  Play,
  Loader2,
  Database,
  ChevronDown,
  Check,
  X,
} from 'lucide-react';
import { rdfManager } from '../../utils/rdfManager';
import { abbreviateIri } from '@/mcp/tools/graph';
import { Badge } from '../ui/badge';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '../ui/dropdown-menu';
import type { NamespaceEntry } from '../../constants/namespaces';
import { cn } from '../../lib/utils';

/** Max rows/triples rendered in the results table before truncating the view. */
const MAX_DISPLAY_ROWS = 200;
/** Limit handed to the worker (mirrors the queryGraph MCP tool default). */
const QUERY_LIMIT = 1000;

/** Shape of the worker SPARQL result (see rdfManager.sparqlQuery). */
type SparqlResult =
  | { type: 'select'; rows: Array<Record<string, string>> }
  | { type: 'construct'; triples: Array<{ s: string; p: string; o: string }> }
  | { type: 'ask'; boolean: boolean }
  | { type: 'update' };

/** Build a default query body using the registered prefixes as PREFIX lines. */
function buildDefaultQuery(namespaces: NamespaceEntry[]): string {
  const seen = new Set<string>();
  const lines: string[] = [];
  for (const ns of namespaces) {
    if (!ns.prefix || !ns.uri) continue;
    const key = ns.prefix.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    lines.push(`PREFIX ${ns.prefix}: <${ns.uri}>`);
  }
  const prefixBlock = lines.length ? lines.join('\n') + '\n\n' : '';
  return `${prefixBlock}SELECT * WHERE {\n  ?s ?p ?o\n} LIMIT 50`;
}

const EXAMPLE_QUERIES: Array<{ label: string; query: string }> = [
  {
    label: 'All classes',
    query:
      'SELECT DISTINCT ?class WHERE {\n  { ?class a owl:Class } UNION { ?class a rdfs:Class }\n} LIMIT 100',
  },
  {
    label: 'All object properties',
    query:
      'SELECT DISTINCT ?property WHERE {\n  ?property a owl:ObjectProperty\n} LIMIT 100',
  },
  {
    label: 'All triples',
    query: 'SELECT * WHERE {\n  ?s ?p ?o\n} LIMIT 50',
  },
];

function abbrev(value: string): string {
  try {
    return abbreviateIri(value);
  } catch {
    return value;
  }
}

export function SparqlPanel() {
  const [namespaces, setNamespaces] = useState<NamespaceEntry[]>(() =>
    rdfManager.getNamespaces(),
  );
  const [query, setQuery] = useState<string>(() =>
    buildDefaultQuery(rdfManager.getNamespaces()),
  );
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<SparqlResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Keep the prefix list fresh as ontologies are loaded; do NOT clobber the
  // user's in-progress query — only refresh the available prefix dropdown.
  useEffect(() => {
    const unsubscribe = rdfManager.onNamespacesChange?.((next) =>
      setNamespaces(next),
    );
    return () => unsubscribe?.();
  }, []);

  const sortedNamespaces = useMemo(
    () =>
      [...namespaces]
        .filter((n) => n.prefix && n.uri)
        .sort((a, b) => a.prefix.localeCompare(b.prefix)),
    [namespaces],
  );

  /** Insert a PREFIX declaration for the chosen namespace at the caret (or top). */
  const insertPrefix = useCallback(
    (ns: NamespaceEntry) => {
      const line = `PREFIX ${ns.prefix}: <${ns.uri}>`;
      setQuery((prev) => {
        // Skip if already declared.
        const re = new RegExp(
          `^\\s*PREFIX\\s+${ns.prefix}\\s*:`,
          'im',
        );
        if (re.test(prev)) {
          toast.info(`Prefix "${ns.prefix}" is already declared.`);
          return prev;
        }
        const ta = textareaRef.current;
        if (ta && typeof ta.selectionStart === 'number') {
          const pos = ta.selectionStart;
          const before = prev.slice(0, pos);
          const after = prev.slice(pos);
          const needsNl = before.length > 0 && !before.endsWith('\n');
          return `${before}${needsNl ? '\n' : ''}${line}\n${after}`;
        }
        return `${line}\n${prev}`;
      });
    },
    [],
  );

  const runQuery = useCallback(async () => {
    const sparql = query.trim();
    if (!sparql) {
      setError('Enter a SPARQL query.');
      return;
    }
    setRunning(true);
    setError(null);
    try {
      const res = (await rdfManager.sparqlQuery(sparql, {
        limit: QUERY_LIMIT,
      })) as SparqlResult;
      setResult(res);
      if (res?.type === 'update') {
        toast.success('Update applied — the graph changed.');
      }
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setResult(null);
      setError(message);
      toast.error(`SPARQL failed: ${message}`);
    } finally {
      setRunning(false);
    }
  }, [query]);

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        void runQuery();
      }
    },
    [runQuery],
  );

  return (
    <div className="space-y-2 px-2 pb-1">
      {/* Editor */}
      <div className="space-y-1.5">
        <label
          htmlFor="sparql-editor"
          className="block text-[11px] font-medium text-muted-foreground"
        >
          SPARQL query
        </label>
        <textarea
          id="sparql-editor"
          ref={textareaRef}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKeyDown}
          spellCheck={false}
          aria-label="SPARQL query editor"
          className={cn(
            'w-full min-h-[140px] rounded-md border border-input bg-background',
            'px-2 py-1.5 font-mono text-[11px] leading-relaxed',
            'resize-y ring-offset-background placeholder:text-muted-foreground',
            'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
          )}
          placeholder="SELECT * WHERE { ?s ?p ?o } LIMIT 50"
        />
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-1.5">
        <button
          type="button"
          onClick={() => void runQuery()}
          disabled={running}
          aria-label="Run SPARQL query"
          className={cn(
            'inline-flex items-center gap-1.5 rounded-md bg-primary px-2.5 py-1',
            'text-xs font-medium text-primary-foreground transition-colors',
            'hover:bg-primary/90 disabled:opacity-50 disabled:pointer-events-none',
          )}
        >
          {running ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          {running ? 'Running…' : 'Run'}
        </button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              aria-label="Insert a namespace prefix"
              className={cn(
                'inline-flex items-center gap-1 rounded-md border border-input',
                'px-2 py-1 text-xs text-foreground transition-colors hover:bg-accent',
              )}
            >
              <Database className="h-3.5 w-3.5" />
              Prefixes
              <ChevronDown className="h-3 w-3 opacity-60" />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            align="start"
            className="z-[99999] max-h-64 min-w-[12rem] overflow-y-auto"
          >
            <DropdownMenuLabel className="text-xs text-muted-foreground">
              Insert PREFIX
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            {sortedNamespaces.length === 0 ? (
              <div className="px-2 py-1.5 text-xs text-muted-foreground">
                No namespaces registered
              </div>
            ) : (
              sortedNamespaces.map((ns) => (
                <DropdownMenuItem
                  key={`${ns.prefix}:${ns.uri}`}
                  onSelect={() => insertPrefix(ns)}
                  className="text-xs"
                >
                  <span className="font-mono font-medium">{ns.prefix}:</span>
                  <span className="ml-1.5 truncate text-muted-foreground" title={ns.uri}>
                    {ns.uri}
                  </span>
                </DropdownMenuItem>
              ))
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        <span className="ml-auto text-[10px] text-muted-foreground">
          Ctrl/⌘+Enter to run
        </span>
      </div>

      {/* Example queries */}
      <div className="flex flex-wrap items-center gap-1">
        <span className="text-[10px] text-muted-foreground">Examples:</span>
        {EXAMPLE_QUERIES.map((ex) => (
          <button
            key={ex.label}
            type="button"
            onClick={() => setQuery(ex.query)}
            className="rounded border border-input px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            {ex.label}
          </button>
        ))}
      </div>

      <p className="text-[10px] text-muted-foreground/80">
        Queries are read-only unless you use INSERT/DELETE. Registered prefixes
        are injected automatically.
      </p>

      {/* Error */}
      {error && (
        <div
          role="alert"
          className="flex items-start gap-1.5 rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-[11px] text-destructive"
        >
          <X className="mt-0.5 h-3 w-3 shrink-0" />
          <span className="break-words">{error}</span>
        </div>
      )}

      {/* Results */}
      {result && !error && <SparqlResults result={result} />}
    </div>
  );
}

function SparqlResults({ result }: { result: SparqlResult }) {
  if (result.type === 'ask') {
    return (
      <div className="flex items-center gap-2 pt-1">
        <span className="text-[11px] text-muted-foreground">Result:</span>
        {result.boolean ? (
          <Badge className="gap-1 bg-green-600 text-white hover:bg-green-600">
            <Check className="h-3 w-3" /> true
          </Badge>
        ) : (
          <Badge variant="destructive" className="gap-1">
            <X className="h-3 w-3" /> false
          </Badge>
        )}
      </div>
    );
  }

  if (result.type === 'update') {
    return (
      <div className="rounded-md border border-green-600/40 bg-green-600/10 px-2 py-1.5 text-[11px] text-green-700 dark:text-green-400">
        Update applied. The graph has changed.
      </div>
    );
  }

  if (result.type === 'select') {
    const rows = result.rows ?? [];
    if (rows.length === 0) {
      return (
        <p className="pt-1 text-[11px] text-muted-foreground">
          0 rows returned.
        </p>
      );
    }
    // Stable, union column set across rows.
    const columns = Array.from(
      rows.reduce((set, row) => {
        for (const k of Object.keys(row)) set.add(k);
        return set;
      }, new Set<string>()),
    );
    const shown = rows.slice(0, MAX_DISPLAY_ROWS);
    return (
      <div className="space-y-1 pt-1">
        <ResultCount shown={shown.length} total={rows.length} noun="row" />
        <div className="max-h-64 overflow-auto rounded-md border">
          <table className="w-full border-collapse text-[11px]">
            <thead className="sticky top-0 bg-muted">
              <tr>
                {columns.map((col) => (
                  <th
                    key={col}
                    scope="col"
                    className="border-b px-2 py-1 text-left font-mono font-medium"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {shown.map((row, i) => (
                <tr key={i} className="odd:bg-muted/30">
                  {columns.map((col) => (
                    <td
                      key={col}
                      className="border-b px-2 py-1 align-top font-mono"
                      title={row[col] ?? ''}
                    >
                      {row[col] != null ? abbrev(row[col]) : ''}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // CONSTRUCT / DESCRIBE
  const triples = result.triples ?? [];
  if (triples.length === 0) {
    return (
      <p className="pt-1 text-[11px] text-muted-foreground">
        0 triples constructed.
      </p>
    );
  }
  const shown = triples.slice(0, MAX_DISPLAY_ROWS);
  return (
    <div className="space-y-1 pt-1">
      <ResultCount shown={shown.length} total={triples.length} noun="triple" />
      <div className="max-h-64 overflow-auto rounded-md border">
        <table className="w-full border-collapse text-[11px]">
          <thead className="sticky top-0 bg-muted">
            <tr>
              {['subject', 'predicate', 'object'].map((h) => (
                <th
                  key={h}
                  scope="col"
                  className="border-b px-2 py-1 text-left font-mono font-medium"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((t, i) => (
              <tr key={i} className="odd:bg-muted/30">
                <td className="border-b px-2 py-1 align-top font-mono" title={t.s}>
                  {abbrev(t.s)}
                </td>
                <td className="border-b px-2 py-1 align-top font-mono" title={t.p}>
                  {abbrev(t.p)}
                </td>
                <td className="border-b px-2 py-1 align-top font-mono" title={t.o}>
                  {abbrev(t.o)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ResultCount({
  shown,
  total,
  noun,
}: {
  shown: number;
  total: number;
  noun: string;
}) {
  return (
    <p className="text-[11px] text-muted-foreground">
      {shown < total
        ? `Showing ${shown} of ${total} ${noun}s`
        : `${total} ${noun}${total !== 1 ? 's' : ''}`}
    </p>
  );
}
