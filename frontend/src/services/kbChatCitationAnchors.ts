const STABLE_CITATION_ID_RE = /^S[1-9]\d*$/i;
const UNSAFE_SCOPE_CHAR_RE = /[^A-Za-z0-9_.:-]+/g;
const UNSAFE_CITATION_CHAR_RE = /[^A-Za-z0-9_-]+/g;

function normalizeText(value: string | null | undefined): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const text = value.trim();
  return text || null;
}

export function normalizeCitationId(value: string | null | undefined): string | null {
  const text = normalizeText(value);
  if (!text) {
    return null;
  }
  const stripped = text.replace(/^\[/, '').replace(/\]$/, '').toUpperCase();
  if (!STABLE_CITATION_ID_RE.test(stripped)) {
    return null;
  }
  return stripped;
}

export function normalizeCitationAnchorScopeId(value: string | null | undefined): string | null {
  const text = normalizeText(value);
  if (!text) {
    return null;
  }
  const normalized = text.replace(UNSAFE_SCOPE_CHAR_RE, '-').replace(/^-+|-+$/g, '');
  return normalized || null;
}

function sanitizeCitationId(value: string): string {
  const text = value.trim().toUpperCase();
  if (!text) {
    return 'S';
  }
  const normalized = text.replace(UNSAFE_CITATION_CHAR_RE, '-').replace(/^-+|-+$/g, '');
  return normalized || 'S';
}

export function buildCitationAnchorId(citationId: string, scopeId?: string | null): string {
  const normalizedCitationId = normalizeCitationId(citationId) ?? sanitizeCitationId(citationId);
  const normalizedScopeId = normalizeCitationAnchorScopeId(scopeId);
  if (normalizedScopeId) {
    return `cite-${normalizedScopeId}-${normalizedCitationId}`;
  }
  return `cite-${normalizedCitationId}`;
}
