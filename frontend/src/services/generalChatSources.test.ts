import { describe, expect, it } from 'vitest';

import { resolveGeneralChatSources } from './generalChatSources';

describe('resolveGeneralChatSources', () => {
  it('deduplicates external evidence and preserves compact source metadata', () => {
    const sources = resolveGeneralChatSources([
      {
        source_kind: 'external',
        kb_id: null,
        material_id: null,
        chunk_id: null,
        locator: {
          url: 'https://docs.langchain.com/oss/python/langchain-mcp',
          source: 'https://docs.langchain.com/oss/python/langchain-mcp',
          domain: 'docs.langchain.com',
          provider: 'tavily',
        },
        excerpt: 'LangChain MCP 文档',
        citation_title: 'MCP - Docs by LangChain',
        citation_source: 'https://docs.langchain.com/oss/python/langchain-mcp',
      },
      {
        source_kind: 'external',
        kb_id: null,
        material_id: null,
        chunk_id: null,
        locator: {
          url: 'https://docs.langchain.com/oss/python/langchain-mcp',
          source: 'https://docs.langchain.com/oss/python/langchain-mcp',
          domain: 'docs.langchain.com',
          provider: 'searxng',
        },
        excerpt: '重复来源',
        citation_title: 'MCP - Docs by LangChain',
        citation_source: 'https://docs.langchain.com/oss/python/langchain-mcp',
      },
    ]);

    expect(sources).toEqual([
      {
        key: 'https://docs.langchain.com/oss/python/langchain-mcp',
        index: 1,
        domain: 'docs.langchain.com',
        title: 'MCP - Docs by LangChain',
        url: 'https://docs.langchain.com/oss/python/langchain-mcp',
        provider: 'tavily',
      },
    ]);
  });
});
