import { Alert, Box, Paper, Stack, Typography } from '@mui/material';

import type { DocumentChunk } from '../../services/materialChunks';

interface KbDetailChunkPreviewProps {
  chunk: DocumentChunk | null;
  groupLabel: string | null;
  emptyText?: string;
}

function resolvedChunkText(chunk: DocumentChunk): string {
  const baseText = chunk.raw_text || chunk.embedding_text;
  const contextText = chunk.context_text;
  if (!contextText || contextText.trim().length === 0) {
    return baseText;
  }
  return `${baseText}\n\n${contextText}`;
}

function buildSecondaryMeta(chunk: DocumentChunk): string[] {
  const items: string[] = [];
  if (chunk.token_count != null) {
    items.push(`Token ${chunk.token_count}`);
  }
  if (chunk.token_start != null && chunk.token_end != null) {
    items.push(`${chunk.token_start}-${chunk.token_end}`);
  }
  return items;
}

export function KbDetailChunkPreview({
  chunk,
  groupLabel,
  emptyText = '请选择一个分块查看正文。',
}: KbDetailChunkPreviewProps) {
  if (!chunk) {
    return (
      <Paper
        variant='outlined'
        sx={{
          height: '100%',
          minHeight: 0,
          borderRadius: 3,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          p: 3,
        }}
      >
        <Typography variant='body2' color='text.secondary' align='center'>
          {emptyText}
        </Typography>
      </Paper>
    );
  }

  const secondaryMeta = buildSecondaryMeta(chunk);

  return (
    <Paper
      variant='outlined'
      sx={{
        height: '100%',
        minHeight: 0,
        borderRadius: 3,
        borderColor: 'divider',
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
      }}
    >
      <Box sx={{ px: 1.75, py: 1.35, borderBottom: 1, borderColor: 'divider' }}>
        <Stack spacing={0.45}>
          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={0.75}
            alignItems={{ xs: 'flex-start', sm: 'center' }}
            justifyContent='space-between'
          >
            <Typography variant='subtitle2' fontWeight={700}>
              Chunk {chunk.chunk_index}
            </Typography>
            {groupLabel && (
              <Typography variant='caption' color='text.secondary'>
                {groupLabel}
              </Typography>
            )}
          </Stack>
          {secondaryMeta.length > 0 && (
            <Typography variant='caption' color='text.secondary'>
              {secondaryMeta.join(' · ')}
            </Typography>
          )}
        </Stack>
      </Box>

      <Box sx={{ flex: 1, minHeight: 0, overflowY: 'auto', px: 2, py: 1.75 }}>
        <Typography
          variant='body2'
          sx={{
            whiteSpace: 'pre-wrap',
            lineHeight: 1.85,
            wordBreak: 'break-word',
          }}
        >
          {resolvedChunkText(chunk)}
        </Typography>
      </Box>

      {chunk.context_error && (
        <Box sx={{ px: 2, pb: 1.75 }}>
          <Alert
            severity={chunk.context_status === 'degraded' ? 'warning' : 'error'}
          >
            {chunk.context_error}
          </Alert>
        </Box>
      )}
    </Paper>
  );
}
