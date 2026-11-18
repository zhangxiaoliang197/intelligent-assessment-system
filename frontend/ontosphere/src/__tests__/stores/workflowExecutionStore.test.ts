import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { useWorkflowExecutionStore } from '../../stores/workflowExecutionStore';
import type { LogEntry } from '../../stores/workflowExecutionStore';

describe('INPUT_TIMEOUT_MS in pyodide.runtime', () => {
  it('INPUT_TIMEOUT_MS is 300000 (5 minutes)', () => {
    // Read the source file and verify the constant value
    const source = readFileSync(
      resolve(__dirname, '../../workers/pyodide.runtime.ts'),
      'utf-8'
    );
    const match = source.match(/const\s+INPUT_TIMEOUT_MS\s*=\s*([\d_]+)/);
    expect(match).toBeTruthy();
    const value = Number(match![1].replace(/_/g, ''));
    expect(value).toBe(300_000);
  });
});

describe('workflowExecutionStore', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useWorkflowExecutionStore.getState().reset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('open() sets isOpen, activityIri, and resets previous state', () => {
    const store = useWorkflowExecutionStore;
    store.getState().setError('old error');
    store.getState().open('urn:act:1', 'Load Data');

    const s = store.getState();
    expect(s.isOpen).toBe(true);
    expect(s.activityIri).toBe('urn:act:1');
    expect(s.activityLabel).toBe('Load Data');
    expect(s.error).toBeNull();
    expect(s.log).toEqual([]);
  });

  it('appendLog() adds entries after 100ms flush', () => {
    const store = useWorkflowExecutionStore;
    const entry: LogEntry = { type: 'stdout', text: 'hello', timestamp: 1000 };
    store.getState().appendLog(entry);

    expect(store.getState().log).toEqual([]);

    vi.advanceTimersByTime(100);
    expect(store.getState().log).toEqual([entry]);
  });

  it('appendLog() batches rapid calls', () => {
    const store = useWorkflowExecutionStore;
    store.getState().appendLog({ type: 'stdout', text: 'a', timestamp: 1 });
    store.getState().appendLog({ type: 'stdout', text: 'b', timestamp: 2 });
    store.getState().appendLog({ type: 'stderr', text: 'c', timestamp: 3 });

    vi.advanceTimersByTime(100);
    expect(store.getState().log).toHaveLength(3);
    expect(store.getState().log.map(e => e.text)).toEqual(['a', 'b', 'c']);
  });

  it('setProgress() updates progress and stage text', () => {
    const store = useWorkflowExecutionStore;
    store.getState().setProgress(42, 'Installing packages');

    expect(store.getState().progress).toBe(42);
    expect(store.getState().progressStage).toBe('Installing packages');
  });

  it('setPendingInput() stores input request; null clears it', () => {
    const store = useWorkflowExecutionStore;
    const input = { requestId: 'r1', prompt: 'Enter name:', inputType: 'text' as const };
    store.getState().setPendingInput(input);
    expect(store.getState().pendingInput).toEqual(input);

    store.getState().setPendingInput(null);
    expect(store.getState().pendingInput).toBeNull();
  });

  it('close() sets isOpen=false but preserves log for re-open', () => {
    const store = useWorkflowExecutionStore;
    store.getState().open('urn:act:1', 'Test');
    store.getState().setExecuting(true);
    store.getState().appendLog({ type: 'stdout', text: 'data', timestamp: 1 });
    vi.advanceTimersByTime(100);

    store.getState().close();
    expect(store.getState().isOpen).toBe(false);
    expect(store.getState().log).toHaveLength(1);
    expect(store.getState().isExecuting).toBe(true);
  });

  it('open() while isExecuting=true reopens without resetting log', () => {
    const store = useWorkflowExecutionStore;
    store.getState().open('urn:act:1', 'Test');
    store.getState().setExecuting(true);
    store.getState().appendLog({ type: 'stdout', text: 'data', timestamp: 1 });
    vi.advanceTimersByTime(100);
    store.getState().close();

    store.getState().open('urn:act:1', 'Test');
    expect(store.getState().isOpen).toBe(true);
    expect(store.getState().log).toHaveLength(1);
  });

  it('open() while isExecuting=false resets all state for fresh run', () => {
    const store = useWorkflowExecutionStore;
    store.getState().open('urn:act:1', 'Test');
    store.getState().appendLog({ type: 'stdout', text: 'old', timestamp: 1 });
    vi.advanceTimersByTime(100);
    store.getState().setExecuting(false);
    store.getState().close();

    store.getState().open('urn:act:2', 'New Run');
    const s = store.getState();
    expect(s.isOpen).toBe(true);
    expect(s.activityIri).toBe('urn:act:2');
    expect(s.log).toEqual([]);
  });

  it('reset() clears all state to defaults', () => {
    const store = useWorkflowExecutionStore;
    store.getState().open('urn:act:1', 'Test');
    store.getState().setExecuting(true);
    store.getState().setProgress(50, 'Running');
    store.getState().setError('boom');

    store.getState().reset();
    const s = store.getState();
    expect(s.isOpen).toBe(false);
    expect(s.isExecuting).toBe(false);
    expect(s.activityIri).toBeNull();
    expect(s.progress).toBe(0);
    expect(s.error).toBeNull();
  });
});
