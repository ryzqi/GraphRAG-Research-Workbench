import { describe, expect, it, vi, beforeEach } from 'vitest';

import { getRecentChats } from './chats';
import { apiFetch } from './http';

vi.mock('./http', () => ({
  apiFetch: vi.fn(),
}));

describe('getRecentChats', () => {
  const apiFetchMock = vi.mocked(apiFetch);

  beforeEach(() => {
    apiFetchMock.mockReset();
    apiFetchMock.mockResolvedValue({
      items: [],
      web_search_available: true,
    });
  });

  it('disables cache so server-prefetched recent chats do not replay stale sessions after restart', async () => {
    await getRecentChats(20);

    expect(apiFetchMock).toHaveBeenCalledWith('/api/v1/chats/recent?limit=20', {
      cache: 'no-store',
    });
  });
});
