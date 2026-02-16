'use client';

/**
 * 知识库创建向导（固定 3 步）
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

const STEPS = ['配置', '文档', '提交'];

function sourceTypeLabel(sourceType: ManifestEntry['source_type']): string {
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
    case 'processing':
      return '处理中';
    case 'completed':
      return '已完成';
    default:
      return status;
  }
}

function docStatusLabel(status: string): string {
  switch (status) {
    case 'processing':
      return '处理中';
    case 'completed':
      return '已完成';
    default:
      return status;
  }
}

function isDocFailed(doc: { status: string; error_code: string | null }): boolean {
  return doc.status === 'completed' && doc.error_code !== null && doc.error_code !== 'DOC_CANCELED';
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

export default function KnowledgeBaseCreateWizardPage() {
  const router = useRouter();
  const [activeStep, setActiveStep] = useState(0);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [indexConfig, setIndexConfig] = useState<IndexConfig>(createDefaultIndexConfig());
  const [entries, setEntries] = useState<ManifestDraftEntry[]>([]);
  const [serverEntryErrors, setServerEntryErrors] = useState<Record<string, string[]>>({});
  const [createdKbId, setCreatedKbId] = useState<string | null>(null);
  const [batchId, setBatchId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [uploadingFiles, setUploadingFiles] = useState(false);

  const createKbMutation = useCreateKnowledgeBase();
  const createBatchMutation = useCreateIngestionBatch({ invalidateMode: 'background' });
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
      setLocalError('请先完成第 1 步并修复索引配置错误。');
      return;
    }

    if (nextStep === 2 && !canProceedStep2) {
      setLocalError('提交前请至少保留一个有效条目。');
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
          uploadErrors[entry.id] = ['缺少文件上传结果'];
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
    setLocalError(null);
    setServerEntryErrors({});

    if (!canProceedStep1 || !canProceedStep2) {
      setLocalError('请先完成前两步。');
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

      void router.prefetch(`/knowledge-bases/${kbId}`);

      const { manifestEntries, uploadErrors } = await buildManifestEntries(kbId);

      if (manifestEntries.length === 0) {
        setServerEntryErrors(uploadErrors);
        setLocalError('没有可提交的有效条目。');
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
      router.push(`/knowledge-bases/${kbId}/documents/new?batch=${response.batch_id}`);
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

  const batchRunning = currentBatch?.status === 'processing';
  const hasRetryableFailedDocs =
    currentBatch?.docs.some((doc) => isDocFailed(doc) && doc.retryable) ?? false;

  return (
    <Box>
      <PageHeader
        title='新建知识库'
        subtitle='固定 3 步：配置 -> 文档 -> 提交'
        action={
          <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
            返回列表
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
            <Typography variant='h6'>第 1 步：配置</Typography>

            <TextField
              label='名称'
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              inputProps={{ maxLength: 64 }}
              fullWidth
            />
            <TextField
              label='描述'
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              inputProps={{ maxLength: 500 }}
              multiline
              minRows={3}
              fullWidth
            />
            <TextField
              label='标签'
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder='多个标签请用逗号分隔'
              fullWidth
            />

            <IndexConfigForm value={indexConfig} onChange={setIndexConfig} />

            {configErrors.length > 0 && (
              <Alert severity='warning' variant='outlined'>
                {'索引配置校验失败：' + configErrors.join('；')}
              </Alert>
            )}

            <Stack direction='row' justifyContent='space-between' sx={{ pt: 1 }}>
              <Box />
              <Button variant='contained' onClick={() => goToStep(1)} disabled={!canProceedStep1}>
                下一步：文档
              </Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      {activeStep === 1 && (
        <Paper variant='outlined' sx={{ p: 2.5 }}>
          <Stack spacing={2}>
            <Typography variant='h6'>第 2 步：文档</Typography>
            <Typography color='text.secondary' variant='body2'>
              支持混合文本/URL/文件条目。返回上一步会保留当前草稿。
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
                上一步
              </Button>
              <Button variant='contained' onClick={() => goToStep(2)} disabled={!canProceedStep2}>
                下一步：提交
              </Button>
            </Stack>
          </Stack>
        </Paper>
      )}

      {activeStep === 2 && (
        <Stack spacing={2}>
          <Paper variant='outlined' sx={{ p: 2.5 }}>
            <Stack spacing={1.5}>
              <Typography variant='h6'>第 3 步：提交</Typography>
              <Typography color='text.secondary' variant='body2'>
                将创建首个初始化批次，并每 2 秒轮询一次状态。
              </Typography>

              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                {createdKbId && <Chip label={'知识库 ID：' + createdKbId} variant='outlined' />}
                {currentBatch && (
                  <Chip
                    label={'批次：' + batchStatusLabel(currentBatch.status)}
                    color={batchStatusColor(currentBatch.status)}
                  />
                )}
              </Stack>

              {currentBatch && (
                <Paper variant='outlined' sx={{ p: 1.5, bgcolor: 'background.default' }}>
                  <Stack spacing={1}>
                    <Typography variant='body2'>
                      {'批次状态：' + batchStatusLabel(currentBatch.status)}
                    </Typography>
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
                    <Typography variant='body2' color='text.secondary'>
                      {'成功分块数：' + currentBatch.succeeded_chunks}
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
                            {sourceTypeLabel(doc.source_type) +
                              ' · 重试次数 ' +
                              doc.retry_count +
                              ' · 上下文降级 ' +
                              (doc.context_failed_chunks?.length ?? 0)}
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

              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Button variant='outlined' onClick={() => goToStep(1)} disabled={submitPending || batchRunning}>
                  返回文档
                </Button>
                <Button variant='contained' onClick={submitBatch} loading={submitPending} disabled={batchRunning}>
                  {createdKbId ? '提交下一批' : '创建并提交'}
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
                {createdKbId && (
                  <Button variant='text' onClick={() => router.push('/knowledge-bases/' + createdKbId)}>
                    打开知识库详情
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
