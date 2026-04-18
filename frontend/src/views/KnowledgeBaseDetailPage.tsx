'use client';

import {
  useCallback,
  useDeferredValue,
  useMemo,
  useState,
  type ChangeEvent,
  type SyntheticEvent,
} from 'react';
import { useRouter } from 'next/navigation';
import {
  Alert,
  Box,
  Paper,
  Stack,
  Tab,
  Tabs,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';

import {
  batchStatusColor,
  batchStatusLabel,
  formatIngestionSummaryText,
} from '../components/ingestion/statusPresentation';
import { KbDetailChunkList } from '../components/knowledge-base-detail/KbDetailChunkList';
import { KbDetailChunkPreview } from '../components/knowledge-base-detail/KbDetailChunkPreview';
import { KbDetailDocumentRail } from '../components/knowledge-base-detail/KbDetailDocumentRail';
import { KbDetailHero } from '../components/knowledge-base-detail/KbDetailHero';
import { KbDetailIngestionStrip } from '../components/knowledge-base-detail/KbDetailIngestionStrip';
import { KbDetailWindowSwitcher } from '../components/knowledge-base-detail/KbDetailWindowSwitcher';
import { Button } from '../components/ui/Button';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import {
  useAllMaterialChunks,
  useAllMaterialsWithChunkStats,
} from '../hooks/queries/useMaterialChunks';
import { useKnowledgeBaseDetailData } from '../hooks/useKnowledgeBaseDetailData';
import { getErrorMessage } from '../lib/errorHandler';
import type { DocumentChunk } from '../services/materialChunks';
import {
  buildKnowledgeBaseWorkspaceModel,
  resolveActiveChunkId,
  resolveActiveKey,
  summarizeKnowledgeBaseInventory,
} from '../services/knowledgeBaseDetailLayout';

type MobilePanel = 'documents' | 'browser' | 'preview';

const EMPTY_WINDOW_CHUNKS: DocumentChunk[] = [];

function buildChunkPreview(text: string, max = 124): string {
  const compact = text.replace(/\s+/g, ' ').trim();
  if (compact.length <= max) {
    return compact;
  }
  return `${compact.slice(0, max)}…`;
}

function buildResolvedChunkText(chunk: DocumentChunk): string {
  const baseText = chunk.raw_text || chunk.embedding_text;
  const contextText = chunk.context_text?.trim();
  if (!contextText) {
    return baseText;
  }
  return `${baseText}\n\n${contextText}`;
}

function buildChunkMeta(chunk: DocumentChunk): string | null {
  const items: string[] = [];
  if (chunk.token_start != null && chunk.token_end != null) {
    items.push(`Token ${chunk.token_start}-${chunk.token_end}`);
  } else if (chunk.token_count != null) {
    items.push(`Token ${chunk.token_count}`);
  }

  if (chunk.context_status === 'degraded') {
    items.push('降级生成');
  } else if (chunk.context_status === 'fallback') {
    items.push('增强失败');
  }

  if (items.length === 0) {
    return null;
  }
  return items.join(' · ');
}

function readinessPresentation(
  readiness: 'ready' | 'not_ready'
): {
  label: string;
  color: 'default' | 'success' | 'warning' | 'error' | 'info';
} {
  if (readiness === 'ready') {
    return { label: '已就绪', color: 'success' };
  }
  return { label: '未就绪', color: 'warning' };
}

interface ChunkBrowserWorkspaceProps {
  kbId: string;
  materials: Array<{
    id: string;
    title: string;
    chunk_count: number;
  }>;
  materialsPending: boolean;
  materialsError: string | null;
  browseLocked: boolean;
  browseLockMessage: string | null;
}

function ChunkBrowserWorkspace({
  kbId,
  materials,
  materialsPending,
  materialsError,
  browseLocked,
  browseLockMessage,
}: ChunkBrowserWorkspaceProps) {
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const [mobilePanel, setMobilePanel] = useState<MobilePanel>('documents');
  const [materialFilter, setMaterialFilter] = useState('');
  const [selectedMaterialId, setSelectedMaterialId] = useState<string | null>(null);
  const [selectedWindowKey, setSelectedWindowKey] = useState<string | null>(null);
  const [selectedChunkId, setSelectedChunkId] = useState<string | null>(null);

  const deferredMaterialFilter = useDeferredValue(materialFilter);
  const filteredMaterials = useMemo(() => {
    const query = deferredMaterialFilter.trim().toLowerCase();
    if (!query) {
      return materials;
    }
    return materials.filter((item) => item.title.toLowerCase().includes(query));
  }, [deferredMaterialFilter, materials]);

  const activeMaterialId = useMemo(() => {
    if (filteredMaterials.length === 0) {
      return null;
    }
    if (
      selectedMaterialId &&
      filteredMaterials.some((item) => item.id === selectedMaterialId)
    ) {
      return selectedMaterialId;
    }
    return filteredMaterials[0]?.id ?? null;
  }, [filteredMaterials, selectedMaterialId]);

  const selectedMaterial = useMemo(
    () =>
      activeMaterialId
        ? filteredMaterials.find((item) => item.id === activeMaterialId) ?? null
        : null,
    [activeMaterialId, filteredMaterials]
  );

  const chunksQuery = useAllMaterialChunks(kbId, activeMaterialId ?? '', {
    limit: 100,
    enabled: !browseLocked && Boolean(activeMaterialId),
  });

  const chunks = useMemo(
    () => (browseLocked ? [] : chunksQuery.data ?? []),
    [browseLocked, chunksQuery.data]
  );

  const workspaceModel = useMemo(
    () => buildKnowledgeBaseWorkspaceModel(chunks),
    [chunks]
  );

  const activeWindowKey = useMemo(
    () => resolveActiveKey(workspaceModel.windows, selectedWindowKey),
    [selectedWindowKey, workspaceModel.windows]
  );

  const activeWindow = useMemo(
    () =>
      activeWindowKey
        ? workspaceModel.windows.find((window) => window.key === activeWindowKey) ??
          null
        : null,
    [activeWindowKey, workspaceModel.windows]
  );

  const activeWindowChunks = activeWindow?.items ?? EMPTY_WINDOW_CHUNKS;
  const activeChunkId = useMemo(
    () => resolveActiveChunkId(activeWindowChunks, selectedChunkId),
    [activeWindowChunks, selectedChunkId]
  );

  const selectedChunk = useMemo(
    () =>
      activeChunkId
        ? activeWindowChunks.find((chunk) => chunk.id === activeChunkId) ?? null
        : null,
    [activeChunkId, activeWindowChunks]
  );

  const sectionError =
    materialsError ??
    (!browseLocked && chunksQuery.error
      ? getErrorMessage(chunksQuery.error)
      : null);

  const documentItems = useMemo(
    () =>
      filteredMaterials.map((material) => ({
        id: material.id,
        title: material.title || material.id,
        chunkCountLabel: `${material.chunk_count} 块`,
      })),
    [filteredMaterials]
  );

  const windowTabs = useMemo(
    () =>
      workspaceModel.windows.map((window) => ({
        key: window.key,
        label: window.label,
        chunkCount: window.items.length,
      })),
    [workspaceModel.windows]
  );

  const chunkItems = useMemo(
    () =>
      activeWindowChunks.map((chunk) => ({
        id: chunk.id,
        title: `Chunk ${chunk.chunk_index}`,
        meta: buildChunkMeta(chunk),
        preview: buildChunkPreview(buildResolvedChunkText(chunk)),
      })),
    [activeWindowChunks]
  );
  const documentEmptyText = materialFilter.trim()
    ? '没有匹配的文档。'
    : '暂无可浏览文档。';

  const handleMobilePanelChange = useCallback(
    (_: SyntheticEvent, value: MobilePanel) => {
      setMobilePanel(value);
    },
    []
  );

  const handleMaterialFilterChange = useCallback(
    (event: ChangeEvent<HTMLInputElement>) => {
      setMaterialFilter(event.target.value);
    },
    []
  );

  const handleSelectMaterial = useCallback(
    (materialId: string) => {
      setSelectedMaterialId(materialId);
      setSelectedChunkId(null);
      if (isMobile) {
        setMobilePanel('browser');
      }
    },
    [isMobile]
  );

  const handleSelectWindow = useCallback(
    (windowKey: string) => {
      setSelectedWindowKey(windowKey);
      const targetWindow =
        workspaceModel.windows.find((window) => window.key === windowKey) ?? null;
      if (!targetWindow) {
        setSelectedChunkId(null);
        return;
      }

      setSelectedChunkId((currentChunkId) =>
        currentChunkId &&
        targetWindow.items.some((chunk) => chunk.id === currentChunkId)
          ? currentChunkId
          : null
      );
    },
    [workspaceModel.windows]
  );

  const handleSelectChunk = useCallback(
    (chunkId: string) => {
      setSelectedChunkId(chunkId);
      if (isMobile) {
        setMobilePanel('preview');
      }
    },
    [isMobile]
  );

  const workspaceAlert = sectionError ?? (browseLocked ? browseLockMessage : null);

  return (
    <Paper
      variant='outlined'
      sx={{
        borderRadius: 4,
        borderColor: 'divider',
        p: { xs: 1.5, md: 1.75 },
      }}
    >
      <Stack spacing={1.75}>
        <Stack spacing={0.45}>
          <Typography variant='overline' color='text.secondary'>
            浏览工作区
          </Typography>
          <Typography variant='h6' fontWeight={700}>
            文档与分块浏览
          </Typography>
        </Stack>

        {isMobile && (
          <Tabs
            value={mobilePanel}
            onChange={handleMobilePanelChange}
            variant='fullWidth'
          >
            <Tab value='documents' label='文档' />
            <Tab value='browser' label='分块' />
            <Tab value='preview' label='正文' />
          </Tabs>
        )}

        {workspaceAlert && (
          <Alert severity={sectionError ? 'error' : 'info'}>
            {workspaceAlert}
          </Alert>
        )}

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: {
              xs: '1fr',
              md: 'minmax(188px, 212px) minmax(0, 1fr)',
            },
            gap: { xs: 1.5, md: 2 },
            minHeight: { md: 640 },
            height: { md: '72vh' },
            maxHeight: { md: 820 },
            minWidth: 0,
          }}
        >
          <Box
            sx={{
              minHeight: 0,
              display: { xs: mobilePanel === 'documents' ? 'block' : 'none', md: 'block' },
            }}
          >
            <KbDetailDocumentRail
              items={documentItems}
              selectedId={activeMaterialId}
              filterValue={materialFilter}
              onFilterChange={handleMaterialFilterChange}
              onSelect={handleSelectMaterial}
              isPending={materialsPending}
              emptyText={documentEmptyText}
            />
          </Box>

          <Box
            sx={{
              minHeight: 0,
              display: { xs: mobilePanel !== 'documents' ? 'block' : 'none', md: 'block' },
            }}
          >
            <Stack spacing={1.75} sx={{ height: '100%', minHeight: 0 }}>
              <KbDetailWindowSwitcher
                items={windowTabs}
                activeKey={activeWindowKey}
                onChange={handleSelectWindow}
              />

              <Box
                sx={{
                  flex: 1,
                  minHeight: 0,
                  display: 'grid',
                  gridTemplateColumns: {
                    xs: '1fr',
                    lg: 'minmax(280px, 320px) minmax(0, 1fr)',
                  },
                  gridTemplateRows: {
                    xs: 'auto',
                    md: 'minmax(260px, 0.95fr) minmax(0, 1.05fr)',
                    lg: 'minmax(0, 1fr)',
                  },
                  gap: { xs: 1.25, md: 1.5 },
                  minWidth: 0,
                }}
              >
                <Box
                  sx={{
                    minHeight: { xs: 320, md: 0 },
                    display: {
                      xs: mobilePanel === 'browser' ? 'block' : 'none',
                      md: 'block',
                    },
                  }}
                >
                  <KbDetailChunkList
                    items={chunkItems}
                    selectedChunkId={activeChunkId}
                    onSelect={handleSelectChunk}
                    isPending={chunksQuery.isPending}
                    emptyText={
                      browseLocked
                        ? browseLockMessage ?? '文档处理中，暂不可浏览分块。'
                        : activeMaterialId
                          ? '当前窗口暂无分块。'
                          : '请先从左侧选择文档。'
                    }
                  />
                </Box>

                <Box
                  sx={{
                    minHeight: { xs: 340, md: 0 },
                    display: {
                      xs: mobilePanel === 'preview' ? 'block' : 'none',
                      md: 'block',
                    },
                  }}
                >
                  <KbDetailChunkPreview
                    chunk={selectedChunk}
                    groupLabel={activeWindow?.label ?? null}
                    emptyText={
                      browseLocked
                        ? browseLockMessage ?? '文档处理中，暂不可浏览正文。'
                        : selectedMaterial?.title
                          ? '请选择一个分块查看正文。'
                          : '请先从左侧选择文档。'
                    }
                  />
                </Box>
              </Box>
            </Stack>
          </Box>
        </Box>
      </Stack>
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

  const materialsQuery = useAllMaterialsWithChunkStats(kbId ?? '', {
    limit: 100,
    enabled: Boolean(kbId),
  });

  const materials = materialsQuery.data ?? [];
  const inventorySummary = summarizeKnowledgeBaseInventory(materials);
  const readiness = kb
    ? readinessPresentation(kb.readiness)
    : { label: '未就绪', color: 'warning' as const };

  if (kbQuery.isPending) {
    return (
      <Stack spacing={2}>
        <LoadingSpinner
          text={showSlowLoading ? '仍在加载知识库，请稍候…' : '加载知识库...'}
        />
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

  const resolvedKbId = kbId ?? kb.id;
  const ingestionState: 'loading' | 'error' | 'idle' | 'active' =
    liveBatchQuery.isPending && !activeBatch
      ? 'loading'
      : progressError
        ? 'error'
        : activeBatch && summaryMetrics
          ? 'active'
          : 'idle';

  return (
    <Stack spacing={{ xs: 2, md: 2.5 }}>
      <KbDetailHero
        name={kb.name}
        description={kb.description}
        documentCount={
          materialsQuery.isPending && materials.length === 0
            ? '—'
            : inventorySummary.documentCount
        }
        chunkCount={
          materialsQuery.isPending && materials.length === 0
            ? '—'
            : inventorySummary.chunkCount
        }
        readinessLabel={readiness.label}
        readinessColor={readiness.color}
        actions={
          <Stack direction='row' spacing={1} flexWrap='wrap' useFlexGap>
            <Button variant='outlined' onClick={() => router.push('/knowledge-bases')}>
              返回列表
            </Button>
            <Button
              variant='contained'
              onClick={() => router.push(`/knowledge-bases/${resolvedKbId}/documents/new`)}
            >
              添加文档
            </Button>
          </Stack>
        }
      />

      <KbDetailIngestionStrip
        state={ingestionState}
        statusLabel={activeBatch ? batchStatusLabel(activeBatch.status) : null}
        statusColor={activeBatch ? batchStatusColor(activeBatch.status) : 'default'}
        summaryText={
          summaryMetrics ? formatIngestionSummaryText(summaryMetrics) : null
        }
        helperText={liveStreamHint}
        errorMessage={progressError}
      />

      <ChunkBrowserWorkspace
        kbId={resolvedKbId}
        materials={materials.map((material) => ({
          id: material.id,
          title: material.title,
          chunk_count: material.chunk_count,
        }))}
        materialsPending={materialsQuery.isPending}
        materialsError={
          materialsQuery.error ? getErrorMessage(materialsQuery.error) : null
        }
        browseLocked={browseLocked}
        browseLockMessage={browseLockMessage}
      />
    </Stack>
  );
}
