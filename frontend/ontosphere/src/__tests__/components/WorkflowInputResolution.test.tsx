import { describe, it, expect, vi, beforeEach } from 'vitest';
import React from 'react';
import { render, fireEvent } from '@testing-library/react';
import { readFileSync } from 'fs';
import { resolve } from 'path';
import { WorkflowExecutionDialog } from '../../components/Canvas/WorkflowExecutionDialog';
import { useWorkflowExecutionStore } from '../../stores/workflowExecutionStore';

const mockRespondToInput = vi.fn();
vi.mock('../../utils/pyodideManager.workerClient', () => ({
  getPyodideClient: () => ({
    respondToInput: mockRespondToInput,
  }),
}));

// ---------------------------------------------------------------------------
// 1. Fixture graph validation
// ---------------------------------------------------------------------------

describe('workflow-input-resolution-fixture.ttl', () => {
  const fixturePath = resolve(__dirname, '../fixtures/workflow-input-resolution-fixture.ttl');
  let ttl: string;

  beforeEach(() => {
    ttl = readFileSync(fixturePath, 'utf-8').replace(/\r\n/g, '\n');
  });

  it('file exists and is non-empty', () => {
    expect(ttl.length).toBeGreaterThan(0);
  });

  it('declares required namespace prefixes', () => {
    const requiredPrefixes = [
      'rdf:', 'rdfs:', 'xsd:', 'prov:', 'p-plan:', 'qudt:', 'spw:', 'oa:',
    ];
    for (const prefix of requiredPrefixes) {
      expect(ttl).toContain(`@prefix ${prefix}`);
    }
  });

  it('contains the activity IRI with prov:Activity type', () => {
    expect(ttl).toContain(':SumRun_1719000000000');
    expect(ttl).toContain('a prov:Activity');
  });

  it('activity has p-plan:correspondsToStep and prov:hadPlan links', () => {
    expect(ttl).toContain('p-plan:correspondsToStep spw:SumStep');
    expect(ttl).toContain('prov:hadPlan spw:SumTemplate');
  });

  it('contains empty placeholder entities with correspondsToVariable but no numericValue', () => {
    // Placeholder 1: has correspondsToVariable, type, but no qudt:numericValue
    expect(ttl).toContain(':SumInput1_1719000000000');
    expect(ttl).toContain('p-plan:correspondsToVariable spw:SumInput1');

    // Placeholder 2
    expect(ttl).toContain(':SumInput2_1719000000000');
    expect(ttl).toContain('p-plan:correspondsToVariable spw:SumInput2');

    // Placeholders should NOT have numeric values
    // Find the placeholder blocks and verify no numericValue within them
    const placeholder1Block = ttl.split(':SumInput1_1719000000000')[1]?.split('\n\n')[0] ?? '';
    expect(placeholder1Block).not.toContain('qudt:numericValue');

    const placeholder2Block = ttl.split(':SumInput2_1719000000000')[1]?.split('\n\n')[0] ?? '';
    expect(placeholder2Block).not.toContain('qudt:numericValue');
  });

  it('activity uses the empty placeholders via prov:used', () => {
    expect(ttl).toContain('prov:used :SumInput1_1719000000000, :SumInput2_1719000000000');
  });

  it('contains at least 2 candidate QuantityValue entities with actual values', () => {
    // Candidate entities must have qudt:numericValue AND qudt:unit
    const candidateIris = [':Temperature_Measurement', ':Pressure_Measurement'];
    for (const iri of candidateIris) {
      expect(ttl).toContain(iri);
    }

    // Verify they have actual numeric values
    expect(ttl).toContain('"42.5"^^xsd:decimal');
    expect(ttl).toContain('"101.3"^^xsd:decimal');
  });

  it('candidate entities have rdfs:label for dropdown display', () => {
    expect(ttl).toContain('"Temperature Measurement"');
    expect(ttl).toContain('"Pressure Measurement"');
  });

  it('template variable definitions are present with rdfs:label', () => {
    expect(ttl).toContain('spw:SumInput1 a p-plan:Variable');
    expect(ttl).toContain('spw:SumInput2 a p-plan:Variable');
    expect(ttl).toContain('"Input Quantity 1"');
    expect(ttl).toContain('"Input Quantity 2"');
  });
});

// ---------------------------------------------------------------------------
// 2. End-to-end mock: input_request (select) through dialog to response
// ---------------------------------------------------------------------------

