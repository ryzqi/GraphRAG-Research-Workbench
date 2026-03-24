import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./MessageItem', () => ({
  MessageItem: ({
    content,
    showActions = true,
  }: {
    content: string;
    showActions?: boolean;
  }) => createElement('div', { 'data-show-actions': String(showActions) }, content),
  ClarificationCard: () => null,
  ToolApprovalCard: () => null,
}));

import { MessageList, type ChatMessage } from './MessageList';

function createAssistantMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'assistant-1',
    role: 'assistant',
    content: '答案正文',
    think: '',
    isStreaming: false,
    evidence: [],
    ...overrides,
  };
}

describe('MessageList', () => {
  it('preserves stripTrailingReferenceSection behavior when inline references are duplicated in content', () => {
    const html = renderToStaticMarkup(
      createElement(MessageList, {
        loading: false,
        messages: [
          createAssistantMessage({
            content: '最终答案。\n\n参考来源\n[S1] 尾部引用块应该被移除',
            evidence: [
              {
                source_kind: 'kb',
                kb_id: 'kb-1',
                material_id: 'mat-1',
                chunk_id: 'chunk-1',
                locator: { filename: 'appendix.pdf' },
                excerpt: '真正展示的证据摘录。',
                citation_id: 'S1',
              },
            ],
          }),
        ],
        normalizeInlineEvidenceSection: true,
      })
    );

    expect(html).toContain('最终答案。');
    expect(html).toContain('真正展示的证据摘录。');
    expect(html).not.toContain('尾部引用块应该被移除');
  });

  it('hides copy actions for assistant clarification messages before a normal answer is produced', () => {
    const html = renderToStaticMarkup(
      createElement(MessageList, {
        loading: false,
        messages: [
          createAssistantMessage({
            content: '',
            pendingClarification: {
              message: '请补充范围',
              pendingClarification: null,
            },
            runId: 'run-clarification-1',
          }),
        ],
        onClarificationSubmit: () => undefined,
      })
    );

    expect(html).toContain('data-show-actions="false"');
  });

  it('renders semantic cache hit type, score and ttl for cached assistant message', () => {
    const html = renderToStaticMarkup(
      createElement(MessageList, {
        loading: false,
        messages: [
          createAssistantMessage({
            responseSource: 'cached',
            cacheMeta: {
              hit: true,
              hit_type: 'strong_hit',
              score: 0.91,
              threshold: 0.88,
              ttl_seconds: 24 * 60 * 60,
              entry_id: 'entry-1',
              schema_version: 'v3',
              created_at: '2026-03-24T10:00:00Z',
            },
          }),
        ],
      })
    );

    expect(html).toContain('语义缓存命中');
    expect(html).toContain('强命中');
    expect(html).toContain('0.91 / 0.88');
    expect(html).toContain('缓存剩余约 24 小时');
  });
});
