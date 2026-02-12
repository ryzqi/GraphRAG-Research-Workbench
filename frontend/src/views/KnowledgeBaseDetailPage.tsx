'use client';

/**
 * Knowledge base detail workspace focused on chunk browsing and ingestion visibility.
 */
import { useEffect, useMemo, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Chip,
  Divider,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SearchIcon from '@mui/icons-material/Search';
import DescriptionOutlinedIcon from '@mui/icons-material/DescriptionOutlined';
import ViewAgendaOutlinedIcon from '@mui/icons-material/ViewAgendaOutlined';
import NotesOutlinedIcon from '@mui/icons-material/NotesOutlined';
import { Button } from '../components/ui/Button';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { ListSkeleton } from '../components/ui/Skeleton';
import {
  useMaterialChunkDetail,
  useMaterialChunks,
  useMaterialsWithChunkStats,
} from '../hooks/queries/useMaterialChunks';
import {
  useKnowledgeBase,
  useKnowledgeBaseIngestionState,
} from '../hooks/queries/useKnowledgeBases';
import { useIngestionBatchLive } from '../hooks/queries/useIngestionBatches';
import { getErrorMessage } from '../lib/errorHandler';
import type { BatchStatus, IngestionBatch, ManifestSourceType } from '../services/ingestionBatches';
import type { DocumentChunk, SourceMaterialWithChunkStats } from '../services/materialChunks';

type MobilePanel = 'docs' | 'chunks' | 'content';

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

function contextStatusLabel(status: string): string {
  switch (status) {
    case 'success':
      return '增强成功';
    case 'degraded':
      return '降级生成';
    case 'fallback':
      return '增强失败';
    case 'not_enabled':
      return '未启用';
    default:
      return status || '未知';
  }
}

function contextStatusColor(status: string):
  | 'default'
  | 'warning'
  | 'success'
  | 'error'
  | 'info' {
  switch (status) {
    case 'success':
      return 'success';
    case 'degraded':
      return 'warning';
    case 'fallback':
      return 'error';
    case 'not_enabled':
      return 'default';
    default:
      return 'info';
  }
}

type StrategyChipColor = 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info';

function normalizedChunkStrategy(chunk: DocumentChunk): string {
  const direct = chunk.chunking_strategy?.trim();
  if (direct) {
    return direct;
  }
  const locatorStrategy = chunk.locator?.['chunking_strategy'];
  if (typeof locatorStrategy === 'string' && locatorStrategy.trim()) {
    return locatorStrategy.trim();
  }
  return 'unknown';
}

function chunkStrategyLabel(strategy: string): string {
  switch (strategy) {
    case 'query_dependent_multiscale':
      return '多尺度窗口';
    case 'markdown_heading':
      return 'Markdown 标题';
    case 'max_min_semantic':
      return '语义分块';
    case 'parent_child':
      return '父子子块';
    case 'parent_window':
      return '父子父块';
    default:
      return strategy || '未知策略';
  }
}

function chunkStrategyColor(strategy: string): StrategyChipColor {
  switch (strategy) {
    case 'query_dependent_multiscale':
      return 'info';
    case 'markdown_heading':
      return 'success';
    case 'max_min_semantic':
      return 'secondary';
    case 'parent_child':
    case 'parent_window':
      return 'warning';
    default:
      return 'default';
  }
}

function locatorNumber(chunk: DocumentChunk, key: string): number | null {
  const rawValue = chunk.locator?.[key];
  if (typeof rawValue === 'number' && Number.isFinite(rawValue)) {
    return rawValue;
  }
  if (typeof rawValue === 'string') {
    const parsed = Number(rawValue);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function chunkStrategyHighlights(chunk: DocumentChunk): string[] {
  const strategy = normalizedChunkStrategy(chunk);
  const highlights: string[] = [];

  if (strategy === 'markdown_heading' && chunk.heading_path) {
    highlights.push('标题路径 ' + chunk.heading_path);
  }

  if (strategy === 'query_dependent_multiscale') {
    const windowId = locatorNumber(chunk, 'window_id');
    const tokenStart = locatorNumber(chunk, 'token_start');
    const tokenEnd = locatorNumber(chunk, 'token_end');
    if (windowId != null) {
      highlights.push('窗口 ' + String(windowId));
    }
    if (tokenStart != null && tokenEnd != null) {
      highlights.push('Token ' + String(tokenStart) + '-' + String(tokenEnd));
    }
  }

  if (strategy === 'parent_child' || strategy === 'parent_window') {
    highlights.push(strategy === 'parent_child' ? '层级子块' : '层级父块');
    const index = locatorNumber(chunk, 'index');
    if (index != null) {
      highlights.push('定位 ' + String(index));
    }
  }

  if (strategy === 'max_min_semantic' && chunk.token_count != null) {
    highlights.push('Token ' + String(chunk.token_count));
  }

  return highlights;
}

function chunkPreview(text: string, max = 100): string {
  const compact = text.replace(/\s+/g, ' ').trim();
  if (compact.length <= max) {
    return compact;
  }
  return compact.slice(0, max) + '…';
}

function resolvedChunkText(chunk: DocumentChunk): string {
  const baseText = chunk.raw_text || chunk.embedding_text;
  const contextText = chunk.context_text;
  if (!contextText || contextText.trim().length === 0) {
    return baseText;
  }
  return baseText + '\n\n' + contextText;
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

function IngestionStatusCard({
  batch,
  streamStatus,
  fallbackIntervalMs,
  isPending,
  error,
}: {
  batch: IngestionBatch | null;
  streamStatus: 'idle' | 'connecting' | 'live' | 'fallback_polling';
  fallbackIntervalMs: number;
  isPending: boolean;
  error: string | null;
}) {
  const streamHint = useMemo(() => {
    if (!batch) {
      return null;
    }
    if (streamStatus === 'connecting') {
      return '正在建立实时状态连接…';
    }
    if (streamStatus === 'live') {
      return '实时状态已连接。';
    }
    if (streamStatus === 'fallback_polling') {
      return `实时连接中断，已切换轮询（每 ${Math.round(fallbackIntervalMs / 1000)} 秒）。`;
    }
    return '正在等待处理状态更新。';
  }, [batch, fallbackIntervalMs, streamStatus]);

  if (isPending && !batch) {
    return (
      <Paper variant='outlined' sx={{ borderRadius: 3, p: 2.5 }}>
        <Stack spacing={1.5}>
          <Typography variant='h6'>导入状态总览</Typography>
          <Typography variant='body2' color='text.secondary'>
            正在获取最新批次状态…
          </Typography>
        </Stack>
      </Paper>
    );
  }

  if (error) {
    return (
      <Paper variant='outlined' sx={{ borderRadius: 3, p: 2.5 }}>
        <Alert severity='error'>{error}</Alert>
      </Paper>
    );
  }

  if (!batch) {
    return (
      <Paper variant='outlined' sx={{ borderRadius: 3, p: 2.5 }}>
        <Stack spacing={1}>
          <Typography variant='h6'>导入状态总览</Typography>
          <Alert severity='info'>当前暂无导入批次。添加文档后可在此查看实时处理状态。</Alert>
        </Stack>
      </Paper>
    );
  }

  const processingDocs = batch.docs.filter((doc) => doc.status === 'processing').length;

  return (
    <Paper
      variant='outlined'
      sx={{
        borderRadius: 3,
        p: { xs: 2, md: 2.5 },
        bgcolor: (theme) =>
          theme.palette.mode === 'light'
            ? alpha(theme.palette.info.light, 0.08)
            : alpha(theme.palette.info.dark, 0.2),
      }}
    >
      <Stack spacing={1.5}>
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={1}
          justifyContent='space-between'
          alignItems={{ xs: 'flex-start', md: 'center' }}
        >
          <Stack spacing={0.5}>
            <Typography variant='h6'>导入状态总览</Typography>
          </Stack>
          <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
            <Chip label={`批次 ${batch.id.slice(0, 8)}…`} variant='outlined' size='small' />
            <Chip
              label={batchStatusLabel(batch.status)}
              color={batchStatusColor(batch.status)}
              size='small'
            />
          </Stack>
        </Stack>

        {streamHint && (
          <Alert severity={streamStatus === 'fallback_polling' ? 'warning' : 'info'}>
            {streamHint}
          </Alert>
        )}

        <Typography variant='body2' color='text.secondary'>
          {'文档：成功 ' +
            batch.succeeded_docs +
            ' / 失败 ' +
            batch.failed_docs +
            ' / 取消 ' +
            batch.canceled_docs +
            ' / 处理中 ' +
            processingDocs +
            ' / 分块 ' +
            batch.succeeded_chunks}
        </Typography>
      </Stack>
    </Paper>
  );
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

  const materialsQuery = useMaterialsWithChunkStats(kbId, {
    skip: 0,
    limit: 100,
  });
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

  const chunks = useMemo(() => (browseLocked ? [] : (chunksQuery.data ?? [])), [browseLocked, chunksQuery.data]);

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
  const selectedChunkStrategy = selectedChunk ? normalizedChunkStrategy(selectedChunk) : null;
  const selectedChunkHighlights = selectedChunk ? chunkStrategyHighlights(selectedChunk) : [];

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
    p: { xs: 1.5, md: 2 },
    minHeight: { xs: 420, md: 'auto' },
  } as const;
  const listSx = {
    flex: 1,
    minHeight: 0,
    maxHeight: { xs: 320, md: 560 },
    overflowY: 'auto',
    pr: 0.5,
  } as const;
  const selectedBg = alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.08 : 0.22);

  return (
    <Paper variant='outlined' sx={{ overflow: 'hidden', borderRadius: 3, borderColor: 'divider' }}>
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        justifyContent='space-between'
        spacing={1.5}
        sx={{
          p: { xs: 1.5, md: 2 },
          borderBottom: 1,
          borderColor: 'divider',
          bgcolor: (t) => alpha(t.palette.background.paper, 0.95),
        }}
      >
        <Stack spacing={0.5}>
          <Typography variant='h6'>分块浏览工作台</Typography>
        </Stack>
        <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
          <Chip icon={<DescriptionOutlinedIcon />} label={`文档 ${filteredMaterials.length}`} size='small' variant='outlined' />
          <Chip icon={<ViewAgendaOutlinedIcon />} label={`分块 ${chunks.length}`} size='small' variant='outlined' color='primary' />
          <Chip icon={<NotesOutlinedIcon />} label={selectedChunk ? `当前 ${selectedChunk.chunk_index}` : '未选择分块'} size='small' variant='outlined' />
        </Stack>
      </Stack>

      {sectionError && (
        <Alert severity='error' sx={{ m: 2, mb: 0 }}>
          {sectionError}
        </Alert>
      )}

      {browseLocked && (
        <Alert severity='info' sx={{ m: 2, mb: 0 }}>
          {browseLockMessage ?? '当前知识库文档仍在处理中，待全部完成后再浏览分块。'}
        </Alert>
      )}

      <Box
        sx={{
          display: { xs: 'block', md: 'none' },
          px: 1,
          pt: 1,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Tabs value={mobilePanel} onChange={(_, value: MobilePanel) => setMobilePanel(value)} variant='fullWidth'>
          <Tab value='docs' label='文档' sx={{ minHeight: 42 }} />
          <Tab value='chunks' label='分块' sx={{ minHeight: 42 }} />
          <Tab value='content' label='详情' sx={{ minHeight: 42 }} />
        </Tabs>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: {
            xs: '1fr',
            lg: 'minmax(280px, 22%) minmax(320px, 28%) minmax(0, 1fr)',
          },
          alignItems: { md: 'start' },
          bgcolor: 'background.default',
        }}
      >
        <Box
          sx={{
            ...panelBaseSx,
            display: {
              xs: mobilePanel === 'docs' ? 'flex' : 'none',
              md: 'flex',
            },
            flexDirection: 'column',
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
              暂无可浏览文档。
            </Typography>
          ) : (
            <List disablePadding sx={listSx}>
              {filteredMaterials.map((item, index) => {
                const selected = item.id === selectedMaterialId;
                return (
                  <ListItemButton
                    key={item.id}
                    selected={selected}
                    onClick={() => onSelectMaterial(item)}
                    sx={{
                      mb: index === filteredMaterials.length - 1 ? 0 : 1,
                      p: 1.25,
                      borderRadius: 2,
                      border: 1,
                      borderColor: selected ? 'primary.main' : 'divider',
                      bgcolor: selected ? selectedBg : 'background.paper',
                      '&.Mui-selected': { bgcolor: selectedBg },
                    }}
                  >
                    <ListItemText
                      primary={
                        <Typography
                          variant='body2'
                          fontWeight={600}
                          sx={{
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                          }}
                        >
                          {item.title || item.id}
                        </Typography>
                      }
                      secondary={
                        <Stack direction='row' spacing={0.75} sx={{ mt: 0.75 }}>
                          <Chip label={sourceTypeLabel(item.source_type)} size='small' variant='outlined' />
                          <Chip label={`${item.chunk_count} 块`} size='small' variant='outlined' color='primary' />
                        </Stack>
                      }
                    />
                  </ListItemButton>
                );
              })}
            </List>
          )}
        </Box>

        <Box
          sx={{
            ...panelBaseSx,
            display: {
              xs: mobilePanel === 'chunks' ? 'flex' : 'none',
              md: 'flex',
            },
            flexDirection: 'column',
            borderRight: { md: 1 },
            borderColor: 'divider',
          }}
        >
          <Typography variant='subtitle2' color='text.secondary' sx={{ mb: 1.25 }}>
            {selectedMaterial ? selectedMaterial.title : '请先选择文档'}
          </Typography>

          {browseLocked ? (
            <Typography variant='body2' color='text.secondary'>
              文档处理中，暂不可浏览分块。
            </Typography>
          ) : !selectedMaterial ? null : chunksQuery.isPending ? (
            <ListSkeleton count={8} />
          ) : chunks.length === 0 ? (
            <Typography variant='body2' color='text.secondary'>
              该文档暂无分块。
            </Typography>
          ) : (
            <List disablePadding sx={listSx}>
              {chunks.map((item, index) => {
                const selected = item.id === selectedChunkId;
                const strategy = normalizedChunkStrategy(item);
                const strategyHighlights = chunkStrategyHighlights(item);
                return (
                  <ListItemButton
                    key={item.id}
                    selected={selected}
                    onClick={() => onSelectChunk(item)}
                    sx={{
                      mb: index === chunks.length - 1 ? 0 : 1,
                      p: 1.25,
                      borderRadius: 2,
                      alignItems: 'flex-start',
                      border: 1,
                      borderColor: selected ? 'primary.main' : 'divider',
                      bgcolor: selected ? selectedBg : 'background.paper',
                    }}
                  >
                    <ListItemText
                      primary={
                        <Stack direction='row' spacing={1} alignItems='center' flexWrap='wrap' useFlexGap>
                          <Typography variant='body2' fontWeight={700}>
                            {item.chunk_index}
                          </Typography>
                          <Chip
                            label={chunkStrategyLabel(strategy)}
                            color={chunkStrategyColor(strategy)}
                            size='small'
                            variant='outlined'
                          />
                          <Chip
                            label={contextStatusLabel(item.context_status)}
                            color={contextStatusColor(item.context_status)}
                            size='small'
                            variant='outlined'
                          />
                        </Stack>
                      }
                      secondary={
                        <Stack spacing={0.65} sx={{ mt: 0.75 }}>
                          {strategyHighlights.length > 0 && (
                            <Stack direction='row' spacing={0.6} flexWrap='wrap' useFlexGap>
                              {strategyHighlights.map((hint, hintIndex) => (
                                <Chip
                                  key={hint + String(hintIndex)}
                                  label={hint}
                                  size='small'
                                  variant='outlined'
                                />
                              ))}
                            </Stack>
                          )}
                          <Typography
                            variant='caption'
                            color='text.secondary'
                            sx={{
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              overflow: 'hidden',
                              lineHeight: 1.5,
                            }}
                          >
                            {chunkPreview(resolvedChunkText(item), 120)}
                          </Typography>
                        </Stack>
                      }
                    />
                  </ListItemButton>
                );
              })}
            </List>
          )}
        </Box>

        <Box
          component='section'
          aria-live='polite'
          sx={{
            ...panelBaseSx,
            display: {
              xs: mobilePanel === 'content' ? 'block' : 'none',
              md: 'block',
            },
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
            <Stack spacing={1.25}>
              <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
                <Chip label={'Chunk ' + String(selectedChunk.chunk_index)} size='small' color='primary' />
                {selectedChunkStrategy && (
                  <Chip
                    label={chunkStrategyLabel(selectedChunkStrategy)}
                    size='small'
                    color={chunkStrategyColor(selectedChunkStrategy)}
                    variant='outlined'
                  />
                )}
                <Chip
                  label={contextStatusLabel(selectedChunk.context_status)}
                  size='small'
                  color={contextStatusColor(selectedChunk.context_status)}
                  variant='outlined'
                />
                {selectedChunk.token_count != null && (
                  <Chip label={'Token ' + String(selectedChunk.token_count)} size='small' variant='outlined' />
                )}
                <Chip label={'增强尝试 ' + String(selectedChunk.context_attempts)} size='small' variant='outlined' />
                <Chip
                  label={'创建于 ' + new Date(selectedChunk.created_at).toLocaleString()}
                  size='small'
                  variant='outlined'
                />
              </Stack>

              <Paper
                variant='outlined'
                sx={{
                  p: { xs: 1.25, md: 1.5 },
                  bgcolor: 'background.paper',
                  borderRadius: 2,
                }}
              >
                <Typography variant='overline' color='text.secondary'>
                  分块策略信息
                </Typography>
                <Stack direction='row' spacing={0.75} flexWrap='wrap' useFlexGap sx={{ mt: 0.5 }}>
                  {selectedChunkStrategy && (
                    <Chip
                      label={chunkStrategyLabel(selectedChunkStrategy)}
                      color={chunkStrategyColor(selectedChunkStrategy)}
                      size='small'
                      variant='outlined'
                    />
                  )}
                  {selectedChunkHighlights.map((hint, hintIndex) => (
                    <Chip key={hint + String(hintIndex)} label={hint} size='small' variant='outlined' />
                  ))}
                </Stack>
              </Paper>

              <Paper
                variant='outlined'
                sx={{
                  p: { xs: 1.5, md: 2 },
                  maxHeight: { xs: 340, md: 420 },
                  overflowY: 'auto',
                  bgcolor: 'background.paper',
                  borderRadius: 2,
                }}
              >
                <Typography variant='overline' color='text.secondary'>
                  分块内容（原文 + 上下文增强）
                </Typography>
                <Typography
                  variant='body2'
                  sx={{
                    mt: 0.75,
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.72,
                    wordBreak: 'break-word',
                  }}
                >
                  {resolvedChunkText(selectedChunk)}
                </Typography>
              </Paper>

              {selectedChunk.context_error && (
                <Alert severity={selectedChunk.context_status === 'degraded' ? 'warning' : 'error'}>
                  {'上下文增强降级原因：' + selectedChunk.context_error}
                </Alert>
              )}

              <Accordion
                disableGutters
                elevation={0}
                sx={{
                  border: 1,
                  borderColor: 'divider',
                  borderRadius: 2,
                  bgcolor: 'background.paper',
                  '&::before': { display: 'none' },
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon fontSize='small' />}>
                  <Typography variant='subtitle2'>定位信息</Typography>
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0.5 }}>
                  {selectedChunk.locator && Object.keys(selectedChunk.locator).length > 0 ? (
                    <Stack spacing={0.85}>
                      {Object.entries(selectedChunk.locator).map(([key, value]) => (
                        <Stack key={key} direction='row' spacing={1} alignItems='flex-start'>
                          <Typography
                            variant='caption'
                            color='text.secondary'
                            sx={{ minWidth: 84, fontWeight: 600 }}
                          >
                            {key}
                          </Typography>
                          <Typography
                            variant='caption'
                            sx={{
                              whiteSpace: 'pre-wrap',
                              wordBreak: 'break-word',
                              lineHeight: 1.5,
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
                </AccordionDetails>
              </Accordion>
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
  const kbId = Array.isArray(params.kbId) ? params.kbId[0] : params.kbId;

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const ingestionStateQuery = useKnowledgeBaseIngestionState(kbId ?? '');
  const liveBatchQuery = useIngestionBatchLive({
    kbId: kbId ?? undefined,
  });

  const [showSlowLoading, setShowSlowLoading] = useState(false);

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

  const kb = kbQuery.data ?? null;
  const activeBatch = liveBatchQuery.data ?? null;
  const batchRunning = activeBatch?.status === 'processing';

  const browseLocked =
    ingestionStateQuery.isPending ||
    Boolean(ingestionStateQuery.error) ||
    Boolean(ingestionStateQuery.data?.has_active_batch) ||
    Boolean(batchRunning);

  const browseLockMessage = useMemo(() => {
    if (ingestionStateQuery.error) {
      return '无法确认文档处理状态，已暂时禁用分块浏览。';
    }
    if (!ingestionStateQuery.data) {
      return '正在同步文档处理状态，请稍后再浏览分块。';
    }

    if (activeBatch && activeBatch.status === 'processing') {
      const activeDocs = activeBatch.docs.filter((doc) => doc.status === 'processing').length;
      if (activeDocs > 0) {
        return `当前批次仍有 ${activeDocs} 个文档处理中，暂不可浏览分块。`;
      }
      return '当前导入批次仍在处理中，暂不可浏览分块。';
    }

    if (!ingestionStateQuery.data.has_active_batch) {
      return null;
    }

    return '当前知识库文档仍在处理中，待全部完成后再浏览分块。';
  }, [activeBatch, ingestionStateQuery.data, ingestionStateQuery.error]);

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
    return <Alert severity='error'>{getErrorMessage(kbQuery.error) ?? '未找到知识库'}</Alert>;
  }

  const progressError = liveBatchQuery.error ? getErrorMessage(liveBatchQuery.error) : null;

  return (
    <Stack spacing={2}>
      <Paper
        variant='outlined'
        sx={{
          borderRadius: 3,
          p: { xs: 2, md: 2.5 },
          background: (theme) =>
            theme.palette.mode === 'light'
              ? `linear-gradient(135deg, ${alpha(theme.palette.primary.light, 0.12)} 0%, ${alpha(theme.palette.background.paper, 0.98)} 65%)`
              : `linear-gradient(135deg, ${alpha(theme.palette.primary.dark, 0.28)} 0%, ${alpha(theme.palette.background.paper, 0.98)} 65%)`,
        }}
      >
        <Stack spacing={1.75}>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            alignItems={{ xs: 'flex-start', md: 'center' }}
            justifyContent='space-between'
            spacing={1.5}
          >
            <Stack spacing={0.6}>
              <Typography variant='h4' component='h1' fontWeight={650} sx={{ lineHeight: 1.2 }}>
                {kb.name}
              </Typography>
              {kb.description && (
                <Typography variant='body2' color='text.secondary'>
                  {kb.description}
                </Typography>
              )}
            </Stack>
            <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
              <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
                返回列表
              </Button>
              <Button variant='contained' onClick={() => router.push(`/knowledge-bases/${kbId}/documents/new`)}>
                添加文档
              </Button>
            </Stack>
          </Stack>

          <Divider />

          <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
            <Chip label={`状态 ${kb.status === 'active' ? '启用中' : '已归档'}`} size='small' variant='outlined' />
            <Chip
              label={`就绪 ${kb.readiness === 'ready' ? '已就绪' : '未就绪'}`}
              color={kb.readiness === 'ready' ? 'success' : 'warning'}
              size='small'
              variant='outlined'
            />
          </Stack>
        </Stack>
      </Paper>

      <IngestionStatusCard
        batch={activeBatch}
        streamStatus={liveBatchQuery.streamStatus}
        fallbackIntervalMs={liveBatchQuery.fallbackIntervalMs}
        isPending={liveBatchQuery.isPending}
        error={progressError}
      />

      {kbId && (
        <ChunkBrowserSection
          kbId={kbId}
          browseLocked={browseLocked}
          browseLockMessage={browseLockMessage}
        />
      )}
    </Stack>
  );
}
