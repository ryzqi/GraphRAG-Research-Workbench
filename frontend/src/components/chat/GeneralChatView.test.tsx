import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/dynamic', () => ({
  default: () =>
    function MockMessageList(props: { showEvidence?: boolean }) {
      return createElement('mock-message-list', {
        'data-show-evidence': String(props.showEvidence),
      });
    },
}));

vi.mock('../ui/ErrorAlert', () => ({
  ErrorAlert: () => null,
}));

vi.mock('./WelcomeScreen', () => ({
  WelcomeScreen: () => null,
}));

vi.mock('./InputComposer', () => ({
  InputComposer: () => null,
}));

vi.mock('./ChatInputDock', () => ({
  ChatInputDock: ({ children }: { children: unknown }) => createElement('div', null, children),
}));

vi.mock('./ChatViewport', () => ({
  ChatViewport: ({
    header,
    renderMessages,
    renderComposer,
  }: {
    header: unknown;
    renderMessages: (args: { bottomInset: number }) => unknown;
    renderComposer: (args: { composerRef: { current: null } }) => unknown;
  }) =>
    createElement(
      'div',
      null,
      header,
      renderMessages({ bottomInset: 180 }),
      renderComposer({ composerRef: { current: null } })
    ),
}));

import { GeneralChatView } from './GeneralChatView';

describe('GeneralChatView', () => {
  it('disables evidence cards for general chat message list', () => {
    const html = renderToStaticMarkup(
      createElement(GeneralChatView, {
        session: null,
        messages: [
          {
            id: 'assistant-1',
            role: 'assistant',
            content: '结论正文',
            evidence: [
              {
                source_kind: 'external',
                kb_id: null,
                material_id: null,
                chunk_id: null,
                locator: { url: 'https://example.com/a' },
                excerpt: '不应显示的摘要',
              },
            ],
          },
        ],
        input: '',
        loading: false,
        error: null,
        allowExternal: true,
        webSearch: { configured: true, verified: true, healthy: true },
        hasPendingApproval: false,
        isInputDisabled: false,
        setAllowExternal: () => undefined,
        setInput: () => undefined,
        setError: () => undefined,
        onSend: async () => undefined,
        onToolApprovalSubmit: async () => undefined,
        onSuggestionClick: () => undefined,
      })
    );

    expect(html).toContain('data-show-evidence="false"');
  });
});
