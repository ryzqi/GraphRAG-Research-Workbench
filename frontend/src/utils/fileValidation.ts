import type { PublicRuntimeConfigRead } from '../services/runtimeConfig';

type UploadPolicyConfig = Pick<
  PublicRuntimeConfigRead,
  | 'upload_max_file_size_bytes'
  | 'upload_allowed_extensions'
  | 'upload_allowed_mime_types'
  | 'upload_mime_type_aliases'
  | 'upload_generic_mime_types'
>;

export interface FileValidationResult {
  valid: boolean;
  error?: string;
}

function normalizeMimeType(rawMimeType: string): string {
  return rawMimeType.split(';', 1)[0]?.trim().toLowerCase() ?? '';
}

function fileExtOf(fileName: string): string {
  return fileName.includes('.') ? '.' + fileName.split('.').pop()?.toLowerCase() : '';
}

function normalizeStringList(values: readonly string[] | undefined): string[] {
  if (!values) {
    return [];
  }
  return Array.from(
    new Set(
      values
        .map((value) => value.trim().toLowerCase())
        .filter(Boolean)
    )
  );
}

export function getAcceptedFileTypes(config?: UploadPolicyConfig | null): string {
  return normalizeStringList(config?.upload_allowed_extensions).join(',');
}

export function getSupportedFileTypesLabel(config?: UploadPolicyConfig | null): string {
  const extensions = normalizeStringList(config?.upload_allowed_extensions);
  if (extensions.length === 0) {
    return '运行时配置加载中';
  }
  return extensions
    .map((ext) => ext.replace('.', '').toUpperCase())
    .join(', ');
}

export function validateFile(
  file: File,
  config?: UploadPolicyConfig | null
): FileValidationResult {
  if (!config) {
    return {
      valid: false,
      error: '上传策略尚未加载完成，请稍后重试',
    };
  }

  const maxFileSize = config?.upload_max_file_size_bytes;
  if (typeof maxFileSize === 'number' && Number.isFinite(maxFileSize) && maxFileSize > 0) {
    if (file.size > maxFileSize) {
      return {
        valid: false,
        error: `文件大小超过限制 (${maxFileSize / 1024 / 1024}MB)`,
      };
    }
  }

  const allowedExtensions = new Set(normalizeStringList(config?.upload_allowed_extensions));
  const ext = fileExtOf(file.name);
  if (allowedExtensions.size > 0 && !allowedExtensions.has(ext)) {
    return {
      valid: false,
      error: `不支持的文件类型: ${ext || '无扩展名'}`,
    };
  }

  if (file.type) {
    const normalizedMimeType = normalizeMimeType(file.type);
    const mimeAliases = Object.fromEntries(
      Object.entries(config?.upload_mime_type_aliases ?? {}).map(([key, value]) => [
        key.trim().toLowerCase(),
        value.trim().toLowerCase(),
      ])
    );
    const canonicalMimeType = mimeAliases[normalizedMimeType] ?? normalizedMimeType;
    const allowedMimeTypes = new Set(normalizeStringList(config?.upload_allowed_mime_types));
    const genericMimeTypes = new Set(normalizeStringList(config?.upload_generic_mime_types));

    if (
      canonicalMimeType &&
      allowedMimeTypes.size > 0 &&
      !genericMimeTypes.has(canonicalMimeType) &&
      !allowedMimeTypes.has(canonicalMimeType)
    ) {
      return {
        valid: false,
        error: `不支持的 MIME 类型: ${file.type}`,
      };
    }
  }

  return { valid: true };
}
