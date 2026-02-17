import type { EntryError } from './ingestionBatches';

function readString(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null;
  }
  const normalized = value.trim();
  return normalized.length > 0 ? normalized : null;
}

function readStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => readString(item))
    .filter((item): item is string => item !== null);
}

export function formatIngestionEntryError(error: EntryError): string {
  if (error.code !== 'URL_SSRF_BLOCKED') {
    return error.message;
  }

  const details = error.details ?? undefined;
  if (!details || typeof details !== 'object') {
    return error.message;
  }

  const host = readString((details as Record<string, unknown>).host);
  const blockedIps = readStringArray((details as Record<string, unknown>).blocked_ips);
  const blockedIp = blockedIps[0] ?? readString((details as Record<string, unknown>).blocked_ip);
  const blockedReason =
    readString((details as Record<string, unknown>).blocked_reason) ??
    readStringArray((details as Record<string, unknown>).blocked_reasons)[0] ??
    readString((details as Record<string, unknown>).reason);

  const diagnostics: string[] = [];
  if (host) {
    diagnostics.push('主机 ' + host);
  }
  if (blockedIp) {
    diagnostics.push('命中 IP ' + blockedIp);
  }
  if (blockedReason) {
    diagnostics.push('原因 ' + blockedReason);
  }

  if (diagnostics.length === 0) {
    return error.message;
  }
  return error.message + '（' + diagnostics.join('，') + '）';
}
