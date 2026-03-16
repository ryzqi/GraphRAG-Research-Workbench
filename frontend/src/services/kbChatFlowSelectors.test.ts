import { describe, expect, it } from 'vitest';

import { selectKbChatFlowDetailItems } from './kbChatFlowSelectors';

describe('kbChatFlowSelectors', () => {
  it('keeps only curated key outputs for known nodes instead of exposing every raw field', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'coref_rewrite',
      section: 'output',
      items: [
        { key: 'coref_query', label: '改写后问题', value: '北京市 2025 年社保缴费基数' },
        { key: 'confidence', label: '消解置信度', value: '0.92' },
        { key: 'selected_mention', label: '选择候选', value: '北京市' },
        { key: 'reason', label: '改写原因', value: 'resolved_pronoun' },
        { key: 'needs_clarification_hint', label: '建议先澄清', value: '否' },
        { key: 'rewritten', label: '是否改写', value: '是' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['coref_query']);
  });

  it('keeps only the candidate answer for answer_subgraph output instead of internal routing fields', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'answer_subgraph',
      section: 'output',
      items: [
        { key: 'reason', label: '原因', value: 'passed' },
        { key: 'best_answer', label: '候选答案', value: 'ok' },
        { key: 'next_node', label: '下一跳', value: 'confidence_calibrate' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['best_answer']);
  });

  it('adds risk hint when confidence level is low', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'confidence_calibrate',
      section: 'output',
      items: [
        { key: 'confidence_score', label: '置信度分数', value: '0.32' },
        { key: 'confidence_level', label: '置信度等级', value: 'low' },
      ],
      event: null,
    });

    expect(result.some((item) => item.key === 'risk_hint')).toBe(true);
  });

  it('keeps explicit display items for dispatch nodes while prioritizing key fields', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'answer_review_dispatch',
      section: 'output',
      items: [
        { key: 'check_count', label: '审查数量', value: '3' },
        { key: 'checks', label: '审查列表', value: ['citation', 'factual', 'answerability'] },
        { key: 'dispatch_reason', label: '分发原因', value: '需要并行审查' },
        { key: 'router_note', label: '路由备注', value: 'keep-me' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['checks']);
  });

  it('does not append raw input fields for known nodes when a curated input policy exists', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'complexity_classify',
      section: 'input',
      items: [
        { key: 'normalized_query', label: '规范化问题', value: '北京社保缴费基数是多少' },
        { key: 'complexity_level', label: '复杂度', value: 'complex' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['normalized_query']);
  });

  it('keeps a compact budget summary for retrieval_budget_plan instead of rendering no key output', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'retrieval_budget_plan',
      section: 'output',
      items: [
        { key: 'query_count', label: '查询数量', value: '3' },
        { key: 'per_query_top_k', label: '单查询 TopK', value: '8' },
        { key: 'rerank_input_limit', label: '重排输入上限', value: '16' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['query_count', 'per_query_top_k']);
  });

  it('shows dispatch targets for doc_gate_dispatch as the key output', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'doc_gate_dispatch',
      section: 'output',
      items: [
        { key: 'route_targets', label: '派发目标', value: ['doc_gate_sufficiency', 'doc_gate_conflict'] },
        { key: 'doc_gate_round', label: '门控轮次', value: '1' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['route_targets', 'doc_gate_round']);
  });

  it('uses high risk verdict as the compact cove_check output', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'cove_check',
      section: 'output',
      items: [
        { key: 'enabled', label: '是否启用验证链', value: '是' },
        { key: 'high_risk', label: '是否高风险问题', value: '否' },
      ],
      event: null,
    });

    expect(result.map((item) => item.key)).toEqual(['high_risk']);
  });
});
