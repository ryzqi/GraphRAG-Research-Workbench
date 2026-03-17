import fs from 'node:fs';

import { describe, expect, it } from 'vitest';

import {
  buildTraceExecutionTimeline,
  buildTraceStageSummaries,
} from './kbChatTraceNodes';
import { createSseParser } from '../lib/sse';
import { normalizeChatStreamEvent } from './chats';
import {
  kbChatTraceSelectors,
  reduceKbChatTraceState,
} from './kbChatTraceStore';
import { resolveKbNodeLabel } from './kbNodeLabels';

describe('kbChatTraceNodes', () => {
  it('filters wrapper subgraph executions while preserving repeated visible node order', () => {
    const executions = buildTraceExecutionTimeline({
      schema: {
        version: '1.1',
        hash: 'schema-hash',
        nodes: [
          { id: 'preprocess_subgraph', label: '预处理子图', phase: 'preprocess', order: 0 },
          { id: 'merge_context', label: '上下文合并', phase: 'preprocess', order: 1 },
          { id: 'retrieve_subquery', label: '子查询检索', phase: 'retrieve', order: 16 },
        ],
        edges: [],
      },
      traceExecutions: [
        {
          execution_id: 'task-wrapper',
          node_name: 'preprocess_subgraph',
          node_label: '预处理子图',
          status: 'completed',
          started_at: '2026-01-01T00:00:00.000Z',
          updated_at: '2026-01-01T00:00:00.000Z',
        },
        {
          execution_id: 'task-1',
          node_name: 'retrieve_subquery',
          node_label: '子查询检索',
          status: 'completed',
          started_at: '2026-01-01T00:00:01.000Z',
          updated_at: '2026-01-01T00:00:02.000Z',
          output_items: [{ key: 'retrieval_count', label: '证据数', value: '4' }],
        },
        {
          execution_id: 'task-2',
          node_name: 'retrieve_subquery',
          node_label: '子查询检索',
          status: 'completed',
          started_at: '2026-01-01T00:00:03.000Z',
          updated_at: '2026-01-01T00:00:04.000Z',
          output_items: [{ key: 'retrieval_count', label: '证据数', value: '2' }],
        },
        {
          execution_id: 'task-model',
          node_name: 'model',
          node_label: 'model',
          status: 'completed',
          started_at: '2026-01-01T00:00:05.000Z',
          updated_at: '2026-01-01T00:00:06.000Z',
        },
      ],
    });

    expect(executions.map((execution) => execution.execution_id)).toEqual(['task-1', 'task-2']);
    expect(executions.map((execution) => execution.summaryText)).toEqual(['证据数：4', '证据数：2']);
  });

  it('derives stage summaries from execution timeline plus authoritative runState', () => {
    const stages = buildTraceStageSummaries({
      schema: {
        version: '1.1',
        hash: 'schema-hash',
        nodes: [
          { id: 'merge_context', label: '上下文合并', phase: 'preprocess', order: 1 },
          { id: 'complexity_classify', label: '复杂度分类', phase: 'route', order: 5 },
          { id: 'retrieve_subquery', label: '子查询检索', phase: 'retrieve', order: 16 },
        ],
        edges: [],
      },
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'retrieve_subquery',
        current_step_label: '子查询检索',
        current_step_status: 'started',
        current_node: 'retrieve_subquery',
        attempt: 1,
        message: null,
        progress: { completed: 2, total: 10, percent: 20 },
        active_path: ['merge_context', 'complexity_classify', 'retrieve_subquery'],
        ts: '2026-01-01T00:00:03.000Z',
      },
      traceExecutions: [
        {
          execution_id: 'task-merge',
          node_name: 'merge_context',
          node_label: '上下文合并',
          status: 'completed',
          started_at: '2026-01-01T00:00:00.000Z',
          updated_at: '2026-01-01T00:00:01.000Z',
        },
        {
          execution_id: 'task-route',
          node_name: 'complexity_classify',
          node_label: '复杂度分类',
          status: 'completed',
          started_at: '2026-01-01T00:00:01.000Z',
          updated_at: '2026-01-01T00:00:02.000Z',
        },
        {
          execution_id: 'task-retrieve',
          node_name: 'retrieve_subquery',
          node_label: '子查询检索',
          status: 'started',
          started_at: '2026-01-01T00:00:02.000Z',
          updated_at: '2026-01-01T00:00:03.000Z',
        },
      ],
    });

    expect(stages.find((stage) => stage.id === 'stage_1_preprocess')).toMatchObject({
      status: 'completed',
      executionCount: 1,
    });
    expect(stages.find((stage) => stage.id === 'stage_2_route')).toMatchObject({
      status: 'completed',
      executionCount: 1,
    });
    expect(stages.find((stage) => stage.id === 'stage_4_retrieve')).toMatchObject({
      status: 'running',
      currentNodeLabel: '子查询检索',
      executionCount: 1,
    });
  });

  it('replays live SSE into a timeline that hides every subgraph wrapper while preserving visible step order', () => {
    const parser = createSseParser();
    const raw = fs.readFileSync(new URL('../../../live_kb_chat_trace.sse', import.meta.url), 'utf8');
    const sseEvents = [...parser.feed(raw), ...parser.flush()];
    const traceStateCtx = {
      totalNodes: 100,
      resolveNodeLabel: (nodeId: string) => resolveKbNodeLabel(nodeId, null),
    };
    let traceState = reduceKbChatTraceState(
      {},
      { type: 'meta', runId: 'live-run' },
      traceStateCtx
    );
    const visibleStepStartOrder: string[] = [];

    for (const sseEvent of sseEvents) {
      const normalized = normalizeChatStreamEvent(sseEvent);
      if (!normalized) {
        continue;
      }
      const { event, payload } = normalized;
      if (event === 'meta') {
        if (typeof payload.run_id === 'string') {
          traceState = reduceKbChatTraceState(
            traceState,
            { type: 'meta', runId: payload.run_id },
            traceStateCtx
          );
        }
        continue;
      }

      if (event === 'step') {
        const stepId = typeof payload.step_id === 'string' ? payload.step_id : null;
        const executionId =
          typeof payload.execution_id === 'string' ? payload.execution_id : null;
        if (
          stepId &&
          executionId &&
          payload.status === 'started' &&
          !stepId.endsWith('_subgraph') &&
          stepId !== 'model'
        ) {
          visibleStepStartOrder.push(`${stepId}#${executionId}`);
        }
        traceState = reduceKbChatTraceState(traceState, { type: 'step', raw: payload }, traceStateCtx);
        continue;
      }

      if (event === 'state') {
        traceState = reduceKbChatTraceState(traceState, { type: 'state', raw: payload }, traceStateCtx);
        continue;
      }

      if (event === 'node_io') {
        traceState = reduceKbChatTraceState(
          traceState,
          { type: 'node_io', raw: payload },
          traceStateCtx
        );
        continue;
      }

      if (event === 'updates') {
        traceState = reduceKbChatTraceState(
          traceState,
          { type: 'updates', raw: payload },
          traceStateCtx
        );
        continue;
      }

      if (event === 'ui_event') {
        traceState = reduceKbChatTraceState(
          traceState,
          { type: 'ui_event', raw: payload },
          traceStateCtx
        );
        continue;
      }

      if (event === 'custom' || event === 'heartbeat') {
        traceState = reduceKbChatTraceState(
          traceState,
          { type: 'custom', raw: payload },
          traceStateCtx
        );
      }
    }

    const timeline = buildTraceExecutionTimeline({
      schema: null,
      runState: kbChatTraceSelectors.runState(traceState),
      traceExecutions: kbChatTraceSelectors.traceExecutions(traceState),
    });

    expect(timeline.map((execution) => `${execution.node_name}#${execution.execution_id}`)).toEqual(
      visibleStepStartOrder
    );
    expect(timeline.some((execution) => execution.node_name.endsWith('_subgraph'))).toBe(false);
  });

  it('keeps the latest visible business node active when runState points at a hidden internal node', () => {
    const schema = {
      version: '1.1',
      hash: 'schema-hash',
      nodes: [
        { id: 'merge_context', label: '上下文合并', phase: 'preprocess', order: 1 },
        { id: 'normalize_rewrite', label: '问题规范', phase: 'preprocess', order: 4 },
        { id: 'complexity_classify', label: '复杂度分类', phase: 'route', order: 5 },
      ],
      edges: [],
    } as const;

    const traceExecutions = [
      {
        execution_id: 'task-merge',
        node_name: 'merge_context',
        node_label: '上下文合并',
        status: 'completed' as const,
        started_at: '2026-01-01T00:00:00.000Z',
        updated_at: '2026-01-01T00:00:01.000Z',
      },
      {
        execution_id: 'task-normalize',
        node_name: 'normalize_rewrite',
        node_label: '问题规范',
        status: 'started' as const,
        started_at: '2026-01-01T00:00:02.000Z',
        updated_at: '2026-01-01T00:00:03.000Z',
      },
    ];

    const timeline = buildTraceExecutionTimeline({
      schema,
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'model',
        current_step_label: 'model',
        current_step_status: 'started',
        current_node: 'model',
        attempt: 1,
        message: null,
        progress: { completed: 1, total: 4, percent: 25 },
        ts: '2026-01-01T00:00:03.500Z',
      },
      traceExecutions,
    });

    expect(timeline.find((execution) => execution.execution_id === 'task-normalize')).toMatchObject({
      isActive: true,
    });

    const stages = buildTraceStageSummaries({
      schema,
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'model',
        current_step_label: 'model',
        current_step_status: 'started',
        current_node: 'model',
        attempt: 1,
        message: null,
        progress: { completed: 1, total: 4, percent: 25 },
        ts: '2026-01-01T00:00:03.500Z',
      },
      traceExecutions,
    });

    expect(stages.find((stage) => stage.id === 'stage_1_preprocess')).toMatchObject({
      status: 'running',
      currentNodeLabel: '问题规范',
    });
    expect(stages.find((stage) => stage.id === 'stage_4_retrieve')).toMatchObject({
      status: 'idle',
      currentNodeLabel: null,
    });
  });
});
