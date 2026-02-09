'use client';
/**
 * Knowledge base detail page focused on chunk browsing.
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
  useTheme
} from '@mui/material';
import { alpha } from '@mui/material/styles';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import SearchIcon from '@mui/icons-material/Search';
import { Button } from '../components/ui/Button';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { PageHeader } from '../components/ui/PageHeader';
import { ListSkeleton } from '../components/ui/Skeleton';
import {
  useMaterialChunkDetail,
  useMaterialChunks,
  useMaterialsWithChunkStats
} from '../hooks/queries/useMaterialChunks';
import {
  useKnowledgeBase,
  useKnowledgeBaseIngestionState
} from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import type { ManifestSourceType } from '../services/ingestionBatches';
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

function chunkPreview(text: string, max = 92): string {
  const compact = text.replace(/\s+/g, ' ').trim();
  if (compact.length <= max) {
    return compact;
  }
  return compact.slice(0, max) + '…';
}

function resolvedChunkText(chunk: DocumentChunk): string {
  return chunk.processed_text || chunk.text;
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
  browseLockMessage
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
    limit: 100
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
    enabled: !browseLocked
  });

  const chunks = useMemo(
    () => (browseLocked ? [] : (chunksQuery.data ?? [])),
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
    enabled: !browseLocked
  });

  const selectedChunk = browseLocked
    ? null
    : (chunkDetailQuery.data ?? chunks.find((item) => item.id === selectedChunkId) ?? null);
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
    p: { xs: 2, md: 2.5 },
    minHeight: { xs: 420, md: 560 }
  } as const;
  const listSx = { maxHeight: { xs: 320, md: 500 }, overflowY: 'auto', pr: 0.5 } as const;
  const selectedBg = alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.1 : 0.22);

  return (
    <Paper
      variant='outlined'
      sx={{
        overflow: 'hidden',
        borderRadius: 3,
        borderColor: 'divider',
        bgcolor: 'background.paper'
      }}
    >
      <Stack
        direction={{ xs: 'column', md: 'row' }}
        justifyContent='space-between'
        spacing={1.25}
        sx={{
          p: { xs: 2, md: 2.5 },
          borderBottom: 1,
          borderColor: 'divider',
          bgcolor: 'background.paper'
        }}
      >
        <Stack spacing={0.5}>
          <Typography variant='h6'>文档分块浏览</Typography>
          <Typography variant='body2' color='text.secondary'>
            展示文档最终处理后的分块文本
          </Typography>
        </Stack>
        <Chip
          label={`文档 ${filteredMaterials.length} · 分块 ${chunks.length}`}
          size='small'
          variant='outlined'
          color='primary'
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

      <Box
        sx={{
          display: { xs: 'block', md: 'none' },
          px: 1,
          pt: 1,
          borderBottom: 1,
          borderColor: 'divider'
        }}
      >
        <Tabs
          value={mobilePanel}
          onChange={(_, value: MobilePanel) => setMobilePanel(value)}
          variant='fullWidth'
          sx={{ minHeight: 44 }}
        >
          <Tab value='docs' label='文档' sx={{ minHeight: 44 }} />
          <Tab value='chunks' label='分块' sx={{ minHeight: 44 }} />
          <Tab value='content' label='内容' sx={{ minHeight: 44 }} />
        </Tabs>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: '320px 360px minmax(0, 1fr)' },
          bgcolor: 'background.default'
        }}
      >
        <Box
          sx={{
            ...panelBaseSx,
            display: {
              xs: mobilePanel === 'docs' ? 'block' : 'none',
              md: 'block'
            },
            borderRight: { md: 1 },
            borderColor: 'divider'
          }}
        >
          <TextField
            size='small'
            placeholder='筛选文档标题'
            value={materialFilter}
            onChange={(event) => setMaterialFilter(event.target.value)}
            fullWidth
            sx={{ mb: 2 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position='start'>
                  <SearchIcon fontSize='small' />
                </InputAdornment>
              )
            }}
          />

          {materialsQuery.isPending ? (
            <ListSkeleton count={6} />
          ) : filteredMaterials.length === 0 ? (
            <Typography variant='body2' color='text.secondary'>
              暂无文档。
            </Typography>
          ) : (
            <List disablePadding sx={listSx}>
              {filteredMaterials.map((item) => {
                const selected = item.id === selectedMaterialId;
                return (
                  <ListItemButton
                    key={item.id}
                    selected={selected}
                    onClick={() => onSelectMaterial(item)}
                    sx={{
                      mb: 1,
                      p: 1.5,
                      borderRadius: 2.5,
                      alignItems: 'flex-start',
                      border: 1,
                      borderColor: selected ? 'primary.main' : 'divider',
                      bgcolor: selected ? selectedBg : 'background.paper',
                      '&.Mui-selected': { bgcolor: selectedBg },
                      '&:hover': {
                        borderColor: selected ? 'primary.main' : 'text.disabled'
                      }
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
                            overflow: 'hidden'
                          }}
                        >
                          {item.title || item.id}
                        </Typography>
                      }
                      secondary={
                        <Stack direction='row' spacing={0.75} sx={{ mt: 0.75 }}>
                          <Chip
                            label={sourceTypeLabel(item.source_type)}
                            size='small'
                            variant='outlined'
                          />
                          <Chip
                            label={`${item.chunk_count} 块`}
                            size='small'
                            color='primary'
                            variant='outlined'
                          />
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
              xs: mobilePanel === 'chunks' ? 'block' : 'none',
              md: 'block'
            },
            borderRight: { md: 1 },
            borderColor: 'divider'
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
              {chunks.map((item) => {
                const selected = item.id === selectedChunkId;
                return (
                  <ListItemButton
                    key={item.id}
                    selected={selected}
                    onClick={() => onSelectChunk(item)}
                    sx={{
                      mb: 1,
                      p: 1.5,
                      borderRadius: 2.5,
                      alignItems: 'flex-start',
                      border: 1,
                      borderColor: selected ? 'primary.main' : 'divider',
                      bgcolor: selected ? selectedBg : 'background.paper',
                      '&.Mui-selected': { bgcolor: selectedBg },
                      '&:hover': {
                        borderColor: selected ? 'primary.main' : 'text.disabled'
                      }
                    }}
                  >
                    <ListItemText
                      primary={
                        <Typography variant='body2' fontWeight={600}>
                          #{item.chunk_index}
                        </Typography>
                      }
                      secondary={
                        <Typography
                          variant='caption'
                          color='text.secondary'
                          sx={{
                            mt: 0.75,
                            display: '-webkit-box',
                            WebkitLineClamp: 2,
                            WebkitBoxOrient: 'vertical',
                            overflow: 'hidden',
                            lineHeight: 1.5
                          }}
                        >
                          {chunkPreview(resolvedChunkText(item), 110)}
                        </Typography>
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
              md: 'block'
            },
            minWidth: 0
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
                  <Chip
                    label={`Token ${selectedChunk.token_count}`}
                    size='small'
                    variant='outlined'
                  />
                )}
                <Chip
                  label={`创建于 ${new Date(selectedChunk.created_at).toLocaleString()}`}
                  size='small'
                  variant='outlined'
                />
              </Stack>
              <Paper
                variant='outlined'
                sx={{
                  p: { xs: 2, md: 2.5 },
                  maxHeight: { xs: 360, md: 520 },
                  overflowY: 'auto',
                  bgcolor: 'background.paper',
                  borderRadius: 2.5
                }}
              >
                <Typography variant='overline' color='text.secondary'>
                  最终处理文本
                </Typography>
                <Typography
                  variant='body2'
                  sx={{
                    mt: 0.75,
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.72,
                    wordBreak: 'break-word'
                  }}
                >
                  {resolvedChunkText(selectedChunk)}
                </Typography>
              </Paper>
              <Accordion
                disableGutters
                elevation={0}
                sx={{
                  border: 1,
                  borderColor: 'divider',
                  borderRadius: 2.5,
                  bgcolor: 'background.paper',
                  '&::before': { display: 'none' }
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
                              lineHeight: 1.5
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

  const browseLocked =
    ingestionStateQuery.isPending ||
    Boolean(ingestionStateQuery.error) ||
    Boolean(ingestionStateQuery.data?.has_active_batch);

  const browseLockMessage = useMemo(() => {
    const ingestionState = ingestionStateQuery.data;
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
  }, [ingestionStateQuery.data, ingestionStateQuery.error]);

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

  return (
    <Stack spacing={2}>
      <PageHeader
        title={kb.name}
        action={
          <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
            <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
              返回列表
            </Button>
            <Button
              variant='contained'
              onClick={() => router.push(`/knowledge-bases/${kbId}/documents/new`)}
            >
              添加文档
            </Button>
          </Stack>
        }
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
