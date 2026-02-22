'use client';
/**
 * Add documents page for an existing knowledge base.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  Alert,
  Box,
  Paper,
  Stack,
  Typography
} from '@mui/material';
import {
  IngestionDocumentResultPanel,
  IngestionStatusOverviewCard,
  batchStatusColor,
  batchStatusLabel,
  bootstrapStatusColor,
  bootstrapStatusLabel,
  buildBatchSummaryMetrics,
  docPresentationColor,
  docPresentationLabel,
  docPresentationStatus,
  formatIngestionSummaryText,
  isDocFailed,
  sourceTypeLabel,
  streamHintSeverity,
  streamHintText,
  type IngestionChipColor
} from '../components/ingestion';
import { Button } from '../components/ui/Button';
import {
  IngestionManifestEditor,
  validateManifestDraftEntries,
  type ManifestDraftEntry
} from '../components/IngestionManifestEditor';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import {
  useCancelIngestionBatch,
  useCreateIngestionBatch,
  useIngestionBatchLive,
  useRetryIngestionBatch
} from '../hooks/queries/useIngestionBatches';
import {
  useBootstrapSubmission,
  useFinalizeBootstrapSubmission,
} from '../hooks/queries/useBootstrapSubmissions';
import { useKnowledgeBase } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import { splitDirectIngestionManifestEntries } from '../lib/manifestBuilders';
import { runWithConcurrency } from '../lib/runWithConcurrency';
import {
  createBootstrapUploadSession,
  uploadBootstrapSubmissionFile
} from '../services/bootstrapSubmissions';
import {
  clearBootstrapPendingUploadSession,
  getBootstrapPendingUploadSession,
} from '../services/bootstrapUploadSession';
import { uploadMaterial } from '../services/materials';
import type {
  EntryError,
  ManifestEntry
} from '../services/ingestionBatches';
import { getLatestIngestionBatch } from '../services/ingestionBatches';
import { formatIngestionEntryError } from '../services/ingestionEntryErrors';
import {
  resolveRecoverableBatchId,
  shouldRecoverAfterSubmitError
} from '../services/ingestionBatchRecovery';
import { HttpError } from '../services/http';

const MAX_PARALLEL_UPLOADS = 4;

interface PendingSubmittedBatch {
  batchId: string;
  submittedDocTitles: string[];
}

interface BootstrapUploadState {
  stage: 'idle' | 'uploading' | 'finalizing' | 'done' | 'failed' | 'missing_files';
  totalFiles: number;
  uploadedFiles: number;
  failedFiles: number;
  message: string | null;
}

const INITIAL_BOOTSTRAP_UPLOAD_STATE: BootstrapUploadState = {
  stage: 'idle',
  totalFiles: 0,
  uploadedFiles: 0,
  failedFiles: 0,
  message: null,
};

function mapEntryErrors(errors: EntryError[]): Record<string, string[]> {
  const mapped: Record<string, string[]> = {};
  for (const err of errors) {
    mapped[err.entry_id] = mapped[err.entry_id] ?? [];
    mapped[err.entry_id].push(formatIngestionEntryError(err));
  }
  return mapped;
}

function extractEntryErrors(error: unknown): EntryError[] {
  if (!(error instanceof HttpError)) {
    return [];
  }

  const body = error.body as {
    error?: { details?: { entry_errors?: EntryError[] } };
  };

  const maybeErrors = body?.error?.details?.entry_errors;
  return Array.isArray(maybeErrors) ? maybeErrors : [];
}

function mergeEntryErrors(
  base: Record<string, string[]>,
  extra: Record<string, string[]>
): Record<string, string[]> {
  const merged: Record<string, string[]> = { ...base };
  for (const key of Object.keys(extra)) {
    merged[key] = Array.from(new Set([...(merged[key] ?? []), ...extra[key]]));
  }
  return merged;
}

function manifestEntryDisplayTitle(entry: ManifestEntry, index: number): string {
  const title = entry.title?.trim();
  if (title) {
    return title;
  }
  if (entry.source_type === 'url') {
    return entry.url;
  }
  return `未命名文档 ${index + 1}`;
}

export default function KnowledgeBaseAddDocumentsPage() {
  const router = useRouter();
  const params = useParams<{ kbId: string }>();
  const searchParams = useSearchParams();
  const kbId = Array.isArray(params.kbId) ? params.kbId[0] : params.kbId;
  const initialBatchId = searchParams.get('batch') ?? undefined;
  const jobId = searchParams.get('job') ?? undefined;

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const createBatchMutation = useCreateIngestionBatch({
    invalidateMode: 'background'
  });
  const finalizeBootstrapMutation = useFinalizeBootstrapSubmission();
  const retryBatchMutation = useRetryIngestionBatch();
  const cancelBatchMutation = useCancelIngestionBatch();

  const [entries, setEntries] = useState<ManifestDraftEntry[]>([]);
  const [serverEntryErrors, setServerEntryErrors] = useState<Record<string, string[]>>({});
  const [preferredBatchId, setPreferredBatchId] = useState<string | undefined>(initialBatchId);
  const [pendingSubmittedBatch, setPendingSubmittedBatch] = useState<PendingSubmittedBatch | null>(
    null
  );
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const [showSlowLoading, setShowSlowLoading] = useState(false);
  const [bootstrapUploadState, setBootstrapUploadState] =
    useState<BootstrapUploadState>(INITIAL_BOOTSTRAP_UPLOAD_STATE);
  const bootstrapUploadStartedRef = useRef<string | null>(null);

  useEffect(() => {
    if (initialBatchId) {
      setPreferredBatchId(initialBatchId);
    }
  }, [initialBatchId]);

  useEffect(() => {
    if (!kbQuery.isPending) {
      setShowSlowLoading(false);
      return;
    }
    const timer = setTimeout(() => {
      setShowSlowLoading(true);
    }, 8_000);
    return () => {
      clearTimeout(timer);
    };
  }, [kbQuery.isPending]);

  const bootstrapJobQuery = useBootstrapSubmission(jobId);

  useEffect(() => {
    if (bootstrapJobQuery.data?.batch_id) {
      setPreferredBatchId(bootstrapJobQuery.data.batch_id);
    }
  }, [bootstrapJobQuery.data?.batch_id]);

  const liveBatchQuery = useIngestionBatchLive({
    kbId: kbId ?? undefined,
    batchId: preferredBatchId
  });

  const kb = kbQuery.data ?? null;
  const bootstrapJob = bootstrapJobQuery.data;
  const bootstrapJobId = bootstrapJob?.id;
  const bootstrapJobStatus = bootstrapJob?.status;
  const currentBatch = liveBatchQuery.data;
  const activeBatchId = liveBatchQuery.resolvedBatchId ?? preferredBatchId ?? null;
  const finalizeBootstrapRef = useRef(finalizeBootstrapMutation.mutateAsync);
  const refetchBootstrapJobRef = useRef(bootstrapJobQuery.refetch);

  useEffect(() => {
    finalizeBootstrapRef.current = finalizeBootstrapMutation.mutateAsync;
  }, [finalizeBootstrapMutation.mutateAsync]);

  useEffect(() => {
    refetchBootstrapJobRef.current = bootstrapJobQuery.refetch;
  }, [bootstrapJobQuery.refetch]);

  useEffect(() => {
    if (!bootstrapJobId || !kbId) {
      return;
    }
    if (bootstrapJobStatus !== 'queued_upload') {
      return;
    }
    if (bootstrapUploadStartedRef.current === bootstrapJobId) {
      return;
    }

    const pendingSession = getBootstrapPendingUploadSession(bootstrapJobId);
    if (!pendingSession || pendingSession.files.length === 0) {
      setBootstrapUploadState({
        stage: 'missing_files',
        totalFiles: 0,
        uploadedFiles: 0,
        failedFiles: 0,
        message: '当前会话缺少待上传文件，请返回“新建知识库”页面重新提交。',
      });
      return;
    }

    bootstrapUploadStartedRef.current = bootstrapJobId;
    const filesByEntryId = new Map(pendingSession.files.map((item) => [item.entry_id, item]));

    let cancelled = false;
    setLocalError(null);

    const runBootstrapUpload = async () => {
      const uploadSession = await createBootstrapUploadSession(bootstrapJobId);
      const uploadTargets = uploadSession.upload_targets ?? [];
      const totalFiles = uploadTargets.length;

      if (cancelled) {
        return;
      }
      if (totalFiles === 0) {
        setBootstrapUploadState({
          stage: 'missing_files',
          totalFiles: 0,
          uploadedFiles: 0,
          failedFiles: 0,
          message: '上传会话未返回可用目标，请稍后重试。',
        });
        return;
      }

      let uploadedFiles = 0;
      let failedFiles = 0;
      setBootstrapUploadState({
        stage: 'uploading',
        totalFiles,
        uploadedFiles: 0,
        failedFiles: 0,
        message: '正在上传文件…',
      });

      await runWithConcurrency(uploadTargets, MAX_PARALLEL_UPLOADS, async (target) => {
        if (cancelled) {
          return;
        }

        const pendingFile = filesByEntryId.get(target.entry_id);
        if (!pendingFile) {
          failedFiles += 1;
          setBootstrapUploadState((prev) => ({
            ...prev,
            stage: 'failed',
            uploadedFiles,
            failedFiles,
            message: '存在缺失文件，请返回上一步重新提交。',
          }));
          return;
        }

        try {
          await uploadBootstrapSubmissionFile(target, pendingFile.file);
          uploadedFiles += 1;
          setBootstrapUploadState((prev) => ({
            ...prev,
            stage: 'uploading',
            uploadedFiles,
            failedFiles,
            message: `已上传 ${uploadedFiles}/${totalFiles}`,
          }));
        } catch (error) {
          failedFiles += 1;
          setBootstrapUploadState((prev) => ({
            ...prev,
            stage: 'failed',
            uploadedFiles,
            failedFiles,
            message: getErrorMessage(error),
          }));
        }
      });

      if (cancelled) {
        return;
      }
      if (failedFiles > 0) {
        setLocalError('部分文件上传失败，请重试上传。');
        return;
      }

      setBootstrapUploadState((prev) => ({
        ...prev,
        stage: 'finalizing',
        message: '文件上传完成，正在提交任务…',
      }));
      await finalizeBootstrapRef.current(bootstrapJobId);
      clearBootstrapPendingUploadSession(bootstrapJobId);

      if (cancelled) {
        return;
      }
      setBootstrapUploadState((prev) => ({
        ...prev,
        stage: 'done',
        uploadedFiles: totalFiles,
        failedFiles: 0,
        message: '文件上传完成，任务已进入处理队列。',
      }));
      await refetchBootstrapJobRef.current();
    };

    void runBootstrapUpload().catch((error) => {
      if (cancelled) {
        return;
      }
      setBootstrapUploadState((prev) => ({
        ...prev,
        stage: 'failed',
        message: getErrorMessage(error),
      }));
      setLocalError(getErrorMessage(error));
    });

    return () => {
      cancelled = true;
    };
  }, [
    bootstrapJobId,
    bootstrapJobStatus,
    kbId,
  ]);

  useEffect(() => {
    if (!jobId) {
      bootstrapUploadStartedRef.current = null;
      setBootstrapUploadState(INITIAL_BOOTSTRAP_UPLOAD_STATE);
      return;
    }
    if (!bootstrapJobStatus || bootstrapJobStatus === 'queued_upload') {
      return;
    }
    bootstrapUploadStartedRef.current = null;
    setBootstrapUploadState(INITIAL_BOOTSTRAP_UPLOAD_STATE);
  }, [bootstrapJobStatus, jobId]);

  const displayedBatch = useMemo(() => {
    if (!currentBatch) {
      return null;
    }
    if (!preferredBatchId) {
      return currentBatch;
    }
    return currentBatch.id === preferredBatchId ? currentBatch : null;
  }, [currentBatch, preferredBatchId]);

  const waitingSubmittedBatch =
    pendingSubmittedBatch !== null &&
    (!displayedBatch || displayedBatch.id !== pendingSubmittedBatch.batchId);
  const waitingBootstrapBatch =
    bootstrapJob !== undefined &&
    bootstrapJob.status !== 'failed' &&
    bootstrapJob.status !== 'queued_upload' &&
    !bootstrapJob.batch_id;

  useEffect(() => {
    if (pendingSubmittedBatch && displayedBatch?.id === pendingSubmittedBatch.batchId) {
      setPendingSubmittedBatch(null);
    }
  }, [pendingSubmittedBatch, displayedBatch?.id]);

  const markdownOnly = kb?.index_config?.chunking.general_strategy === 'markdown_heading';
  const validation = useMemo(
    () =>
      validateManifestDraftEntries(entries, {
        markdownOnly: Boolean(markdownOnly)
      }),
    [entries, markdownOnly]
  );

  const bootstrapUploadActive =
    bootstrapJob?.status === 'queued_upload' &&
    (bootstrapUploadState.stage === 'uploading' || bootstrapUploadState.stage === 'finalizing');
  const bootstrapQueuedUploadMessage = useMemo(() => {
    if (!bootstrapJob || bootstrapJob.status !== 'queued_upload') {
      return null;
    }
    if (bootstrapUploadState.message) {
      return bootstrapUploadState.message;
    }
    if (bootstrapJob.upload_progress.total_files > 0) {
      return (
        '上传进度：' +
        bootstrapJob.upload_progress.uploaded_files +
        '/' +
        bootstrapJob.upload_progress.total_files +
        '，失败 ' +
        bootstrapJob.upload_progress.failed_files
      );
    }
    return bootstrapJob.progress_message ?? '正在等待文件上传完成…';
  }, [bootstrapJob, bootstrapUploadState.message]);
  const showLocalBootstrapMessage =
    bootstrapJob?.status === 'queued_upload' &&
    (bootstrapUploadState.stage === 'uploading' ||
      bootstrapUploadState.stage === 'finalizing' ||
      bootstrapUploadState.stage === 'failed' ||
      bootstrapUploadState.stage === 'missing_files') &&
    Boolean(bootstrapUploadState.message);
  const submitPending =
    createBatchMutation.isPending ||
    uploadingFiles ||
    finalizeBootstrapMutation.isPending ||
    bootstrapUploadActive;
  const batchRunning = displayedBatch?.status === 'processing';
  const hasRetryableFailedDocs =
    displayedBatch?.docs.some((doc) => isDocFailed(doc) && doc.retryable) ?? false;
  const streamHint = useMemo(
    () =>
      streamHintText({
        enabled: Boolean(activeBatchId && displayedBatch && !waitingSubmittedBatch),
        streamStatus: liveBatchQuery.streamStatus,
        fallbackIntervalMs: liveBatchQuery.fallbackIntervalMs
      }),
    [
      activeBatchId,
      displayedBatch,
      liveBatchQuery.fallbackIntervalMs,
      liveBatchQuery.streamStatus,
      waitingSubmittedBatch
    ]
  );
  const displayedBatchMetrics = useMemo(
    () => (displayedBatch ? buildBatchSummaryMetrics(displayedBatch) : null),
    [displayedBatch]
  );
  const pendingBatchMetrics = useMemo(() => {
    if (!pendingSubmittedBatch) {
      return null;
    }
    return {
      succeededDocs: 0,
      failedDocs: 0,
      canceledDocs: 0,
      processingDocs: pendingSubmittedBatch.submittedDocTitles.length,
      succeededChunks: 0
    };
  }, [pendingSubmittedBatch]);
  const bootstrapMetrics = useMemo(() => {
    if (!bootstrapJob) {
      return null;
    }
    const succeededDocs = bootstrapJob.accepted_entries;
    const failedDocs = bootstrapJob.failed_entries;
    return {
      succeededDocs,
      failedDocs,
      canceledDocs: 0,
      processingDocs: Math.max(bootstrapJob.total_entries - succeededDocs - failedDocs, 0),
      succeededChunks: 0
    };
  }, [bootstrapJob]);
  const documentRows = useMemo(() => {
    if (waitingSubmittedBatch && pendingSubmittedBatch) {
      return pendingSubmittedBatch.submittedDocTitles.map((title, index) => ({
        id: pendingSubmittedBatch.batchId + '-' + index,
        title,
        sourceLabel: '待同步',
        retryCount: 0,
        contextFailedChunks: 0,
        status: 'processing' as const,
        statusLabel: docPresentationLabel('processing'),
        statusColor: docPresentationColor('processing'),
        errorMessage: null
      }));
    }
    if (!displayedBatch) {
      return [];
    }
    return displayedBatch.docs.map((doc) => {
      const status = docPresentationStatus(doc);
      return {
        id: doc.id,
        title: doc.title || doc.id,
        sourceLabel: sourceTypeLabel(doc.source_type),
        retryCount: doc.retry_count,
        contextFailedChunks: doc.context_failed_chunks?.length ?? 0,
        status,
        statusLabel: docPresentationLabel(status),
        statusColor: docPresentationColor(status),
        errorMessage: doc.error_message
      };
    });
  }, [displayedBatch, pendingSubmittedBatch, waitingSubmittedBatch]);
  const documentSummaryText = useMemo(() => {
    if (waitingSubmittedBatch && pendingSubmittedBatch) {
      return `文档：处理中 ${pendingSubmittedBatch.submittedDocTitles.length}（等待服务端首个状态快照）`;
    }
    if (displayedBatchMetrics) {
      return formatIngestionSummaryText(displayedBatchMetrics);
    }
    return '文档处理明细将在提交后展示。';
  }, [displayedBatchMetrics, pendingSubmittedBatch, waitingSubmittedBatch]);

  const mergedError =
    localError ??
    (createBatchMutation.error ? getErrorMessage(createBatchMutation.error) : null) ??
    (finalizeBootstrapMutation.error ? getErrorMessage(finalizeBootstrapMutation.error) : null) ??
    (retryBatchMutation.error ? getErrorMessage(retryBatchMutation.error) : null) ??
    (cancelBatchMutation.error ? getErrorMessage(cancelBatchMutation.error) : null) ??
    (bootstrapJobQuery.error ? getErrorMessage(bootstrapJobQuery.error) : null) ??
    (liveBatchQuery.error ? getErrorMessage(liveBatchQuery.error) : null) ??
    (kbQuery.error ? getErrorMessage(kbQuery.error) : null);

  const buildManifestEntries = async () => {
    if (!kbId) {
      return {
        manifestEntries: [] as ManifestEntry[],
        uploadErrors: {} as Record<string, string[]>
      };
    }

    const { manifestEntries, fileEntries } = splitDirectIngestionManifestEntries(
      validation.normalizedValidEntries
    );
    const uploadErrors: Record<string, string[]> = {};

    setUploadingFiles(true);
    try {
      const fileUploadResults = await runWithConcurrency(
        fileEntries,
        MAX_PARALLEL_UPLOADS,
        async (entry) => {
          try {
            const uploaded = await uploadMaterial(kbId, entry.title ?? entry.file.name, entry.file);
            return {
              entryId: entry.id,
              materialId: uploaded.id,
              error: null as string | null
            };
          } catch (error) {
            return {
              entryId: entry.id,
              materialId: null as string | null,
              error: getErrorMessage(error)
            };
          }
        }
      );

      const fileResultById = new Map(fileUploadResults.map((item) => [item.entryId, item]));

      for (const entry of fileEntries) {
        const uploadResult = fileResultById.get(entry.id);
        if (!uploadResult) {
          uploadErrors[entry.id] = ['未获取上传结果'];
          continue;
        }
        if (!uploadResult.materialId) {
          uploadErrors[entry.id] = [uploadResult.error ?? '文件上传失败'];
          continue;
        }

        manifestEntries.push({
          source_type: 'file',
          entry_id: entry.id,
          title: entry.title,
          material_id: uploadResult.materialId
        });
      }
    } finally {
      setUploadingFiles(false);
    }

    return { manifestEntries, uploadErrors };
  };

  const submitBatch = async () => {
    if (!kbId) {
      return;
    }

    setLocalError(null);
    setServerEntryErrors({});

    if (validation.globalErrors.length > 0 || validation.normalizedValidEntries.length === 0) {
      setLocalError('请先修复条目问题。');
      return;
    }

    try {
      const { manifestEntries, uploadErrors } = await buildManifestEntries();
      if (manifestEntries.length === 0) {
        setServerEntryErrors(uploadErrors);
        setLocalError('无可提交条目。');
        return;
      }

      const response = await createBatchMutation.mutateAsync({
        kb_id: kbId,
        entries: manifestEntries
      });

      const submittedDocTitles = manifestEntries.map((entry, index) =>
        manifestEntryDisplayTitle(entry, index)
      );
      setPendingSubmittedBatch({
        batchId: response.batch_id,
        submittedDocTitles
      });
      setPreferredBatchId(response.batch_id);
      setServerEntryErrors(mergeEntryErrors(uploadErrors, mapEntryErrors(response.entry_errors)));
      router.replace(`/knowledge-bases/${kbId}/documents/new?batch=${response.batch_id}`, {
        scroll: false
      });
    } catch (error) {
      const backendErrors = extractEntryErrors(error);
      if (backendErrors.length > 0) {
        setServerEntryErrors(mapEntryErrors(backendErrors));
      }
      if (kbId && shouldRecoverAfterSubmitError(error)) {
        try {
          const latestBatch = await getLatestIngestionBatch(kbId);
          const recoveredBatchId = resolveRecoverableBatchId(latestBatch);
          if (recoveredBatchId) {
            setPreferredBatchId(recoveredBatchId);
            setPendingSubmittedBatch(null);
            router.replace(`/knowledge-bases/${kbId}/documents/new?batch=${recoveredBatchId}`, {
              scroll: false
            });
            setLocalError('提交请求超时，已自动恢复到服务端处理中批次。');
            return;
          }
        } catch {
          // Keep original error message when latest batch recovery also fails.
        }
      }
      setLocalError(getErrorMessage(error));
    }
  };

  const retryBootstrapUpload = async () => {
    if (!bootstrapJob || bootstrapJob.status !== 'queued_upload') {
      return;
    }
    bootstrapUploadStartedRef.current = null;
    setBootstrapUploadState(INITIAL_BOOTSTRAP_UPLOAD_STATE);
    setLocalError(null);
    await bootstrapJobQuery.refetch();
  };

  const retryFailedDocs = async () => {
    if (!activeBatchId) {
      return;
    }

    setLocalError(null);
    try {
      await retryBatchMutation.mutateAsync(activeBatchId);
      await liveBatchQuery.refetch();
    } catch (error) {
      setLocalError(getErrorMessage(error));
    }
  };

  const cancelBatch = async () => {
    if (!activeBatchId) {
      return;
    }

    setLocalError(null);
    try {
      await cancelBatchMutation.mutateAsync(activeBatchId);
      await liveBatchQuery.refetch();
    } catch (error) {
      setLocalError(getErrorMessage(error));
    }
  };

  if (kbQuery.isPending) {
    return (
      <Stack spacing={2}>
        <LoadingSpinner text={showSlowLoading ? '仍在加载知识库，请稍候…' : '加载知识库...'} />
        {showSlowLoading && (
          <Alert
            severity='info'
            action={
              <Button variant='text' onClick={() => void kbQuery.refetch()}>
                重新请求
              </Button>
            }
          >
            加载时间较长，可能是网络或服务端处理较慢。你可以重试或稍后刷新页面。
          </Alert>
        )}
      </Stack>
    );
  }

  if (!kb) {
    return <Alert severity='error'>{mergedError ?? '未找到知识库'}</Alert>;
  }

  const bootstrapUploadProgressText =
    bootstrapJob && bootstrapJob.upload_progress.total_files > 0
      ? `上传进度：${bootstrapJob.upload_progress.uploaded_files}/${bootstrapJob.upload_progress.total_files}，失败 ${bootstrapJob.upload_progress.failed_files}`
      : null;
  const bootstrapProgressMessage =
    (showLocalBootstrapMessage && bootstrapUploadState.message) ||
    bootstrapJob?.progress_message ||
    (bootstrapJob?.status === 'queued_upload' && !bootstrapUploadProgressText
      ? bootstrapQueuedUploadMessage
      : null);
  const bootstrapErrorMessage =
    bootstrapJob?.error_message ||
    ((bootstrapUploadState.stage === 'failed' || bootstrapUploadState.stage === 'missing_files') &&
    bootstrapJob?.status === 'queued_upload'
      ? bootstrapUploadState.message
      : null);
  const shouldShowRetryBootstrapButton =
    (bootstrapUploadState.stage === 'failed' || bootstrapUploadState.stage === 'missing_files') &&
    bootstrapJob?.status === 'queued_upload';
  const overviewMetrics =
    (waitingSubmittedBatch && pendingBatchMetrics) ||
    displayedBatchMetrics ||
    bootstrapMetrics ||
    null;
  const overviewStatusLabel =
    (waitingSubmittedBatch && pendingSubmittedBatch && '状态同步中') ||
    (displayedBatch ? batchStatusLabel(displayedBatch.status) : null) ||
    (bootstrapJob ? bootstrapStatusLabel(bootstrapJob.status) : null);
  const overviewStatusColor: IngestionChipColor =
    (waitingSubmittedBatch && pendingSubmittedBatch && 'info') ||
    (displayedBatch ? batchStatusColor(displayedBatch.status) : null) ||
    (bootstrapJob ? bootstrapStatusColor(bootstrapJob.status) : null) ||
    'default';
  const overviewDescription = waitingSubmittedBatch
    ? '新批次已创建，正在等待服务端返回首个状态快照。'
    : displayedBatch
      ? '实时追踪批次处理进度，失败文档支持按需查看错误并重试。'
      : bootstrapJob?.status === 'queued_upload'
        ? '文件上传完成后会自动进入批次处理。'
        : bootstrapJob
          ? '任务已提交，正在同步批次信息。'
          : null;
  const overviewBatchId =
    (waitingSubmittedBatch ? pendingSubmittedBatch?.batchId : null) ||
    displayedBatch?.id ||
    bootstrapJob?.batch_id ||
    null;
  const overviewFooterHint =
    (displayedBatchMetrics && formatIngestionSummaryText(displayedBatchMetrics)) ||
    (bootstrapJob && bootstrapJob.entry_errors.length > 0
      ? `条目失败：${bootstrapJob.entry_errors.length}，可在下方查看并重试。`
      : null);

  return (
    <Stack spacing={2}>
      <PageHeader
        title='添加文档'
        subtitle={kb.name}
        action={
          <Button variant='outlined' onClick={() => router.push(`/knowledge-bases/${kbId}`)}>
            返回知识库详情
          </Button>
        }
      />

      {mergedError && <Alert severity='error'>{mergedError}</Alert>}

      <Box
        sx={{
          display: 'grid',
          gap: 2,
          gridTemplateColumns: {
            xs: '1fr',
            xl: 'minmax(620px, 1.3fr) minmax(420px, 0.9fr)'
          },
          alignItems: 'start'
        }}
      >
        <Paper variant='outlined' sx={{ p: 2.5, borderRadius: 3 }}>
          <Stack spacing={2}>
            <Typography variant='h6'>导入任务</Typography>
            <Typography color='text.secondary' variant='body2'>
              支持文本、URL、文件混合导入，提交后自动开始处理。
            </Typography>
            <IngestionManifestEditor
              entries={entries}
              onChange={setEntries}
              validation={validation}
              serverEntryErrors={serverEntryErrors}
              markdownOnly={Boolean(markdownOnly)}
              disabled={submitPending || batchRunning}
            />
            <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
              <Button
                variant='contained'
                onClick={submitBatch}
                loading={submitPending}
                disabled={batchRunning}
              >
                提交批次
              </Button>
              <Button
                variant='outlined'
                onClick={retryFailedDocs}
                disabled={!activeBatchId || !hasRetryableFailedDocs || retryBatchMutation.isPending}
                loading={retryBatchMutation.isPending}
              >
                重试失败文档
              </Button>
              <Button
                variant='outlined'
                onClick={cancelBatch}
                disabled={!activeBatchId || !batchRunning || cancelBatchMutation.isPending}
                loading={cancelBatchMutation.isPending}
              >
                取消批次
              </Button>
            </Stack>
          </Stack>
        </Paper>

        <Stack spacing={1.5}>
          <Typography variant='h6'>实时状态</Typography>

          {overviewMetrics ? (
            <IngestionStatusOverviewCard
              title='导入状态总览'
              description={overviewDescription}
              taskId={bootstrapJob?.id ?? null}
              batchId={overviewBatchId}
              statusLabel={overviewStatusLabel}
              statusColor={overviewStatusColor}
              streamHint={streamHint}
              streamHintSeverity={streamHintSeverity(liveBatchQuery.streamStatus)}
              metrics={overviewMetrics}
              uploadProgressText={bootstrapUploadProgressText}
              progressMessage={bootstrapProgressMessage}
              errorMessage={bootstrapErrorMessage}
              footerHint={overviewFooterHint}
              actions={
                shouldShowRetryBootstrapButton ? (
                  <Button variant='outlined' onClick={() => void retryBootstrapUpload()}>
                    重试上传
                  </Button>
                ) : null
              }
            />
          ) : waitingBootstrapBatch ? (
            <Alert severity='info'>创建任务正在处理中，等待批次生成…</Alert>
          ) : (
            <Alert severity='info'>
              当前暂无导入批次。提交文档后，这里会展示实时处理状态与文档级结果。
            </Alert>
          )}

          {waitingSubmittedBatch && pendingSubmittedBatch ? (
            <IngestionDocumentResultPanel
              summaryText={documentSummaryText}
              docs={documentRows}
              emptyMessage='正在等待服务端返回文档详情。'
              defaultExpanded={false}
            />
          ) : displayedBatch ? (
            <IngestionDocumentResultPanel
              summaryText={documentSummaryText}
              docs={documentRows}
              emptyMessage='批次已创建，正在等待文档处理明细。'
              defaultExpanded={false}
            />
          ) : null}
        </Stack>
      </Box>
    </Stack>
  );
}
