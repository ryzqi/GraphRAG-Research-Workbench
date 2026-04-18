import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

import { describe, expect, it } from 'vitest';

function readRelativeSource(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8');
}

describe('react performance guards', () => {
  it('does not memoize simple streaming booleans in MessageList', () => {
    const source = readRelativeSource('../components/chat/MessageList.tsx');

    expect(source).not.toContain(
      "const hasStreaming = useMemo(() => messages.some((msg) => msg.isStreaming), [messages]);"
    );
    expect(source).not.toContain('const hasStreamingContent = useMemo(');
  });

  it('does not memoize the fallback materials array in KnowledgeBaseDetailPage', () => {
    const source = readRelativeSource('../views/KnowledgeBaseDetailPage.tsx');

    expect(source).not.toContain('const materials = useMemo(');
    expect(source).toContain('const materials = materialsQuery.data ?? [];');
  });
});
