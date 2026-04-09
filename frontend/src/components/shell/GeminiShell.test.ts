import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const geminiShellPath = path.resolve(process.cwd(), 'src/components/shell/GeminiShell.tsx');

describe('GeminiShell fluid content rules', () => {
  it('treats /research as a fluid content page so the content area can use the full main width', () => {
    const source = fs.readFileSync(geminiShellPath, 'utf8');

    expect(source).toMatch(/isResearchPage/);
    expect(source).toMatch(/pathname === '\/research'/);
    expect(source).toMatch(/useFluidContent = isChatPage \|\| isKnowledgeWorkspacePage \|\| isResearchPage/);
  });
});
