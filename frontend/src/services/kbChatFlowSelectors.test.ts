import { describe, expect, it } from 'vitest';

import type { ChatNodeDisplayItem, ChatNodeIoEvent } from './chats';
import { selectKbChatFlowDetailItems } from './kbChatFlowSelectors';

function createEvent(items: ChatNodeDisplayItem[]): ChatNodeIoEvent {
  return {
    run_id: 'run-1',
    node_name: 'merge_context',
    node_id: 'merge_context#1',
    phase: 'end',
    ts: '2026-02-24T10:00:00.000Z',
    display_output_items: items,
  };
}

describe('selectKbChatFlowDetailItems', () => {
  it('prioritizes new merge_context observability keys', () => {
    const items: ChatNodeDisplayItem[] = [
      { key: 'summary_source', label: 'summary_source', value: 'generated' },
      { key: 'compression_ratio', label: 'compression_ratio', value: '0.5' },
      { key: 'merged_context', label: 'merged_context', value: 'ctx' },
    ];
    const selected = selectKbChatFlowDetailItems({
      nodeId: 'merge_context',
      section: 'output',
      items,
      event: createEvent(items),
    });

    expect(selected.map((item) => item.key)).toEqual(['summary_source', 'compression_ratio']);
  });
});

