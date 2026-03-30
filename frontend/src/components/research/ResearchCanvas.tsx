import type { ReactNode } from 'react';
import { Paper, Stack, Typography } from '@mui/material';

import { MarkdownContent } from '../chat/MarkdownContent';

interface ResearchCanvasModel {
  mode: 'progressive' | 'final';
  currentStepTitle: string;
  currentStepBody: string | null;
  findingsTitle: string;
  findingsBody: string | null;
  finalReportTitle: string;
  finalReportBody: string | null;
  coverageGap: string | null;
}

export function ResearchCanvas({
  model,
  artifactPanel,
  exportButton,
}: {
  model: ResearchCanvasModel;
  artifactPanel: ReactNode;
  exportButton: ReactNode;
}) {
  return (
    <Stack spacing={2}>
      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 4 }}>
        <Typography variant="subtitle1" fontWeight={700}>
          {model.currentStepTitle}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {model.currentStepBody ?? '等待研究启动。'}
        </Typography>
      </Paper>
      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 4 }}>
        <Typography variant="subtitle1" fontWeight={700}>
          {model.findingsTitle}
        </Typography>
        <Typography variant="body1">
          {model.findingsBody ?? '研究进行中，阶段性发现将在这里持续更新。'}
        </Typography>
        {model.coverageGap ? (
          <Typography variant="body2" color="warning.main">
            {model.coverageGap}
          </Typography>
        ) : null}
      </Paper>
      <Paper variant="outlined" sx={{ p: 2.5, borderRadius: 4 }}>
        <Stack spacing={1.5}>
          <Stack direction="row" justifyContent="space-between" alignItems="center">
            <Typography variant="subtitle1" fontWeight={700}>
              {model.finalReportTitle}
            </Typography>
            {model.mode === 'final' ? exportButton : null}
          </Stack>
          {model.finalReportBody ? (
            <MarkdownContent content={model.finalReportBody} />
          ) : (
            <Typography variant="body2" color="text.secondary">
              最终报告生成后会在这里成为主阅读区。
            </Typography>
          )}
        </Stack>
      </Paper>
      {artifactPanel}
    </Stack>
  );
}
