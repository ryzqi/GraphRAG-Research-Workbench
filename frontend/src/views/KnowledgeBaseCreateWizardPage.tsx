/**
 * Knowledge base creation wizard (3 fixed steps)
 */

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  Alert,
  Box,
  Chip,
  Paper,
  Stack,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
} from '@mui/material';
import { Button } from '../components/ui/Button';
import { PageHeader } from '../components/ui/PageHeader';
import {
  IngestionManifestEditor,
  createEmptyManifestEntry,
  validateManifestDraftEntries,
  type ManifestDraftEntry,
} from '../components/IngestionManifestEditor';
import { IndexConfigForm } from '../components/IndexConfigForm';
import {
  useCancelIngestionBatch,
  useCreateIngestionBatch,
  useIngestionBatch,
  useRetryIngestionBatch,
} from '../hooks/queries/useIngestionBatches';
import { useCreateKnowledgeBase } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import { validateIndexConfig } from '../lib/indexConfig';
import { HttpError } from '../services/http';
import {
  type EntryError,
  type ManifestEntry,
  type BatchStatus,
} from '../services/ingestionBatches';
import {
  createDefaultIndexConfig,
  type IndexConfig,
  type KnowledgeBaseCreate,
} from '../services/knowledgeBases';
import { runWithConcurrency } from '../lib/runWithConcurrency';
import { uploadMaterial } from '../services/materials';

const MAX_PARALLEL_UPLOADS = 4;

const STEPS = ['Configure', 'Documents', 'Submit'];

