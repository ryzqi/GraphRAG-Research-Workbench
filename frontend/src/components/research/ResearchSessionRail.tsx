import type { ReactNode } from 'react';
import { Paper, Stack, Typography } from '@mui/material';

import { Button } from '../ui/Button';
import { StatusBadge } from '../ui/StatusBadge';
import { ResearchProgressFeed } from './ResearchProgressFeed';
import { ResearchSourceSummary } from './ResearchSourceSummary';

interface ResearchProgressItem {
  id: string;
  title: string;
  phaseLabel: string;
  providerLabel: string | null;
  sourceLabel: string | null;
  finding: string | null;
}

interface ResearchSourceSummaryModel {
  heading: string;
  modeLabel: string;
  helperText: string;
}

export function ResearchSessionRail({
  question,
  statusLabel,
  statusTone,
  progressItems,
  sourceSummary,
  planPanel,
  interruptPanel,
  advancedEventsPanel,
  onReset,
}: {
  question: string;
  statusLabel: string;
  statusTone: 'pending' | 'queued' | 'running' | 'succeeded' | 'canceled' | 'failed';
  progressItems: ResearchProgressItem[];
  sourceSummary: ResearchSourceSummaryModel;
  planPanel: ReactNode;
  interruptPanel: ReactNode;
  advancedEventsPanel: ReactNode;
  onReset: () => void;
}) {
  const sectionSx = {
    p: 2,
    borderRadius: 4,
    borderColor: 'rgba(223, 225, 229, 0.92)',
    bgcolor: '#ffffff',
    boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
  } as const;

  return (
    <Stack spacing={1.5}>
      <Paper variant="outlined" sx={sectionSx}>
        <Stack spacing={1.25}>
          <Typography variant="overline" sx={{ color: '#80868b', letterSpacing: '0.18em' }}>
            research
          </Typography>
          <Typography variant="body2" sx={{ color: '#202124' }}>
            {question}
          </Typography>
          <Stack direction="row" spacing={1} alignItems="center">
            <StatusBadge status={statusTone} label={statusLabel} />
            <Button variant="outlined" size="small" onClick={onReset}>
              新研究
            </Button>
          </Stack>
        </Stack>
      </Paper>
      {planPanel}
      <ResearchProgressFeed items={progressItems} />
      <ResearchSourceSummary summary={sourceSummary} />
      {interruptPanel}
      {advancedEventsPanel}
    </Stack>
  );
}
