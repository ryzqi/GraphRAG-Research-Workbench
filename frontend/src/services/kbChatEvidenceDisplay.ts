import type { EvidenceItem } from './chats';
import { normalizeCitationId } from './kbChatCitationAnchors';

export interface EvidenceCardItem {
  key: string;
  citationId: string;
  citationChipLabel: string;
  sourceKind: EvidenceItem['source_kind'];
  sourceTypeLabel: string;
  sourceTitle: string;
  sourceDetail: string | null;
  pageHint: string | null;
  excerpt: string;
}

function normalizeText(value: string | null | undefined): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const text = value.trim();
  return text || null;
}

function isHttpUrl(value: string | null | undefined): value is string {
  return typeof value === 'string' && /^https?:\/\//i.test(value.trim());
}

function getLocatorString(
  locator: Record<string, unknown> | null | undefined,
  key: string
): string | null {
  const value = locator?.[key];
  return typeof value === 'string' ? value : null;
}

function stripExtension(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) {
    return '';
  }
  const normalized = trimmed.replace(/\\/g, '/');
  const base = normalized.split('/').pop() ?? normalized;
  const dotIndex = base.lastIndexOf('.');
  if (dotIndex <= 0) {
    return base;
  }
  return base.slice(0, dotIndex);
}

function getFallbackDocumentLabel(item: EvidenceItem, index: number): string {
  const citationLabel = getLocatorString(item.locator, 'citation_label');
  if (citationLabel && citationLabel.trim()) {
    return citationLabel.trim();
  }

  const filename = getLocatorString(item.locator, 'filename');
  if (filename && filename.trim()) {
    const stem = stripExtension(filename);
    if (stem.trim()) {
      return stem.trim();
    }
  }

  return `资料${index + 1}`;
}

function getCitationId(item: EvidenceItem, index: number): string {
  const explicit = normalizeCitationId(item.citation_id);
  if (explicit) {
    return explicit;
  }
  return `S${index + 1}`;
}

function getPageHint(item: EvidenceItem): string | null {
  const explicit = normalizeText(item.citation_page_hint);
  if (explicit) {
    return explicit;
  }

  const locator = item.locator;
  if (!locator || typeof locator !== 'object') {
    return null;
  }

  const pageStart = locator.page_start;
  const pageEnd = locator.page_end;
  if (typeof pageStart === 'number' && pageStart > 0) {
    if (typeof pageEnd === 'number' && pageEnd > 0 && pageEnd !== pageStart) {
      return `p.${pageStart}-${pageEnd}`;
    }
    return `p.${pageStart}`;
  }
  if (typeof pageEnd === 'number' && pageEnd > 0) {
    return `p.${pageEnd}`;
  }
  return null;
}

function getSourceTitle(item: EvidenceItem, index: number): string {
  const citationTitle = normalizeText(item.citation_title);
  if (citationTitle) {
    return citationTitle;
  }

  const locatorMaterialTitle = normalizeText(getLocatorString(item.locator, 'material_title'));
  if (locatorMaterialTitle) {
    return locatorMaterialTitle;
  }

  return getFallbackDocumentLabel(item, index);
}

function isDuplicateSourceDetail(title: string, detail: string): boolean {
  const normalizedTitle = title.trim().toLowerCase();
  const normalizedDetail = detail.trim().replace(/\\/g, '/').toLowerCase();
  const detailBase = normalizedDetail.split('/').pop() ?? normalizedDetail;
  const detailStem = stripExtension(detailBase).toLowerCase();

  return (
    normalizedTitle === normalizedDetail ||
    normalizedTitle === detailBase ||
    normalizedTitle === detailStem
  );
}

function getSourceDetail(item: EvidenceItem, sourceTitle: string): string | null {
  const explicit = normalizeText(item.citation_source);
  const locatorFilename = normalizeText(getLocatorString(item.locator, 'filename'));
  const locatorSource = normalizeText(getLocatorString(item.locator, 'source'));
  const locatorUrl = normalizeText(getLocatorString(item.locator, 'url'));
  const urlLikeDetail =
    item.source_kind === 'external'
      ? [explicit, locatorUrl, locatorSource, locatorFilename].find((value) => isHttpUrl(value)) ?? null
      : null;
  const detail =
    item.source_kind === 'external'
      ? urlLikeDetail ?? explicit ?? locatorFilename ?? locatorSource ?? locatorUrl
      : explicit ?? locatorFilename ?? locatorSource;
  if (!detail || isDuplicateSourceDetail(sourceTitle, detail)) {
    return null;
  }
  return detail;
}

function getEvidenceKey(item: EvidenceItem, citationId: string, index: number): string {
  if (citationId) {
    return `citation-${citationId}`;
  }

  const chunkId = getLocatorString(item.locator, 'chunk_id');
  if (chunkId) {
    return `chunk-${chunkId}`;
  }

  if (item.kb_id && item.material_id) {
    return `kb-${item.kb_id}-mat-${item.material_id}-${index}`;
  }

  const excerptHash = item.excerpt.slice(0, 50).replace(/\s+/g, '-');
  return `${item.source_kind}-${excerptHash}-${index}`;
}

export function resolveEvidenceCardItems(evidence: EvidenceItem[]): EvidenceCardItem[] {
  return evidence.map((item, index) => {
    const citationId = getCitationId(item, index);
    const sourceTitle = getSourceTitle(item, index);
    const sourceExcerpt = normalizeText(item.source_excerpt);
    const excerpt = sourceExcerpt ?? item.excerpt.trim();

    return {
      key: getEvidenceKey(item, citationId, index),
      citationId,
      citationChipLabel: `[${citationId}]`,
      sourceKind: item.source_kind,
      sourceTypeLabel: item.source_kind === 'kb' ? '知识库文档' : '外部来源',
      sourceTitle,
      sourceDetail: getSourceDetail(item, sourceTitle),
      pageHint: getPageHint(item),
      excerpt,
    };
  });
}
