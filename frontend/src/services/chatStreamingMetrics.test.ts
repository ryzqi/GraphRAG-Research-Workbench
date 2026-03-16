import { describe, expect, it } from 'vitest';

import { createChatStreamMetricsCollector } from './chatStreamingMetrics';

describe('chatStreamingMetrics', () => {
  it('treats heartbeat as a known event and tracks heartbeat/idle gaps', () => {
    let now = 0;
    const metrics = createChatStreamMetricsCollector({
      now: () => now,
      idleThresholdMs: 10,
    });

    metrics.onEvent('meta');
    now = 5;
    metrics.onEvent('heartbeat');
    now = 17;
    metrics.onEvent('heartbeat');
    now = 20;
    metrics.onEvent('final');

    expect(metrics.finalize()).toMatchObject({
      unknown_events: 0,
      heartbeat_events: 2,
      heartbeat_gap_ms_p95: 12,
      max_idle_gap_ms: 12,
      idle_warning_count: 1,
    });
  });
});
