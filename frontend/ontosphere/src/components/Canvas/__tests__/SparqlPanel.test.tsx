// src/components/Canvas/__tests__/SparqlPanel.test.tsx
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
  sparqlQuery: vi.fn(),
  getNamespaces: vi.fn(),
  onNamespacesChange: vi.fn(() => () => {}),
}));
const { toastMocks, sparqlQuery, getNamespaces, onNamespacesChange } = hoisted;

vi.mock('sonner', () => ({ toast: hoisted.toastMocks }));

vi.mock('../../../utils/rdfManager', () => ({
  rdfManager: {
    sparqlQuery: hoisted.sparqlQuery,
    getNamespaces: hoisted.getNamespaces,
    onNamespacesChange: hoisted.onNamespacesChange,
  },
}));

// Keep IRI display deterministic and dependency-free.
vi.mock('@/mcp/tools/graph', () => ({
  abbreviateIri: (iri: string) => iri,
}));

import { SparqlPanel } from '../SparqlPanel';

const NAMESPACES = [
  { prefix: 'owl', uri: 'http://www.w3.org/2002/07/owl#' },
  { prefix: 'ex', uri: 'http://example.org/' },
];

describe('SparqlPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    getNamespaces.mockReturnValue(NAMESPACES);
    onNamespacesChange.mockReturnValue(() => {});
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the editor prefilled with PREFIX lines and a default SELECT', () => {
    render(<SparqlPanel />);
    const editor = screen.getByLabelText('SPARQL query editor') as HTMLTextAreaElement;
    expect(editor).toBeTruthy();
    expect(editor.value).toContain('PREFIX owl: <http://www.w3.org/2002/07/owl#>');
    expect(editor.value).toContain('PREFIX ex: <http://example.org/>');
    expect(editor.value).toContain('SELECT * WHERE');
  });

  it('runs the editor content and renders a SELECT result table', async () => {
    sparqlQuery.mockResolvedValue({
      type: 'select',
      rows: [
        { s: 'http://example.org/Alice', p: 'http://example.org/knows', o: 'http://example.org/Bob' },
      ],
    });
    render(<SparqlPanel />);

    const editor = screen.getByLabelText('SPARQL query editor') as HTMLTextAreaElement;
    fireEvent.change(editor, { target: { value: 'SELECT * WHERE { ?s ?p ?o }' } });
    fireEvent.click(screen.getByRole('button', { name: 'Run SPARQL query' }));

    await waitFor(() => expect(sparqlQuery).toHaveBeenCalled());
    expect(sparqlQuery.mock.calls[0][0]).toBe('SELECT * WHERE { ?s ?p ?o }');

    // Columns (variables) and a binding value are rendered.
    await screen.findByText('s');
    expect(screen.getByText('p')).toBeTruthy();
    expect(screen.getByText('http://example.org/Alice')).toBeTruthy();
    expect(screen.getByText('http://example.org/Bob')).toBeTruthy();
  });

  it('renders a true/false badge for ASK results', async () => {
    sparqlQuery.mockResolvedValue({ type: 'ask', boolean: true });
    render(<SparqlPanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Run SPARQL query' }));
    await screen.findByText('true');
  });

  it('shows a readable error message and toast when the query throws', async () => {
    sparqlQuery.mockRejectedValue(new Error('SPARQL parse error: unexpected token'));
    render(<SparqlPanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Run SPARQL query' }));
    await screen.findByRole('alert');
    expect(screen.getByText(/unexpected token/)).toBeTruthy();
    await waitFor(() => expect(toastMocks.error).toHaveBeenCalled());
  });

  it('shows a success toast when an UPDATE is applied', async () => {
    sparqlQuery.mockResolvedValue({ type: 'update' });
    render(<SparqlPanel />);
    fireEvent.click(screen.getByRole('button', { name: 'Run SPARQL query' }));
    await waitFor(() => expect(toastMocks.success).toHaveBeenCalled());
    expect(screen.getByText(/Update applied/)).toBeTruthy();
  });

  it('fills the editor from an example-query button', () => {
    render(<SparqlPanel />);
    fireEvent.click(screen.getByText('All classes'));
    const editor = screen.getByLabelText('SPARQL query editor') as HTMLTextAreaElement;
    expect(editor.value).toContain('owl:Class');
  });
});
