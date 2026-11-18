import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  ChevronDown,
  ChevronRight,
  History,
  Plus,
  Minus,
  Undo2,
  RefreshCw,
} from 'lucide-react';
import { Badge } from '../ui/badge';
import { cn } from '../../lib/utils';
import { toPrefixed } from '../../utils/termUtils';
import {
  getProvenanceRecorder,
  onEditsChanged,
  type EditSummary,
  type ProvQuad,
} from '@/mcp/provenance';

/** How many triples to show per side before collapsing into a "… and N more" line. */
const MAX_TRIPLES_SHOWN = 12;

function shortTerm(value: string): string {
  try {
    return toPrefixed(value);
  } catch {
    return value;
  }
}

function relativeTime(iso: string): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return iso;
  const diffMs = Date.now() - then;
  const sec = Math.round(diffMs / 1000);
  if (sec < 5) return 'just now';
  if (sec < 60) return `${sec}s ago`;
  const min = Math.round(sec / 60);
  if (min < 60) return `${min}m ago`;
  const hr = Math.round(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.round(hr / 24);
  return `${day}d ago`;
}

function agentLabel(agent: string): string {
  const local = agent.split(/[:/#]/).pop();
  return local && local.trim() ? local : agent;
}

function TripleRow({ quad, kind }: { quad: ProvQuad; kind: 'added' | 'removed' }) {
  const sign = kind === 'added' ? '+' : '−';
  const colorClass = kind === 'added' ? 'text-green-600 dark:text-green-400' : 'text-destructive';
  return (
    <div
      className={cn(
        'flex items-start gap-1 font-mono text-[11px] leading-snug',
        colorClass,
        kind === 'removed' && 'line-through decoration-destructive/50',
      )}
    >
      <span className="shrink-0 select-none">{sign}</span>
      <span className="break-all">
        {shortTerm(quad.s)} {shortTerm(quad.p)} {shortTerm(quad.o)}
      </span>
    </div>
  );
}

function BatchDiff({ batchId }: { batchId: string }) {
  const record = getProvenanceRecorder().getBatch(batchId);
  if (!record) {
    return <div className="px-2 py-1.5 text-xs text-muted-foreground">Diff unavailable.</div>;
  }
  const { added, removed } = record;
  const renderSide = (quads: ProvQuad[], kind: 'added' | 'removed') => {
    if (quads.length === 0) return null;
    const shown = quads.slice(0, MAX_TRIPLES_SHOWN);
    const remaining = quads.length - shown.length;
    return (
      <div className="space-y-0.5">
        {shown.map((q, i) => (
          <TripleRow key={`${kind}-${i}`} quad={q} kind={kind} />
        ))}
        {remaining > 0 && (
          <div className="text-[11px] text-muted-foreground pl-3">
            … and {remaining} more
          </div>
        )}
      </div>
    );
  };
  if (added.length === 0 && removed.length === 0) {
    return <div className="px-2 py-1.5 text-xs text-muted-foreground">No triple changes recorded.</div>;
  }
  return (
    <div className="px-2 py-1.5 space-y-1.5 bg-muted/30">
      {renderSide(added, 'added')}
      {renderSide(removed, 'removed')}
    </div>
  );
}

export function AgentEditsPanel() {
  const [edits, setEdits] = useState<EditSummary[]>([]);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [reverting, setReverting] = useState<Set<string>>(new Set());
  const mounted = useRef(true);

  const refresh = useCallback(() => {
    // FIX3: no-op when unmounted so async callers (e.g. the revert finally
    // block) cannot trigger setEdits on an unmounted component (React warning).
    if (!mounted.current) return;
    try {
      setEdits(getProvenanceRecorder().listEdits());
    } catch (err) {
      console.warn('[AgentEditsPanel] Failed to list edits', err);
      setEdits([]);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const unsubscribe = onEditsChanged(() => {
      if (mounted.current) refresh();
    });
    return () => {
      mounted.current = false;
      unsubscribe();
    };
  }, [refresh]);

  const toggle = (batchId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(batchId)) next.delete(batchId);
      else next.add(batchId);
      return next;
    });
  };

  const handleRevert = useCallback(
    async (batchId: string) => {
      setReverting((prev) => new Set(prev).add(batchId));
      try {
        const result = await getProvenanceRecorder().revertBatch(batchId);
        if (result.alreadyReverted) {
          toast.info('Batch was already reverted.');
        } else if (result.success) {
          const { addedRemoved, removedRestored } = result.reverted;
          const { addedToRemove, removedToRestore } = result.requested;
          const partial =
            addedRemoved < addedToRemove || removedRestored < removedToRestore;
          const summary = `−${addedRemoved} re-removed, +${removedRestored} restored`;
          if (partial) {
            toast.warning(`Partially reverted (${summary}).`);
          } else {
            toast.success(`Reverted batch (${summary}).`);
          }
        } else {
          toast.error('Revert failed.');
        }
      } catch (err) {
        console.error('[AgentEditsPanel] Revert failed', err);
        toast.error('Revert failed (see console).');
      } finally {
        if (mounted.current) {
          setReverting((prev) => {
            const next = new Set(prev);
            next.delete(batchId);
            return next;
          });
        }
        refresh();
      }
    },
    [refresh],
  );

  return (
    <div className="space-y-1.5 px-2">
      <div className="flex items-center justify-between px-1">
        <span className="text-xs text-muted-foreground">
          {edits.length} edit{edits.length !== 1 ? 's' : ''}
        </span>
        <button
          type="button"
          onClick={refresh}
          aria-label="Refresh agent edits"
          className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
        >
          <RefreshCw className="w-3 h-3" />
          Refresh
        </button>
      </div>

      {edits.length === 0 ? (
        <div className="px-3 py-6 text-center">
          <History className="w-8 h-8 mx-auto mb-2 text-muted-foreground/40" />
          <p className="text-sm text-muted-foreground mb-1">No agent edits yet</p>
          <p className="text-xs text-muted-foreground">
            Edits made by AI agents will appear here, with diffs and one-click revert.
          </p>
        </div>
      ) : (
        <ul className="space-y-1">
          {edits.map((edit) => {
            const isOpen = expanded.has(edit.batchId);
            const isReverting = reverting.has(edit.batchId);
            return (
              <li key={edit.batchId} className="border rounded-md overflow-hidden">
                <div className="flex items-stretch">
                  <button
                    type="button"
                    onClick={() => toggle(edit.batchId)}
                    aria-expanded={isOpen}
                    className="flex-1 flex items-center gap-1.5 px-2 py-1.5 text-xs hover:bg-accent/50 transition-colors min-w-0 text-left"
                  >
                    {isOpen ? (
                      <ChevronDown className="w-3 h-3 shrink-0" />
                    ) : (
                      <ChevronRight className="w-3 h-3 shrink-0" />
                    )}
                    <span className="font-medium truncate" title={edit.tool}>
                      {edit.tool}
                    </span>
                    <span className="flex items-center gap-1 shrink-0 font-mono text-[11px]">
                      <span className="text-green-600 dark:text-green-400 inline-flex items-center">
                        <Plus className="w-2.5 h-2.5" />
                        {edit.addedCount}
                      </span>
                      <span className="text-destructive inline-flex items-center">
                        <Minus className="w-2.5 h-2.5" />
                        {edit.removedCount}
                      </span>
                    </span>
                    {edit.reverted && (
                      <Badge variant="secondary" className="text-[9px] h-4 px-1 shrink-0">
                        reverted
                      </Badge>
                    )}
                  </button>
                  {!edit.reverted && (
                    <button
                      type="button"
                      onClick={() => handleRevert(edit.batchId)}
                      disabled={isReverting}
                      aria-label={`Revert ${edit.tool} edit`}
                      className="shrink-0 flex items-center gap-1 px-2 border-l text-[11px] text-muted-foreground hover:text-foreground hover:bg-accent/50 transition-colors disabled:opacity-50 disabled:pointer-events-none"
                    >
                      <Undo2 className="w-3 h-3" />
                      {isReverting ? 'Reverting…' : 'Revert'}
                    </button>
                  )}
                </div>
                <div className="flex items-center gap-2 px-2 pb-1 text-[10px] text-muted-foreground">
                  <span title={edit.timestamp}>{relativeTime(edit.timestamp)}</span>
                  <span className="opacity-50">·</span>
                  <span className="truncate" title={edit.agent}>
                    {agentLabel(edit.agent)}
                  </span>
                </div>
                {isOpen && <BatchDiff batchId={edit.batchId} />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
