/**
 * 知识库选择器组件
 * 复用在 KbChatPage、ResearchPage
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Box, Button, Checkbox, Chip, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';
import type { KnowledgeBase } from '../services/knowledgeBases';
import {
  createKnowledgeBaseVisibleCount,
  extendKnowledgeBaseVisibleCount,
  syncKnowledgeBaseVisibleCount,
} from '../services/knowledgeBaseSelectorRenderPlan';
import { EmptyState } from './ui/EmptyState';
import { LoadingSpinner } from './ui/LoadingSpinner';

interface KnowledgeBaseSelectorProps {
  knowledgeBases: KnowledgeBase[];
  selectedIds: string[];
  onToggle: (kbId: string) => void;
  loading?: boolean;
  emptyText?: string;
  emptyDescription?: string;
}

export function KnowledgeBaseSelector({
  knowledgeBases,
  selectedIds,
  onToggle,
  loading = false,
  emptyText = '暂无可用知识库',
  emptyDescription = '请先创建知识库并导入资料',
}: KnowledgeBaseSelectorProps) {
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);
  const datasetKey = useMemo(() => knowledgeBases.map((kb) => kb.id).join('|'), [knowledgeBases]);
  const previousDatasetKeyRef = useRef(datasetKey);
  const [visibleCount, setVisibleCount] = useState(() =>
    createKnowledgeBaseVisibleCount(knowledgeBases.length)
  );

  useEffect(() => {
    setVisibleCount((current) =>
      syncKnowledgeBaseVisibleCount({
        currentVisibleCount: current,
        totalCount: knowledgeBases.length,
        previousDatasetKey: previousDatasetKeyRef.current,
        nextDatasetKey: datasetKey,
      })
    );
    previousDatasetKeyRef.current = datasetKey;
  }, [datasetKey, knowledgeBases.length]);

  const visibleKnowledgeBases = useMemo(
    () => knowledgeBases.slice(0, visibleCount),
    [knowledgeBases, visibleCount]
  );

  if (loading && knowledgeBases.length === 0) {
    return <LoadingSpinner text="加载知识库..." />;
  }

  if (knowledgeBases.length === 0) {
    return <EmptyState title={emptyText} description={emptyDescription} />;
  }

  return (
    <Stack spacing={1.25}>
      {visibleKnowledgeBases.map((kb, index) => {
        const isSelected = selectedIdSet.has(kb.id);
        return (
          <Paper
            key={kb.id}
            variant="outlined"
            sx={{
              position: 'relative',
              overflow: 'hidden',
              p: 1.75,
              borderRadius: 3,
              cursor: loading ? 'not-allowed' : 'pointer',
              contentVisibility: 'auto',
              containIntrinsicSize: '1px 120px',
              bgcolor: (theme) =>
                theme.palette.mode === 'light'
                  ? alpha(theme.palette.common.white, isSelected ? 0.86 : 0.72)
                  : alpha(theme.palette.background.paper, isSelected ? 0.72 : 0.62),
              borderColor: isSelected ? 'primary.main' : 'divider',
              boxShadow: (theme) =>
                isSelected
                  ? `0 0 0 1px ${alpha(theme.palette.primary.main, 0.32)}, 0 14px 40px ${alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.16 : 0.35)}`
                  : 'none',
              transform: isSelected ? 'translateY(-1px)' : 'translateY(0)',
              transition:
                'border-color 200ms ease, background-color 200ms ease, box-shadow 220ms ease, transform 220ms ease',
              animation: 'kbCardEnter 380ms cubic-bezier(0.2, 0, 0, 1)',
              animationDelay: `${index * 35}ms`,
              animationFillMode: 'backwards',
              '@keyframes kbCardEnter': {
                from: { opacity: 0, transform: 'translateY(8px)' },
                to: { opacity: 1, transform: 'translateY(0)' },
              },
              '&::before': {
                content: '""',
                position: 'absolute',
                inset: 0,
                opacity: isSelected ? 1 : 0,
                background:
                  'linear-gradient(120deg, rgba(66,133,244,0.16), rgba(155,114,203,0.12), rgba(217,101,112,0.16))',
                transition: 'opacity 220ms ease',
                pointerEvents: 'none',
              },
              '@media (prefers-reduced-motion: reduce)': {
                animation: 'none',
                transition: 'none',
                transform: 'none',
              },
              '&:hover': {
                borderColor: loading ? undefined : 'primary.main',
                transform: loading ? undefined : 'translateY(-2px)',
                boxShadow: loading
                  ? undefined
                  : (theme) =>
                      `0 10px 30px ${alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.14 : 0.28)}`,
              },
            }}
            onClick={() => !loading && onToggle(kb.id)}
          >
            <Stack direction="row" alignItems="flex-start" sx={{ width: '100%' }}>
              <Checkbox
                checked={isSelected}
                disabled={loading}
                onChange={() => !loading && onToggle(kb.id)}
                onClick={(event) => event.stopPropagation()}
                sx={{ pt: 0, '& .MuiSvgIcon-root': { fontSize: 22 } }}
              />
              <Box sx={{ ml: 1, flex: 1, minWidth: 0 }}>
                <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                  <Typography fontWeight={600}>{kb.name}</Typography>
                  {isSelected && (
                    <Chip size="small" label="已选择" color="primary" variant="filled" />
                  )}
                </Stack>
                {kb.description && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                    {kb.description}
                  </Typography>
                )}
                {kb.tags && kb.tags.length > 0 && (
                  <Stack direction="row" spacing={0.5} sx={{ mt: 1 }} flexWrap="wrap" useFlexGap>
                    {kb.tags.map((tag) => (
                      <Chip key={tag} label={tag} size="small" variant="outlined" />
                    ))}
                  </Stack>
                )}
              </Box>
            </Stack>
          </Paper>
        );
      })}
      {visibleCount < knowledgeBases.length && (
        <Box sx={{ display: 'flex', justifyContent: 'center', pt: 0.5 }}>
          <Button
            size="small"
            variant="outlined"
            onClick={() =>
              setVisibleCount((current) =>
                extendKnowledgeBaseVisibleCount(current, knowledgeBases.length)
              )
            }
          >
            加载更多知识库
          </Button>
        </Box>
      )}
    </Stack>
  );
}
