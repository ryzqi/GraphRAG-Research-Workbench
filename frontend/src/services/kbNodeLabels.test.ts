import { describe, expect, it } from 'vitest';

import { resolveKbNodeLabel } from './kbNodeLabels';

describe('kbNodeLabels', () => {
  it('does not keep hard-coded labels for legacy nodes removed from the flowchart', () => {
    expect(resolveKbNodeLabel('rewrite_plan', null)).toBe('rewrite_plan');
    expect(resolveKbNodeLabel('doc_gate_precheck', null)).toBe('doc_gate_precheck');
    expect(resolveKbNodeLabel('answer_self_check', null)).toBe('answer_self_check');
    expect(resolveKbNodeLabel('adaptive_routing', null)).toBe('adaptive_routing');
    expect(resolveKbNodeLabel('finalize', null)).toBe('finalize');
    expect(resolveKbNodeLabel('doc_gate_sufficiency', null)).toBe('doc_gate_sufficiency');
    expect(resolveKbNodeLabel('doc_gate_route', null)).toBe('doc_gate_route');
    expect(resolveKbNodeLabel('confidence_calibrate', null)).toBe('confidence_calibrate');
    expect(resolveKbNodeLabel('complexity_classify', null)).toBe('complexity_classify');
    expect(resolveKbNodeLabel('prepare_messages', null)).toBe('prepare_messages');
  });

  it('keeps labels for nodes that still belong to the current flowchart', () => {
    expect(resolveKbNodeLabel('query_plan', null)).toBe('查询规划');
    expect(resolveKbNodeLabel('resolve_reference', null)).toBe('指代消解');
    expect(resolveKbNodeLabel('hyde', null)).toBe('假设文档扩展');
    expect(resolveKbNodeLabel('query_plan_finalize', null)).toBe('查询定稿');
  });

  it('resolves labels for control and dispatch nodes from the shared catalog', () => {
    expect(resolveKbNodeLabel('retrieval_plan', null)).toBe('检索预算规划');
    expect(resolveKbNodeLabel('answer_review_dispatch', null)).toBe('审查分发');
    expect(resolveKbNodeLabel('preprocess_subgraph', null)).toBe('预处理子图');
  });

  it('resolves the semantic cache synthetic node label from the shared catalog', () => {
    expect(resolveKbNodeLabel('semantic_cache', null)).toBe('语义缓存');
  });
});
