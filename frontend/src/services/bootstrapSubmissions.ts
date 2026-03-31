import { apiFetch, fetchWithTimeout, HttpError, type ApiFetchOptions } from './http';
import type { EntryError } from './ingestionBatches';
import type { KnowledgeBaseCreate } from './knowledgeBases';

export type BootstrapSubmissionStatus =
  | 'queued_upload'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed';

export interface BootstrapManifestTextEntry {
  source_type: 'text';
  entry_id?: string;
  title?: string;
  text: string;
}

export interface BootstrapManifestUrlEntry {
  source_type: 'url';
  entry_id?: string;
  title?: string;
  url: string;
}

export interface BootstrapManifestFileEntry {
  source_type: 'file';
  entry_id?: string;
  title?: string;
  filename: string;
  size_bytes: number;
  content_type?: string;
  sha256?: string;
}

export type BootstrapManifestEntry =
  | BootstrapManifestTextEntry
  | BootstrapManifestUrlEntry
  | BootstrapManifestFileEntry;

export interface BootstrapUploadTarget {
  entry_id: string;
  material_id: string;
  filename: string;
  upload_url: string;
  method: string;
  headers: Record<string, string>;
  object_key: string;
  expires_at: string;
}

export interface BootstrapUploadProgress {
  total_files: number;
  uploaded_files: number;
  failed_files: number;
}

export interface BootstrapSubmissionCreateRequest {
  kb_id: string;
  entries: BootstrapManifestEntry[];
}

export interface BootstrapSubmissionCreateResponse {
  job_id: string;
  kb_id: string;
  status: BootstrapSubmissionStatus;
  upload_targets: BootstrapUploadTarget[];
  upload_progress: BootstrapUploadProgress;
}

export interface BootstrapCreateKnowledgeBaseRequest {
  kb: KnowledgeBaseCreate;
  entries: BootstrapManifestEntry[];
}

export interface BootstrapCreateKnowledgeBaseResponse {
  kb_id: string;
  job_id: string;
  status: BootstrapSubmissionStatus;
  monitor_url: string;
}

export interface BootstrapSubmissionFinalizeResponse {
  job_id: string;
  kb_id: string;
  status: BootstrapSubmissionStatus;
  upload_progress: BootstrapUploadProgress;
}

export interface BootstrapUploadSessionResponse {
  job_id: string;
  kb_id: string;
  status: BootstrapSubmissionStatus;
  upload_targets: BootstrapUploadTarget[];
  upload_progress: BootstrapUploadProgress;
}

export interface BootstrapSubmission {
  id: string;
  kb_id: string;
  batch_id: string | null;
  status: BootstrapSubmissionStatus;
  total_entries: number;
  accepted_entries: number;
  failed_entries: number;
  entry_errors: EntryError[];
  progress_message: string | null;
  error_code: string | null;
  error_message: string | null;
  upload_progress: BootstrapUploadProgress;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export async function createBootstrapSubmission(
  data: BootstrapSubmissionCreateRequest
): Promise<BootstrapSubmissionCreateResponse> {
  return apiFetch<BootstrapSubmissionCreateResponse>('/api/v1/knowledge-bases/bootstrap-submissions', {
    method: 'POST',
    body: JSON.stringify(data),
    timeoutMs: 30_000,
  });
}

export async function createBootstrapKnowledgeBase(
  data: BootstrapCreateKnowledgeBaseRequest
): Promise<BootstrapCreateKnowledgeBaseResponse> {
  return apiFetch<BootstrapCreateKnowledgeBaseResponse>(
    '/api/v1/knowledge-bases/bootstrap-create',
    {
      method: 'POST',
      body: JSON.stringify(data),
      timeoutMs: 30_000,
    }
  );
}

export async function finalizeBootstrapSubmission(
  jobId: string
): Promise<BootstrapSubmissionFinalizeResponse> {
  return apiFetch<BootstrapSubmissionFinalizeResponse>(
    `/api/v1/knowledge-bases/bootstrap-submissions/${jobId}/finalize`,
    {
      method: 'POST',
      timeoutMs: 300_000,
    }
  );
}

export async function getBootstrapSubmission(
  jobId: string,
  options?: ApiFetchOptions
): Promise<BootstrapSubmission> {
  return apiFetch<BootstrapSubmission>(
    `/api/v1/knowledge-bases/bootstrap-submissions/${jobId}`,
    options
  );
}

export async function createBootstrapUploadSession(
  jobId: string
): Promise<BootstrapUploadSessionResponse> {
  return apiFetch<BootstrapUploadSessionResponse>(
    `/api/v1/knowledge-bases/bootstrap-submissions/${jobId}/upload-session`,
    {
      method: 'POST',
      timeoutMs: 30_000,
    }
  );
}

export async function uploadBootstrapSubmissionFile(
  target: BootstrapUploadTarget,
  file: File
): Promise<void> {
  const headers = new Headers(target.headers ?? {});
  if (!headers.has('Content-Type') && file.type) {
    headers.set('Content-Type', file.type);
  }

  const { response } = await fetchWithTimeout(target.upload_url, {
    method: target.method || 'PUT',
    headers,
    body: file,
    timeoutMs: 120_000,
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const message = body?.error?.message ?? `上传失败（${response.status}）`;
    throw new HttpError(message, response.status, { body });
  }
}
