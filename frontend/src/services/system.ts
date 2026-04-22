import { apiFetch, apiV1Path } from './http';
import type { QueueHealthSnapshot } from './queueHealthDiagnostics';

export async function getQueueHealth(): Promise<QueueHealthSnapshot> {
  return apiFetch<QueueHealthSnapshot>(apiV1Path('/system/queue-health'));
}
