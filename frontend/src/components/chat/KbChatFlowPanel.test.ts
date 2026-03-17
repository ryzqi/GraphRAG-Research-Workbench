import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { KbChatFlowPanel, extractTraceCommandGoto } from './KbChatFlowPanel';

const MINIMAL_SCHEMA = {
  version: '1.1',
  hash: 'schema-hash',
  nodes: [
    { id: 'complexity_classify', label: '复杂度分类', phase: 'route', order: 5 },
    { id: 'hyde', label: 'HyDE 生成', phase: 'enhance', order: 10 },
    { id: 'doc_gate_route', label: '门控路由', phase: 'judge', order: 26 },
    { id: 'preprocess_subgraph', label: '预处理子图', phase: 'preprocess', order: 0 },
  ],
  edges: [],
} as const;

describe('KbChatFlowPanel', () => {
  it('reads branch targets only from __trace_command__', () => {
    expect(
      extractTraceCommandGoto({
        __trace_command__: { goto: 'draft_generate' },
        __command__: { goto: 'generate' },
      })
    ).toBe('draft_generate');

    expect(
      extractTraceCommandGoto({
        __command__: { goto: 'generate' },
      })
    ).toBeNull();

    expect(extractTraceCommandGoto({})).toBeNull();
  });

  it('renders execution detail items directly without raw snapshot fallback', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA,
        defaultExpandedExecutionId: 'task-1',
        traceExecutions: [
          {
            execution_id: 'task-1',
            node_name: 'complexity_classify',
            node_label: '复杂度分类',
            status: 'completed',
            started_at: '2026-01-01T00:00:01.000Z',
            updated_at: '2026-01-01T00:00:02.000Z',
            input_items: [
              { key: 'user_input', label: '用户问题', value: '解释 CoT 和 ToT 的区别' },
            ],
            output_items: [
              { key: 'decision', label: '结论', value: '复杂问题' },
              { key: 'next_node_label', label: '下一跳', value: '问题分解' },
            ],
          },
        ],
      })
    );

    expect(html).toContain('用户问题');
    expect(html).toContain('解释 CoT 和 ToT 的区别');
    expect(html).toContain('复杂问题');
    expect(html).toContain('问题分解');
  });

  it('shows explicit empty states when an execution has no detail items', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA,
        defaultExpandedExecutionId: 'task-1',
        traceExecutions: [
          {
            execution_id: 'task-1',
            node_name: 'hyde',
            node_label: 'HyDE 生成',
            status: 'started',
            started_at: '2026-01-01T00:00:01.000Z',
            updated_at: '2026-01-01T00:00:01.000Z',
          },
        ],
      })
    );

    expect(html).toContain('HyDE 生成');
    expect(html).toContain('暂无关键输入');
    expect(html).toContain('暂无关键输出');
  });

  it('shows only the node name before expansion and hides summary and timing text', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA,
        traceExecutions: [
          {
            execution_id: 'task-1',
            node_name: 'complexity_classify',
            node_label: '复杂度分类',
            status: 'completed',
            started_at: '2026-01-01T00:00:01.000Z',
            updated_at: '2026-01-01T00:00:02.000Z',
            latency_ms: 88,
            output_items: [{ key: 'decision', label: '结论', value: '无需澄清' }],
          },
        ],
      })
    );

    expect(html).toContain('复杂度分类');
    expect(html).not.toContain('结论：无需澄清');
    expect(html).not.toContain('开始');
    expect(html).not.toContain('更新');
    expect(html).not.toContain('耗时');
  });

  it('does not render fake node progress labels in the timeline-first view', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA,
        runState: {
          run_id: 'run-1',
          run_status: 'running',
          current_step_id: 'complexity_classify',
          current_step_label: '复杂度分类',
          current_step_status: 'started',
          current_node: 'complexity_classify',
          active_path: ['complexity_classify'],
          attempt: 1,
          message: null,
          progress: { completed: 50, total: 100, percent: 50 },
          ts: '2026-01-01T00:00:02.000Z',
        },
        traceExecutions: [
          {
            execution_id: 'task-1',
            node_name: 'complexity_classify',
            node_label: '复杂度分类',
            status: 'started',
            started_at: '2026-01-01T00:00:01.000Z',
            updated_at: '2026-01-01T00:00:02.000Z',
          },
        ],
      })
    );

    expect(html).toContain('整体进度');
    expect(html).not.toContain('节点进度');
  });

  it('does not render stage summary blocks above the node timeline', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA,
        runState: {
          run_id: 'run-1',
          run_status: 'running',
          current_step_id: 'complexity_classify',
          current_step_label: '复杂度分类',
          current_step_status: 'started',
          current_node: 'complexity_classify',
          active_path: ['complexity_classify'],
          attempt: 1,
          message: null,
          progress: { completed: 50, total: 100, percent: 50 },
          ts: '2026-01-01T00:00:02.000Z',
        },
        traceExecutions: [
          {
            execution_id: 'task-1',
            node_name: 'merge_context',
            node_label: '上下文合并',
            status: 'completed',
            started_at: '2026-01-01T00:00:01.000Z',
            updated_at: '2026-01-01T00:00:02.000Z',
          },
          {
            execution_id: 'task-2',
            node_name: 'complexity_classify',
            node_label: '复杂度分类',
            status: 'started',
            started_at: '2026-01-01T00:00:03.000Z',
            updated_at: '2026-01-01T00:00:04.000Z',
          },
        ],
      })
    );

    expect(html).toContain('上下文合并');
    expect(html).toContain('复杂度分类');
    expect(html).not.toContain('阶段1 理解问题');
    expect(html).not.toContain('阶段2 选择路径');
    expect(html).not.toContain('执行实例');
  });

  it('renders repeated visible node executions without showing collapsed output summaries', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA,
        traceExecutions: [
          {
            execution_id: 'task-1',
            node_name: 'complexity_classify',
            node_label: '复杂度分类',
            status: 'completed',
            started_at: '2026-01-01T00:00:01.000Z',
            updated_at: '2026-01-01T00:00:02.000Z',
            output_items: [{ key: 'decision', label: '结论', value: '复杂问题' }],
          },
          {
            execution_id: 'task-2',
            node_name: 'complexity_classify',
            node_label: '复杂度分类',
            status: 'completed',
            started_at: '2026-01-01T00:00:03.000Z',
            updated_at: '2026-01-01T00:00:04.000Z',
            output_items: [{ key: 'decision', label: '结论', value: '重新判定复杂问题' }],
          },
        ],
      })
    );

    expect(html.match(/复杂度分类/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain('结论：复杂问题');
    expect(html).not.toContain('结论：重新判定复杂问题');
  });
});
