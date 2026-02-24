'use client';

/**
 * Knowledge base detail workspace focused on chunk browsing and ingestion visibility.
 */
import {
  memo,
  useCallback,
  useDeferredValue,
  useEffect,
  useMemo,
  useState,
  type ChangeEvent,
  type SyntheticEvent,
} from 'react';
import { useRouter } from 'next/navigation';
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
  IngestionStatusOverviewCard,
  batchStatusColor,
  batchStatusLabel,
  formatIngestionSummaryText,
  streamHintSeverity,
} from '../components/ingestion';
import {
  useMaterialChunkDetail,
  useMaterialChunks,
  useMaterialsWithChunkStats,
} from '../hooks/queries/useMaterialChunks';
import { useKnowledgeBaseDetailData } from '../hooks/useKnowledgeBaseDetailData';
import { getErrorMessage } from '../lib/errorHandler';
import type { ManifestSourceType } from '../services/ingestionBatches';
import type { DocumentChunk } from '../services/materialChunks';

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

type ContextChipColor = ReturnType<typeof contextStatusColor>;

interface MaterialListItemViewModel {
  id: string;
  title: string;
  sourceLabel: string;
  chunkCountLabel: string;
}

interface ChunkListItemViewModel {
  id: string;
  chunkIndexLabel: string;
  strategyLabel: string;
  strategyColor: StrategyChipColor;
  contextLabel: string;
  contextColor: ContextChipColor;
  primaryHint: string | null;
  preview: string;
}

const PANEL_BASE_SX = {
  p: { xs: 1.5, md: 2 },
  minHeight: { xs: 420, md: 'auto' },
} as const;

const LIST_SX = {
  flex: 1,
  minHeight: 0,
  maxHeight: { xs: 320, md: 560 },
  overflowY: 'auto',
  pr: 0.5,
  contentVisibility: 'auto',
  containIntrinsicSize: '1px 560px',
} as const;

const CLAMPED_TWO_LINES_SX = {
  display: '-webkit-box',
  WebkitLineClamp: 2,
  WebkitBoxOrient: 'vertical',
  overflow: 'hidden',
} as const;

interface ChunkWorkspaceHeaderProps {
  documentCount: number;
  chunkCount: number;
  selectedChunkIndex: number | null;
}

const ChunkWorkspaceHeader = memo(function ChunkWorkspaceHeader({
  documentCount,
  chunkCount,
  selectedChunkIndex,
}: ChunkWorkspaceHeaderProps) {
  return (
    <Stack
      direction={{ xs: 'column', md: 'row' }}
      justifyContent='space-between'
      spacing={1.5}
      sx={{
        p: { xs: 1.5, md: 2 },
        borderBottom: 1,
        borderColor: 'divider',
        bgcolor: (theme) => alpha(theme.palette.background.paper, 0.95),
      }}
    >
      <Stack spacing={0.35}>
        <Typography variant='h6'>分块阅读工作台</Typography>
      </Stack>
      <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
        <Chip icon={<DescriptionOutlinedIcon />} label={`文档 ${documentCount}`} size='small' variant='outlined' />
        <Chip
          icon={<ViewAgendaOutlinedIcon />}
          label={`分块 ${chunkCount}`}
          size='small'
          variant='outlined'
          color='primary'
        />
        <Chip
          icon={<NotesOutlinedIcon />}
          label={selectedChunkIndex != null ? `当前 ${selectedChunkIndex}` : '未选择分块'}
          size='small'
          variant='outlined'
        />
      </Stack>
    </Stack>
  );
});

interface MaterialColumnProps {
  mobilePanel: MobilePanel;
  materialFilter: string;
  onMaterialFilterChange: (event: ChangeEvent<HTMLInputElement>) => void;
  items: MaterialListItemViewModel[];
  selectedMaterialId: string | null;
  selectedBg: string;
  isPending: boolean;
  onSelectMaterial: (materialId: string) => void;
}

