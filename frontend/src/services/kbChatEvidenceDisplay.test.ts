import { describe, expect, it } from 'vitest';

import type { EvidenceItem } from './chats';
import { resolveEvidenceCardItems } from './kbChatEvidenceDisplay';

describe('kbChatEvidenceDisplay', () => {
  it('prefers explicit citation metadata and keeps clean source details', () => {
    const evidence: EvidenceItem[] = [
      {
        source_kind: 'kb',
        kb_id: null,
        material_id: null,
        chunk_id: null,
        locator: {
          material_title: '2026 年第一季度经营分析',
          filename: 'reports/q1-analysis.pdf',
          page_start: 3,
          page_end: 4,
        },
        excerpt: '季度收入同比增长 18%。',
        citation_id: 's1',
        citation_title: '经营分析报告（修订版）',
        citation_page_hint: 'p.9',
        citation_source: 'reports/q1-analysis.pdf',
      },
    ];

    expect(resolveEvidenceCardItems(evidence)).toEqual([
      expect.objectContaining({
        citationId: 'S1',
        citationChipLabel: '[S1]',
        sourceTitle: '经营分析报告（修订版）',
        pageHint: 'p.9',
        sourceTypeLabel: '知识库文档',
        sourceDetail: 'reports/q1-analysis.pdf',
        excerpt: '季度收入同比增长 18%。',
      }),
    ]);
  });

  it('falls back to locator material title, page range and synthetic citation ids', () => {
    const evidence: EvidenceItem[] = [
      {
        source_kind: 'external',
        kb_id: null,
        material_id: null,
        chunk_id: null,
        locator: {
          material_title: '外部调研纪要',
          filename: 'notes/market-brief.md',
          page_start: 12,
          page_end: 14,
        },
        excerpt: '竞争对手在华东地区加快渠道扩张。',
      },
    ];

    expect(resolveEvidenceCardItems(evidence)).toEqual([
      expect.objectContaining({
        citationId: 'S1',
        citationChipLabel: '[S1]',
        sourceTitle: '外部调研纪要',
        pageHint: 'p.12-14',
        sourceTypeLabel: '外部来源',
        sourceDetail: 'notes/market-brief.md',
      }),
    ]);
  });

  it('prefers locator citation labels over raw filename stems when both exist', () => {
    const evidence: EvidenceItem[] = [
      {
        source_kind: 'kb',
        kb_id: null,
        material_id: null,
        chunk_id: null,
        locator: {
          citation_label: '渠道周报（人工校对）',
          filename: 'reports/channel-weekly.pdf',
        },
        excerpt: '渠道反馈显示促销转化率提升。',
      },
    ];

    expect(resolveEvidenceCardItems(evidence)).toEqual([
      expect.objectContaining({
        sourceTitle: '渠道周报（人工校对）',
      }),
    ]);
  });
});
