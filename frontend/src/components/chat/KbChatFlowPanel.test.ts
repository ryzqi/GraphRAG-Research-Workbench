import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import {
  buildFallbackOutputItems,
  KbChatFlowPanel,
  extractTraceCommandGoto,
} from './KbChatFlowPanel';

describe('KbChatFlowPanel', () => {
  it('prefers __trace_command__ over legacy __command__ for branch targets', () => {
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
    ).toBe('generate');

    expect(extractTraceCommandGoto({})).toBeNull();
  });

  it('renders compact summaries without exposing execution path or machine summary keys', () => {
    const html = renderToStaticMarkup(
      createElement(KbChatFlowPanel, {
        schema: null,
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
            node_path: ['preprocess_subgraph', 'complexity_classify'],
            phase: 'end',
            latency_ms: 321,
            output_summary: {
              complexity_level: 'complex',
              fallback_used: true,
              slot_count: 0,
            },
            ts: '2026-01-01T00:00:02.000Z',
          },
        ],
      })
    );

    expect(html).toContain('已识别为复杂问题');
    expect(html).toContain('复杂度: 复杂');
    expect(html).not.toContain('执行路径');
    expect(html).not.toContain('fallback_used');
    expect(html).not.toContain('slot_count');
  });

  it('uses canonical routing record for answer_subgraph fallback output items', () => {
    const items = buildFallbackOutputItems('answer_subgraph', {
      output_snapshot: {
        routing_decisions: {
          answer_subgraph: {
            next_node: 'confidence_calibrate',
            action: 'none',
            reason: 'passed',
          },
        },
        stage_summaries: {
          answer_subgraph: {
            next_step: 'force_exit',
            reason: 'stale_stage_reason',
          },
        },
        reflection: {
          reason: 'stale_reflection_reason',
        },
        best_answer: '答案 [S1]',
      },
    } as never);

    const byKey = new Map(items.map((item) => [item.key, item.value]));
    expect(byKey.get('next_node')).toBe('confidence_calibrate');
    expect(byKey.get('reason')).toBe('passed');
  });

  it('does not synthesize answer_subgraph routing details from legacy summary fields', () => {
    const items = buildFallbackOutputItems('answer_subgraph', {
      output_snapshot: {
        stage_summaries: {
          answer_subgraph: {
            next_step: 'force_exit',
            reason: 'stale_stage_reason',
          },
        },
        reflection: {
          reason: 'stale_reflection_reason',
        },
      },
    } as never);

    const keys = items.map((item) => item.key);
    expect(keys).not.toContain('next_node');
    expect(keys).not.toContain('reason');
  });
});