const MaterialColumn = memo(function MaterialColumn({
  mobilePanel,
  materialFilter,
  onMaterialFilterChange,
  items,
  selectedMaterialId,
  selectedBg,
  isPending,
  onSelectMaterial,
}: MaterialColumnProps) {
  return (
    <Box
      sx={{
        ...PANEL_BASE_SX,
        display: {
          xs: mobilePanel === 'docs' ? 'flex' : 'none',
          md: 'flex',
        },
        flexDirection: 'column',
        borderRight: { md: 1 },
        borderColor: 'divider',
      }}
    >
      <Stack spacing={1.25} sx={{ mb: 1.5 }}>
        <Stack spacing={0.35}>
          <Typography variant='subtitle2' fontWeight={650}>
            文档列表
          </Typography>
        </Stack>
        <TextField
          size='small'
          placeholder='筛选文档标题'
          value={materialFilter}
          onChange={onMaterialFilterChange}
          fullWidth
          InputProps={{
            startAdornment: (
              <InputAdornment position='start'>
                <SearchIcon fontSize='small' />
              </InputAdornment>
            ),
          }}
        />
      </Stack>

      {isPending ? (
        <ListSkeleton count={6} />
      ) : items.length === 0 ? (
        <Typography variant='body2' color='text.secondary'>
          暂无可浏览文档。
        </Typography>
      ) : (
        <List disablePadding sx={LIST_SX}>
          {items.map((item, index) => {
            const selected = item.id === selectedMaterialId;
            return (
              <ListItemButton
                key={item.id}
                selected={selected}
                onClick={() => onSelectMaterial(item.id)}
                sx={{
                  cursor: 'pointer',
                  mb: index === items.length - 1 ? 0 : 1,
                  p: 1.25,
                  borderRadius: 2,
                  border: 1,
                  borderColor: selected ? 'primary.main' : 'divider',
                  bgcolor: selected ? selectedBg : 'background.paper',
                  transition: 'border-color 180ms ease, background-color 180ms ease',
                  '&.Mui-selected, &.Mui-selected:hover': {
                    bgcolor: selectedBg,
                    borderColor: 'primary.main',
                  },
                }}
              >
                <ListItemText
                  primary={
                    <Typography variant='body2' fontWeight={600} sx={CLAMPED_TWO_LINES_SX}>
                      {item.title}
                    </Typography>
                  }
                  secondary={
                    <Stack direction='row' spacing={0.75} sx={{ mt: 0.75 }}>
                      <Chip label={item.sourceLabel} size='small' variant='outlined' />
                      <Chip label={item.chunkCountLabel} size='small' variant='outlined' color='primary' />
                    </Stack>
                  }
                />
              </ListItemButton>
            );
          })}
        </List>
      )}
    </Box>
  );
});

interface ChunkColumnProps {
  mobilePanel: MobilePanel;
  browseLocked: boolean;
  selectedMaterialTitle: string | null;
  hasSelectedMaterial: boolean;
  isPending: boolean;
  items: ChunkListItemViewModel[];
  selectedChunkId: string | null;
  selectedBg: string;
  onSelectChunk: (chunkId: string) => void;
}

