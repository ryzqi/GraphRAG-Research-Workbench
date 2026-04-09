import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const researchPagePath = path.resolve(process.cwd(), 'src/views/ResearchPage.tsx');

describe('ResearchPage initial surface styling', () => {
  it('does not apply a dedicated landing gradient when there is no active research session', () => {
    const source = fs.readFileSync(researchPagePath, 'utf8');

    expect(source).toContain("background: !sessionId ? 'transparent'");
    expect(source).not.toContain("linear-gradient(180deg, #fbfbfa 0%, #f6f6f3 100%)");
  });
});
