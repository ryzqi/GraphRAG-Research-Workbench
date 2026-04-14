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
  type NormalizedManifestDraftEntry,
} from '../components/IngestionManifestEditor';
import { IndexConfigForm } from '../components/IndexConfigForm';
import {
  useCreateBootstrapKnowledgeBase,
} from '../hooks/queries/useBootstrapSubmissions';
import { getErrorMessage } from '../lib/errorHandler';
import { validateIndexConfig } from '../lib/indexConfig';
import { buildBootstrapSubmissionManifestEntries } from '../lib/manifestBuilders';
import {
  setBootstrapPendingUploadSession,
} from '../services/bootstrapUploadSession';
import {
  createDefaultIndexConfig,
  type IndexConfig,
  type KnowledgeBaseCreate,
} from '../services/knowledgeBases';

const STEPS = ['配置', '文档', '提交'];

function countByType(
  entries: NormalizedManifestDraftEntry[],
  sourceType: NormalizedManifestDraftEntry['sourceType']
): number {
  return entries.filter((entry) => entry.sourceType === sourceType).length;
}

export default function KnowledgeBaseCreateWizardPage() {
  const router = useRouter();
  const [activeStep, setActiveStep] = useState(0);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [tagsInput, setTagsInput] = useState('');
  const [indexConfig, setIndexConfig] = useState<IndexConfig>(createDefaultIndexConfig());
  const [entries, setEntries] = useState<ManifestDraftEntry[]>([]);
  const [createdKbId, setCreatedKbId] = useState<string | null>(null);
  const [localError, setLocalError] = useState<string | null>(null);
  const [preparingSubmit, setPreparingSubmit] = useState(false);

  const createBootstrapKbMutation = useCreateBootstrapKnowledgeBase({ invalidateMode: 'background' });

  const markdownOnly = indexConfig.chunking.general_strategy === 'markdown_heading';
  const validation = useMemo(
    () => validateManifestDraftEntries(entries, { markdownOnly }),
    [entries, markdownOnly]
  );
  const configErrors = useMemo(() => validateIndexConfig(indexConfig), [indexConfig]);
  const canProceedStep1 = name.trim().length > 0 && configErrors.length === 0;
  const canProceedStep2 =
    validation.globalErrors.length === 0 && validation.normalizedValidEntries.length > 0;
  const submitPending = createBootstrapKbMutation.isPending || preparingSubmit;

  const mergedError =
    localError ??
    (createBootstrapKbMutation.error ? getErrorMessage(createBootstrapKbMutation.error) : null);

  const goToStep = async (nextStep: number) => {
    setLocalError(null);

    if (nextStep <= activeStep) {
      if (nextStep === 0 && createdKbId) {
        setLocalError('知识库已创建，基础配置不可再修改。');
        return;
      }
      setActiveStep(nextStep);
      return;
    }

    if (nextStep === 1 && !canProceedStep1) {
      setLocalError('请先完成第 1 步并修复索引配置错误。');
      return;
    }

    if (nextStep === 2) {
      if (!canProceedStep2) {
        setLocalError('提交前请至少保留一个有效条目。');
        return;
      }
      if (createdKbId) {
        void router.prefetch(`/knowledge-bases/${createdKbId}/documents/new`);
      }
    }

    setActiveStep(nextStep);
  };

  const submitBatch = async () => {
    setLocalError(null);
    if (!canProceedStep1 || !canProceedStep2) {
      setLocalError('请先完成前两步。');
      return;
    }

    setPreparingSubmit(true);
    try {
      const tags = tagsInput
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean);
      const kbPayload: KnowledgeBaseCreate = {
        name: name.trim(),
        description: description.trim() || undefined,
        tags: tags.length > 0 ? tags : undefined,
        index_config: indexConfig,
      };
      const { manifestEntries, pendingUploadFiles } = buildBootstrapSubmissionManifestEntries(
        validation.normalizedValidEntries
      );
      if (manifestEntries.length === 0) {
        setLocalError('没有可提交的有效条目。');
        return;
      }

      const response = await createBootstrapKbMutation.mutateAsync({
        kb: kbPayload,
        entries: manifestEntries,
      });
      setCreatedKbId(response.kb_id);

      if (pendingUploadFiles.length > 0) {
        if (!response.job_id) {
          throw new Error('缺少 bootstrap job_id，无法进入文件上传流程');
        }
        setBootstrapPendingUploadSession(response.job_id, {
          files: pendingUploadFiles,
        });
        router.push(`/knowledge-bases/${response.kb_id}/documents/new?job=${response.job_id}`);
        return;
      }

      if (!response.batch_id) {
        throw new Error('缺少 ingestion batch_id，无法进入文档处理页');
      }
      router.push(`/knowledge-bases/${response.kb_id}/documents/new?batch=${response.batch_id}`);
    } catch (error) {
      setLocalError(getErrorMessage(error));
    } finally {
      setPreparingSubmit(false);
    }
  };

  const handleEntriesChange = (nextEntries: ManifestDraftEntry[]) => {
    setEntries(nextEntries);
    setLocalError(null);
  };

  return (
    <Box>
      <PageHeader
        title='新建知识库'
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
              disabled={Boolean(createdKbId)}
              fullWidth
            />
            <TextField
              label='描述'
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              inputProps={{ maxLength: 500 }}
              multiline
              minRows={3}
              disabled={Boolean(createdKbId)}
              fullWidth
            />
            <TextField
              label='标签'
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder='多个标签请用逗号分隔'
              disabled={Boolean(createdKbId)}
              fullWidth
            />

            <IndexConfigForm
              value={indexConfig}
              onChange={(nextConfig) => {
                setIndexConfig(nextConfig);
              }}
              disabled={Boolean(createdKbId)}
            />

            {createdKbId && (
              <Alert severity='info' variant='outlined'>
                已创建知识库，基础配置已锁定。若需修改请返回列表后重新创建。
              </Alert>
            )}

            {configErrors.length > 0 && (
              <Alert severity='warning' variant='outlined'>
                {'索引配置校验失败：' + configErrors.join('；')}
              </Alert>
            )}

            <Stack direction='row' justifyContent='space-between' sx={{ pt: 1 }}>
              <Box />
              <Button variant='contained' onClick={() => void goToStep(1)} disabled={!canProceedStep1 || submitPending}>
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
              支持混合文本/URL/文件条目。点击创建后将立即跳转，并在下一页执行文件上传与处理。
            </Typography>

            <IngestionManifestEditor
              entries={entries}
              onChange={handleEntriesChange}
              validation={validation}
              markdownOnly={markdownOnly}
              disabled={submitPending}
            />

            <Stack direction='row' justifyContent='space-between' sx={{ pt: 1 }}>
              <Button variant='outlined' onClick={() => void goToStep(0)} disabled={Boolean(createdKbId) || submitPending}>
                上一步
              </Button>
              <Button variant='contained' onClick={() => void goToStep(2)} disabled={!canProceedStep2 || submitPending}>
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
                点击后会立即跳转到处理页，文件上传与任务状态会在下一页实时展示。
              </Typography>

              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                {createdKbId && <Chip label={'知识库 ID：' + createdKbId} variant='outlined' />}
                <Chip label={'待处理条目：' + validation.normalizedValidEntries.length} color='info' variant='outlined' />
                <Chip label={'文本 ' + countByType(validation.normalizedValidEntries, 'text')} variant='outlined' />
                <Chip label={'URL ' + countByType(validation.normalizedValidEntries, 'url')} variant='outlined' />
                <Chip label={'文件 ' + countByType(validation.normalizedValidEntries, 'file')} variant='outlined' />
              </Stack>

              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Button variant='outlined' onClick={() => void goToStep(1)} disabled={submitPending}>
                  返回文档
                </Button>
                <Button variant='contained' onClick={submitBatch} loading={submitPending}>
                  创建并开始处理
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
