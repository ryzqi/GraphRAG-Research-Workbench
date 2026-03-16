import { describe, expect, it } from 'vitest';

import { createSseParser } from './sse';

describe('sse parser', () => {
  it('ignores comment heartbeats and parses explicit heartbeat events', () => {
    const parser = createSseParser();

    const events = parser.feed(
      ': keep-alive\n\n' +
        'event: heartbeat\n' +
        'data: {"type":"heartbeat","ts":"2026-03-13T00:00:00Z"}\n\n'
    );

    expect(events).toEqual([
      {
        event: 'heartbeat',
        data: '{"type":"heartbeat","ts":"2026-03-13T00:00:00Z"}',
      },
    ]);
  });
});
