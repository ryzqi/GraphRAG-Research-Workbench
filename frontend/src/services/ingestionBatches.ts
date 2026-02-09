/**
 * 统一 ingestion-batch API 封装
 */

import type { SseEvent } from '../lib/sse';
import { apiFetch } from './http';
import { openSseStream } from './sse';

export type ManifestSourceType = 'text' | 'url' | 'file';
export type BatchStatus =
  | 'queued'
  | 'running'
  | 'succeeded'
  | 'partial_failed'
  | 'failed'
  | 'canceled';
export type DocStatus = 'pending' | 'running' | 'succeeded' | 'failed' | 'canceled';

export interface ManifestTextEntry {
  source_type: 'text';
  entry_id?: string;
  title?: string;
  text: string;
}

export interface ManifestUrlEntry {
  source_type: 'url';
  entry_id?: string;
  title?: string;
  url: string;
}

export interface ManifestFileEntry {
  source_type: 'file';
  entry_id?: string;
  title?: string;
  material_id: string;
}

export type ManifestEntry = ManifestTextEntry | ManifestUrlEntry | ManifestFileEntry;

export interface IngestionBatchCreateRequest {
  kb_id: string;
  entries: ManifestEntry[];
}

export interface EntryError {
  entry_id: string;
  source_type: ManifestSourceType;
  code: string;
  message: string;
  retryable: boolean;
  details?: Record<string, unknown> | null;
}

export interface IngestionBatchSubmitResponse {
  batch_id: string;
  kb_id: string;
  status: BatchStatus;
  is_bootstrap: boolean;
  config_snapshot_id: string;
  config_version: number;
  total_docs: number;
  accepted_docs: number;
  failed_docs: number;
  entry_errors: EntryError[];
}

export interface IngestionBatchDoc {
  id: string;
  source_type: ManifestSourceType;
  source_ref: string | null;
  title: string | null;
  fingerprint: string;
  status: DocStatus;
  error_code: string | null;
  error_message: string | null;
  retry_count: number;
  retryable: boolean;
  chunk_count: number;
  config_version: number;
  created_at: string;
  updated_at: string;
}

export interface IngestionBatch {
  id: string;
  kb_id: string;
  config_snapshot_id: string;
  config_version: number;
  is_bootstrap: boolean;
  status: BatchStatus;
  total_docs: number;
  succeeded_docs: number;
  failed_docs: number;
  canceled_docs: number;
  succeeded_chunks: number;
  progress_percent: number;
  error_summary: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  docs: IngestionBatchDoc[];
}

export interface IngestionBatchRetryResponse {
  batch_id: string;
  status: BatchStatus;
  requeued_docs: number;
  ignored_docs: number;
}

export interface IngestionBatchCancelResponse {
  batch_id: string;
  status: BatchStatus;
  canceled_docs: number;
  finished_at: string | null;
}

export async function createIngestionBatch(
  data: IngestionBatchCreateRequest
): Promise<IngestionBatchSubmitResponse> {
  return apiFetch<IngestionBatchSubmitResponse>('/api/v1/ingestion-batches', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getLatestIngestionBatch(kbId: string): Promise<IngestionBatch | null> {
  const query = new URLSearchParams({ kb_id: kbId, prefer_active: 'true' }).toString();
  const payload = await apiFetch<IngestionBatch | null>(`/api/v1/ingestion-batches/latest?${query}`);
  return payload ?? null;
}

export async function getIngestionBatch(batchId: string): Promise<IngestionBatch> {
  return apiFetch<IngestionBatch>('/api/v1/ingestion-batches/' + batchId);
}

export async function streamIngestionBatch(
  batchId: string,
  signal?: AbortSignal
): Promise<AsyncIterable<SseEvent>> {
  return openSseStream(`/api/v1/ingestion-batches/${batchId}/stream`, { method: 'GET' }, signal);
}

export async function retryIngestionBatch(batchId: string): Promise<IngestionBatchRetryResponse> {
  return apiFetch<IngestionBatchRetryResponse>('/api/v1/ingestion-batches/' + batchId + '/retry', {
    method: 'POST',
  });
}

export async function cancelIngestionBatch(batchId: string): Promise<IngestionBatchCancelResponse> {
  return apiFetch<IngestionBatchCancelResponse>('/api/v1/ingestion-batches/' + batchId + '/cancel', {
    method: 'POST',
  });
}
