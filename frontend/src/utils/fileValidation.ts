/**
 * 文件上传验证工具。
 */

// 文件大小限制 (100MB)
export const MAX_FILE_SIZE = 100 * 1024 * 1024;

// 允许的文件扩展名
export const ALLOWED_EXTENSIONS = new Set(['.pdf', '.txt', '.md', '.docx']);

// 允许的 MIME 类型
export const ALLOWED_MIME_TYPES = new Set([
  'application/pdf',
  'text/plain',
  'text/markdown',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
]);

export interface FileValidationResult {
  valid: boolean;
  error?: string;
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
  if (file.type && !ALLOWED_MIME_TYPES.has(file.type)) {
    return {
      valid: false,
      error: `不支持的 MIME 类型: ${file.type}`,
    };
  }

  return { valid: true };
}
