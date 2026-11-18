/**
 * @fileoverview Type definitions for Pyodide worker communication protocol
 */

// Commands sent from main thread to Pyodide worker
export type PyodideWorkerCommand =
  | PyodideWorkerInitCommand
  | PyodideWorkerExecuteCommand
  | PyodideWorkerStatusCommand;

export interface PyodideWorkerInitCommand {
  type: 'command';
  id: string;
  command: 'init';
  payload?: {
    pyodideUrl?: string;
  };
}

export interface PyodideWorkerExecuteCommand {
  type: 'command';
  id: string;
  command: 'execute';
  payload: {
    activityIri: string;
    codeUrl: string;
    requirementsUrl?: string;
    inputTurtle: string;
  };
}

export interface PyodideWorkerStatusCommand {
  type: 'command';
  id: string;
  command: 'status';
}

// Responses sent from Pyodide worker to main thread
export type PyodideWorkerMessage =
  | PyodideWorkerResponse
  | PyodideWorkerEvent;

export interface PyodideWorkerResponse {
  type: 'response';
  id: string;
  ok: boolean;
  result?: any;
  error?: string;
  stack?: string;
}

export interface PyodideWorkerEvent {
  type: 'event';
  event: PyodideWorkerEventName;
  payload: any;
}

// Command name type for type-safe dispatch
export type PyodideWorkerCommandName = 'init' | 'execute' | 'status';

// Payload types mapped to command names
export interface PyodideWorkerCommandPayloads {
  init: PyodideWorkerInitCommand['payload'];
  execute: PyodideWorkerExecuteCommand['payload'];
  status: undefined;
}

// Result types for each command
export interface ExecuteResult {
  activityIri: string;
  outputTurtle: string;
  executionTime?: number;
}

export interface StatusResult {
  ready: boolean;
  pyodideVersion?: string;
  loadedPackages?: string[];
}

// Event payload types
export interface StdoutPayload {
  text: string;
  timestamp: number;
}

export interface StderrPayload {
  text: string;
  timestamp: number;
}

export interface InputOptionObject {
  label: string;
  value: string;
}

export type InputOption = string | InputOptionObject;

export interface InputRequestPayload {
  requestId: string;
  prompt: string;
  inputType?: 'text' | 'number' | 'select';
  options?: InputOption[];
  defaultValue?: string;
}

export interface InitBuffersPayload {
  signalBuffer: SharedArrayBuffer;
  textBuffer: SharedArrayBuffer;
}

// Event name union
export type PyodideWorkerEventName =
  | 'progress'
  | 'status'
  | 'stdout'
  | 'stderr'
  | 'input_request'
  | 'init_buffers';

// Event payload map for type-safe dispatch
export interface PyodideWorkerEventPayloads {
  progress: { stage: string; percent: number };
  status: { ready: boolean };
  stdout: StdoutPayload;
  stderr: StderrPayload;
  input_request: InputRequestPayload;
  init_buffers: InitBuffersPayload;
}
