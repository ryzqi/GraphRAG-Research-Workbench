import { describe, expect, it } from 'vitest';
import { getErrorMessage, isNetworkError } from './errorHandler';

describe('errorHandler', () => {
  it('getErrorMessage: 支持 Error / string / message 对象', () => {
    expect(getErrorMessage(new Error('boom'))).toBe('boom');
    expect(getErrorMessage('plain')).toBe('plain');
    expect(getErrorMessage({ message: 'obj' })).toBe('obj');
  });

  it('isNetworkError: 能识别常见网络错误文案', () => {
    expect(isNetworkError(new Error('Failed to fetch'))).toBe(true);
    expect(isNetworkError(new Error('NetworkError when attempting to fetch resource.'))).toBe(true);
    expect(isNetworkError(new Error('其他错误'))).toBe(false);
  });
});