describe('end-to-end input_request flow through dialog', () => {
  beforeEach(() => {
    useWorkflowExecutionStore.getState().reset();
    mockRespondToInput.mockClear();
  });

  it('select-type input_request flows through store to dialog, user selects, response goes back', () => {
    // Step 1: Open the dialog (simulates executeActivity opening it)
    useWorkflowExecutionStore.getState().open('urn:act:sum-run', 'Sum QUDT Quantities Run');

    // Step 2: Simulate worker posting an input_request event (select type with label/value)
    // In production, executeActivity bridges this from the worker event to the store.
    // Here we simulate that bridge by calling setPendingInput directly.
    useWorkflowExecutionStore.getState().setPendingInput({
      requestId: 'ir-001',
      prompt: 'Select Input Quantity 1:',
      inputType: 'select',
      options: [
        { label: 'Temperature Measurement (42.5 DEG_C)', value: 'http://example.com/Temperature_Measurement' },
        { label: 'Pressure Measurement (101.3 K_PA)', value: 'http://example.com/Pressure_Measurement' },
        { label: 'Length Measurement (5.0 MilliM)', value: 'http://example.com/Length_Measurement' },
      ],
    });

    // Step 3: Render dialog — it should show the select dropdown
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.textContent).toContain('Select Input Quantity 1:');

    const select = container.querySelector('select') as HTMLSelectElement;
    expect(select).toBeTruthy();
    const optionEls = select.querySelectorAll('option');
    expect(optionEls.length).toBe(3);
    expect(optionEls[0].textContent).toBe('Temperature Measurement (42.5 DEG_C)');
    expect(optionEls[0].getAttribute('value')).toBe('http://example.com/Temperature_Measurement');

    // Step 4: User changes selection to second option
    fireEvent.change(select, { target: { value: 'http://example.com/Pressure_Measurement' } });

    // Step 5: User clicks Submit
    const submitBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent === 'Submit'
    )!;
    expect(submitBtn).toBeTruthy();
    fireEvent.click(submitBtn);

    // Step 6: Verify the IRI value (not the label) was sent back
    expect(mockRespondToInput).toHaveBeenCalledTimes(1);
    expect(mockRespondToInput).toHaveBeenCalledWith('http://example.com/Pressure_Measurement');

    // Step 7: pendingInput is cleared after submit
    expect(useWorkflowExecutionStore.getState().pendingInput).toBeNull();
  });

  it('text-type input_request flows through store to dialog, user types, response goes back', () => {
    useWorkflowExecutionStore.getState().open('urn:act:load-run', 'Load CSVW Column Run');

    // Simulate a text-type input_request (e.g. for CSVW Metadata URI)
    useWorkflowExecutionStore.getState().setPendingInput({
      requestId: 'ir-002',
      prompt: 'Enter CSVW Metadata URI:',
      inputType: 'text',
    });

    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.textContent).toContain('Enter CSVW Metadata URI:');

    // Should render a text input, not a select
    const textInput = container.querySelector('input[placeholder="Type your response…"]') as HTMLInputElement;
    expect(textInput).toBeTruthy();
    expect(container.querySelector('select')).toBeNull();

    // User types a URI
    fireEvent.change(textInput, {
      target: { value: 'https://example.org/metadata.json' },
    });

    // User presses Enter to submit
    fireEvent.keyDown(textInput, { key: 'Enter' });

    // Verify the typed value was sent back
    expect(mockRespondToInput).toHaveBeenCalledTimes(1);
    expect(mockRespondToInput).toHaveBeenCalledWith('https://example.org/metadata.json');
    expect(useWorkflowExecutionStore.getState().pendingInput).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. Edge cases
// ---------------------------------------------------------------------------

describe('input_request edge cases', () => {
  beforeEach(() => {
    useWorkflowExecutionStore.getState().reset();
    mockRespondToInput.mockClear();
  });

  it('input_request with empty options array renders empty select', () => {
    useWorkflowExecutionStore.getState().open('urn:act:edge', 'Edge Case Run');
    useWorkflowExecutionStore.getState().setPendingInput({
      requestId: 'ir-edge-1',
      prompt: 'Select a value:',
      inputType: 'select',
      options: [],
    });

    const { container } = render(<WorkflowExecutionDialog />);
    const select = container.querySelector('select') as HTMLSelectElement;
    expect(select).toBeTruthy();
    expect(select.querySelectorAll('option').length).toBe(0);
  });

  it('text-type input_request through to cancel response', () => {
    useWorkflowExecutionStore.getState().open('urn:act:cancel', 'Cancel Test Run');
    useWorkflowExecutionStore.getState().setPendingInput({
      requestId: 'ir-cancel-1',
      prompt: 'Enter Column Name:',
      inputType: 'text',
    });

    const { container } = render(<WorkflowExecutionDialog />);

    // User clicks the Cancel button instead of Submit
    const cancelBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent === 'Cancel'
    )!;
    expect(cancelBtn).toBeTruthy();
    fireEvent.click(cancelBtn);

    // respondToInput called with empty string and cancelled=true
    expect(mockRespondToInput).toHaveBeenCalledTimes(1);
    expect(mockRespondToInput).toHaveBeenCalledWith('', true);
    expect(useWorkflowExecutionStore.getState().pendingInput).toBeNull();
  });

  it('select-type submit without changing selection returns first option value', () => {
    useWorkflowExecutionStore.getState().open('urn:act:default', 'Default Selection Run');
    useWorkflowExecutionStore.getState().setPendingInput({
      requestId: 'ir-default-1',
      prompt: 'Select input:',
      inputType: 'select',
      options: [
        { label: 'Alpha (1.0 m)', value: 'http://example.com/alpha' },
        { label: 'Beta (2.0 m)', value: 'http://example.com/beta' },
      ],
    });

    const { container } = render(<WorkflowExecutionDialog />);

    // User clicks Submit immediately without changing the dropdown
    const submitBtn = Array.from(container.querySelectorAll('button')).find(
      b => b.textContent === 'Submit'
    )!;
    fireEvent.click(submitBtn);

    // Should submit the first option's value (auto-initialized)
    expect(mockRespondToInput).toHaveBeenCalledWith('http://example.com/alpha');
  });
});
