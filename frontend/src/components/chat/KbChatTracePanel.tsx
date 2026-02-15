import { useMemo, useState } from 'react';
import {
  Box,
  Chip,
  Drawer,
  Paper,
  Stack,
  Typography,
} from '@mui/material';

import { PipelineProgress, type PipelineTimelineEvent } from './PipelineProgress';
import type { ChatRunStateEvent } from '../../services/chats';

interface KbChatTracePanelProps {
  timeline: PipelineTimelineEvent[];
  runState?: ChatRunStateEvent;
  isStreaming: boolean;
}

type FilterKey = 'all' | 'started' | 'completed' | 'failed';

function matchesFilter(item: PipelineTimelineEvent, filter: FilterKey): boolean {
  if (filter === 'all') return true;
  return item.status === filter;
}

export function KbChatTracePanel({ timeline, runState, isStreaming }: KbChatTracePanelProps) {
  const [filter, setFilter] = useState<FilterKey>('all');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filtered = useMemo(
    () => timeline.filter((item) => matchesFilter(item, filter)),
    [timeline, filter]
  );
  const selected = useMemo(
    () => filtered.find((item) => item.id === selectedId) ?? null,
    [filtered, selectedId]
  );

  return (
    <Paper variant='outlined' sx={{ p: 2, borderRadius: 2.5, minHeight: 220 }}>
      <Stack spacing={1.25}>
        <Stack direction='row' spacing={1} alignItems='center' justifyContent='space-between'>
          <Typography variant='subtitle2' fontWeight={700}>
            节点追踪
          </Typography>
          <Stack direction='row' spacing={0.5} useFlexGap flexWrap='wrap'>
            {(['all', 'started', 'completed', 'failed'] as FilterKey[]).map((key) => (
              <Chip
                key={key}
                size='small'
                label={key === 'all' ? '全部' : key}
                color={filter === key ? 'primary' : 'default'}
                onClick={() => setFilter(key)}
              />
            ))}
          </Stack>
        </Stack>

        <PipelineProgress timeline={filtered} isStreaming={isStreaming} runState={runState} />

        <Stack direction='row' spacing={0.75} useFlexGap flexWrap='wrap'>
          {filtered.slice(-8).map((item) => (
            <Chip
              key={item.id}
              size='small'
              variant={selectedId === item.id ? 'filled' : 'outlined'}
              color={item.status === 'failed' ? 'error' : selectedId === item.id ? 'primary' : 'default'}
              label={`${item.label} · ${item.status}`}
              onClick={() => setSelectedId(item.id)}
            />
          ))}
        </Stack>
      </Stack>

      <Drawer
        anchor='right'
        open={Boolean(selected)}
        onClose={() => setSelectedId(null)}
        ModalProps={{ keepMounted: true }}
      >
        <Box sx={{ width: { xs: 320, sm: 420 }, p: 2 }}>
          <Stack spacing={1}>
            <Typography variant='subtitle1' fontWeight={700}>
              追踪详情
            </Typography>
            {selected ? (
              <>
                <Typography variant='body2'>节点: {selected.node ?? '-'}</Typography>
                <Typography variant='body2'>状态: {selected.status}</Typography>
                {selected.message && <Typography variant='body2'>信息: {selected.message}</Typography>}
                {selected.io_summary && (
                  <Box
                    component='pre'
                    sx={{
                      p: 1,
                      borderRadius: 1,
                      bgcolor: 'action.hover',
                      fontSize: 12,
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {JSON.stringify(selected.io_summary, null, 2)}
                  </Box>
                )}
              </>
            ) : null}
          </Stack>
        </Box>
      </Drawer>
    </Paper>
  );
}
