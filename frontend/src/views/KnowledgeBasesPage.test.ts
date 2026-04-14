import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const knowledgeBasesPagePath = path.resolve(process.cwd(), 'src/views/KnowledgeBasesPage.tsx');

describe('KnowledgeBasesPage knowledge base cards', () => {
  it('shows long knowledge base names with a two-line clamp instead of single-line truncation', () => {
    const source = fs.readFileSync(knowledgeBasesPagePath, 'utf8');

    expect(source).toContain("WebkitLineClamp: 2");
    expect(source).toContain("display: '-webkit-box'");
    expect(source).toContain("overflow: 'hidden'");
    expect(source).not.toContain("<Typography variant='h6' fontWeight={600} noWrap>");
  });
});
