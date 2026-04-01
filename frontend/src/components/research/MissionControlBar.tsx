import type { ReactNode } from 'react';
import { Paper, Stack, Typography } from '@mui/material';

import { MarkdownContent } from '../chat/MarkdownContent';
import { StatusBadge } from '../ui/StatusBadge';

export function MissionControlBar({
  question,
  statusLabel,
  statusTone,
  coverageLabel,
  missionMarkdown,
  actions,
}: {
  question: string;
  statusLabel: string;
  statusTone: 'pending' | 'queued' | 'running' | 'succeeded' | 'canceled' | 'failed';
  coverageLabel: string;
  missionMarkdown: string | null;
  actions?: ReactNode;
}) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: { xs: 2.25, md: 3 },
        borderRadius: 5,
        borderColor: 'rgba(223, 225, 229, 0.92)',
        bgcolor: '#ffffff',
        boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
      }}
    >
      <Stack spacing={2}>
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', md: 'flex-start' }}
          spacing={1.5}
        >
          <Stack spacing={0.75}>
            <Typography variant="overline" sx={{ color: '#80868b', letterSpacing: '0.18em' }}>
              Mission Control
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, color: '#202124' }}>
              {question || '未命名研究任务'}
            </Typography>
          </Stack>
          {actions ? <Stack direction="row" spacing={1}>{actions}</Stack> : null}
        </Stack>

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
          <StatusBadge status={statusTone} label={statusLabel} />
          <Typography
            component="span"
            variant="body2"
            sx={{
              display: 'inline-flex',
              alignItems: 'center',
              minHeight: 32,
              px: 1.5,
              borderRadius: 999,
              bgcolor: 'rgba(26, 115, 232, 0.08)',
              color: '#1967d2',
              fontWeight: 600,
            }}
          >
            {coverageLabel}
          </Typography>
        </Stack>

        {missionMarkdown ? (
          <Stack spacing={0.75}>
            <Typography variant="subtitle2" sx={{ color: '#5f6368' }}>
              当前任务摘要
            </Typography>
            <MarkdownContent content={missionMarkdown} />
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}
