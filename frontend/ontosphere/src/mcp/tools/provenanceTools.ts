// src/mcp/tools/provenanceTools.ts
//
// Agent-edit audit & undo surface. Reads/writes the in-memory PROV-O journal
// maintained by the ProvenanceRecorder (mirrored into urn:vg:provenance).
import type { McpTool, McpResult } from '@/mcp/types';
import { getProvenanceRecorder, type EvictionWarning } from '@/mcp/provenance';

const listAgentEdits: McpTool = {
  name: 'listAgentEdits',
  description:
    'List recorded agent edit batches (provenance of mutations) most-recent-first. ' +
    'Each mutating tool call (addNode/updateNode/removeNode/addTriple/removeLink/loadRdf) is recorded ' +
    'as a PROV-O Activity in the urn:vg:provenance sidecar graph. ' +
    'Returns [{batchId, tool, agent, timestamp, addedCount, removedCount, reverted}]. ' +
    'Use diffAgentEdits to inspect the exact triples and revertAgentBatch to undo a batch. ' +
    'NOTE: the journal is in-memory and volatile — it is cleared on page reload (the store itself is also volatile). ' +
    'NOTE: only the most recent few thousand batches are retained (MAX_BATCHES, default 5000); ' +
    'older batches are evicted and can no longer be listed or reverted.',
  inputSchema: {
    type: 'object',
    properties: {
      limit: { type: 'integer', description: 'Maximum number of batches to return (most recent first).' },
    },
  },
  async handler(params): Promise<McpResult> {
    try {
      const { limit } = (params ?? {}) as { limit?: number };
      const recorder = getProvenanceRecorder();
      const edits = recorder.listEdits(
        typeof limit === 'number' && limit > 0 ? limit : undefined,
      );
      const state = recorder.getState();
      const result: Record<string, unknown> = { edits, count: edits.length };
      if (state.evictionWarning) {
        // Surface the warning so the caller knows revert history was truncated.
        const w: EvictionWarning = state.evictionWarning;
        result.evictionWarning = {
          evictedCount: w.evictedCount,
          revertibleDropped: w.revertibleDropped,
          droppedBatchIds: w.droppedBatchIds,
          message:
            w.revertibleDropped > 0
              ? `${w.revertibleDropped} revertible batch(es) were evicted from the journal ` +
                `(cap=${state.cap}). One-click reversal history has been truncated.`
              : `${w.evictedCount} already-reverted batch(es) evicted (cap=${state.cap}).`,
        };
      }
      return { success: true, data: result };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const diffAgentEdits: McpTool = {
  name: 'diffAgentEdits',
  description:
    'Inspect the exact triples added and removed by a recorded agent edit batch. ' +
    'Pass the batchId from listAgentEdits. ' +
    'Returns {tool, agent, timestamp, reverted, added:[{s,p,o}], removed:[{s,p,o}]}.',
  inputSchema: {
    type: 'object',
    required: ['batchId'],
    properties: {
      batchId: { type: 'string', description: 'Batch identifier from listAgentEdits.' },
    },
  },
  async handler(params): Promise<McpResult> {
    try {
      const { batchId } = (params ?? {}) as { batchId?: string };
      if (!batchId) return { success: false, error: 'batchId is required' };
      const record = getProvenanceRecorder().getBatch(batchId);
      if (!record) return { success: false, error: `Unknown batchId: ${batchId}` };
      return {
        success: true,
        data: {
          batchId: record.batchId,
          tool: record.tool,
          agent: record.agent,
          timestamp: record.timestamp,
          reverted: record.reverted,
          ...(record.note ? { note: record.note } : {}),
          added: record.added.map((q) => ({ s: q.s, p: q.p, o: q.o })),
          removed: record.removed.map((q) => ({ s: q.s, p: q.p, o: q.o })),
        },
      };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

const revertAgentBatch: McpTool = {
  name: 'revertAgentBatch',
  description:
    'Undo a recorded agent edit batch: re-removes the triples it added and re-adds the triples it removed, in urn:vg:data. ' +
    'Idempotent — reverting an already-reverted batch is a safe no-op (reported via alreadyReverted). ' +
    'Because the graph may have changed since the edit, the revert is best-effort: ' +
    'returns {success, alreadyReverted?, reverted:{addedRemoved, removedRestored}, requested:{addedToRemove, removedToRestore}}. ' +
    'reverted.* are the ACTUAL store deltas (quads really removed/re-added); requested.* are the batch\'s recorded counts. ' +
    'When reverted < requested the revert was PARTIAL — a later edit had already removed some added triples or re-added some removed ones. ' +
    'The batch is then marked reverted (prov:wasInvalidatedBy + vg:reverted true) in urn:vg:provenance. ' +
    'Evicted batches (older than MAX_BATCHES) report success:false (unknown batchId).',
  inputSchema: {
    type: 'object',
    required: ['batchId'],
    properties: {
      batchId: { type: 'string', description: 'Batch identifier from listAgentEdits.' },
    },
  },
  async handler(params): Promise<McpResult> {
    try {
      const { batchId } = (params ?? {}) as { batchId?: string };
      if (!batchId) return { success: false, error: 'batchId is required' };
      const result = await getProvenanceRecorder().revertBatch(batchId);
      if (result.notFound) {
        return { success: false, error: `Unknown batchId: ${batchId}` };
      }
      return {
        success: true,
        data: {
          batchId,
          reverted: result.reverted,
          requested: result.requested,
          ...(result.alreadyReverted ? { alreadyReverted: true } : {}),
        },
      };
    } catch (e) {
      return { success: false, error: String(e) };
    }
  },
};

export const provenanceTools: McpTool[] = [listAgentEdits, diffAgentEdits, revertAgentBatch];
