'use client';

/**
 * Knowledge base detail page (manifest submit + batch polling)
 */

import { useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { Button } from '../components/ui/Button';
import {
  IngestionManifestEditor,
  createEmptyManifestEntry,
  validateManifestDraftEntries,
  type ManifestDraftEntry,
} from '../components/IngestionManifestEditor';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import {
  useCancelIngestionBatch,
  useCreateIngestionBatch,
  useIngestionBatch,
  useRetryIngestionBatch,
} from '../hooks/queries/useIngestionBatches';
import { useKnowledgeBase } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import type {
  EntryError,
  ManifestEntry,
  BatchStatus,
  DocStatus,
  ManifestSourceType,
} from '../services/ingestionBatches';
import { HttpError } from '../services/http';
import { runWithConcurrency } from '../lib/runWithConcurrency';
import { uploadMaterial } from '../services/materials';

const MAX_PARALLEL_UPLOADS = 4;

function mapEntryErrors(errors: EntryError[]): Record<string, string[]> {
  const mapped: Record<string, string[]> = {};
  for (const err of errors) {
    mapped[err.entry_id] = mapped[err.entry_id] ?? [];
    mapped[err.entry_id].push(err.message);
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
    case 'queued':
      return '排队中';
    case 'running':
      return '进行中';
    case 'succeeded':
      return '成功';
    case 'partial_failed':
      return '部分失败';
    case 'failed':
      return '失败';
    case 'canceled':
      return '已取消';
    default:
      return status;
  }
}

function docStatusLabel(status: DocStatus): string {
  switch (status) {
    case 'pending':
      return '待处理';
    case 'running':
      return '进行中';
    case 'succeeded':
      return '成功';
    case 'failed':
      return '失败';
    case 'canceled':
      return '已取消';
    default:
      return status;
  }
}

function sourceTypeLabel(sourceType: ManifestSourceType): string {
  switch (sourceType) {
    case 'text':
      return '文本';
    case 'url':
      return 'URL';
    case 'file':
      return '文件';
    default:
      return sourceType;
  }
}

function knowledgeBaseStatusLabel(status: string): string {
  switch (status) {
    case 'active':
      return '活跃';
    case 'archived':
      return '已归档';
    default:
      return status;
  }
}

function readinessLabel(readiness: string): string {
  switch (readiness) {
    case 'ready':
      return '可用';
    case 'not_ready':
      return '未就绪';
    default:
      return readiness;
  }
}

function batchStatusColor(status: BatchStatus): 'default' | 'warning' | 'success' | 'error' {
  switch (status) {
    case 'queued':
    case 'running':
      return 'warning';
    case 'succeeded':
      return 'success';
    case 'partial_failed':
      return 'warning';
    case 'failed':
      return 'error';
    case 'canceled':
      return 'default';
    default:
      return 'default';
  }
}

export default function KnowledgeBaseDetailPage() {
  const router = useRouter();
  const params = useParams<{ kbId: string }>();
  const kbId = Array.isArray(params.kbId) ? params.kbId[0] : params.kbId;

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const createBatchMutation = useCreateIngestionBatch();
  const retryBatchMutation = useRetryIngestionBatch();
  const cancelBatchMutation = useCancelIngestionBatch();

  const [entries, setEntries] = useState<ManifestDraftEntry[]>([createEmptyManifestEntry('text')]);
  const [serverEntryErrors, setServerEntryErrors] = useState<Record<string, string[]>>({});
  const [batchId, setBatchId] = useState<string | null>(null);
  const [uploadingFiles, setUploadingFiles] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

  const kb = kbQuery.data ?? null;
  const batchQuery = useIngestionBatch(batchId ?? undefined);
  const currentBatch = batchQuery.data;

  const markdownOnly = kb?.index_config?.chunking.general_strategy === 'markdown_heading';
  const validation = useMemo(
    () => validateManifestDraftEntries(entries, { markdownOnly: Boolean(markdownOnly) }),
    [entries, markdownOnly]
  );

  const submitPending = createBatchMutation.isPending || uploadingFiles;
  const batchRunning = currentBatch?.status === 'queued' || currentBatch?.status === 'running';
  const hasRetryableFailedDocs =
    currentBatch?.docs.some((doc) => doc.status === 'failed' && doc.retryable) ?? false;

  const mergedError =
    localError ??
    (createBatchMutation.error ? getErrorMessage(createBatchMutation.error) : null) ??
    (retryBatchMutation.error ? getErrorMessage(retryBatchMutation.error) : null) ??
    (cancelBatchMutation.error ? getErrorMessage(cancelBatchMutation.error) : null) ??
    (batchQuery.error ? getErrorMessage(batchQuery.error) : null) ??
    (kbQuery.error ? getErrorMessage(kbQuery.error) : null);

  const buildManifestEntries = async () => {
    if (!kbId) {
      return { manifestEntries: [] as ManifestEntry[], uploadErrors: {} as Record<string, string[]> };
    }

    const manifestEntries: ManifestEntry[] = [];
    const uploadErrors: Record<string, string[]> = {};
    const fileEntries = validation.normalizedValidEntries.filter((entry) => entry.sourceType === 'file');

    setUploadingFiles(true);
    try {
      const fileUploadResults = await runWithConcurrency(
        fileEntries,
        MAX_PARALLEL_UPLOADS,
        async (entry) => {
          try {
            const uploaded = await uploadMaterial(kbId, entry.title ?? entry.file.name, entry.file);
            return { entryId: entry.id, materialId: uploaded.id, error: null as string | null };
          } catch (error) {
            return { entryId: entry.id, materialId: null as string | null, error: getErrorMessage(error) };
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
            text: entry.text,
          });
          continue;
        }

        if (entry.sourceType === 'url') {
          manifestEntries.push({
            source_type: 'url',
            entry_id: entry.id,
            title: entry.title,
            url: entry.url,
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
          material_id: uploadResult.materialId,
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
        entries: manifestEntries,
      });

      setBatchId(response.batch_id);
      setServerEntryErrors(mergeEntryErrors(uploadErrors, mapEntryErrors(response.entry_errors)));
    } catch (error) {
      const backendErrors = extractEntryErrors(error);
      if (backendErrors.length > 0) {
        setServerEntryErrors(mapEntryErrors(backendErrors));
      }
      setLocalError(getErrorMessage(error));
    }
  };

  const retryFailedDocs = async () => {
    if (!batchId) {
      return;
    }

    setLocalError(null);
    try {
      await retryBatchMutation.mutateAsync(batchId);
      await batchQuery.refetch();
    } catch (error) {
      setLocalError(getErrorMessage(error));
    }
  };

  const cancelBatch = async () => {
    if (!batchId) {
      return;
    }

    setLocalError(null);
    try {
      await cancelBatchMutation.mutateAsync(batchId);
      await batchQuery.refetch();
    } catch (error) {
      setLocalError(getErrorMessage(error));
    }
  };

  if (kbQuery.isPending) {
    return <LoadingSpinner text='加载知识库...' />;
  }

  if (!kb) {
    return (
      <Alert severity='error'>
        {mergedError ?? '未找到知识库'}
      </Alert>
    );
  }

  return (
    <Box>
      <PageHeader
        title={kb.name}
        subtitle='增量批次复用当前配置。'
        action={
          <Stack direction='row' spacing={1}>
            <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
              返回列表
            </Button>
            <Button variant='contained' onClick={() => router.push('/knowledge-bases/new')}>
              新建知识库
            </Button>
          </Stack>
        }
      />

      {mergedError && (
        <Alert severity='error' sx={{ mb: 2 }}>
          {mergedError}
        </Alert>
      )}

      <Paper variant='outlined' sx={{ p: 2, mb: 2 }}>
        <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
          <Chip label={'状态：' + knowledgeBaseStatusLabel(kb.status)} variant='outlined' />
          <Chip
            label={'可用性：' + readinessLabel(kb.readiness)}
            color={kb.readiness === 'ready' ? 'success' : 'warning'}
          />
          <Chip label={'配置版本：' + kb.current_config_version} variant='outlined' />
        </Stack>
      </Paper>

      <Paper variant='outlined' sx={{ p: 2.5, mb: 2 }}>
        <Stack spacing={2}>
          <Typography variant='h6'>统一文档输入</Typography>
          <Typography color='text.secondary' variant='body2'>
            支持文本/URL/文件混合导入，每 2 秒刷新进度。
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
            <Button variant='contained' onClick={submitBatch} loading={submitPending} disabled={batchRunning}>
              提交批次
            </Button>
            <Button
              variant='outlined'
              onClick={retryFailedDocs}
              disabled={!batchId || !hasRetryableFailedDocs || retryBatchMutation.isPending}
              loading={retryBatchMutation.isPending}
            >
              重试失败文档
            </Button>
            <Button
              variant='outlined'
              onClick={cancelBatch}
              disabled={!batchId || !batchRunning || cancelBatchMutation.isPending}
              loading={cancelBatchMutation.isPending}
            >
              取消批次
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {currentBatch && (
        <Paper variant='outlined' sx={{ p: 2.5 }}>
          <Stack spacing={1.5}>
            <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
              <Chip label={'批次：' + currentBatch.id} variant='outlined' />
              <Chip label={batchStatusLabel(currentBatch.status)} color={batchStatusColor(currentBatch.status)} />
              <Chip label={'进度：' + currentBatch.progress_percent + '%'} variant='outlined' />
            </Stack>

            <Typography variant='body2' color='text.secondary'>
              {
                '文档：成功 ' +
                currentBatch.succeeded_docs +
                ' / 失败 ' +
                currentBatch.failed_docs +
                ' / 取消 ' +
                currentBatch.canceled_docs
              }
            </Typography>

            {currentBatch.docs.length > 0 && (
              <Paper variant='outlined' sx={{ p: 1.5 }}>
                <Stack spacing={1}>
                  {currentBatch.docs.map((doc) => (
                    <Stack
                      key={doc.id}
                      direction={{ xs: 'column', sm: 'row' }}
                      justifyContent='space-between'
                      sx={{ borderBottom: '1px solid', borderColor: 'divider', pb: 1 }}
                    >
                      <Box>
                        <Typography variant='body2' fontWeight={600}>
                          {doc.title || doc.id}
                        </Typography>
                        <Typography variant='caption' color='text.secondary'>
                          {sourceTypeLabel(doc.source_type) + ' · 重试 ' + doc.retry_count}
                        </Typography>
                      </Box>
                      <Stack direction='row' spacing={1} alignItems='center'>
                        <Chip label={docStatusLabel(doc.status)} size='small' variant='outlined' />
                        {doc.error_message && (
                          <Typography variant='caption' color='error.main'>
                            {doc.error_message}
                          </Typography>
                        )}
                      </Stack>
                    </Stack>
                  ))}
                </Stack>
              </Paper>
            )}
          </Stack>
        </Paper>
      )}
    </Box>
  );
}


