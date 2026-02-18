import {
  applyDelta,
  parseDelta,
  type MessageState,
  type StreamDelta,
} from '../lib/deltaParser';

function asRecord(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    return null;
  }
  return value as Record<string, unknown>;
}

export function extractDeltasFromMessagesEvent(data: Record<string, unknown>): StreamDelta[] {
  const deltas = data.deltas;
  if (!Array.isArray(deltas)) {
    return [];
  }

  const parsed: StreamDelta[] = [];
  for (const item of deltas) {
    const record = asRecord(item);
    if (!record) {
      continue;
    }
    const delta = parseDelta(record);
    if (delta) {
      parsed.push(delta);
    }
  }
  return parsed;
}

export function applyMessagesEventToState(
  state: MessageState,
  data: Record<string, unknown>
): MessageState {
  let nextState = state;
  const deltas = extractDeltasFromMessagesEvent(data);
  for (const delta of deltas) {
    nextState = applyDelta(nextState, delta);
  }
  return nextState;
}

export function createMessageStateBatcher(onFlush: (nextState: MessageState) => void) {
  let pendingState: MessageState | null = null;
  let rafId: number | null = null;

  const flush = () => {
    if (rafId !== null && typeof window !== 'undefined') {
      window.cancelAnimationFrame(rafId);
      rafId = null;
    }
    if (!pendingState) {
      return;
    }
    const snapshot = pendingState;
    pendingState = null;
    onFlush(snapshot);
  };

  const push = (nextState: MessageState) => {
    pendingState = nextState;
    if (typeof window === 'undefined') {
      flush();
      return;
    }
    if (rafId !== null) {
      return;
    }

    rafId = window.requestAnimationFrame(() => {
      rafId = null;
      if (!pendingState) {
        return;
      }
      const snapshot = pendingState;
      pendingState = null;
      onFlush(snapshot);
    });
  };

  return { push, flush };
}
