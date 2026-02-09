'use client';

/**
 * Knowledge base detail page (manifest submit + batch polling)
 */

import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter, useSearchParams } from 'next/navigation';
import {
  Alert,
  Box,
  Chip,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  LinearProgress,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import { Button } from '../components/ui/Button';
import {
  IngestionManifestEditor,
  createEmptyManifestEntry,
  validateManifestDraftEntries,
  type ManifestDraftEntry,
} from '../components/IngestionManifestEditor';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import { ListSkeleton } from '../components/ui/Skeleton';
import {
  useCancelIngestionBatch,
  useCreateIngestionBatch,
  useIngestionBatchLive,
  useRetryIngestionBatch,
} from '../hooks/queries/useIngestionBatches';
import {
  useMaterialChunkDetail,
  useMaterialChunks,
  useMaterialsWithChunkStats,
} from '../hooks/queries/useMaterialChunks';
import { useKnowledgeBase, useKnowledgeBaseIngestionState } from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import { runWithConcurrency } from '../lib/runWithConcurrency';
import { uploadMaterial } from '../services/materials';
import type {
  EntryError,
  ManifestEntry,
  BatchStatus,
  DocStatus,
  ManifestSourceType,
} from '../services/ingestionBatches';
import type {
  DocumentChunk,
  SourceMaterialWithChunkStats,
} from '../services/materialChunks';
import { HttpError } from '../services/http';

const MAX_PARALLEL_UPLOADS = 4;

type MobilePanel = 'docs' | 'chunks' | 'content';

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

function chunkPreview(text: string, max = 92): string {
  const compact = text.replace(/\s+/g, ' ').trim();
  if (compact.length <= max) {
    return compact;
  }
  return compact.slice(0, max) + '…';
}

function formatLocatorValue(value: unknown): string {
  if (value === null || value === undefined) {
    return '-';
  }
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return String(value);
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function ChunkBrowserSection({
  kbId,
  browseLocked,
  browseLockMessage,
}: {
  kbId: string;
  browseLocked: boolean;
  browseLockMessage: string | null;
}) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>('docs');
  const [materialFilter, setMaterialFilter] = useState('');
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);

  const materialsQuery = useMaterialsWithChunkStats(kbId, { skip: 0, limit: 100 });
  const materials = useMemo(() => materialsQuery.data ?? [], [materialsQuery.data]);

  const filteredMaterials = useMemo(() => {
    const q = materialFilter.trim().toLowerCase();
    if (!q) {
      return materials;
    }
    return materials.filter((item) => item.title.toLowerCase().includes(q));
  }, [materials, materialFilter]);

  useEffect(() => {
    if (filteredMaterials.length === 0) {
      setSelectedMaterialId(null);
      return;
    }

    if (!selectedMaterialId) {
      setSelectedMaterialId(filteredMaterials[0].id);
      return;
    }

    const exists = filteredMaterials.some((item) => item.id === selectedMaterialId);
    if (!exists) {
      setSelectedMaterialId(filteredMaterials[0].id);
    }
  }, [filteredMaterials, selectedMaterialId]);

  const chunksQuery = useMaterialChunks(kbId, selectedMaterialId ?? '', {
    skip: 0,
    limit: 100,
    enabled: !browseLocked,
  });
  const chunks = useMemo(
    () => (browseLocked ? [] : chunksQuery.data ?? []),
    [browseLocked, chunksQuery.data]
  );

  useEffect(() => {
    if (browseLocked) {
      setSelectedChunkId(null);
      return;
    }

    if (chunks.length === 0) {
      setSelectedChunkId(null);
      return;
    }

    if (!selectedChunkId) {
      setSelectedChunkId(chunks[0].id);
      return;
    }

    const exists = chunks.some((item) => item.id === selectedChunkId);
    if (!exists) {
      setSelectedChunkId(chunks[0].id);
    }
  }, [browseLocked, chunks, selectedChunkId]);

  const chunkDetailQuery = useMaterialChunkDetail(kbId, selectedMaterialId ?? '', selectedChunkId, {
    enabled: !browseLocked,
  });
  const selectedChunk = browseLocked
    ? null
    : chunkDetailQuery.data ?? chunks.find((item) => item.id === selectedChunkId) ?? null;

  const selectedMaterial = filteredMaterials.find((item) => item.id === selectedMaterialId) ?? null;

  const sectionError =
    (materialsQuery.error ? getErrorMessage(materialsQuery.error) : null) ??
    (!browseLocked && chunksQuery.error ? getErrorMessage(chunksQuery.error) : null) ??
    (!browseLocked && chunkDetailQuery.error ? getErrorMessage(chunkDetailQuery.error) : null);

  const onSelectMaterial = (item: SourceMaterialWithChunkStats) => {
    setSelectedMaterialId(item.id);
    setSelectedChunkId(null);
    if (isMobile) {
      setMobilePanel('chunks');
    }
  };

  const onSelectChunk = (item: DocumentChunk) => {
    setSelectedChunkId(item.id);
    if (isMobile) {
      setMobilePanel('content');
    }
  };

  const panelBaseSx = {
    p: 2,
    minHeight: 460,
  } as const;

  return (
    <Paper variant='outlined' sx={{ mt: 2, overflow: 'hidden' }}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        justifyContent='space-between'
        spacing={1}
        sx={{ p: 2, borderBottom: 1, borderColor: 'divider', bgcolor: 'background.paper' }}
      >
        <Box>
          <Typography variant='h6'>文档分块浏览</Typography>
          <Typography variant='body2' color='text.secondary'>
            左侧选择文档，中间浏览分块，右侧查看完整内容与定位信息。
          </Typography>
        </Box>
        <Chip
          label={`文档 ${filteredMaterials.length} · 分块 ${chunks.length}`}
          size='small'
          variant='outlined'
          sx={{ alignSelf: { xs: 'flex-start', md: 'center' } }}
        />
      </Stack>

      {sectionError && (
        <Alert severity='error' sx={{ m: 2 }}>
          {sectionError}
        </Alert>
      )}

      {browseLocked && (
        <Alert severity='info' sx={{ m: 2, mb: 0 }}>
          {browseLockMessage ?? '当前知识库文档仍在处理中，待全部完成后再浏览分块。'}
        </Alert>
      )}

      <Box sx={{ display: { xs: 'block', md: 'none' }, borderBottom: 1, borderColor: 'divider' }}>
        <Tabs
          value={mobilePanel}
          onChange={(_, value: MobilePanel) => setMobilePanel(value)}
          variant='fullWidth'
        >
          <Tab value='docs' label='文档' />
          <Tab value='chunks' label='分块' />
          <Tab value='content' label='内容' />
        </Tabs>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            md: '300px 340px minmax(0, 1fr)',
          },
          bgcolor: 'background.default',
        }}
      >
        <Box
          sx={{
            ...panelBaseSx,
            display: { xs: mobilePanel === 'docs' ? 'block' : 'none', md: 'block' },
            borderRight: { md: 1 },
            borderColor: 'divider',
          }}
        >
          <TextField
            size='small'
            placeholder='筛选文档标题'
            value={materialFilter}
            onChange={(event) => setMaterialFilter(event.target.value)}
            fullWidth
            sx={{ mb: 1.5 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position='start'>
                  <SearchIcon fontSize='small' />
                </InputAdornment>
              ),
            }}
          />

          {materialsQuery.isPending ? (
            <ListSkeleton count={6} />
          ) : filteredMaterials.length === 0 ? (
            <Typography variant='body2' color='text.secondary'>
              暂无文档。
            </Typography>
          ) : (
            <List dense disablePadding sx={{ maxHeight: 380, overflowY: 'auto' }}>
              {filteredMaterials.map((item) => (
                <ListItemButton
                  key={item.id}
                  selected={item.id === selectedMaterialId}
                  onClick={() => onSelectMaterial(item)}
                  sx={{
                    mb: 0.75,
                    borderRadius: 2,
                    alignItems: 'flex-start',
                    border: 1,
                    borderColor: item.id === selectedMaterialId ? 'primary.main' : 'divider',
                    '&.Mui-selected': {
                      bgcolor: 'action.selected',
                    },
                  }}
                >
                  <ListItemText
                    primary={
                      <Typography variant='body2' fontWeight={600} noWrap>
                        {item.title || item.id}
                      </Typography>
                    }
                    secondary={
                      <Stack direction='row' spacing={0.75} sx={{ mt: 0.5 }}>
                        <Chip label={sourceTypeLabel(item.source_type)} size='small' variant='outlined' />
                        <Chip label={`${item.chunk_count} 块`} size='small' color='primary' variant='outlined' />
                      </Stack>
                    }
                  />
                </ListItemButton>
              ))}
            </List>
          )}
        </Box>

        <Box
          sx={{
            ...panelBaseSx,
            display: { xs: mobilePanel === 'chunks' ? 'block' : 'none', md: 'block' },
            borderRight: { md: 1 },
            borderColor: 'divider',
          }}
        >
          <Typography variant='subtitle2' color='text.secondary' sx={{ mb: 1 }}>
            {selectedMaterial ? selectedMaterial.title : '请先选择文档'}
          </Typography>

          {browseLocked ? (
            <Typography variant='body2' color='text.secondary'>
              文档处理中，暂不可浏览分块。
            </Typography>
          ) : !selectedMaterial ? (
            <Typography variant='body2' color='text.secondary'>
              先从左侧选择一个文档。
            </Typography>
          ) : chunksQuery.isPending ? (
            <ListSkeleton count={8} />
          ) : chunks.length === 0 ? (
            <Typography variant='body2' color='text.secondary'>
              该文档暂无分块。
            </Typography>
          ) : (
            <List dense disablePadding sx={{ maxHeight: 380, overflowY: 'auto' }}>
              {chunks.map((item) => (
                <ListItemButton
                  key={item.id}
                  selected={item.id === selectedChunkId}
                  onClick={() => onSelectChunk(item)}
                  sx={{
                    mb: 0.75,
                    borderRadius: 2,
                    alignItems: 'flex-start',
                    border: 1,
                    borderColor: item.id === selectedChunkId ? 'primary.main' : 'divider',
                    '&.Mui-selected': {
                      bgcolor: 'action.selected',
                    },
                  }}
                >
                  <ListItemText
                    primary={
                      <Typography variant='body2' fontWeight={600}>
                        #{item.chunk_index}
                      </Typography>
                    }
                    secondary={
                      <Typography variant='caption' color='text.secondary' sx={{ mt: 0.5 }}>
                        {chunkPreview(item.text)}
                      </Typography>
                    }
                  />
                </ListItemButton>
              ))}
            </List>
          )}
        </Box>

        <Box
          component='section'
          aria-live='polite'
          sx={{
            ...panelBaseSx,
            display: { xs: mobilePanel === 'content' ? 'block' : 'none', md: 'block' },
            minWidth: 0,
          }}
        >
          {browseLocked ? (
            <Typography variant='body2' color='text.secondary'>
              文档处理中，处理完成后可查看分块详情。
            </Typography>
          ) : !selectedChunk ? (
            <Typography variant='body2' color='text.secondary'>
              请选择一个分块查看详情。
            </Typography>
          ) : (
            <Stack spacing={1.5}>
              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Chip label={`Chunk #${selectedChunk.chunk_index}`} size='small' color='primary' />
                {selectedChunk.token_count != null && (
                  <Chip label={`Token ${selectedChunk.token_count}`} size='small' variant='outlined' />
                )}
                <Chip label={`创建于 ${new Date(selectedChunk.created_at).toLocaleString()}`} size='small' variant='outlined' />
              </Stack>

              <Paper
                variant='outlined'
                sx={{
                  p: 2,
                  maxHeight: 260,
                  overflowY: 'auto',
                  bgcolor: 'background.paper',
                }}
              >
                <Typography
                  variant='body2'
                  sx={{
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.7,
                    wordBreak: 'break-word',
                  }}
                >
                  {selectedChunk.text}
                </Typography>
              </Paper>

              <Paper variant='outlined' sx={{ p: 1.5, bgcolor: 'background.paper' }}>
                <Typography variant='subtitle2' sx={{ mb: 1 }}>
                  定位信息
                </Typography>
                {selectedChunk.locator && Object.keys(selectedChunk.locator).length > 0 ? (
                  <Stack spacing={0.75}>
                    {Object.entries(selectedChunk.locator).map(([key, value]) => (
                      <Stack key={key} direction='row' spacing={1} alignItems='flex-start'>
                        <Typography
                          variant='caption'
                          color='text.secondary'
                          sx={{ minWidth: 72, fontWeight: 600 }}
                        >
                          {key}
                        </Typography>
                        <Typography
                          variant='caption'
                          sx={{
                            whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {formatLocatorValue(value)}
                        </Typography>
                      </Stack>
                    ))}
                  </Stack>
                ) : (
                  <Typography variant='caption' color='text.secondary'>
                    暂无定位信息。
                  </Typography>
                )}
              </Paper>
            </Stack>
          )}
        </Box>
      </Box>
    </Paper>
  );
}

