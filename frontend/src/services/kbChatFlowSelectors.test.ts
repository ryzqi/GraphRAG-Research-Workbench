import { describe, expect, it } from 'vitest';

import { selectKbChatFlowDetailItems } from './kbChatFlowSelectors';

describe('kbChatFlowSelectors', () => {
  it('keeps backend canonical items in original order for known nodes', () => {
    const items = [
      { key: 'decision', label: '结论', value: '复杂问题' },
      { key: 'reason', label: '原因', value: '涉及方法比较与边界说明' },
      { key: 'next_node_label', label: '下一跳', value: '问题分解' },
    ] as const;

    const result = selectKbChatFlowDetailItems({
      nodeId: 'complexity_classify',
      section: 'output',
      items,
      event: null,
    });

    expect(result).toEqual(items);
  });

  it('does not append risk hints or re-curate low confidence outputs', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'answer_commit',
      section: 'output',
      items: [
        { key: 'decision', label: '结论', value: '高置信' },
        { key: 'reason', label: '原因', value: '多信号一致' },
        { key: 'next_node_label', label: '下一跳', value: '结束' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual([
      'decision',
      'reason',
      'next_node_label',
    ]);
    expect(result.some((item) => item.key === 'risk_hint')).toBe(false);
  });

  it('preserves canonical planning keys instead of legacy compact policy keys', () => {
    const items = [
      { key: 'planned_query_count', label: '计划查询数', value: '2' },
      { key: 'planned_per_query_top_k', label: '每路召回条数', value: '6' },
    ] as const;

    const result = selectKbChatFlowDetailItems({
      nodeId: 'retrieval_plan',
      section: 'output',
      items,
      event: null,
    });

    expect(result).toEqual(items);
  });

  it('passes through evidence and review arrays without reshaping', () => {
    const evidenceItems = selectKbChatFlowDetailItems({
      nodeId: 'retrieve',
      section: 'output',
      items: [
        {
          key: 'retrieved_evidence',
          label: '检索证据',
          value: ['文档名：未命名文档\nChunk 内容：CoT 关注线性推理。'],
        },
      ],
      event: null,
    });
    const mergedEvidenceItems = selectKbChatFlowDetailItems({
      nodeId: 'merge_subquery_context',
      section: 'output',
      items: [
        {
          key: 'merged_evidence',
          label: '合并后证据',
          value: ['文档名：未命名文档\nChunk 内容：多子查询结果已汇总。'],
        },
      ],
      event: null,
    });
    const reviewItems = selectKbChatFlowDetailItems({
      nodeId: 'answer_review_dispatch',
      section: 'output',
      items: [
        {
          key: 'review_checks',
          label: '审查项',
          value: ['引用覆盖审查', '事实正确性审查', '可回答性审查'],
        },
      ],
      event: null,
    });

    expect(evidenceItems).toEqual([
      {
        key: 'retrieved_evidence',
        label: '检索证据',
        value: ['文档名：未命名文档\nChunk 内容：CoT 关注线性推理。'],
      },
    ]);
    expect(mergedEvidenceItems).toEqual([
      {
        key: 'merged_evidence',
        label: '合并后证据',
        value: ['文档名：未命名文档\nChunk 内容：多子查询结果已汇总。'],
      },
    ]);
    expect(reviewItems).toEqual([
      {
        key: 'review_checks',
        label: '审查项',
        value: ['引用覆盖审查', '事实正确性审查', '可回答性审查'],
      },
    ]);
  });
});
