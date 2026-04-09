import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const researchPagePath = path.resolve(process.cwd(), 'src/views/ResearchPage.tsx');

describe('ResearchPage initial surface styling', () => {
  it('does not use the old workbench gradients for either the landing or active research surfaces', () => {
    const source = fs.readFileSync(researchPagePath, 'utf8');

    expect(source).toContain("background: 'transparent'");
    expect(source).toContain("minHeight: '100%'");
    expect(source).not.toContain("linear-gradient(180deg, #fbfbfa 0%, #f6f6f3 100%)");
    expect(source).not.toContain("linear-gradient(180deg, #f8fbff 0%, #f4f7fb 42%, #eef3f9 100%)");
  });
});
