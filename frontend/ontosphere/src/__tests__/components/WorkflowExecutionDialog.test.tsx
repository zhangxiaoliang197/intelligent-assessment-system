import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import React from 'react';
import { render, screen, fireEvent, act } from '@testing-library/react';
import { WorkflowExecutionDialog } from '../../components/Canvas/WorkflowExecutionDialog';
import { useWorkflowExecutionStore } from '../../stores/workflowExecutionStore';

const mockRespondToInput = vi.fn();
vi.mock('../../utils/pyodideManager.workerClient', () => ({
  getPyodideClient: () => ({
    respondToInput: mockRespondToInput,
  }),
}));

describe('WorkflowExecutionDialog', () => {
  beforeEach(() => {
    useWorkflowExecutionStore.getState().reset();
  });

  it('renders nothing when isOpen=false', () => {
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.innerHTML).toBe('');
  });

  it('renders overlay when isOpen=true', () => {
    useWorkflowExecutionStore.setState({ isOpen: true, activityLabel: 'Load Data' });
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.querySelector('h2')?.textContent).toContain('Load Data');
  });

  it('renders log entries with correct styling per type', () => {
    useWorkflowExecutionStore.setState({
      isOpen: true,
      log: [
        { type: 'stdout', text: 'hello world', timestamp: 1 },
        { type: 'stderr', text: 'warning msg', timestamp: 2 },
        { type: 'info', text: 'Step: Load', timestamp: 3 },
      ],
    });
    const { container } = render(<WorkflowExecutionDialog />);
    const logEntries = container.querySelectorAll('.font-mono');
    expect(logEntries.length).toBeGreaterThanOrEqual(3);
    expect(logEntries[0].textContent).toBe('hello world');
    expect(logEntries[1].textContent).toBe('warning msg');
    expect(logEntries[1].className).toContain('orange');
    expect(logEntries[2].textContent).toBe('Step: Load');
  });

  it('shows progress bar when executing with progress > 0', () => {
    useWorkflowExecutionStore.setState({
      isOpen: true,
      isExecuting: true,
      progress: 42,
      progressStage: 'Installing packages',
    });
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.querySelector('[role="progressbar"]')).toBeTruthy();
    expect(container.textContent).toContain('Installing packages');
  });

  it('renders pending input field with prompt text', () => {
    useWorkflowExecutionStore.setState({
      isOpen: true,
      pendingInput: { requestId: 'r1', prompt: 'Enter your name:', inputType: 'text' },
    });
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.textContent).toContain('Enter your name:');
    expect(container.querySelector('input[placeholder="Type your response…"]')).toBeTruthy();
  });

  it('renders select input when inputType=select', () => {
    useWorkflowExecutionStore.setState({
      isOpen: true,
      pendingInput: {
        requestId: 'r1',
        prompt: 'Choose:',
        inputType: 'select',
        options: ['Option A', 'Option B'],
      },
    });
    const { container } = render(<WorkflowExecutionDialog />);
    const select = container.querySelector('select');
    expect(select).toBeTruthy();
    const options = select!.querySelectorAll('option');
    expect(options.length).toBe(2);
    expect(options[0].textContent).toBe('Option A');
  });

  it('close button calls store.close()', () => {
    useWorkflowExecutionStore.setState({ isOpen: true, activityLabel: 'Test' });
    const { container } = render(<WorkflowExecutionDialog />);
    const closeBtn = container.querySelector('button[aria-label="Close"]') as HTMLElement;
    expect(closeBtn).toBeTruthy();
    fireEvent.click(closeBtn);
    expect(useWorkflowExecutionStore.getState().isOpen).toBe(false);
  });

  it('shows error state', () => {
    useWorkflowExecutionStore.setState({
      isOpen: true,
      error: 'Something went wrong',
    });
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.textContent).toContain('Something went wrong');
    expect(container.textContent).toContain('Error');
  });

  it('shows execution time when not executing', () => {
    useWorkflowExecutionStore.setState({
      isOpen: true,
      isExecuting: false,
      executionTime: 2500,
    });
    const { container } = render(<WorkflowExecutionDialog />);
    expect(container.textContent).toContain('2.5s');
  });

  describe('label/value option objects', () => {
    beforeEach(() => {
      mockRespondToInput.mockClear();
    });

    it('renders label as display text for {label, value} options', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Select entity:',
          inputType: 'select',
          options: [
            { label: 'Temperature (42.5 °C)', value: 'http://example.org/temp1' },
            { label: 'Pressure (101.3 kPa)', value: 'http://example.org/press1' },
          ],
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      const select = container.querySelector('select');
      expect(select).toBeTruthy();
      const options = select!.querySelectorAll('option');
      expect(options.length).toBe(2);
      expect(options[0].textContent).toBe('Temperature (42.5 °C)');
      expect(options[0].getAttribute('value')).toBe('http://example.org/temp1');
      expect(options[1].textContent).toBe('Pressure (101.3 kPa)');
      expect(options[1].getAttribute('value')).toBe('http://example.org/press1');
    });

    it('renders plain string options correctly (backward compat)', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Choose:',
          inputType: 'select',
          options: ['Alpha', 'Beta', 'Gamma'],
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      const options = container.querySelectorAll('option');
      expect(options.length).toBe(3);
      expect(options[0].textContent).toBe('Alpha');
      expect(options[0].getAttribute('value')).toBe('Alpha');
      expect(options[2].textContent).toBe('Gamma');
    });

    it('submitting a label/value select returns the value, not the label', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Select entity:',
          inputType: 'select',
          options: [
            { label: 'Temperature (42.5 °C)', value: 'http://example.org/temp1' },
            { label: 'Pressure (101.3 kPa)', value: 'http://example.org/press1' },
          ],
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      // inputValue is auto-initialized to first option's value
      const submitBtn = container.querySelector('button')!;
      const buttons = container.querySelectorAll('button');
      const submit = Array.from(buttons).find(b => b.textContent === 'Submit')!;
      fireEvent.click(submit);
      expect(mockRespondToInput).toHaveBeenCalledWith('http://example.org/temp1');
    });

    it('renders mixed array of strings and objects correctly', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Pick one:',
          inputType: 'select',
          options: [
            'plain-string-option',
            { label: 'Labeled Option', value: 'http://example.org/labeled' },
            'another-plain',
          ],
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      const options = container.querySelectorAll('option');
      expect(options.length).toBe(3);
      expect(options[0].textContent).toBe('plain-string-option');
      expect(options[0].getAttribute('value')).toBe('plain-string-option');
      expect(options[1].textContent).toBe('Labeled Option');
      expect(options[1].getAttribute('value')).toBe('http://example.org/labeled');
      expect(options[2].textContent).toBe('another-plain');
      expect(options[2].getAttribute('value')).toBe('another-plain');
    });

    it('initializes inputValue to first option value when no defaultValue', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Select:',
          inputType: 'select',
          options: [
            { label: 'First', value: 'http://example.org/first' },
            { label: 'Second', value: 'http://example.org/second' },
          ],
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      const select = container.querySelector('select') as HTMLSelectElement;
      expect(select).toBeTruthy();
      // The select value should be the first option's value, not empty string
      expect(select.value).toBe('http://example.org/first');
    });
  });

  describe('dialog close cancel behavior', () => {
    beforeEach(() => {
      mockRespondToInput.mockClear();
    });

    it('closing dialog via X button while input pending calls respondToInput with cancelled=true', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Select entity:',
          inputType: 'select',
          options: ['Option A', 'Option B'],
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      const closeBtn = container.querySelector('button[aria-label="Close"]') as HTMLElement;
      expect(closeBtn).toBeTruthy();
      fireEvent.click(closeBtn);

      // Dialog closed
      expect(useWorkflowExecutionStore.getState().isOpen).toBe(false);
      // respondToInput called with cancelled=true
      expect(mockRespondToInput).toHaveBeenCalledWith('', true);
      // pendingInput cleared
      expect(useWorkflowExecutionStore.getState().pendingInput).toBeNull();
    });

    it('closing dialog with no pending input does not call respondToInput', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: null,
      });
      const { container } = render(<WorkflowExecutionDialog />);
      const closeBtn = container.querySelector('button[aria-label="Close"]') as HTMLElement;
      fireEvent.click(closeBtn);

      expect(useWorkflowExecutionStore.getState().isOpen).toBe(false);
      expect(mockRespondToInput).not.toHaveBeenCalled();
    });

    it('backdrop click while pendingInput is set does not close dialog', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Enter value:',
          inputType: 'text',
        },
      });
      const { container } = render(<WorkflowExecutionDialog />);
      // The backdrop is the outermost div with the bg-black/60 class
      const backdrop = container.firstElementChild as HTMLElement;
      expect(backdrop).toBeTruthy();
      fireEvent.mouseDown(backdrop);

      // Dialog should still be open
      expect(useWorkflowExecutionStore.getState().isOpen).toBe(true);
      expect(mockRespondToInput).not.toHaveBeenCalled();
    });

    it('Escape key while pendingInput is set does not close dialog', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: {
          requestId: 'r1',
          prompt: 'Enter value:',
          inputType: 'text',
        },
      });
      render(<WorkflowExecutionDialog />);

      fireEvent.keyDown(document, { key: 'Escape' });

      // Dialog should still be open — Escape blocked when pendingInput is set
      expect(useWorkflowExecutionStore.getState().isOpen).toBe(true);
      expect(mockRespondToInput).not.toHaveBeenCalled();
    });

    it('Escape key without pendingInput closes dialog normally', () => {
      useWorkflowExecutionStore.setState({
        isOpen: true,
        pendingInput: null,
      });
      render(<WorkflowExecutionDialog />);

      fireEvent.keyDown(document, { key: 'Escape' });

      expect(useWorkflowExecutionStore.getState().isOpen).toBe(false);
      expect(mockRespondToInput).not.toHaveBeenCalled();
    });
  });
});
