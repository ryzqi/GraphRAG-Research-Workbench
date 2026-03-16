export interface ChatStreamMetricsSnapshot {
  started_at: string;
  finished_at: string;
  duration_ms: number;
  first_token_latency_ms: number | null;
  total_events: number;
  unknown_events: number;
  error_events: number;
  heartbeat_events: number;
  heartbeat_gap_ms_p95: number;
  max_idle_gap_ms: number;
  idle_warning_count: number;
  event_loss_rate: number;
  error_rate: number;
}

interface ChatStreamMetricsCollectorOptions {
  now?: () => number;
  idleThresholdMs?: number;
}

const KNOWN_EVENTS = new Set([
  'meta',
  'messages',
  'updates',
  'custom',
  'step',
  'state',
  'ui_event',
  'node_io',
  'node_trace',
  'tool_trace',
  'stream_end',
  'interrupt',
  'final',
  'error',
  'heartbeat',
]);

function calcPercentile(values: number[], percentile: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((left, right) => left - right);
  const rawIndex = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil(percentile * sorted.length) - 1)
  );
  return sorted[rawIndex] ?? 0;
}

export function createChatStreamMetricsCollector(
  options: ChatStreamMetricsCollectorOptions = {}
) {
  const now = options.now ?? (() => Date.now());
  const idleThresholdMs = Math.max(1, options.idleThresholdMs ?? 15000);
  const startedAt = now();
  const startedAtIso = new Date(startedAt).toISOString();
  let firstTokenLatencyMs: number | null = null;
  let totalEvents = 0;
  let unknownEvents = 0;
  let errorEvents = 0;
  let heartbeatEvents = 0;
  let idleWarningCount = 0;
  let maxIdleGapMs = 0;
  let lastEventAt = startedAt;
  let lastHeartbeatAt: number | null = null;
  const heartbeatGapsMs: number[] = [];

  const onEvent = (eventName: string) => {
    const observedAt = now();
    totalEvents += 1;
    if (!KNOWN_EVENTS.has(eventName)) {
      unknownEvents += 1;
    }
    if (eventName === 'messages' && firstTokenLatencyMs === null) {
      firstTokenLatencyMs = observedAt - startedAt;
    }
    if (eventName === 'error') {
      errorEvents += 1;
    }
    const idleGapMs = Math.max(0, observedAt - lastEventAt);
    maxIdleGapMs = Math.max(maxIdleGapMs, idleGapMs);
    if (idleGapMs > idleThresholdMs) {
      idleWarningCount += 1;
    }
    lastEventAt = observedAt;
    if (eventName === 'heartbeat') {
      heartbeatEvents += 1;
      if (lastHeartbeatAt !== null) {
        heartbeatGapsMs.push(Math.max(0, observedAt - lastHeartbeatAt));
      }
      lastHeartbeatAt = observedAt;
    }
  };

  const onFailure = () => {
    errorEvents += 1;
  };

  const finalize = (): ChatStreamMetricsSnapshot => {
    const finishedAt = now();
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
      heartbeat_events: heartbeatEvents,
      heartbeat_gap_ms_p95: calcPercentile(heartbeatGapsMs, 0.95),
      max_idle_gap_ms: maxIdleGapMs,
      idle_warning_count: idleWarningCount,
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
