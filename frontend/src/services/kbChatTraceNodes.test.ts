import { describe, expect, it } from 'vitest';

import { buildTraceNodes, buildTraceStageGroups } from './kbChatTraceNodes';

describe('kbChatTraceNodes', () => {
  it('keeps every executed node inside its stage instead of collapsing to the latest stage node', () => {
    const groups = buildTraceStageGroups({
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'preprocess_subgraph',
          node_name: 'preprocess_subgraph',
          phase: 'end',
          ts: '2026-01-01T00:00:00.000Z',
        },
        {
          run_id: 'run-1',
          node_id: 'merge_context',
          node_name: 'merge_context',
          phase: 'end',
          ts: '2026-01-01T00:00:01.000Z',
        },
        {
          run_id: 'run-1',
          node_id: 'answer_review_factual',
          node_name: 'answer_review_factual',
          phase: 'end',
          ts: '2026-01-01T00:00:02.000Z',
        },
      ],
    });

    const preprocessStage = groups.find((stage) => stage.id === 'stage_1_preprocess');
    expect(preprocessStage?.nodes.some((node) => node.id === 'preprocess_subgraph')).toBe(true);
    expect(preprocessStage?.nodes.some((node) => node.id === 'merge_context')).toBe(true);
    expect(preprocessStage?.nodes.find((node) => node.id === 'merge_context')?.status).toBe('completed');

    const answerStage = groups.find((stage) => stage.id === 'stage_6_answer');
    expect(answerStage?.nodes.some((node) => node.id === 'answer_review_factual')).toBe(true);
    expect(answerStage?.nodes.find((node) => node.id === 'answer_review_factual')?.status).toBe(
      'completed'
    );
  });

  it('builds flat node cards with stable ordering and stage metadata', () => {
    const nodes = buildTraceNodes({
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'merge_context',
        current_step_label: '上下文合并',
        current_step_status: 'started',
        current_node: 'merge_context',
        attempt: 1,
        message: null,
        progress: { completed: 1, total: 10, percent: 10 },
        ts: '2026-01-01T00:00:00.000Z',
      },
      pipelineSteps: [
        {
          step_id: 'merge_context',
          label: '上下文合并',
          status: 'started',
          message: '正在合并上下文',
          ts: '2026-01-01T00:00:00.000Z',
        },
      ],
    });

    const preprocessWrapperIndex = nodes.findIndex((node) => node.id === 'preprocess_subgraph');
    const mergeContextIndex = nodes.findIndex((node) => node.id === 'merge_context');
    const gateDispatch = nodes.find((node) => node.id === 'doc_gate_dispatch');

    expect(preprocessWrapperIndex).toBeGreaterThanOrEqual(0);
    expect(mergeContextIndex).toBeGreaterThan(preprocessWrapperIndex);
    expect(nodes[mergeContextIndex]?.status).toBe('running');
    expect(gateDispatch?.stageId).toBe('stage_5_gate');
  });

  it('does not expose english node ids as node subtitles in the flow panel', () => {
    const nodes = buildTraceNodes({
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'merge_context',
          node_name: 'merge_context',
          phase: 'end',
          ts: '2026-01-01T00:00:01.000Z',
        },
      ],
    });

    expect(nodes.find((node) => node.id === 'merge_context')?.title).toBe('上下文合并');
    expect(nodes.find((node) => node.id === 'merge_context')?.subtitle).toBeNull();
  });
});
