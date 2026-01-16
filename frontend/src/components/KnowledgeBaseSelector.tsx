/**
 * 知识库选择器组件
 * 复用于 KbChatPage、ResearchPage、EvaluationsPage
 */
import { useMemo } from 'react';
import {
  Box,
  Checkbox,
  Chip,
  FormControlLabel,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import type { KnowledgeBase } from '../services/knowledgeBases';
import { EmptyState, LoadingSpinner } from './ui';

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

  if (loading && knowledgeBases.length === 0) {
    return <LoadingSpinner text="加载知识库..." />;
  }

  if (knowledgeBases.length === 0) {
    return <EmptyState title={emptyText} description={emptyDescription} />;
  }

  return (
    <Stack spacing={1}>
      {knowledgeBases.map((kb) => {
        const isSelected = selectedIdSet.has(kb.id);
        return (
          <Paper
            key={kb.id}
            variant="outlined"
            sx={{
              p: 1.5,
              cursor: loading ? 'not-allowed' : 'pointer',
              bgcolor: isSelected ? 'primary.50' : 'background.paper',
              borderColor: isSelected ? 'primary.main' : 'divider',
              transition: 'all 0.2s',
              '&:hover': {
                borderColor: loading ? undefined : 'primary.main',
                bgcolor: loading ? undefined : isSelected ? 'primary.100' : 'action.hover',
              },
            }}
            onClick={() => !loading && onToggle(kb.id)}
          >
            <FormControlLabel
              sx={{ m: 0, alignItems: 'flex-start', width: '100%' }}
              control={
                <Checkbox
                  checked={isSelected}
                  disabled={loading}
                  sx={{ pt: 0 }}
                />
              }
              label={
                <Box sx={{ ml: 1 }}>
                  <Typography fontWeight={500}>{kb.name}</Typography>
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
              }
            />
          </Paper>
        );
      })}
    </Stack>
  );
}