const ChunkColumn = memo(function ChunkColumn({
  mobilePanel,
  browseLocked,
  selectedMaterialTitle,
  hasSelectedMaterial,
  isPending,
  items,
  selectedChunkId,
  selectedBg,
  onSelectChunk,
}: ChunkColumnProps) {
  return (
    <Box
      sx={{
        ...PANEL_BASE_SX,
        display: {
          xs: mobilePanel === 'chunks' ? 'flex' : 'none',
          md: 'flex',
        },
        flexDirection: 'column',
        borderRight: { md: 1 },
        borderColor: 'divider',
      }}
    >
      <Stack spacing={0.35} sx={{ mb: 1.25 }}>
        <Typography variant='subtitle2' fontWeight={650}>
          分块索引
        </Typography>
        <Typography variant='caption' color='text.secondary' sx={CLAMPED_TWO_LINES_SX}>
          {selectedMaterialTitle ?? '请先选择文档'}
        </Typography>
      </Stack>

      {browseLocked ? (
        <Typography variant='body2' color='text.secondary'>
          文档处理中，暂不可浏览分块。
        </Typography>
      ) : !hasSelectedMaterial ? (
        <Typography variant='body2' color='text.secondary'>
          请先从左侧选择文档。
        </Typography>
      ) : isPending ? (
        <ListSkeleton count={8} />
      ) : items.length === 0 ? (
        <Typography variant='body2' color='text.secondary'>
          该文档暂无分块。
        </Typography>
      ) : (
        <List disablePadding sx={LIST_SX}>
          {items.map((item, index) => {
            const selected = item.id === selectedChunkId;
            return (
              <ListItemButton
                key={item.id}
                selected={selected}
                onClick={() => onSelectChunk(item.id)}
                sx={{
                  cursor: 'pointer',
                  mb: index === items.length - 1 ? 0 : 1,
                  p: 1.25,
                  borderRadius: 2,
                  alignItems: 'flex-start',
                  border: 1,
                  borderColor: selected ? 'primary.main' : 'divider',
                  bgcolor: selected ? selectedBg : 'background.paper',
                  transition: 'border-color 180ms ease, background-color 180ms ease',
                  '&.Mui-selected, &.Mui-selected:hover': {
                    bgcolor: selectedBg,
                    borderColor: 'primary.main',
                  },
                }}
              >
                <ListItemText
                  primary={
                    <Stack direction='row' spacing={1} alignItems='center' flexWrap='wrap' useFlexGap>
                      <Typography variant='body2' fontWeight={700}>
                        {item.chunkIndexLabel}
                      </Typography>
                      <Chip label={item.strategyLabel} color={item.strategyColor} size='small' variant='outlined' />
                      <Chip label={item.contextLabel} color={item.contextColor} size='small' variant='outlined' />
                    </Stack>
                  }
                  secondary={
                    <Stack spacing={0.55} sx={{ mt: 0.75 }}>
                      {item.primaryHint && (
                        <Typography variant='caption' color='text.secondary'>
                          {item.primaryHint}
                        </Typography>
                      )}
                      <Typography variant='caption' color='text.secondary' sx={CLAMPED_TWO_LINES_SX}>
                        {item.preview}
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
  );
});

interface ChunkReadingPanelProps {
  mobilePanel: MobilePanel;
  browseLocked: boolean;
  selectedChunk: DocumentChunk | null;
  selectedChunkStrategy: string | null;
  selectedChunkHighlights: string[];
}

const ChunkReadingPanel = memo(function ChunkReadingPanel({
  mobilePanel,
  browseLocked,
  selectedChunk,
  selectedChunkStrategy,
  selectedChunkHighlights,
}: ChunkReadingPanelProps) {
  const locatorEntries =
    selectedChunk?.locator && Object.keys(selectedChunk.locator).length > 0
      ? Object.entries(selectedChunk.locator)
      : [];
  const hasStrategyInfo = Boolean(selectedChunkStrategy) || selectedChunkHighlights.length > 0;

  return (
    <Box
      component='section'
      aria-live='polite'
      sx={{
        ...PANEL_BASE_SX,
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
        <Stack spacing={1.35}>
          <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
            <Chip label={`Chunk ${selectedChunk.chunk_index}`} size='small' color='primary' />
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
              <Chip label={`Token ${selectedChunk.token_count}`} size='small' variant='outlined' />
            )}
            <Chip label={`增强尝试 ${selectedChunk.context_attempts}`} size='small' variant='outlined' />
            <Chip label={`创建于 ${new Date(selectedChunk.created_at).toLocaleString()}`} size='small' variant='outlined' />
          </Stack>

          <Paper
            variant='outlined'
            sx={{
              p: { xs: 1.75, md: 2.25 },
              maxHeight: { xs: 360, md: 500 },
              overflowY: 'auto',
              bgcolor: 'background.paper',
              borderRadius: 2.5,
              borderColor: 'divider',
            }}
          >
            <Stack spacing={0.85}>
              <Typography variant='subtitle2' fontWeight={650}>
                正文阅读
              </Typography>
            </Stack>
            <Typography
              variant='body2'
              sx={{
                mt: 1.25,
                whiteSpace: 'pre-wrap',
                lineHeight: 1.82,
                wordBreak: 'break-word',
                color: 'text.primary',
              }}
            >
              {resolvedChunkText(selectedChunk)}
            </Typography>
          </Paper>

          {hasStrategyInfo && (
            <Paper
              variant='outlined'
              sx={{
                p: { xs: 1.25, md: 1.5 },
                bgcolor: 'background.paper',
                borderRadius: 2.25,
                borderColor: 'divider',
              }}
            >
              <Stack spacing={0.8}>
                <Typography variant='overline' color='text.secondary'>
                  分块策略信息
                </Typography>
                <Stack direction='row' spacing={0.75} flexWrap='wrap' useFlexGap>
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
              </Stack>
            </Paper>
          )}

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
              {locatorEntries.length > 0 ? (
                <Stack spacing={0.85}>
                  {locatorEntries.map(([key, value]) => (
                    <Stack key={key} direction='row' spacing={1} alignItems='flex-start'>
                      <Typography variant='caption' color='text.secondary' sx={{ minWidth: 84, fontWeight: 600 }}>
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
  );
});

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

  const deferredMaterialFilter = useDeferredValue(materialFilter);
  const filteredMaterials = useMemo(() => {
    const q = deferredMaterialFilter.trim().toLowerCase();
    if (!q) {
      return materials;
    }
    return materials.filter((item) => item.title.toLowerCase().includes(q));
  }, [deferredMaterialFilter, materials]);

  useEffect(() => {
    if (filteredMaterials.length === 0) {
      setSelectedMaterialId(null);
      return;
    }
    if (!selectedMaterialId) {
      setSelectedMaterialId(filteredMaterials[0].id);
      return;
    }
    if (!filteredMaterials.some((item) => item.id === selectedMaterialId)) {
      setSelectedMaterialId(filteredMaterials[0].id);
    }
  }, [filteredMaterials, selectedMaterialId]);

  const selectedMaterial = useMemo(() => {
    if (!selectedMaterialId) {
      return null;
    }
    return filteredMaterials.find((item) => item.id === selectedMaterialId) ?? null;
  }, [filteredMaterials, selectedMaterialId]);

  const materialItems = useMemo<MaterialListItemViewModel[]>(
    () =>
      filteredMaterials.map((item) => ({
        id: item.id,
        title: item.title || item.id,
        sourceLabel: sourceTypeLabel(item.source_type),
        chunkCountLabel: `${item.chunk_count} 块`,
      })),
    [filteredMaterials]
  );

  const chunksQuery = useMaterialChunks(kbId, selectedMaterialId ?? '', {
    skip: 0,
    limit: 100,
    enabled: !browseLocked,
  });
  const chunks = useMemo(() => (browseLocked ? [] : (chunksQuery.data ?? [])), [browseLocked, chunksQuery.data]);

  useEffect(() => {
    if (browseLocked || chunks.length === 0) {
      setSelectedChunkId(null);
      return;
    }
    if (!selectedChunkId) {
      setSelectedChunkId(chunks[0].id);
      return;
    }
    if (!chunks.some((item) => item.id === selectedChunkId)) {
      setSelectedChunkId(chunks[0].id);
    }
  }, [browseLocked, chunks, selectedChunkId]);

  const chunkItems = useMemo<ChunkListItemViewModel[]>(
    () =>
      chunks.map((item) => {
        const strategy = normalizedChunkStrategy(item);
        const hints = chunkStrategyHighlights(item);
        return {
          id: item.id,
          chunkIndexLabel: `${item.chunk_index}`,
          strategyLabel: chunkStrategyLabel(strategy),
          strategyColor: chunkStrategyColor(strategy),
          contextLabel: contextStatusLabel(item.context_status),
          contextColor: contextStatusColor(item.context_status),
          primaryHint: hints[0] ?? null,
          preview: chunkPreview(resolvedChunkText(item), 140),
        };
      }),
    [chunks]
  );

  const chunkDetailQuery = useMaterialChunkDetail(kbId, selectedMaterialId ?? '', selectedChunkId, {
    enabled: !browseLocked,
  });

  const chunkMap = useMemo(() => new Map(chunks.map((item) => [item.id, item])), [chunks]);
  const selectedChunk = browseLocked
    ? null
    : chunkDetailQuery.data ?? (selectedChunkId ? (chunkMap.get(selectedChunkId) ?? null) : null);
  const selectedChunkStrategy = selectedChunk ? normalizedChunkStrategy(selectedChunk) : null;
  const selectedChunkHighlights = selectedChunk ? chunkStrategyHighlights(selectedChunk) : [];

  const sectionError =
    (materialsQuery.error ? getErrorMessage(materialsQuery.error) : null) ??
    (!browseLocked && chunksQuery.error ? getErrorMessage(chunksQuery.error) : null) ??
    (!browseLocked && chunkDetailQuery.error ? getErrorMessage(chunkDetailQuery.error) : null);

  const selectedBg = useMemo(
    () => alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.08 : 0.22),
    [theme.palette.mode, theme.palette.primary.main]
  );

  const handleMobilePanelChange = useCallback((_: SyntheticEvent, value: MobilePanel) => {
    setMobilePanel(value);
  }, []);

  const handleMaterialFilterChange = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    setMaterialFilter(event.target.value);
  }, []);

  const handleSelectMaterial = useCallback(
    (materialId: string) => {
      setSelectedMaterialId(materialId);
      setSelectedChunkId(null);
      if (isMobile) {
        setMobilePanel('chunks');
      }
    },
    [isMobile]
  );

  const handleSelectChunk = useCallback(
    (chunkId: string) => {
      setSelectedChunkId(chunkId);
      if (isMobile) {
        setMobilePanel('content');
      }
    },
    [isMobile]
  );

  return (
    <Paper variant='outlined' sx={{ overflow: 'hidden', borderRadius: 3, borderColor: 'divider' }}>
      <ChunkWorkspaceHeader
        documentCount={materialItems.length}
        chunkCount={chunkItems.length}
        selectedChunkIndex={selectedChunk?.chunk_index ?? null}
      />

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
        <Tabs value={mobilePanel} onChange={handleMobilePanelChange} variant='fullWidth'>
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
        <MaterialColumn
          mobilePanel={mobilePanel}
          materialFilter={materialFilter}
          onMaterialFilterChange={handleMaterialFilterChange}
          items={materialItems}
          selectedMaterialId={selectedMaterialId}
          selectedBg={selectedBg}
          isPending={materialsQuery.isPending}
          onSelectMaterial={handleSelectMaterial}
        />

        <ChunkColumn
          mobilePanel={mobilePanel}
          browseLocked={browseLocked}
          selectedMaterialTitle={selectedMaterial?.title ?? null}
          hasSelectedMaterial={Boolean(selectedMaterial)}
          isPending={chunksQuery.isPending}
          items={chunkItems}
          selectedChunkId={selectedChunkId}
          selectedBg={selectedBg}
          onSelectChunk={handleSelectChunk}
        />

        <ChunkReadingPanel
          mobilePanel={mobilePanel}
          browseLocked={browseLocked}
          selectedChunk={selectedChunk}
          selectedChunkStrategy={selectedChunkStrategy}
          selectedChunkHighlights={selectedChunkHighlights}
        />
      </Box>
    </Paper>
  );
}


export default function KnowledgeBaseDetailPage() {
  const router = useRouter();
  const {
    kbId,
    kbQuery,
    kb,
    showSlowLoading,
    activeBatch,
    browseLocked,
    browseLockMessage,
    progressError,
    summaryMetrics,
    liveStreamHint,
    liveBatchQuery,
  } = useKnowledgeBaseDetailData();

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
      <Paper
        variant='outlined'
        sx={{
          borderRadius: 3,
          borderColor: 'divider',
          overflow: 'hidden',
          p: { xs: 2, md: 2.5 },
          background: (theme) =>
            theme.palette.mode === 'light'
              ? `linear-gradient(135deg, ${alpha(theme.palette.primary.light, 0.12)} 0%, ${alpha(theme.palette.background.paper, 0.98)} 65%)`
              : `linear-gradient(135deg, ${alpha(theme.palette.primary.dark, 0.28)} 0%, ${alpha(theme.palette.background.paper, 0.98)} 65%)`,
        }}
      >
        <Stack spacing={2}>
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

      {liveBatchQuery.isPending && !activeBatch ? (
        <Paper variant='outlined' sx={{ borderRadius: 3, p: 2.5 }}>
          <Stack spacing={1.5}>
            <Typography variant='h6'>导入状态总览</Typography>
            <Typography variant='body2' color='text.secondary'>
              正在获取最新批次状态…
            </Typography>
          </Stack>
        </Paper>
      ) : progressError ? (
        <Paper variant='outlined' sx={{ borderRadius: 3, p: 2.5 }}>
          <Alert severity='error'>{progressError}</Alert>
        </Paper>
      ) : !activeBatch || !summaryMetrics ? (
        <Paper variant='outlined' sx={{ borderRadius: 3, p: 2.5 }}>
          <Stack spacing={1}>
            <Typography variant='h6'>导入状态总览</Typography>
            <Alert severity='info'>当前暂无导入批次。添加文档后可在此查看实时处理状态。</Alert>
          </Stack>
        </Paper>
      ) : (
        <IngestionStatusOverviewCard
          batchId={activeBatch.id}
          statusLabel={batchStatusLabel(activeBatch.status)}
          statusColor={batchStatusColor(activeBatch.status)}
          streamHint={liveStreamHint}
          streamHintSeverity={streamHintSeverity(liveBatchQuery.streamStatus)}
          metrics={summaryMetrics}
          footerHint={formatIngestionSummaryText(summaryMetrics)}
        />
      )}

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
