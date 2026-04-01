import type { ReactNode } from 'react';
import { Paper, Stack, Typography } from '@mui/material';

import { MarkdownContent } from '../chat/MarkdownContent';
import { ResearchProgressFeed } from './ResearchProgressFeed';

interface ResearchProgressItem {
  id: string;
  title: string;
  phaseLabel: string;
  providerLabel: string | null;
  sourceLabel: string | null;
  finding: string | null;
}

const sectionSx = {
  p: 2,
  borderRadius: 4,
  borderColor: 'rgba(223, 225, 229, 0.92)',
  bgcolor: '#ffffff',
  boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
} as const;

export function ResearchPlanRail({
  planMarkdown,
  subtaskCount,
  progressItems,
  controls,
  advancedEventsPanel,
}: {
  planMarkdown: string | null;
  subtaskCount: number;
  progressItems: ResearchProgressItem[];
  controls?: ReactNode;
  advancedEventsPanel?: ReactNode;
}) {
  return (
    <Stack spacing={1.5}>
      <Paper variant="outlined" sx={sectionSx}>
        <Stack spacing={1.25}>
          <Typography variant="overline" sx={{ color: '#80868b', letterSpacing: '0.18em' }}>
            Plan Rail
          </Typography>
          <Typography variant="h6" fontWeight={700}>
            执行计划
          </Typography>
          <Typography variant="body2" color="text.secondary">
            当前已拆分 {subtaskCount} 个子任务
          </Typography>
          {planMarkdown ? (
            <MarkdownContent content={planMarkdown} />
          ) : (
            <Typography variant="body2" color="text.secondary">
              计划工件尚未写入，研究启动后会在这里展示。
            </Typography>
          )}
        </Stack>
      </Paper>

      <ResearchProgressFeed items={progressItems} />

      {controls ? (
        <Paper variant="outlined" sx={sectionSx}>
          <Stack spacing={1.25}>
            <Typography variant="subtitle1" fontWeight={600}>
              执行控制
            </Typography>
            {controls}
          </Stack>
        </Paper>
      ) : null}

      {advancedEventsPanel}
    </Stack>
  );
}
