import type { EvidenceItem } from './chats';

export interface GeneralChatSource {
  key: string;
  index: number;
  domain: string;
  title: string;
  url: string;
  provider: string | null;
}

function normalizeText(value: unknown): string | null {
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
  return typeof value === 'string' ? value.trim() || null : null;
}

function resolveSourceUrl(item: EvidenceItem): string | null {
  const candidates = [
    normalizeText(item.citation_source),
    getLocatorString(item.locator, 'url'),
    getLocatorString(item.locator, 'source'),
  ];
  return candidates.find((value) => isHttpUrl(value)) ?? null;
}

function resolveDomain(item: EvidenceItem, url: string): string {
  const locatorDomain = getLocatorString(item.locator, 'domain');
  if (locatorDomain) {
    return locatorDomain;
  }
  try {
    return new URL(url).hostname || url;
  } catch {
    return url;
  }
}

function resolveTitle(item: EvidenceItem, fallback: string): string {
  return (
    normalizeText(item.citation_title) ??
    getLocatorString(item.locator, 'material_title') ??
    fallback
  );
}

export function resolveGeneralChatSources(evidence: EvidenceItem[]): GeneralChatSource[] {
  const deduped = new Map<string, GeneralChatSource>();

  for (const item of evidence) {
    const url = resolveSourceUrl(item);
    if (!url) {
      continue;
    }
    if (deduped.has(url)) {
      continue;
    }
    const domain = resolveDomain(item, url);
    deduped.set(url, {
      key: url,
      index: deduped.size + 1,
      domain,
      title: resolveTitle(item, domain),
      url,
      provider: getLocatorString(item.locator, 'provider'),
    });
  }

  return Array.from(deduped.values());
}
