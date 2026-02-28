import { describe, expect, it } from 'vitest';

import { selectKbChatFlowDetailItems } from './kbChatFlowSelectors';

describe('kbChatFlowSelectors', () => {
  it('returns all candidate detail items instead of truncating', () => {
    const result = selectKbChatFlowDetailItems({
      nodeId: 'answer_subgraph',
      section: 'output',
      items: [
        { key: 'next_step', label: '下一步', value: 'answer_commit' },
        { key: 'reason', label: '原因', value: 'passed' },
        { key: 'degrade_reason', label: '降级原因', value: 'none' },
        { key: 'best_answer', label: '候选答案', value: 'ok' },
        { key: 'repair_attempts', label: '修复次数', value: '1' },
        { key: 'extra_signal', label: '扩展信号', value: 'keep-me' },
      ],
      event: null,
    });

    expect(result).toHaveLength(6);
    expect(result[result.length - 1]?.key).toBe('extra_signal');
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
});
