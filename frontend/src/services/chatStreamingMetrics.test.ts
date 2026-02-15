import { describe, expect, it } from 'vitest';

import { createChatStreamMetricsCollector } from './chatStreamingMetrics';

describe('createChatStreamMetricsCollector', () => {
  it('calculates first token latency and rates', () => {
    const collector = createChatStreamMetricsCollector();
    collector.onEvent('meta');
    collector.onEvent('messages');
    collector.onEvent('unknown');
    collector.onEvent('error');

    const snapshot = collector.finalize();

    expect(snapshot.total_events).toBe(4);
    expect(snapshot.first_token_latency_ms).not.toBeNull();
    expect(snapshot.event_loss_rate).toBe(0.25);
    expect(snapshot.error_rate).toBe(0.25);
  });
});
