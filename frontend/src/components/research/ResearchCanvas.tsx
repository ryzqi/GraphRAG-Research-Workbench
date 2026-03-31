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
  const sectionSx = {
    p: { xs: 2.25, md: 3 },
    borderRadius: 5,
    borderColor: 'rgba(223, 225, 229, 0.92)',
    bgcolor: '#ffffff',
    boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
  } as const;

  return (
    <Stack spacing={2.5}>
      <Paper variant="outlined" sx={sectionSx}>
        <Typography variant="overline" sx={{ color: '#80868b', letterSpacing: '0.16em' }}>
          {model.currentStepTitle}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {model.currentStepBody ?? '等待研究启动。'}
        </Typography>
      </Paper>
      <Paper variant="outlined" sx={sectionSx}>
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
      <Paper variant="outlined" sx={sectionSx}>
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
