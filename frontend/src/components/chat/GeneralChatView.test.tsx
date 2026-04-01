import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';

vi.mock('next/dynamic', () => ({
  default: () =>
    function MockMessageList(props: {
      showEvidence?: boolean;
      showSourceChips?: boolean;
      normalizeInlineEvidenceSection?: boolean;
    }) {
      return createElement('mock-message-list', {
        'data-show-evidence': String(props.showEvidence),
        'data-show-source-chips': String(props.showSourceChips),
        'data-normalize-inline-evidence-section': String(props.normalizeInlineEvidenceSection),
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
  ChatInputDock: ({ children }: { children: ReactNode }) => createElement('div', null, children),
}));

vi.mock('./ChatViewport', () => ({
  ChatViewport: ({
    header,
    renderMessages,
    renderComposer,
  }: {
    header: ReactNode;
    renderMessages: (args: { bottomInset: number }) => ReactNode;
    renderComposer: (args: { composerRef: { current: null } }) => ReactNode;
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
        webSearch: {
          configured: true,
          verified: true,
          mode: 'healthy',
          providers: [
            {
              name: 'tavily',
              configured: true,
              verified: true,
              healthy: true,
              mode: 'healthy',
              latency_ms: 320,
              error: null,
            },
          ],
        },
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
    expect(html).toContain('data-show-source-chips="true"');
    expect(html).toContain('data-normalize-inline-evidence-section="true"');
  });

  it('renders only the MCP switch label and overall web status in header', () => {
    const html = renderToStaticMarkup(
      createElement(GeneralChatView, {
        session: null,
        messages: [],
        input: '',
        loading: false,
        error: null,
        allowExternal: true,
        webSearch: {
          configured: true,
          verified: true,
          mode: 'healthy',
          providers: [
            {
              name: 'tavily',
              configured: true,
              verified: true,
              healthy: true,
              mode: 'healthy',
              latency_ms: 320,
              error: null,
            },
            {
              name: 'searxng',
              configured: true,
              verified: true,
              healthy: true,
              mode: 'healthy',
              latency_ms: 280,
              error: null,
            },
          ],
        },
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

    expect(html).toContain('MCP 扩展');
    expect(html).toContain('联网正常');
    expect(html).not.toContain('Tavily 正常');
    expect(html).not.toContain('SearXNG 正常');
    expect(html).not.toContain('Jina Reader 正常');
    expect(html).not.toContain('MCP 将启用');
    expect(html).not.toContain('MCP 已启用');
    expect(html).not.toContain('MCP 未启用');
    expect(html).not.toContain('MCP 已关闭');
  });
});
