// src/components/Canvas/__tests__/AgentEditsPanel.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, act } from '@testing-library/react';

// --- mocks (declared before importing the component under test) ---

const hoisted = vi.hoisted(() => ({
  toastMocks: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
  listEdits: vi.fn(),
  getBatch: vi.fn(),
  revertBatch: vi.fn(),
  editsChangedCb: { current: null as null | (() => void) },
}));
const { toastMocks, listEdits, getBatch, revertBatch } = hoisted;

vi.mock('sonner', () => ({ toast: hoisted.toastMocks }));

// Keep term display deterministic and dependency-free.
vi.mock('../../../utils/termUtils', () => ({
  toPrefixed: (iri: string) => iri,
}));

vi.mock('@/mcp/provenance', () => ({
  getProvenanceRecorder: () => ({
    listEdits: hoisted.listEdits,
    getBatch: hoisted.getBatch,
    revertBatch: hoisted.revertBatch,
  }),
  onEditsChanged: (cb: () => void) => {
    hoisted.editsChangedCb.current = cb;
    return () => {
      hoisted.editsChangedCb.current = null;
    };
  },
}));

import { AgentEditsPanel } from '../AgentEditsPanel';

const BATCH_A = {
  batchId: 'batch-a',
  tool: 'addNode',
  agent: 'urn:vg:agent:mcp-agent',
  timestamp: new Date().toISOString(),
  addedCount: 2,
  removedCount: 0,
  reverted: false,
};

const BATCH_B = {
  batchId: 'batch-b',
  tool: 'removeNode',
  agent: 'urn:vg:agent:mcp-agent',
  timestamp: new Date().toISOString(),
  addedCount: 0,
  removedCount: 1,
  reverted: true,
};

describe('AgentEditsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.editsChangedCb.current = null;
    listEdits.mockReturnValue([BATCH_A, BATCH_B]);
    getBatch.mockImplementation((id: string) => {
      if (id === 'batch-a') {
        return {
          batchId: 'batch-a',
          tool: 'addNode',
          agent: 'urn:vg:agent:mcp-agent',
          timestamp: BATCH_A.timestamp,
          reverted: false,
          added: [
            { s: 'http://ex/Foo', p: 'http://ex/p', o: 'http://ex/Bar' },
            { s: 'http://ex/Foo', p: 'http://ex/q', o: 'lit', ot: 'literal' },
          ],
          removed: [],
        };
      }
      return {
        batchId: 'batch-b',
        tool: 'removeNode',
        agent: 'urn:vg:agent:mcp-agent',
        timestamp: BATCH_B.timestamp,
        reverted: true,
        added: [],
        removed: [{ s: 'http://ex/Gone', p: 'http://ex/r', o: 'http://ex/X' }],
      };
    });
  });

  afterEach(() => {
    cleanup();
  });

  it('renders both batch rows', () => {
    render(<AgentEditsPanel />);
    expect(screen.getByText('addNode')).toBeTruthy();
    expect(screen.getByText('removeNode')).toBeTruthy();
    expect(screen.getByText('2 edits')).toBeTruthy();
  });

  it('shows the reverted badge and no active revert button for a reverted batch', () => {
    render(<AgentEditsPanel />);
    expect(screen.getByText('reverted')).toBeTruthy();
    // Only the non-reverted batch (addNode) has a revert button.
    const revertButtons = screen.getAllByRole('button', { name: /Revert .* edit/i });
    expect(revertButtons).toHaveLength(1);
    expect(revertButtons[0].getAttribute('aria-label')).toBe('Revert addNode edit');
  });

  it('shows the diff when a batch is expanded', () => {
    render(<AgentEditsPanel />);
    // Expand batch A via its toggle (the tool-name button).
    fireEvent.click(screen.getByText('addNode'));
    expect(getBatch).toHaveBeenCalledWith('batch-a');
    expect(screen.getByText(/http:\/\/ex\/Foo http:\/\/ex\/p http:\/\/ex\/Bar/)).toBeTruthy();
  });

  it('calls revertBatch and shows a success toast on revert', async () => {
    revertBatch.mockResolvedValue({
      success: true,
      reverted: { addedRemoved: 2, removedRestored: 0 },
      requested: { addedToRemove: 2, removedToRestore: 0 },
    });
    render(<AgentEditsPanel />);
    const revertButton = screen.getByRole('button', { name: 'Revert addNode edit' });
    fireEvent.click(revertButton);
    await waitFor(() => expect(revertBatch).toHaveBeenCalledWith('batch-a'));
    await waitFor(() => expect(toastMocks.success).toHaveBeenCalled());
  });

  it('shows a friendly empty state when there are no edits', () => {
    listEdits.mockReturnValue([]);
    render(<AgentEditsPanel />);
    expect(screen.getByText('No agent edits yet')).toBeTruthy();
  });

  it('FIX3: a revert that resolves AFTER unmount does not setState (no warning/throw)', async () => {
    // Hold the revert open so we can unmount before it resolves; the finally
    // block then runs against an unmounted component. refresh() must no-op.
    let resolveRevert: (v: unknown) => void = () => {};
    revertBatch.mockReturnValue(
      new Promise((res) => {
        resolveRevert = res;
      }),
    );
    // Spy on console to assert React does not warn about setState-on-unmounted,
    // and listEdits to assert refresh() did not run after unmount.
    const errorSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

    const { unmount } = render(<AgentEditsPanel />);
    const revertButton = screen.getByRole('button', { name: 'Revert addNode edit' });
    fireEvent.click(revertButton);
    await waitFor(() => expect(revertBatch).toHaveBeenCalledWith('batch-a'));

    // Unmount while the revert is still in flight.
    unmount();
    const callsAfterUnmount = listEdits.mock.calls.length;

    // Resolve the revert AFTER unmount — the finally block runs now.
    await act(async () => {
      resolveRevert({
        success: true,
        reverted: { addedRemoved: 2, removedRestored: 0 },
        requested: { addedToRemove: 2, removedToRestore: 0 },
      });
      await Promise.resolve();
    });

    // refresh() no-ops when unmounted: listEdits was not called again.
    expect(listEdits.mock.calls.length).toBe(callsAfterUnmount);
    // No React "setState on unmounted component" warning.
    const warned = [...errorSpy.mock.calls, ...warnSpy.mock.calls]
      .flat()
      .some((arg) => typeof arg === 'string' && /unmounted/i.test(arg));
    expect(warned).toBe(false);

    errorSpy.mockRestore();
    warnSpy.mockRestore();
  });

  it('auto-refreshes when the provenance change emitter fires', () => {
    listEdits.mockReturnValue([]);
    render(<AgentEditsPanel />);
    expect(screen.getByText('No agent edits yet')).toBeTruthy();
    // A new edit arrives.
    listEdits.mockReturnValue([BATCH_A]);
    act(() => {
      hoisted.editsChangedCb.current?.();
    });
    expect(screen.getByText('addNode')).toBeTruthy();
  });
});
