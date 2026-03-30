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
  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={{ p: 2, borderRadius: 3 }}>
        <Stack spacing={1.25}>
          <Typography variant="subtitle1" fontWeight={600}>
            当前研究
          </Typography>
          <Typography variant="body2">{question}</Typography>
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
