'use client';
/**
 * Add documents page for an existing knowledge base.
 */
import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Typography
} from '@mui/material';
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
import { useKnowledgeBase } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import { runWithConcurrency } from '../lib/runWithConcurrency';
import { uploadMaterial } from '../services/materials';
import type {
  EntryError,
  ManifestEntry,
  BatchStatus,
  DocStatus,
  ManifestSourceType
} from '../services/ingestionBatches';
import { formatIngestionEntryError } from '../services/ingestionEntryErrors';
import { HttpError } from '../services/http';

const MAX_PARALLEL_UPLOADS = 4;

interface PendingSubmittedBatch {
  batchId: string;
  submittedDocTitles: string[];
}

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

function batchStatusLabel(status: BatchStatus): string {
  switch (status) {
    case 'processing':
      return '处理中';
    case 'completed':
      return '已完成';
    default:
      return status;
  }
}

function docStatusLabel(status: DocStatus): string {
  switch (status) {
    case 'processing':
      return '处理中';
    case 'completed':
      return '已完成';
    default:
      return status;
  }
}

function isDocFailed(doc: { status: DocStatus; error_code: string | null }): boolean {
  return doc.status === 'completed' && doc.error_code !== null && doc.error_code !== 'DOC_CANCELED';
}

function sourceTypeLabel(sourceType: ManifestSourceType | 'upload'): string {
  switch (sourceType) {
    case 'text':
      return '文本';
    case 'url':
      return 'URL';
    case 'file':
      return '文件';
    case 'upload':
      return '上传文件';
    default:
      return sourceType;
  }
}