function mapEntryErrors(errors: EntryError[]): Record<string, string[]> {
  const mapped: Record<string, string[]> = {};
  for (const err of errors) {
    mapped[err.entry_id] = mapped[err.entry_id] ?? [];
    mapped[err.entry_id].push(err.message);
  }
  return mapped;
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

export default function KnowledgeBaseCreateWizardPage() {
  const router = useRouter();
  const [activeStep, setActiveStep] = useState(0);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [indexConfig, setIndexConfig] = useState<IndexConfig>(createDefaultIndexConfig());
  const [entries, setEntries] = useState<ManifestDraftEntry[]>([
    createEmptyManifestEntry('text'),
  ]);
  const [serverEntryErrors, setServerEntryErrors] = useState<Record<string, string[]>>({});
  const [createdKbId, setCreatedKbId] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [uploadingFiles, setUploadingFiles] = useState(false);

  const createKbMutation = useCreateKnowledgeBase();
  const createBatchMutation = useCreateIngestionBatch();
  const retryBatchMutation = useRetryIngestionBatch();
  const cancelBatchMutation = useCancelIngestionBatch();
  const batchQuery = useIngestionBatch(batchId ?? undefined);

  const currentBatch = batchQuery.data;
  const markdownOnly = indexConfig.chunking.general_strategy === 'markdown_heading';

  const validation = useMemo(
    () => validateManifestDraftEntries(entries, { markdownOnly }),
    [entries, markdownOnly]
  );

  const configErrors = useMemo(() => validateIndexConfig(indexConfig), [indexConfig]);
  const canProceedStep1 = name.trim().length > 0 && configErrors.length === 0;
  const canProceedStep2 =
    validation.globalErrors.length === 0 && validation.normalizedValidEntries.length > 0;
  const submitPending = createKbMutation.isPending || createBatchMutation.isPending || uploadingFiles;

  const mergedError =
    localError ??
    (createKbMutation.error ? getErrorMessage(createKbMutation.error) : null) ??
    (createBatchMutation.error ? getErrorMessage(createBatchMutation.error) : null) ??
    (batchQuery.error ? getErrorMessage(batchQuery.error) : null) ??
    (retryBatchMutation.error ? getErrorMessage(retryBatchMutation.error) : null) ??
    (cancelBatchMutation.error ? getErrorMessage(cancelBatchMutation.error) : null);

  const goToStep = (nextStep: number) => {
    setLocalError(null);
    if (nextStep <= activeStep) {
      setActiveStep(nextStep);
      return;
    }

    if (nextStep === 1 && !canProceedStep1) {
      setLocalError('Complete step 1 and fix index config errors first.');
      return;
    }

    if (nextStep === 2 && !canProceedStep2) {
      setLocalError('Keep at least one valid entry before submit.');
      return;
    }

    setActiveStep(nextStep);
  };

  const buildManifestEntries = async (kbId: string) => {
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
            const uploaded = await uploadMaterial(
              kbId,
              entry.title ?? entry.file.name,
              entry.file
            );
            return { entryId: entry.id, materialId: uploaded.id };
          } catch (error) {
            return { entryId: entry.id, error: getErrorMessage(error) };
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
          uploadErrors[entry.id] = ['File upload result missing'];
          continue;
        }
        if ('error' in uploadResult) {
          uploadErrors[entry.id] = [uploadResult.error];
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
    setLocalError(null);
    setServerEntryErrors({});

    if (!canProceedStep1 || !canProceedStep2) {
      setLocalError('Please complete the first two steps.');
      return;
    }

    try {
      let kbId = createdKbId;
      if (!kbId) {
        const tags = tagsInput
          .split(',')
          .map((item) => item.trim())
          .filter(Boolean);

        const payload: KnowledgeBaseCreate = {
          name: name.trim(),
          description: description.trim() || undefined,
          tags: tags.length > 0 ? tags : undefined,
          index_config: indexConfig,
        };

        const created = await createKbMutation.mutateAsync(payload);
        kbId = created.id;
        setCreatedKbId(created.id);
      }

      const { manifestEntries, uploadErrors } = await buildManifestEntries(kbId);

      if (manifestEntries.length === 0) {
        setServerEntryErrors(uploadErrors);
        setLocalError('No valid entries to submit.');
        return;
      }

      const response = await createBatchMutation.mutateAsync({
        kb_id: kbId,
        entries: manifestEntries,
      });

      const backendErrors = mapEntryErrors(response.entry_errors);
      setServerEntryErrors(mergeEntryErrors(uploadErrors, backendErrors));
      setBatchId(response.batch_id);
      setActiveStep(2);
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

  const batchRunning = currentBatch?.status === 'queued' || currentBatch?.status === 'running';
  const hasRetryableFailedDocs =
    currentBatch?.docs.some((doc) => doc.status === 'failed' && doc.retryable) ?? false;

  return (
    <Box>
      <PageHeader
        title='Create Knowledge Base'
        subtitle='Fixed 3 steps: Configure -> Documents -> Submit'
        action={
          <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
            Back to list
          </Button>
        }
      />

      <Paper variant='outlined' sx={{ p: 2.5, mb: 2.5 }}>
        <Stepper activeStep={activeStep} alternativeLabel>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>
      </Paper>

      {mergedError && (
        <Alert severity='error' sx={{ mb: 2 }}>
          {mergedError}
        </Alert>
      )}

      {activeStep === 0 && (
        <Paper variant='outlined' sx={{ p: 2.5 }}>
          <Stack spacing={2}>
            <Typography variant='h6'>Step 1: Configure</Typography>

            <TextField
              label='Name'
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              inputProps={{ maxLength: 64 }}
              fullWidth
            />
            <TextField
              label='Description'
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              inputProps={{ maxLength: 500 }}
              multiline
              minRows={3}
              fullWidth
            />
            <TextField
              label='Tags'
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder='Comma-separated tags'
              fullWidth
            />

            <IndexConfigForm value={indexConfig} onChange={setIndexConfig} />

            {configErrors.length > 0 && (
              <Alert severity='warning' variant='outlined'>
                {'Index config validation failed: ' + configErrors.join('; ')}
              </Alert>
            )}

            <Stack direction='row' justifyContent='space-between' sx={{ pt: 1 }}>
              <Box />
              <Button variant='contained' onClick={() => goToStep(1)} disabled={!canProceedStep1}>
                Next: Documents
              </Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      {activeStep === 1 && (
        <Paper variant='outlined' sx={{ p: 2.5 }}>
          <Stack spacing={2}>
            <Typography variant='h6'>Step 2: Documents</Typography>
            <Typography color='text.secondary' variant='body2'>
              Mixed text/url/file entries are supported. Going back keeps your draft.
            </Typography>

            <IngestionManifestEditor
              entries={entries}
              onChange={setEntries}
              validation={validation}
              serverEntryErrors={serverEntryErrors}
              markdownOnly={markdownOnly}
            />

            <Stack direction='row' justifyContent='space-between' sx={{ pt: 1 }}>
              <Button variant='outlined' onClick={() => goToStep(0)}>
                Back
              </Button>
              <Button variant='contained' onClick={() => goToStep(2)} disabled={!canProceedStep2}>
                Next: Submit
              </Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      {activeStep === 2 && (
        <Stack spacing={2}>
          <Paper variant='outlined' sx={{ p: 2.5 }}>
            <Stack spacing={1.5}>
              <Typography variant='h6'>Step 3: Submit</Typography>
              <Typography color='text.secondary' variant='body2'>
                A first bootstrap batch will be created and polled every 2 seconds.
              </Typography>

              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                {createdKbId && <Chip label={'KB ID: ' + createdKbId} variant='outlined' />}
                {currentBatch && (
                  <Chip
                    label={'Batch: ' + batchStatusLabel(currentBatch.status)}
                    color={batchStatusColor(currentBatch.status)}
                  />
                )}
              </Stack>

              {currentBatch && (
                <Paper variant='outlined' sx={{ p: 1.5, bgcolor: 'background.default' }}>
                  <Stack spacing={1}>
                    <Typography variant='body2'>
                      {'Progress: ' + currentBatch.progress_percent + '%'}
                    </Typography>
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
                    <Typography variant='body2' color='text.secondary'>
                      {'Succeeded chunks: ' + currentBatch.succeeded_chunks}
                    </Typography>
                  </Stack>
                </Paper>
              )}

              {currentBatch && currentBatch.docs.length > 0 && (
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

              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Button variant='outlined' onClick={() => goToStep(1)} disabled={submitPending || batchRunning}>
                  Back to documents
                </Button>
                <Button variant='contained' onClick={submitBatch} loading={submitPending} disabled={batchRunning}>
                  {createdKbId ? 'Submit next batch' : 'Create and submit'}
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
                {createdKbId && (
                  <Button variant='text' onClick={() => router.push('/knowledge-bases/' + createdKbId)}>
                    Open KB detail
                  </Button>
                )}
              </Stack>
            </Stack>
          </Paper>
        </Stack>
      )}
    </Box>
  );
}


