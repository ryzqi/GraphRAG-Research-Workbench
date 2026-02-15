import { describe, expect, it } from 'vitest';

import type { ChatNodeIoEvent, ChatRunStateEvent, KbGraphNode, KbGraphSchema } from './chats';
import { buildTraceStages } from './chatTraceStages';
import type { PipelineStep } from '../components/chat/PipelineProgress';

function createSchema(nodes: KbGraphNode[]): KbGraphSchema {
  return {
    version: '1.0',
    nodes,
    edges: [],
  };
}

function createState(partial: Partial<ChatRunStateEvent>): ChatRunStateEvent {
  return {
    run_id: 'run-1',
    run_status: 'running',
    current_step_id: null,
    current_step_label: null,
    current_step_status: null,
    current_node: null,
    attempt: null,
    message: null,
    progress: {
      completed: 0,
      total: 10,
      percent: 0,
    },
    ts: '2026-02-14T10:23:00.000Z',
    ...partial,
  };
}

function createStep(partial: Partial<PipelineStep>): PipelineStep {
  return {
    step_id: 'merge_context',
    label: '上下文合并',
    status: 'started',
    ts: '2026-02-14T10:23:00.000Z',
    ...partial,
  };
}

function createNodeEvent(partial: Partial<ChatNodeIoEvent>): ChatNodeIoEvent {
  return {
    run_id: 'run-1',
    node_name: 'retrieve',
    node_id: 'retrieve#1',
    phase: 'end',
    ts: '2026-02-14T10:23:02.000Z',
    ...partial,
  };
}

describe('buildTraceStages', () => {
  it('展示 schema 中的所有节点（全图）', () => {
    const schema = createSchema([
      {
        id: 'merge_context',
        label: '上下文合并',
        phase: 'preprocess',
        order: 0,
      },
      {
        id: 'hyde',
        label: 'HyDE 扩展',
        phase: 'preprocess',
        order: 1,
      },
    ]);
    const stages = buildTraceStages({
      schema,
      runState: createState({}),
      pipelineSteps: [createStep({ step_id: 'merge_context', status: 'completed' })],
      nodeIoEvents: [],
    });

    expect(stages.map((item) => item.id)).toEqual(['merge_context', 'hyde']);
  });

  it('marks unvisited schema nodes as skipped after terminal completion', () => {
    const schema = createSchema([
      { id: 'merge_context', label: '上下文合并', phase: 'preprocess', order: 0 },
      { id: 'retrieve', label: '知识检索', phase: 'retrieve', order: 1 },
      { id: 'finalize', label: '最终回答', phase: 'finalize', order: 2 },
    ]);
    const stages = buildTraceStages({
      schema,
      runState: createState({
        run_status: 'succeeded',
        current_step_id: 'retrieve',
        current_node: 'retrieve',
        active_path: ['merge_context', 'retrieve'],
      }),
      pipelineSteps: [
        createStep({ step_id: 'merge_context', status: 'completed' }),
        createStep({ step_id: 'retrieve', label: '知识检索', status: 'completed' }),
      ],
      nodeIoEvents: [],
    });

    expect(stages.map((item) => item.id)).toEqual(['merge_context', 'retrieve', 'finalize']);
    expect(stages.map((item) => item.status)).toEqual(['completed', 'completed', 'skipped']);
  });

  it('按 schema.order 排序节点', () => {
    const schema = createSchema([
      {
        id: 'retrieve',
        label: '知识检索',
        phase: 'retrieve',
        order: 10,
      },
      {
        id: 'merge_context',
        label: '上下文合并',
        phase: 'preprocess',
        order: 1,
      },
    ]);
    const stages = buildTraceStages({
      schema,
      runState: createState({}),
      pipelineSteps: [],
      nodeIoEvents: [],
    });

    expect(stages.map((item) => item.id)).toEqual(['merge_context', 'retrieve']);
  });

  it('根据运行态将节点标记为运行中', () => {
    const schema = createSchema([
      {
        id: 'retrieve',
        label: '知识检索',
        phase: 'retrieve',
        order: 1,
      },
    ]);
    const stages = buildTraceStages({
      schema,
      runState: createState({ current_step_id: 'retrieve', current_node: 'retrieve', run_status: 'running' }),
      pipelineSteps: [createStep({ step_id: 'retrieve', label: '知识检索', status: 'started' })],
      nodeIoEvents: [],
    });

    expect(stages[0]?.status).toBe('running');
    expect(stages[0]?.isActive).toBe(true);
  });

  it('从节点摘要中提取指标', () => {
    const schema = createSchema([
      {
        id: 'retrieve',
        label: '知识检索',
        phase: 'retrieve',
        order: 1,
      },
    ]);
    const stages = buildTraceStages({
      schema,
      runState: createState({}),
      pipelineSteps: [createStep({ step_id: 'retrieve', label: '知识检索', status: 'completed' })],
      nodeIoEvents: [
        createNodeEvent({
          node_name: 'retrieve',
          latency_ms: 420,
          output_summary: { evidence_count: 15, attempted: true },
        }),
      ],
    });

    const metrics = stages[0]?.metrics ?? [];
    expect(metrics.some((item) => item.label === '证据数' && item.value === '15')).toBe(true);
    expect(metrics.some((item) => item.label === '耗时' && item.value === '0.4s')).toBe(true);
  });

  it('当节点出现 error 事件时标记失败', () => {
    const schema = createSchema([
      {
        id: 'generate',
        label: '草稿生成',
        phase: 'generate',
        order: 1,
      },
    ]);
    const stages = buildTraceStages({
      schema,
      runState: createState({ run_status: 'failed', current_step_id: 'generate' }),
      pipelineSteps: [],
      nodeIoEvents: [
        createNodeEvent({
          node_name: 'generate',
          node_id: 'generate#1',
          phase: 'error',
        }),
      ],
    });

    expect(stages[0]?.status).toBe('failed');
    expect(stages[0]?.percent).toBe(100);
  });
});
