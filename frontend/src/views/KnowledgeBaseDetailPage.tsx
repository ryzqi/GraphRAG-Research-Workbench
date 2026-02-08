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
import type { EntryError, ManifestEntry, BatchStatus } from '../services/ingestionBatches';
import { HttpError } from '../services/http';
import { uploadMaterial } from '../services/materials';

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
      return 'Queued';
    case 'running':
      return 'Running';
    case 'succeeded':
      return 'Succeeded';
    case 'partial_failed':
      return 'Partial failed';
    case 'failed':
      return 'Failed';
    case 'canceled':
      return 'Canceled';
    default:
      return status;
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

    setUploadingFiles(true);
    try {
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

        try {
          const uploaded = await uploadMaterial(kbId, entry.title ?? entry.file.name, entry.file);
          manifestEntries.push({
            source_type: 'file',
            entry_id: entry.id,
            title: entry.title,
            material_id: uploaded.id,
          });
        } catch (error) {
          uploadErrors[entry.id] = [getErrorMessage(error)];
        }
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
      setLocalError('Please fix entry issues before submit.');
      return;
    }

    try {
      const { manifestEntries, uploadErrors } = await buildManifestEntries();

      if (manifestEntries.length === 0) {
        setServerEntryErrors(uploadErrors);
        setLocalError('No valid entries to submit.');
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
    return <LoadingSpinner text='Loading knowledge base...' />;
  }

  if (!kb) {
    return (
      <Alert severity='error'>
        {mergedError ?? 'Knowledge base not found'}
      </Alert>
    );
  }

  return (
    <Box>
      <PageHeader
        title={kb.name}
        subtitle='Incremental batches always reuse current config version.'
        action={
          <Stack direction='row' spacing={1}>
            <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
              Back to list
            </Button>
            <Button variant='contained' onClick={() => router.push('/knowledge-bases/new')}>
              New wizard
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
          <Chip label={'Status: ' + kb.status} variant='outlined' />
          <Chip label={'Readiness: ' + kb.readiness} color={kb.readiness === 'ready' ? 'success' : 'warning'} />
          <Chip label={'Config version: ' + kb.current_config_version} variant='outlined' />
        </Stack>
      </Paper>

      <Paper variant='outlined' sx={{ p: 2.5, mb: 2 }}>
        <Stack spacing={2}>
          <Typography variant='h6'>Unified document input</Typography>
          <Typography color='text.secondary' variant='body2'>
            Mixed text/url/file entries are supported. Batch progress is polled every 2 seconds.
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
              Submit batch
            </Button>
            <Button
              variant='outlined'
              onClick={retryFailedDocs}
              disabled={!batchId || !hasRetryableFailedDocs || retryBatchMutation.isPending}
              loading={retryBatchMutation.isPending}
            >
              Retry failed docs
            </Button>
            <Button
              variant='outlined'
              onClick={cancelBatch}
              disabled={!batchId || !batchRunning || cancelBatchMutation.isPending}
              loading={cancelBatchMutation.isPending}
            >
              Cancel batch
            </Button>
          </Stack>
        </Stack>
      </Paper>

      {currentBatch && (
        <Paper variant='outlined' sx={{ p: 2.5 }}>
          <Stack spacing={1.5}>
            <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
              <Chip label={'Batch: ' + currentBatch.id} variant='outlined' />
              <Chip label={batchStatusLabel(currentBatch.status)} color={batchStatusColor(currentBatch.status)} />
              <Chip label={'Progress: ' + currentBatch.progress_percent + '%'} variant='outlined' />
            </Stack>

            <Typography variant='body2' color='text.secondary'>
              {
                'Docs: success ' +
                currentBatch.succeeded_docs +
                ' / failed ' +
                currentBatch.failed_docs +
                ' / canceled ' +
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
                          {doc.source_type + ' · retries ' + doc.retry_count}
                        </Typography>
                      </Box>
                      <Stack direction='row' spacing={1} alignItems='center'>
                        <Chip label={doc.status} size='small' variant='outlined' />
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


