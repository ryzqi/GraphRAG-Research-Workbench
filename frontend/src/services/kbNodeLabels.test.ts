import { describe, expect, it } from 'vitest';

import { resolveKbNodeLabel } from './kbNodeLabels';

describe('kbNodeLabels', () => {
  it('does not keep hard-coded labels for legacy nodes removed from the flowchart', () => {
    expect(resolveKbNodeLabel('rewrite_plan', null)).toBe('rewrite_plan');
    expect(resolveKbNodeLabel('doc_gate_precheck', null)).toBe('doc_gate_precheck');
    expect(resolveKbNodeLabel('answer_self_check', null)).toBe('answer_self_check');
  });

  it('keeps labels for nodes that still belong to the current flowchart', () => {
    expect(resolveKbNodeLabel('complexity_classify', null)).toBe('复杂度分类');
    expect(resolveKbNodeLabel('doc_gate_sufficiency', null)).toBe('证据充分度');
  });
});
