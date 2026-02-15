export interface ChatStreamMetricsSnapshot {
  started_at: string;
  finished_at: string;
  duration_ms: number;
  first_token_latency_ms: number | null;
  total_events: number;
  unknown_events: number;
  error_events: number;
  event_loss_rate: number;
  error_rate: number;
}

const KNOWN_EVENTS = new Set([
  'meta',
  'messages',
  'updates',
  'custom',
  'delta',
  'step',
  'state',
  'ui_event',
  'node_io',
  'node_trace',
  'tool_trace',
  'interrupt',
  'final',
  'error',
]);

export function createChatStreamMetricsCollector() {
  const startedAt = Date.now();
  const startedAtIso = new Date(startedAt).toISOString();
  let firstTokenLatencyMs: number | null = null;
  let totalEvents = 0;
  let unknownEvents = 0;
  let errorEvents = 0;

  const onEvent = (eventName: string) => {
    totalEvents += 1;
    if (!KNOWN_EVENTS.has(eventName)) {
      unknownEvents += 1;
    }
    if ((eventName === 'messages' || eventName === 'delta') && firstTokenLatencyMs === null) {
      firstTokenLatencyMs = Date.now() - startedAt;
    }
    if (eventName === 'error') {
      errorEvents += 1;
    }
  };

  const onFailure = () => {
    errorEvents += 1;
  };

  const finalize = (): ChatStreamMetricsSnapshot => {
    const finishedAt = Date.now();
    const durationMs = Math.max(0, finishedAt - startedAt);
    const eventLossRate = totalEvents > 0 ? unknownEvents / totalEvents : 0;
    const errorRate = totalEvents > 0 ? errorEvents / totalEvents : 0;
    return {
      started_at: startedAtIso,
      finished_at: new Date(finishedAt).toISOString(),
      duration_ms: durationMs,
      first_token_latency_ms: firstTokenLatencyMs,
      total_events: totalEvents,
      unknown_events: unknownEvents,
      error_events: errorEvents,
      event_loss_rate: Number(eventLossRate.toFixed(4)),
      error_rate: Number(errorRate.toFixed(4)),
    };
  };

  return {
    onEvent,
    onFailure,
    finalize,
  };
}
