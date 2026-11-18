import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.mock('../../workers/pyodide.worker.ts?worker', () => {
  return {
    default: class FakeWorker {
      addEventListener() {}
      removeEventListener() {}
      postMessage() {}
      terminate() {}
    },
  };
});

import { PyodideManagerWorkerClient } from '../../utils/pyodideManager.workerClient';

describe('PyodideManagerWorkerClient', () => {
  let client: PyodideManagerWorkerClient;

  beforeEach(() => {
    client = new PyodideManagerWorkerClient();
  });

  it('dispatches stdout events to subscribers', () => {
    const handler = vi.fn();
    client.on('stdout', handler);

    const msg = { data: { type: 'event', event: 'stdout', payload: { text: 'hello', timestamp: 1 } } };
    (client as any).handleMessage(msg);

    expect(handler).toHaveBeenCalledWith({ text: 'hello', timestamp: 1 });
  });

  it('dispatches stderr events to subscribers', () => {
    const handler = vi.fn();
    client.on('stderr', handler);

    (client as any).handleMessage({
      data: { type: 'event', event: 'stderr', payload: { text: 'warn', timestamp: 2 } },
    });

    expect(handler).toHaveBeenCalledWith({ text: 'warn', timestamp: 2 });
  });

  it('dispatches input_request events to subscribers', () => {
    const handler = vi.fn();
    client.on('input_request', handler);

    const payload = { requestId: 'r1', prompt: 'Name?', inputType: 'text' };
    (client as any).handleMessage({ data: { type: 'event', event: 'input_request', payload } });

    expect(handler).toHaveBeenCalledWith(payload);
  });

  it('init_buffers event stores buffer references', () => {
    const signalBuffer = new SharedArrayBuffer(8);
    const textBuffer = new SharedArrayBuffer(16);

    (client as any).handleMessage({
      data: { type: 'event', event: 'init_buffers', payload: { signalBuffer, textBuffer } },
    });

    expect((client as any).signalView).toBeInstanceOf(Int32Array);
    expect((client as any).textView).toBeInstanceOf(Uint8Array);
  });

  it('respondToInput() encodes value to text buffer and signals ready', () => {
    const signalBuffer = new SharedArrayBuffer(8);
    const textBuffer = new SharedArrayBuffer(256);

    (client as any).handleMessage({
      data: { type: 'event', event: 'init_buffers', payload: { signalBuffer, textBuffer } },
    });

    client.respondToInput('hello');

    const sv = new Int32Array(signalBuffer);
    const tv = new Uint8Array(textBuffer);
    expect(Atomics.load(sv, 0)).toBe(1);
    expect(Atomics.load(sv, 1)).toBe(5);
    expect(new TextDecoder().decode(tv.slice(0, 5))).toBe('hello');
  });

  it('respondToInput() with cancelled=true sets signal to -1', () => {
    const signalBuffer = new SharedArrayBuffer(8);
    const textBuffer = new SharedArrayBuffer(256);

    (client as any).handleMessage({
      data: { type: 'event', event: 'init_buffers', payload: { signalBuffer, textBuffer } },
    });

    client.respondToInput('', true);

    const sv = new Int32Array(signalBuffer);
    expect(Atomics.load(sv, 0)).toBe(-1);
  });

  it('respondToInput() with empty string sets signal=1, byteLength=0', () => {
    const signalBuffer = new SharedArrayBuffer(8);
    const textBuffer = new SharedArrayBuffer(256);

    (client as any).handleMessage({
      data: { type: 'event', event: 'init_buffers', payload: { signalBuffer, textBuffer } },
    });

    client.respondToInput('');

    const sv = new Int32Array(signalBuffer);
    expect(Atomics.load(sv, 0)).toBe(1);
    expect(Atomics.load(sv, 1)).toBe(0);
  });

  it('respondToInput() throws before buffers initialized', () => {
    expect(() => client.respondToInput('test')).toThrow('Input buffers not initialized');
  });

  it('unsubscribe function removes handler', () => {
    const handler = vi.fn();
    const unsub = client.on('stdout', handler);

    unsub();

    (client as any).handleMessage({
      data: { type: 'event', event: 'stdout', payload: { text: 'x', timestamp: 1 } },
    });
    expect(handler).not.toHaveBeenCalled();
  });
});
