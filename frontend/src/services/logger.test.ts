import { afterEach, describe, expect, it, vi } from 'vitest';

import { appLogger } from './logger';

describe('appLogger', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it('does not emit info/debug logs in production', () => {
    vi.stubEnv('NODE_ENV', 'production');
    const info = vi.spyOn(console, 'info').mockImplementation(() => {});
    const debug = vi.spyOn(console, 'debug').mockImplementation(() => {});

    appLogger.info('kb-chat-stream-metrics', { attempts: 1 });
    appLogger.debug('debug-only', { cache: 'miss' });

    expect(info).not.toHaveBeenCalled();
    expect(debug).not.toHaveBeenCalled();
  });

  it('still emits warn/error logs in production', () => {
    vi.stubEnv('NODE_ENV', 'production');
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const error = vi.spyOn(console, 'error').mockImplementation(() => {});

    appLogger.warn('warn-path', { code: 'DOWNLOAD_BLOCKED' });
    appLogger.error('error-path', new Error('boom'));

    expect(warn).toHaveBeenCalledWith('warn-path', { code: 'DOWNLOAD_BLOCKED' });
    expect(error).toHaveBeenCalledWith('error-path', expect.any(Error));
  });
});
