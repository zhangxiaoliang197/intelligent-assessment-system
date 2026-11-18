import { useRef, useEffect, useState, useCallback } from 'react';
import { X, Clock } from 'lucide-react';
import { Progress } from '../ui/progress';
import { Badge } from '../ui/badge';
import { cn } from '@/lib/utils';
import { useWorkflowExecutionStore, type PendingInput } from '@/stores/workflowExecutionStore';
import { getPyodideClient } from '@/utils/pyodideManager.workerClient';
import { getWorkspaceRefs } from '@/mcp/workspaceContext';
import type { InputOption } from '@/workers/pyodide.workerProtocol';

/** Extract the underlying value from an InputOption (string or {label, value} object). */
function getOptionValue(opt: InputOption): string {
  return typeof opt === 'string' ? opt : opt.value;
}

/** Extract the display label from an InputOption. */
function getOptionLabel(opt: InputOption): string {
  return typeof opt === 'string' ? opt : opt.label;
}

function computeInitialInput(pi: PendingInput | null): string {
  if (!pi) return '';
  let v = pi.defaultValue ?? '';
  if (!v && pi.inputType === 'select' && pi.options?.length) {
    v = getOptionValue(pi.options[0]);
  }
  return v;
}

export function WorkflowExecutionDialog() {
  const {
    isOpen, isExecuting, activityLabel, progress, progressStage,
    log, pendingInput, error, executionTime, close,
  } = useWorkflowExecutionStore();

  const logEndRef = useRef<HTMLDivElement>(null);
  const logContainerRef = useRef<HTMLDivElement>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const [inputValue, setInputValue] = useState(() => computeInitialInput(pendingInput));
  const inputRef = useRef<HTMLInputElement | HTMLSelectElement>(null);
  const [prevPendingInput, setPrevPendingInput] = useState(pendingInput);
  if (pendingInput !== prevPendingInput) {
    setPrevPendingInput(pendingInput);
    setInputValue(computeInitialInput(pendingInput));
  }

  useEffect(() => {
    if (autoScroll && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [log, autoScroll]);

  useEffect(() => {
    if (pendingInput) {
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [pendingInput]);

  const handleLogScroll = useCallback(() => {
    const el = logContainerRef.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(nearBottom);
  }, []);

  const handleSubmitInput = useCallback(() => {
    if (!pendingInput) return;
    try {
      const client = getPyodideClient();
      console.debug('[WorkflowExecutionDialog] respondToInput', { inputValue, pendingInput: pendingInput.requestId });
      client.respondToInput(inputValue);
      useWorkflowExecutionStore.getState().setPendingInput(null);
      setInputValue('');
    } catch (err) {
      console.error('[WorkflowExecutionDialog] submit failed', err);
    }
  }, [pendingInput, inputValue]);

  const handleCancelInput = useCallback(() => {
    if (!pendingInput) return;
    const client = getPyodideClient();
    client.respondToInput('', true);
    useWorkflowExecutionStore.getState().setPendingInput(null);
    setInputValue('');
  }, [pendingInput]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmitInput();
    }
  }, [handleSubmitInput]);

  // Cancel pending input when dialog closes (prevents worker hang)
  const pendingInputRef = useRef(pendingInput);
  useEffect(() => {
    pendingInputRef.current = pendingInput;
  }, [pendingInput]);
  useEffect(() => {
    if (isOpen) return;
    // Dialog just closed — if there was a pending input, cancel it
    if (pendingInputRef.current) {
      try {
        getPyodideClient().respondToInput('', true);
      } catch {
        // Ignore if buffers not initialized (e.g., worker never started)
      }
      useWorkflowExecutionStore.getState().setPendingInput(null);
    }

    // Navigate to last step's output entities on successful close
    const { lastOutputIris, error: execError } = useWorkflowExecutionStore.getState();
    if (lastOutputIris.length > 0 && !execError) {
      const { navigateToIri } = getWorkspaceRefs();
      if (navigateToIri) {
        // Small delay to let dialog unmount before viewport animates
        setTimeout(() => navigateToIri(lastOutputIris[0]), 150);
      }
    }
  }, [isOpen]);

  const handleClose = useCallback(() => {
    close();
  }, [close]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      // Block Escape close while input is pending — user must use X button
      if (e.key === 'Escape') {
        if (pendingInputRef.current) return;
        close();
      }
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [isOpen, close]);

  if (!isOpen) return null;

  const statusBadge = error
    ? <Badge variant="destructive">Error</Badge>
    : isExecuting
      ? <Badge variant="default">Running</Badge>
      : <Badge variant="secondary">Complete</Badge>;

  return (
    <div
      className="absolute inset-0 z-50 flex items-start justify-center bg-black/60 pt-4"
      onMouseDown={e => { if (e.target === e.currentTarget && !pendingInputRef.current) close(); }}
    >
      <div className="w-full max-w-[min(90%,48rem)] max-h-[calc(100dvh-2rem)] flex flex-col overflow-hidden rounded-lg border bg-background shadow-lg animate-in fade-in-0 zoom-in-95 duration-200">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <div className="min-w-0 flex-1">
            <h2 className="text-sm font-semibold flex items-center gap-2 truncate">
              {activityLabel ?? 'Workflow Execution'}
              {statusBadge}
            </h2>
            {progressStage && (
              <p className="text-xs text-muted-foreground mt-0.5">{progressStage}</p>
            )}
          </div>
          <button
            onClick={handleClose}
            className="rounded-sm p-1.5 opacity-70 hover:opacity-100 hover:bg-accent transition-colors ml-2 flex-shrink-0"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Progress bar */}
        {isExecuting && progress > 0 && (
          <div className="px-4 py-2">
            <Progress value={progress} className="h-2" />
          </div>
        )}

        {/* Log area */}
        <div
          ref={logContainerRef}
          onScroll={handleLogScroll}
          className="flex-1 overflow-y-auto px-4 py-2 min-h-[120px]"
        >
          {log.length === 0 && !error && (
            <p className="text-sm text-muted-foreground italic">Waiting for output…</p>
          )}
          {log.map((entry, i) => (
            <div
              key={i}
              className={cn(
                'text-xs font-mono whitespace-pre-wrap break-all py-0.5',
                entry.type === 'stdout' && 'text-foreground',
                entry.type === 'stderr' && 'text-orange-500 dark:text-orange-400',
                entry.type === 'error' && 'text-destructive',
                entry.type === 'info' && 'text-muted-foreground',
                entry.type === 'progress' && 'text-muted-foreground italic',
              )}
            >
              {entry.text}
            </div>
          ))}
          {error && (
            <div className="text-xs font-mono whitespace-pre-wrap break-all py-1 text-destructive border-t border-destructive/20 mt-2 pt-2">
              {error}
            </div>
          )}
          <div ref={logEndRef} />
        </div>

        {/* Input prompt */}
        {pendingInput && (
          <div className="px-4 py-3 border-t bg-muted/50">
            <label className="text-xs font-medium mb-1.5 block">{pendingInput.prompt}</label>
            <div className="flex gap-2">
              {pendingInput.inputType === 'select' && pendingInput.options ? (
                <select
                  ref={inputRef as React.RefObject<HTMLSelectElement>}
                  value={inputValue}
                  onChange={e => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  className="flex-1 min-h-[44px] rounded-md border bg-background px-3 py-2 text-sm"
                >
                  {pendingInput.options.map(opt => (
                    <option key={getOptionValue(opt)} value={getOptionValue(opt)}>
                      {getOptionLabel(opt)}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  ref={inputRef as React.RefObject<HTMLInputElement>}
                  type={pendingInput.inputType === 'number' ? 'number' : 'text'}
                  value={inputValue}
                  onChange={e => setInputValue(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type your response…"
                  className="flex-1 min-h-[44px] rounded-md border bg-background px-3 py-2 text-sm"
                />
              )}
              <button
                onClick={handleSubmitInput}
                className="min-h-[44px] px-4 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90"
              >
                Submit
              </button>
              <button
                onClick={handleCancelInput}
                className="min-h-[44px] px-3 rounded-md border text-sm hover:bg-accent"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Footer */}
        {executionTime != null && !isExecuting && (
          <div className="px-4 py-2 border-t text-xs text-muted-foreground flex items-center gap-1">
            <Clock className="w-3 h-3" />
            {(executionTime / 1000).toFixed(1)}s
          </div>
        )}
      </div>
    </div>
  );
}
