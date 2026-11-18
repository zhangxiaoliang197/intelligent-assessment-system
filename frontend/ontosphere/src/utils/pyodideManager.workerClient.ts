/**
 * @fileoverview Pyodide worker client for main thread communication
 * Manages communication with the Pyodide web worker
 */

import WorkerFactory from '../workers/pyodide.worker.ts?worker';
import type {
  PyodideWorkerCommandName,
  PyodideWorkerCommand,
  PyodideWorkerCommandPayloads,
  PyodideWorkerMessage,
  PyodideWorkerEventName,
  InitBuffersPayload,
} from '../workers/pyodide.workerProtocol';

type EventName = PyodideWorkerEventName;

type EventHandlerMap = Record<EventName, Set<(payload: any) => void>>;

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (reason?: unknown) => void;
}

export class PyodideManagerWorkerClient {
  private worker: Worker | null = null;
  private workerInit: Promise<Worker | null> | null = null;
  private pending: Map<string, PendingRequest> = new Map();
  private events: EventHandlerMap = {
    progress: new Set(),
    status: new Set(),
    stdout: new Set(),
    stderr: new Set(),
    input_request: new Set(),
    init_buffers: new Set(),
  };
  private signalView: Int32Array | null = null;
  private textView: Uint8Array | null = null;

  constructor() {
    void this.ensureWorker();
  }

  private handleMessage = (event: { data: PyodideWorkerMessage }) => {
    const data = event.data;
    if (!data) return;

    if (data.type === 'response') {
      const responder = this.pending.get(data.id);
      if (!responder) return;
      this.pending.delete(data.id);
      if (data.ok) {
        responder.resolve(data.result);
      } else {
        const err = new Error(data.error || 'pyodide-worker-error');
        if (data.stack) {
          (err as any).stack = data.stack;
        }
        responder.reject(err);
      }
      return;
    }

    if (data.type === 'event') {
      if (data.event === 'init_buffers') {
        const { signalBuffer, textBuffer } = data.payload as InitBuffersPayload;
        this.signalView = new Int32Array(signalBuffer);
        this.textView = new Uint8Array(textBuffer);
      }

      const handlers = this.events[data.event as EventName];
      if (!handlers || handlers.size === 0) return;
      for (const handler of handlers) {
        try {
          handler(data.payload);
        } catch (err) {
          console.error('[pyodideManager.workerClient] event handler error', err);
        }
      }
    }
  };

  private handleError = (event: ErrorEvent | Error) => {
    const message = event instanceof Error ? event.message : event?.message;
    console.error('[pyodideManager.workerClient] worker runtime error', message);
  };

  private async ensureWorker(): Promise<Worker | null> {
    if (this.worker) return this.worker;
    if (this.workerInit) return this.workerInit;

    this.workerInit = (async () => {
      try {
        console.debug('[VG_PYODIDE] ensureWorker start');

        if (typeof Worker !== 'undefined') {
          const worker = new WorkerFactory() as Worker;
          worker.addEventListener('message', this.handleMessage);
          worker.addEventListener('error', this.handleError);
          this.worker = worker;
          return worker;
        }

        console.warn('[pyodideManager.workerClient] Worker not available in this environment');
        return null;
      } catch (err) {
        console.error('[pyodideManager.workerClient] failed to initialize worker', err);
        return null;
      }
    })();

    return this.workerInit;
  }

  async call<C extends PyodideWorkerCommandName, T = unknown>(
    command: C,
    payload?: PyodideWorkerCommandPayloads[C]
  ): Promise<T> {
    const id = `cmd-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
    
    if (!this.worker) {
      await this.ensureWorker();
    }
    
    if (!this.worker) {
      throw new Error('Pyodide worker not initialized');
    }

    const message: PyodideWorkerCommand = Object.freeze({
      type: 'command',
      id,
      command,
      ...(typeof payload === 'undefined' ? {} : { payload }),
    }) as PyodideWorkerCommand;

    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.worker?.postMessage(message);
      } catch (err) {
        this.pending.delete(id);
        reject(err);
      }
    });
  }

  on(event: EventName, handler: (payload: any) => void): () => void {
    const set = this.events[event];
    set.add(handler);
    return () => {
      set.delete(handler);
    };
  }

  respondToInput(value: string, cancelled = false) {
    if (!this.signalView || !this.textView) {
      throw new Error('Input buffers not initialized — worker has not sent init_buffers event yet');
    }

    if (cancelled) {
      Atomics.store(this.signalView, 0, -1);
      Atomics.store(this.signalView, 1, 0);
    } else {
      const encoded = new TextEncoder().encode(value);
      const written = Math.min(encoded.byteLength, this.textView.byteLength);
      this.textView.set(encoded.subarray(0, written));
      Atomics.store(this.signalView, 0, 1);
      Atomics.store(this.signalView, 1, written);
    }
    Atomics.notify(this.signalView, 0);
  }

  terminate() {
    if (this.worker) {
      this.worker.removeEventListener('message', this.handleMessage);
      this.worker.removeEventListener('error', this.handleError);
      this.worker.terminate();
      this.worker = null;
    }
    this.pending.clear();
  }
}

// Singleton instance for global use
let pyodideClientInstance: PyodideManagerWorkerClient | null = null;

export function getPyodideClient(): PyodideManagerWorkerClient {
  if (!pyodideClientInstance) {
    pyodideClientInstance = new PyodideManagerWorkerClient();
  }
  return pyodideClientInstance;
}

export function createPyodideManagerWorkerClient() {
  return new PyodideManagerWorkerClient();
}
