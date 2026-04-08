import { apiFetch } from './http';
import type { QueueHealthSnapshot } from './queueHealthDiagnostics';

export async function getQueueHealth(): Promise<QueueHealthSnapshot> {
  return apiFetch<QueueHealthSnapshot>('/api/v1/system/queue-health');
}