export default function KnowledgeBaseDetailPage() {
  const router = useRouter();
  const params = useParams<{ kbId: string }>();
  const searchParams = useSearchParams();
  const kbId = Array.isArray(params.kbId) ? params.kbId[0] : params.kbId;

  const initialBatchId = searchParams.get('batch') ?? undefined;

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const ingestionStateQuery = useKnowledgeBaseIngestionState(kbId ?? '');
  const createBatchMutation = useCreateIngestionBatch();
  const retryBatchMutation = useRetryIngestionBatch();
  const cancelBatchMutation = useCancelIngestionBatch();

  const [entries, setEntries] = useState<ManifestDraftEntry[]>([createEmptyManifestEntry('text')]);
  const [serverEntryErrors, setServerEntryErrors] = useState<Record<string, string[]>>({});
  const [preferredBatchId, setPreferredBatchId] = useState<string | undefined>(initialBatchId);
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
    batchId: preferredBatchId,
  });

  const kb = kbQuery.data ?? null;
  const currentBatch = liveBatchQuery.data;
  const activeBatchId = liveBatchQuery.resolvedBatchId ?? preferredBatchId ?? null;
  const ingestionState = ingestionStateQuery.data;

  const browseLocked =
    ingestionStateQuery.isPending ||
    Boolean(ingestionStateQuery.error) ||
    Boolean(ingestionState?.has_active_batch);
  const browseLockMessage = useMemo(() => {
    if (ingestionStateQuery.error) {
      return '无法确认文档处理状态，已暂时禁用分块浏览。';
    }
    if (!ingestionState) {
      return '正在同步文档处理状态，请稍后再浏览分块。';
    }
    if (!ingestionState.has_active_batch) {
      return null;
    }

    const activeDocs = ingestionState.pending_docs + ingestionState.running_docs;
    if (activeDocs > 0) {
      return `当前仍有 ${activeDocs} 个文档处理中，待全部完成后再浏览分块。`;
    }
    return '当前知识库文档仍在处理中，待全部完成后再浏览分块。';
  }, [ingestionState, ingestionStateQuery.error]);

  const markdownOnly = kb?.index_config?.chunking.general_strategy === 'markdown_heading';
  const validation = useMemo(
    () => validateManifestDraftEntries(entries, { markdownOnly: Boolean(markdownOnly) }),
    [entries, markdownOnly]
  );

  const submitPending = createBatchMutation.isPending || uploadingFiles;
  const batchRunning = currentBatch?.status === 'queued' || currentBatch?.status === 'running';
  const hasRetryableFailedDocs =
    currentBatch?.docs.some((doc) => doc.status === 'failed' && doc.retryable) ?? false;

  const streamHint = useMemo(() => {
    if (!activeBatchId || !currentBatch) {
      return null;
    }

    if (liveBatchQuery.streamStatus === 'connecting') {
      return '正在建立实时进度连接…';
    }
    if (liveBatchQuery.streamStatus === 'live') {
      return '实时进度已连接。';
    }
    if (liveBatchQuery.streamStatus === 'fallback_polling') {
      return `实时连接中断，已切换轮询（每 ${Math.round(liveBatchQuery.fallbackIntervalMs / 1000)} 秒）。`;
    }
    return '正在等待处理状态更新。';
  }, [activeBatchId, currentBatch, liveBatchQuery.fallbackIntervalMs, liveBatchQuery.streamStatus]);

  const mergedError =
    localError ??
    (createBatchMutation.error ? getErrorMessage(createBatchMutation.error) : null) ??
    (retryBatchMutation.error ? getErrorMessage(retryBatchMutation.error) : null) ??
    (cancelBatchMutation.error ? getErrorMessage(cancelBatchMutation.error) : null) ??
    (liveBatchQuery.error ? getErrorMessage(liveBatchQuery.error) : null) ??
    (ingestionStateQuery.error ? getErrorMessage(ingestionStateQuery.error) : null) ??
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

      setPreferredBatchId(response.batch_id);
      setServerEntryErrors(mergeEntryErrors(uploadErrors, mapEntryErrors(response.entry_errors)));
      router.replace(`/knowledge-bases/${kbId}?batch=${response.batch_id}`, { scroll: false });
      await liveBatchQuery.refetch();
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
        subtitle='双栏工作台：左侧管理导入任务，右侧跟踪实时处理进度。'
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

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', lg: '360px minmax(0, 1fr)' },
          gap: 2,
          alignItems: 'start',
        }}
      >
        <Stack spacing={2}>
          <Paper variant='outlined' sx={{ p: 2 }}>
            <Stack spacing={1.25}>
              <Typography variant='h6'>知识库状态</Typography>
              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Chip label={'状态：' + knowledgeBaseStatusLabel(kb.status)} variant='outlined' />
                <Chip
                  label={'可用性：' + readinessLabel(kb.readiness)}
                  color={kb.readiness === 'ready' ? 'success' : 'warning'}
                />
                <Chip label={'配置版本：' + kb.current_config_version} variant='outlined' />
              </Stack>
              {streamHint && (
                <Alert
                  severity={liveBatchQuery.streamStatus === 'fallback_polling' ? 'warning' : 'info'}
                  sx={{ mt: 1 }}
                >
                  {streamHint}
                </Alert>
              )}
            </Stack>
          </Paper>

          <Paper variant='outlined' sx={{ p: 2.5 }}>
            <Stack spacing={2}>
              <Typography variant='h6'>导入任务</Typography>
              <Typography color='text.secondary' variant='body2'>
                支持文本/URL/文件混合导入，提交后会自动接管并持续同步任务进度。
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
        </Stack>

        <Paper variant='outlined' sx={{ p: 2.5 }}>
          <Stack spacing={1.5}>
            <Typography variant='h6'>实时进度面板</Typography>
            {!currentBatch ? (
              <Alert severity='info'>
                当前暂无导入批次。提交文档后，这里会展示实时处理状态与文档级结果。
              </Alert>
            ) : (
              <>
                <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                  <Chip label={'批次：' + currentBatch.id} variant='outlined' />
                  <Chip label={batchStatusLabel(currentBatch.status)} color={batchStatusColor(currentBatch.status)} />
                  <Chip label={'进度：' + currentBatch.progress_percent + '%'} variant='outlined' />
                </Stack>

                <Box>
                  <Typography variant='body2' color='text.secondary' sx={{ mb: 0.75 }}>
                    {'文档：成功 ' +
                      currentBatch.succeeded_docs +
                      ' / 失败 ' +
                      currentBatch.failed_docs +
                      ' / 取消 ' +
                      currentBatch.canceled_docs +
                      ' / 分块 ' +
                      currentBatch.succeeded_chunks}
                  </Typography>
                  <LinearProgress variant='determinate' value={Math.max(0, Math.min(100, currentBatch.progress_percent))} />
                </Box>

                {currentBatch.docs.length > 0 ? (
                  <Paper variant='outlined' sx={{ p: 1.5, maxHeight: 460, overflowY: 'auto' }}>
                    <Stack spacing={1}>
                      {currentBatch.docs.map((doc) => (
                        <Stack
                          key={doc.id}
                          direction={{ xs: 'column', sm: 'row' }}
                          justifyContent='space-between'
                          sx={{ borderBottom: '1px solid', borderColor: 'divider', pb: 1 }}
                        >
                          <Box sx={{ minWidth: 0 }}>
                            <Typography variant='body2' fontWeight={600} noWrap>
                              {doc.title || doc.id}
                            </Typography>
                            <Typography variant='caption' color='text.secondary'>
                              {sourceTypeLabel(doc.source_type) + ' · 重试 ' + doc.retry_count}
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
      </Box>

      {kbId && (
        <ChunkBrowserSection
          kbId={kbId}
          browseLocked={browseLocked}
          browseLockMessage={browseLockMessage}
        />
      )}
    </Box>
  );
}

