/**
 * 统一错误处理工具
 */

/**
 * 从未知错误对象中提取错误消息
 */
export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  if (typeof error === 'string') {
    return error;
  }

  if (error && typeof error === 'object') {
    if ('message' in error && typeof error.message === 'string') {
      return error.message;
    }
    if ('detail' in error && typeof error.detail === 'string') {
      return error.detail;
    }
  }

  return '发生未知错误，请稍后重试';
}

/**
 * 判断是否为网络错误
 */
export function isNetworkError(error: unknown): boolean {
  if (error instanceof Error) {
    return (
      error.message.includes('Network') ||
      error.message.includes('Failed to fetch') ||
      error.message.includes('网络')
    );
  }
  return false;
}
