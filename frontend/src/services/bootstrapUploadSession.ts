import type { BootstrapUploadTarget } from './bootstrapSubmissions';

export interface BootstrapPendingUploadFile {
  entry_id: string;
  title?: string;
  file: File;
}

export interface BootstrapPendingUploadSession {
  files: BootstrapPendingUploadFile[];
  uploadTargets?: BootstrapUploadTarget[];
  createdAt: number;
}

const SESSION_TTL_MS = 30 * 60 * 1000;
const pendingUploadSessions = new Map<string, BootstrapPendingUploadSession>();

function purgeExpiredSessions(now: number): void {
  for (const [jobId, session] of pendingUploadSessions) {
    if (now - session.createdAt > SESSION_TTL_MS) {
      pendingUploadSessions.delete(jobId);
    }
  }
}

export function setBootstrapPendingUploadSession(
  jobId: string,
  payload: Omit<BootstrapPendingUploadSession, 'createdAt'>
): void {
  const now = Date.now();
  purgeExpiredSessions(now);
  pendingUploadSessions.set(jobId, {
    ...payload,
    createdAt: now,
  });
}

export function getBootstrapPendingUploadSession(
  jobId: string
): BootstrapPendingUploadSession | undefined {
  const now = Date.now();
  purgeExpiredSessions(now);
  return pendingUploadSessions.get(jobId);
}

export function clearBootstrapPendingUploadSession(jobId: string): void {
  pendingUploadSessions.delete(jobId);
}
