/**
 * URL 验证工具。
 */

import { DEFAULT_DOWNLOAD_ALLOWED_HOSTS } from '../constants/runtimeDefaults';

function isRelativeDownloadUrl(url: string): boolean {
  const candidate = url.trim();
  return /^(\/(?!\/)|\.{1,2}\/)/.test(candidate);
}

function normalizeAllowedHosts(allowedHosts: readonly string[]): Set<string> {
  const source = allowedHosts.length > 0 ? allowedHosts : DEFAULT_DOWNLOAD_ALLOWED_HOSTS;
  return new Set(
    source
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean)
  );
}

/**
 * 验证 URL 是否来自允许的域名。
 */
export function isAllowedDownloadUrl(
  url: string,
  allowedHosts: readonly string[] = DEFAULT_DOWNLOAD_ALLOWED_HOSTS
): boolean {
  if (isRelativeDownloadUrl(url)) {
    return true;
  }

  try {
    const parsed = new URL(url);
    return normalizeAllowedHosts(allowedHosts).has(parsed.hostname.toLowerCase());
  } catch {
    return false;
  }
}

/**
 * 安全地触发浏览器下载。
 */
export function safeDownloadUrl(
  url: string,
  allowedHosts: readonly string[] = DEFAULT_DOWNLOAD_ALLOWED_HOSTS
): boolean {
  if (!isAllowedDownloadUrl(url, allowedHosts)) {
    console.warn('下载链接来自不受信任的域名:', url);
    return false;
  }

  if (typeof document === 'undefined' || !document.body) {
    console.warn('当前环境不支持触发下载:', url);
    return false;
  }

  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.rel = 'noopener noreferrer';
  anchor.style.display = 'none';
  document.body.appendChild(anchor);
  try {
    anchor.click();
  } finally {
    document.body.removeChild(anchor);
  }
  return true;
}
