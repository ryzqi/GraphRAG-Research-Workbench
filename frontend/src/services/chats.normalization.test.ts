import { describe, expect, it } from 'vitest';

import {
  isUnexpectedStreamEnd,
  normalizeChatStreamEvent,
  resolveTerminalRunStatus,
  toKbGraphSchemaQuery,
} from './chats';

describe('normalizeChatStreamEvent', () => {
  it('maps v2 envelope to legacy-compatible fields', () => {
    const event = normalizeChatStreamEvent({
      event: 'state',
      data: JSON.stringify({
        type: 'state',
        version: '2.0',
        run: { id: 'run-1' },
        node: { id: 'retrieve#1', name: 'retrieve' },
        run_status: 'running',
      }),
    });

    expect(event).not.toBeNull();
    expect(event?.event).toBe('state');
    expect(event?.version).toBe('2.0');
    expect(event?.payload.run_id).toBe('run-1');
    expect(event?.payload.node_id).toBe('retrieve#1');
    expect(event?.payload.current_node).toBe('retrieve');
  });

  it('keeps legacy stream events as version 1.0', () => {
    const event = normalizeChatStreamEvent({
      event: 'step',
      data: JSON.stringify({ step_id: 'retrieve', status: 'started' }),
    });

    expect(event).not.toBeNull();
    expect(event?.event).toBe('step');
    expect(event?.version).toBe('1.0');
    expect(event?.payload.step_id).toBe('retrieve');
  });

  it('returns null for invalid JSON payload', () => {
    const event = normalizeChatStreamEvent({ event: 'state', data: '{not-json' });
    expect(event).toBeNull();
  });

  it('normalizes node_io protocol events', () => {
    const event = normalizeChatStreamEvent({
      event: 'node_io',
      data: JSON.stringify({
        type: 'node_io',
        version: '2.0',
        run: { id: 'run-io' },
        node: { id: 'retrieve#1', name: 'retrieve' },
        phase: 'end',
        output_summary: { keys: ['evidence_items'] },
        display_output_items: [
          { key: 'evidence_count', label: '证据数量', value: '12' },
        ],
      }),
    });

    expect(event).not.toBeNull();
    expect(event?.event).toBe('node_io');
    expect(event?.payload.run_id).toBe('run-io');
    expect(event?.payload.node_name).toBe('retrieve');
    expect(event?.payload.display_output_items).toEqual([
      { key: 'evidence_count', label: '证据数量', value: '12' },
    ]);
  });

  it('normalizes updates protocol envelopes for LangGraph state chunks', () => {
    const event = normalizeChatStreamEvent({
      event: 'updates',
      data: JSON.stringify({
        type: 'updates',
        version: '2.0',
        run: { id: 'run-updates' },
        chunk: {
          retrieve: { attempt: 1, evidence_count: 4 },
        },
      }),
    });

    expect(event).not.toBeNull();
    expect(event?.event).toBe('updates');
    expect(event?.payload.run_id).toBe('run-updates');
    expect(event?.payload.chunk).toEqual({
      retrieve: { attempt: 1, evidence_count: 4 },
    });
  });

  it('keeps custom node_io envelopes compatible with node parser', () => {
    const event = normalizeChatStreamEvent({
      event: 'custom',
      data: JSON.stringify({
        type: 'custom',
        version: '2.0',
        event_type: 'node_io',
        run: { id: 'run-custom' },
        node: { id: 'retrieve#1', name: 'retrieve' },
        phase: 'start',
      }),
    });

    expect(event).not.toBeNull();
    expect(event?.event).toBe('custom');
    expect(event?.payload.event_type).toBe('node_io');
    expect(event?.payload.run_id).toBe('run-custom');
    expect(event?.payload.node_name).toBe('retrieve');
    expect(event?.payload.node_id).toBe('retrieve#1');
  });

  it('builds kb graph schema query from toggles', () => {
    const query = toKbGraphSchemaQuery({
      decomposition_enabled: true,
      multi_query_enabled: false,
      hyde_enabled: true,
      retrieval_hybrid_ranker: 'weighted',
      retrieval_hybrid_dense_weight: 0.6,
      retrieval_hybrid_sparse_weight: 0.4,
    });
    expect(query).toContain('decomposition_enabled=true');
    expect(query).toContain('multi_query_enabled=false');
    expect(query).toContain('hyde_enabled=true');
    expect(query).toContain('retrieval_hybrid_ranker=weighted');
    expect(query).toContain('retrieval_hybrid_dense_weight=0.6');
    expect(query).toContain('retrieval_hybrid_sparse_weight=0.4');
  });

  it('resolves terminal run status in fail-closed mode', () => {
    expect(resolveTerminalRunStatus(undefined)).toBe('failed');
    expect(resolveTerminalRunStatus('running')).toBe('failed');
    expect(resolveTerminalRunStatus('running', 'waiting_user')).toBe('waiting_user');
    expect(resolveTerminalRunStatus('succeeded')).toBe('succeeded');
  });

  it('detects unexpected stream endings without final/error events', () => {
    expect(isUnexpectedStreamEnd({ sawFinalEvent: false, sawErrorEvent: false })).toBe(true);
    expect(isUnexpectedStreamEnd({ sawFinalEvent: true, sawErrorEvent: false })).toBe(false);
    expect(isUnexpectedStreamEnd({ sawFinalEvent: false, sawErrorEvent: true })).toBe(false);
  });
});
