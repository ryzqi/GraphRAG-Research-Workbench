/**
 * URL 验证工具。
 */

// 允许的下载域名白名单
const ALLOWED_DOWNLOAD_DOMAINS = new Set([
  'localhost',
  '127.0.0.1',
  // 添加其他允许的域名
]);

/**
 * 验证 URL 是否来自允许的域名。
 */
export function isAllowedDownloadUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    // 允许相对路径
    if (!parsed.hostname) return true;
    // 检查域名白名单
    return ALLOWED_DOWNLOAD_DOMAINS.has(parsed.hostname);
  } catch {
    return false;
  }
}

/**
 * 安全地触发浏览器下载。
 */
export function safeDownloadUrl(url: string): boolean {
  if (!isAllowedDownloadUrl(url)) {
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
