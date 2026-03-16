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

  it('renders backend display items directly without raw summary or snapshot fallback', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA as never,
        defaultExpandedNodeId: 'complexity_classify',
        nodeIoEvents: [
          {
            run_id: 'run-1',
            node_id: 'complexity_classify',
            node_name: 'complexity_classify',
            phase: 'end',
            ts: '2026-01-01T00:00:02.000Z',
            input_summary: { raw_input_summary: '不要展示这个输入摘要' },
            output_summary: { raw_output_summary: '不要展示这个输出摘要' },
            input_snapshot: { user_input: '也不要展示这个输入快照' },
            output_snapshot: { complexity_level: 'complex' },
            display_input_items: [
              {
                key: 'user_input',
                label: '用户问题',
                value: '解释 CoT 和 ToT 的区别',
              },
            ],
            display_output_items: [
              { key: 'decision', label: '结论', value: '复杂问题' },
              { key: 'reason', label: '原因', value: '涉及方法比较与边界说明' },
              { key: 'next_node_label', label: '下一跳', value: '问题分解' },
            ],
          },
        ],
      } as never)
    );

    expect(html).toContain('用户问题');
    expect(html).toContain('解释 CoT 和 ToT 的区别');
    expect(html).toContain('复杂问题');
    expect(html).toContain('问题分解');
    expect(html).not.toContain('不要展示这个输入摘要');
    expect(html).not.toContain('不要展示这个输出摘要');
    expect(html).not.toContain('也不要展示这个输入快照');
    expect(html).not.toContain('complexity_level');
  });

  it('shows explicit empty states when a visible node has no display items', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: {
          version: '1.1',
          hash: 'schema-hash',
          nodes: [
            { id: 'preprocess_subgraph', label: '预处理子图', phase: 'preprocess', order: 0 },
          ],
          edges: [],
        } as never,
        runState: {
          run_id: 'run-1',
          run_status: 'running',
          current_step_id: 'entity_expand',
          current_step_label: '实体扩展',
          current_step_status: 'started',
          current_node: 'entity_expand',
          active_path: ['preprocess_subgraph', 'entity_expand'],
          attempt: 1,
          message: null,
          progress: { completed: 1, total: 10, percent: 10 },
          ts: '2026-01-01T00:00:02.000Z',
        },
        nodeIoEvents: [
          {
            run_id: 'run-1',
            node_id: 'preprocess_subgraph',
            node_name: 'preprocess_subgraph',
            node_path: ['preprocess_subgraph', 'entity_expand'],
            phase: 'start',
            ts: '2026-01-01T00:00:01.000Z',
          },
        ],
        defaultExpandedNodeId: 'entity_expand',
      } as never)
    );

    expect(html).toContain('实体扩展');
    expect(html).toContain('暂无关键输入');
    expect(html).toContain('暂无关键输出');
  });

  it('renders list items and long text in full without expand fallback controls', () => {
    const longText = 'HyDE 长文全文。'.repeat(80);
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA as never,
        defaultExpandedNodeId: 'hyde',
        nodeIoEvents: [
          {
            run_id: 'run-1',
            node_id: 'hyde',
            node_name: 'hyde',
            phase: 'end',
            ts: '2026-01-01T00:00:02.000Z',
            display_input_items: [
              { key: 'normalized_query', label: '规范化问题', value: '解释 CoT 和 ToT 的区别' },
            ],
            display_output_items: [
              {
                key: 'hyde_docs',
                label: 'HyDE 文档',
                value: [longText, '第二段 HyDE 全文。'],
              },
            ],
          },
        ],
      } as never)
    );

    expect(html).toContain(longText);
    expect(html).toContain('第二段 HyDE 全文。');
    expect(html).not.toContain('展开全文');
  });

  it('renders idle status and error summary using backend display contract', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: MINIMAL_SCHEMA as never,
        defaultExpandedNodeId: 'doc_gate_route',
        nodeIoEvents: [
          {
            run_id: 'run-1',
            node_id: 'doc_gate_route',
            node_name: 'doc_gate_route',
            phase: 'error',
            ts: '2026-01-01T00:00:02.000Z',
            display_output_items: [
              { key: 'error_summary', label: '错误信息', value: '节点执行失败' },
            ],
            error_summary: '节点执行失败',
          },
        ],
      } as never)
    );

    expect(html).toContain('待执行');
    expect(html).toContain('错误信息');
    expect(html).toContain('节点执行失败');
  });
});
