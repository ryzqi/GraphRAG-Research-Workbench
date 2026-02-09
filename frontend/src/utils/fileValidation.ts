/**
 * 文件上传验证工具。
 */

// 文件大小限制 (50MB)
export const MAX_FILE_SIZE = 50 * 1024 * 1024;

// 允许的文件扩展名
export const ALLOWED_EXTENSIONS = new Set(['.pdf', '.txt', '.md', '.docx']);

// 与 <input accept> 保持一致的字符串表示（中心化，避免多处维护）。
export const ACCEPTED_FILE_TYPES = Array.from(ALLOWED_EXTENSIONS).join(',');

// UI 展示用（例如：PDF, TXT, MD, DOCX）
export const SUPPORTED_FILE_TYPES_LABEL = Array.from(ALLOWED_EXTENSIONS)
  .map((ext) => ext.replace('.', '').toUpperCase())
  .join(', ');

// 允许的 MIME 类型（规范化后）
export const ALLOWED_MIME_TYPES = new Set([
  'application/pdf',
  'text/plain',
  'text/markdown',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]);

// MIME 类型别名归一化
const MIME_TYPE_ALIASES = new Map([
  ['text/x-markdown', 'text/markdown'],
  ['application/x-pdf', 'application/pdf'],
]);

// 浏览器无法识别文件类型时的通用 MIME，后端会结合扩展名再次校验
const GENERIC_MIME_TYPES = new Set(['application/octet-stream', 'binary/octet-stream']);

export interface FileValidationResult {
  valid: boolean;
  error?: string;
}

function normalizeMimeType(rawMimeType: string): string {
  return rawMimeType.split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

/**
 * 验证上传文件的大小和类型。
 */
export function validateFile(file: File): FileValidationResult {
  // 检查文件大小
  if (file.size > MAX_FILE_SIZE) {
    return {
      valid: false,
      error: `文件大小超过限制 (${MAX_FILE_SIZE / 1024 / 1024}MB)`,
    };
  }

  // 检查文件扩展名
  const ext = file.name.includes('.') ? '.' + file.name.split('.').pop()?.toLowerCase() : '';
  if (!ALLOWED_EXTENSIONS.has(ext)) {
    return {
      valid: false,
      error: `不支持的文件类型: ${ext || '无扩展名'}`,
    };
  }

  // 检查 MIME 类型
  if (file.type) {
    const normalizedMimeType = normalizeMimeType(file.type);
    const canonicalMimeType = MIME_TYPE_ALIASES.get(normalizedMimeType) ?? normalizedMimeType;

    if (
      canonicalMimeType &&
      !GENERIC_MIME_TYPES.has(canonicalMimeType) &&
      !ALLOWED_MIME_TYPES.has(canonicalMimeType)
    ) {
      return {
        valid: false,
        error: `不支持的 MIME 类型: ${file.type}`,
      };
    }
  }

  return { valid: true };
}