function batchStatusColor(status: BatchStatus): 'default' | 'warning' | 'success' {
  switch (status) {
    case 'processing':
      return 'warning';
    case 'completed':
      return 'success';
    default:
      return 'default';
  }
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

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const createBatchMutation = useCreateIngestionBatch({
    invalidateMode: 'background'
  });
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

  const liveBatchQuery = useIngestionBatchLive({
    kbId: kbId ?? undefined,
    batchId: preferredBatchId
  });

  const kb = kbQuery.data ?? null;
  const currentBatch = liveBatchQuery.data;
  const activeBatchId = liveBatchQuery.resolvedBatchId ?? preferredBatchId ?? null;

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

  const submitPending = createBatchMutation.isPending || uploadingFiles;
  const batchRunning = displayedBatch?.status === 'processing';
  const hasRetryableFailedDocs =
    displayedBatch?.docs.some((doc) => isDocFailed(doc) && doc.retryable) ?? false;

  const streamHint = useMemo(() => {
    if (!activeBatchId || !displayedBatch) {
      return null;
    }
    if (liveBatchQuery.streamStatus === 'connecting') {
      return '正在建立实时状态连接…';
    }
    if (liveBatchQuery.streamStatus === 'live') {
      return '实时状态已连接。';
    }
    if (liveBatchQuery.streamStatus === 'fallback_polling') {
      return `实时连接中断，已切换轮询（每 ${Math.round(liveBatchQuery.fallbackIntervalMs / 1000)} 秒）。`;
    }
    return '正在等待处理状态更新。';
  }, [activeBatchId, displayedBatch, liveBatchQuery.fallbackIntervalMs, liveBatchQuery.streamStatus]);

  const mergedError =
    localError ??
    (createBatchMutation.error ? getErrorMessage(createBatchMutation.error) : null) ??
    (retryBatchMutation.error ? getErrorMessage(retryBatchMutation.error) : null) ??
    (cancelBatchMutation.error ? getErrorMessage(cancelBatchMutation.error) : null) ??
    (liveBatchQuery.error ? getErrorMessage(liveBatchQuery.error) : null) ??
    (kbQuery.error ? getErrorMessage(kbQuery.error) : null);

  const buildManifestEntries = async () => {
    if (!kbId) {
      return {
        manifestEntries: [] as ManifestEntry[],
        uploadErrors: {} as Record<string, string[]>
      };
    }

    const manifestEntries: ManifestEntry[] = [];
    const uploadErrors: Record<string, string[]> = {};
    const fileEntries = validation.normalizedValidEntries.filter(
      (entry) => entry.sourceType === 'file'
    );

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

      for (const entry of validation.normalizedValidEntries) {
        if (entry.sourceType === 'text') {
          manifestEntries.push({
            source_type: 'text',
            entry_id: entry.id,
            title: entry.title,
            text: entry.text
          });
          continue;
        }

        if (entry.sourceType === 'url') {
          manifestEntries.push({
            source_type: 'url',
            entry_id: entry.id,
            title: entry.title,
            url: entry.url
          });
          continue;
        }

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
      setLocalError(getErrorMessage(error));
    }
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

      <Paper variant='outlined' sx={{ p: 2.5 }}>
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

      <Paper variant='outlined' sx={{ p: 2.5 }}>
        <Stack spacing={1.5}>
          <Typography variant='h6'>实时状态</Typography>

          {!waitingSubmittedBatch && streamHint && (
            <Alert
              severity={liveBatchQuery.streamStatus === 'fallback_polling' ? 'warning' : 'info'}
            >
              {streamHint}
            </Alert>
          )}

          {waitingSubmittedBatch && pendingSubmittedBatch ? (
            <>
              <Alert severity='info'>新批次已创建，正在等待文档处理明细。</Alert>
              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Chip label={'批次：' + pendingSubmittedBatch.batchId} variant='outlined' />
                <Chip label='排队中' color='warning' />
                <Chip label='状态同步中' variant='outlined' color='info' />
              </Stack>
              <Typography variant='body2' color='text.secondary'>
                {'文档：处理中 ' + pendingSubmittedBatch.submittedDocTitles.length + '（等待服务端首个状态快照）'}
              </Typography>
              <Paper variant='outlined' sx={{ p: 1.5, maxHeight: 460, overflowY: 'auto' }}>
                <Stack spacing={1}>
                  {pendingSubmittedBatch.submittedDocTitles.map((title, index) => (
                    <Stack
                      key={pendingSubmittedBatch.batchId + '-' + index}
                      direction={{ xs: 'column', sm: 'row' }}
                      justifyContent='space-between'
                      sx={{
                        borderBottom: '1px solid',
                        borderColor: 'divider',
                        pb: 1
                      }}
                    >
                      <Box sx={{ minWidth: 0 }}>
                        <Typography variant='body2' fontWeight={600} noWrap>
                          {title}
                        </Typography>
                        <Typography variant='caption' color='text.secondary'>
                          等待服务端返回文档详情
                        </Typography>
                      </Box>
                      <Chip label={docStatusLabel('processing')} size='small' variant='outlined' />
                    </Stack>
                  ))}
                </Stack>
              </Paper>
            </>
          ) : !displayedBatch ? (
            <Alert severity='info'>
              当前暂无导入批次。提交文档后，这里会展示实时处理状态与文档级结果。
            </Alert>
          ) : (
            <>
              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Chip label={'批次：' + displayedBatch.id} variant='outlined' />
                <Chip
                  label={batchStatusLabel(displayedBatch.status)}
                  color={batchStatusColor(displayedBatch.status)}
                />
              </Stack>
              <Typography variant='body2' color='text.secondary'>
                {'文档：成功 ' +
                  displayedBatch.succeeded_docs +
                  ' / 失败 ' +
                  displayedBatch.failed_docs +
                  ' / 取消 ' +
                  displayedBatch.canceled_docs +
                  ' / 分块 ' +
                  displayedBatch.succeeded_chunks}
              </Typography>
              {displayedBatch.docs.length > 0 ? (
                <Paper variant='outlined' sx={{ p: 1.5, maxHeight: 460, overflowY: 'auto' }}>
                  <Stack spacing={1}>
                    {displayedBatch.docs.map((doc) => (
                      <Stack
                        key={doc.id}
                        direction={{ xs: 'column', sm: 'row' }}
                        justifyContent='space-between'
                        sx={{
                          borderBottom: '1px solid',
                          borderColor: 'divider',
                          pb: 1
                        }}
                      >
                        <Box sx={{ minWidth: 0 }}>
                          <Typography variant='body2' fontWeight={600} noWrap>
                            {doc.title || doc.id}
                          </Typography>
                          <Typography variant='caption' color='text.secondary'>
                            {sourceTypeLabel(doc.source_type) +
                              ' · 重试 ' +
                              doc.retry_count +
                              ' · 上下文降级 ' +
                              (doc.context_failed_chunks?.length ?? 0)}
                          </Typography>
                        </Box>
                        <Stack direction='row' spacing={1} alignItems='center'>
                          <Chip label={docStatusLabel(doc.status)} size='small' variant='outlined' />
                          {doc.error_message && (
                            <Typography variant='caption' color='error.main' sx={{ maxWidth: 300 }}>
                              {doc.error_message}
                            </Typography>
                          )}
                        </Stack>
                      </Stack>
                    ))}
                  </Stack>
                </Paper>
              ) : (
                <Typography variant='body2' color='text.secondary'>
                  批次已创建，正在等待文档处理明细。
                </Typography>
              )}
            </>
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}
