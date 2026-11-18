// src/components/Canvas/__tests__/MetricsPanel.test.tsx
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';

// --- mocks (declared before importing the component under test) ---

const hoisted = vi.hoisted(() => ({
  toastMocks: {
    success: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  },
  getOntologyStats: vi.fn(),
  onSubjectsChange: vi.fn(),
  offSubjectsChange: vi.fn(),
}));
const { getOntologyStats, onSubjectsChange, offSubjectsChange } = hoisted;

vi.mock('sonner', () => ({ toast: hoisted.toastMocks }));

vi.mock('../../../utils/rdfManager', () => ({
  rdfManager: {
    getOntologyStats: hoisted.getOntologyStats,
    onSubjectsChange: hoisted.onSubjectsChange,
    offSubjectsChange: hoisted.offSubjectsChange,
  },
}));

import { MetricsPanel } from '../MetricsPanel';

function makeStats(overrides?: Partial<ReturnType<typeof defaultStats>>) {
  return { ...defaultStats(), ...overrides };
}

function defaultStats() {
  return {
    totalTriples: 200,
    classCount: 12,
    objectPropertyCount: 24,
    datatypePropertyCount: 9,
    namedIndividualCount: 15,
    subjectCount: 42,
    labeledClassCount: 6,
    assertedTriples: 200,
    inferredTriples: 50,
    namespaceBreakdown: [
      { prefix: 'ex', uri: 'http://example.org/', subjects: 7 },
      { prefix: 'owl', uri: 'http://www.w3.org/2002/07/owl#', subjects: 4 },
    ],
  };
}

describe('MetricsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    onSubjectsChange.mockImplementation(() => {});
    offSubjectsChange.mockImplementation(() => {});
    getOntologyStats.mockResolvedValue(defaultStats());
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the structural counts as stat cards', async () => {
    render(<MetricsPanel />);
    await waitFor(() => expect(getOntologyStats).toHaveBeenCalled());

    await screen.findByText('Triples');
    expect(screen.getByText('Classes')).toBeTruthy();
    expect(screen.getByText('Object props')).toBeTruthy();
    expect(screen.getByText('Datatype props')).toBeTruthy();
    expect(screen.getByText('Individuals')).toBeTruthy();

    expect(screen.getByText('200')).toBeTruthy();
    expect(screen.getByText('12')).toBeTruthy();
    expect(screen.getByText('24')).toBeTruthy();
    expect(screen.getByText('9')).toBeTruthy();
    expect(screen.getByText('15')).toBeTruthy();
  });

  it('renders the per-namespace breakdown table sorted by subject count', async () => {
    render(<MetricsPanel />);
    await screen.findByText('Subjects by namespace');

    const exCell = screen.getByText('ex');
    const owlCell = screen.getByText('owl');
    expect(exCell).toBeTruthy();
    expect(owlCell).toBeTruthy();
    expect(exCell.closest('tr')?.textContent).toContain('7');
    expect(owlCell.closest('tr')?.textContent).toContain('4');
  });

  it('renders the quality heuristics derived from the counts', async () => {
    render(<MetricsPanel />);
    await screen.findByText('Quality heuristics');

    expect(screen.getByText('Avg properties / class')).toBeTruthy();
    expect(screen.getByText('Classes with rdfs:label')).toBeTruthy();
    expect(screen.getByText('50%')).toBeTruthy();
    expect(screen.getByText(/not a/i)).toBeTruthy();
  });

  it('re-gathers when the Refresh button is clicked', async () => {
    render(<MetricsPanel />);
    await waitFor(() => expect(getOntologyStats).toHaveBeenCalledTimes(1));

    fireEvent.click(screen.getByRole('button', { name: 'Refresh metrics' }));
    await waitFor(() => expect(getOntologyStats).toHaveBeenCalledTimes(2));
  });

  it('subscribes to subject changes on mount and unsubscribes on unmount', async () => {
    const { unmount } = render(<MetricsPanel />);
    await waitFor(() => expect(onSubjectsChange).toHaveBeenCalled());
    unmount();
    expect(offSubjectsChange).toHaveBeenCalled();
  });

  it('shows an empty state when there are no triples', async () => {
    getOntologyStats.mockResolvedValue(makeStats({ totalTriples: 0, assertedTriples: 0, inferredTriples: 0, namespaceBreakdown: [] }));
    render(<MetricsPanel />);
    await screen.findByText('Load data to see metrics.');
  });
});
