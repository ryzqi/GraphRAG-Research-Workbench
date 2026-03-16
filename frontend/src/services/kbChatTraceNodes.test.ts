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

  it('keeps chinese fallback titles for legacy preprocess shell nodes that still arrive in trace events', () => {
    const nodes = buildTraceNodes({
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'AMBIGUITY_CHECK_ENABLED',
          node_name: 'AMBIGUITY_CHECK_ENABLED',
          phase: 'end',
          ts: '2026-01-01T00:00:01.000Z',
        },
        {
          run_id: 'run-1',
          node_id: 'adaptive_routing',
          node_name: 'adaptive_routing',
          phase: 'end',
          ts: '2026-01-01T00:00:02.000Z',
        },
        {
          run_id: 'run-1',
          node_id: 'ENABLE_HYDE',
          node_name: 'ENABLE_HYDE',
          phase: 'end',
          ts: '2026-01-01T00:00:03.000Z',
        },
      ],
    });

    expect(nodes.find((node) => node.id === 'AMBIGUITY_CHECK_ENABLED')).toMatchObject({
      title: '歧义检查入口',
      subtitle: null,
    });
    expect(nodes.find((node) => node.id === 'adaptive_routing')).toMatchObject({
      title: '自适应路由',
      subtitle: null,
    });
    expect(nodes.find((node) => node.id === 'ENABLE_HYDE')).toMatchObject({
      title: 'HyDE开关',
      subtitle: null,
    });
  });

  it('prefers terminal waiting_user and failed state for the current node over stale started steps', () => {
    const waitingNodes = buildTraceNodes({
      runState: {
        run_id: 'run-1',
        run_status: 'waiting_user',
        current_step_id: 'merge_context',
        current_step_label: '上下文合并',
        current_step_status: 'waiting_user',
        current_node: 'merge_context',
        attempt: 1,
        message: '请补充范围',
        active_path: ['merge_context'],
        progress: { completed: 1, total: 10, percent: 10 },
        ts: '2026-01-01T00:00:02.000Z',
      },
      pipelineSteps: [
        {
          step_id: 'merge_context',
          label: '上下文合并',
          status: 'started',
          ts: '2026-01-01T00:00:01.000Z',
        },
      ],
    });

    const failedNodes = buildTraceNodes({
      runState: {
        run_id: 'run-1',
        run_status: 'failed',
        current_step_id: 'merge_context',
        current_step_label: '上下文合并',
        current_step_status: 'failed',
        current_node: 'merge_context',
        attempt: 1,
        message: '检索失败',
        active_path: ['merge_context'],
        progress: { completed: 1, total: 10, percent: 10 },
        ts: '2026-01-01T00:00:03.000Z',
      },
      pipelineSteps: [
        {
          step_id: 'merge_context',
          label: '上下文合并',
          status: 'started',
          ts: '2026-01-01T00:00:01.000Z',
        },
      ],
    });

    expect(waitingNodes.find((node) => node.id === 'merge_context')?.status).toBe('waiting_user');
    expect(failedNodes.find((node) => node.id === 'merge_context')?.status).toBe('failed');
  });

  it('prefers current_step_status over stale pipeline step status for the active node', () => {
    const nodes = buildTraceNodes({
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'merge_context',
        current_step_label: '上下文合并',
        current_step_status: 'completed',
        current_node: 'merge_context',
        attempt: 1,
        message: null,
        active_path: ['merge_context'],
        progress: { completed: 1, total: 10, percent: 10 },
        ts: '2026-01-01T00:00:02.000Z',
      },
      pipelineSteps: [
        {
          step_id: 'merge_context',
          label: '上下文合并',
          status: 'started',
          ts: '2026-01-01T00:00:01.000Z',
        },
      ],
    });

    expect(nodes.find((node) => node.id === 'merge_context')?.status).toBe('completed');
  });

  it('builds compact chinese summaries and tags instead of exposing machine summary fields', () => {
    const nodes = buildTraceNodes({
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'complexity_classify',
        current_step_label: '复杂度分类',
        current_step_status: 'completed',
        current_node: 'complexity_classify',
        attempt: 1,
        message: null,
        active_path: ['merge_context', 'complexity_classify'],
        progress: { completed: 2, total: 10, percent: 20 },
        ts: '2026-01-01T00:00:02.000Z',
      },
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'complexity_classify',
          node_name: 'complexity_classify',
          phase: 'end',
          latency_ms: 321,
          output_summary: {
            complexity_level: 'complex',
            fallback_used: true,
            slot_count: 0,
            ambiguous: false,
          },
          ts: '2026-01-01T00:00:02.000Z',
        },
      ],
    });

    const node = nodes.find((item) => item.id === 'complexity_classify');
    expect(node?.summaryText).toBe('已识别为复杂问题');
    expect(node?.summaryTags).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ label: '耗时', value: '0.3s' }),
        expect.objectContaining({ label: '复杂度', value: '复杂' }),
      ])
    );
    expect(node?.summaryTags.some((tag) => tag.label.includes('fallback'))).toBe(false);
    expect(node?.summaryTags.some((tag) => tag.label.includes('slot'))).toBe(false);
  });

  it('builds stage summary text from the most relevant node summary', () => {
    const groups = buildTraceStageGroups({
      runState: {
        run_id: 'run-1',
        run_status: 'running',
        current_step_id: 'complexity_classify',
        current_step_label: '复杂度分类',
        current_step_status: 'completed',
        current_node: 'complexity_classify',
        attempt: 1,
        message: null,
        active_path: ['merge_context', 'complexity_classify'],
        progress: { completed: 2, total: 10, percent: 20 },
        ts: '2026-01-01T00:00:02.000Z',
      },
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'complexity_classify',
          node_name: 'complexity_classify',
          phase: 'end',
          output_summary: {
            complexity_level: 'complex',
          },
          ts: '2026-01-01T00:00:02.000Z',
        },
      ],
    });

    expect(groups.find((stage) => stage.id === 'stage_2_route')?.summaryText).toBe(
      '已识别为复杂问题'
    );
  });

  it('renders only schema nodes plus observed nodes when graph schema exists', () => {
    const groups = buildTraceStageGroups({
      schema: {
        version: '2026-03-12',
        hash: 'schema-hash-legacy',
        nodes: [
          { id: 'answer_subgraph', label: '答案子图', phase: 'generate', order: 37 },
          { id: 'draft_generate', label: '草稿生成', phase: 'generate', order: 38 },
          { id: 'answer_review_fuse', label: '审查结果融合', phase: 'verify', order: 43 },
        ],
        edges: [],
      },
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'draft_generate',
          node_name: 'draft_generate',
          phase: 'end',
          ts: '2026-01-01T00:00:01.000Z',
        },
        {
          run_id: 'run-1',
          node_id: 'answer_review_fuse',
          node_name: 'answer_review_fuse',
          phase: 'end',
          ts: '2026-01-01T00:00:02.000Z',
        },
      ],
    });

    const nodeIds = groups.flatMap((stage) => stage.nodes.map((node) => node.id));

    expect(nodeIds).toContain('draft_generate');
    expect(nodeIds).toContain('answer_review_fuse');
    expect(nodeIds).not.toContain('generate');
    expect(nodeIds).not.toContain('answer_review');
  });

  it('prefers backend schema phase and order over local catalog when building nodes', () => {
    const nodes = buildTraceNodes({
      schema: {
        version: '1.1',
        hash: 'schema-hash',
        nodes: [
          {
            id: 'transform_query',
            label: '重试改写',
            phase: 'finalize',
            order: 999,
            metadata: { label: '重试改写', phase: 'finalize', order: 999 },
          },
        ],
        edges: [],
      },
      nodeIoEvents: [
        {
          run_id: 'run-1',
          node_id: 'transform_query',
          node_name: 'transform_query',
          phase: 'end',
          ts: '2026-01-01T00:00:01.000Z',
        },
      ],
    });

    expect(nodes.find((node) => node.id === 'transform_query')).toMatchObject({
      title: '重试改写',
      stageId: 'stage_7_finalize',
      order: 999,
    });
  });

  it('does not include deprecated preprocess shell nodes in fallback trace view', () => {
    const nodes = buildTraceNodes({});
    const nodeIds = new Set(nodes.map((node) => node.id));

    [
      'AMBIGUITY_CHECK_ENABLED',
      'adaptive_routing',
      'simple_path',
      'moderate_path',
      'complex_path',
      'ENABLE_MULTI_QUERY_MOD',
      'ENABLE_DECOMPOSITION',
      'ENABLE_MULTI_QUERY',
      'ENABLE_HYDE',
    ].forEach((nodeId) => {
      expect(nodeIds.has(nodeId)).toBe(false);
    });
  });
});
