import type { ReactNode } from 'react';
import { Box, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchPageViewModel } from '../../services/researchWorkbench';
import { MarkdownContent } from '../chat/MarkdownContent';
import { ResearchEvidenceLedger } from './ResearchEvidenceLedger';
import { ResearchShell } from './ResearchShell';
import {
  researchDisplayFont,
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
} from './researchWorkbenchStyles';

export function ResearchReportReader({
  model,
  actions = null,
  exportButton = null,
}: {
  model: ResearchPageViewModel;
  actions?: ReactNode;
  exportButton?: ReactNode;
}) {
  const report = model.report;
  if (!report) {
    return null;
  }

  const aside = (
    <>
      <Paper
        sx={{
          ...researchWorkbenchInnerCardSx,
          p: 2.25,
          borderRadius: 3.5,
          bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.72),
        }}
      >
        <Stack spacing={1.1}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            目录
          </Typography>
          {report.outline.map((item) => (
            <Typography key={item.id} variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
              {item.title}
            </Typography>
          ))}
        </Stack>
      </Paper>

      <Paper
        sx={{
          ...researchWorkbenchInnerCardSx,
          p: 2.25,
          borderRadius: 3.5,
          bgcolor: alpha('#ffffff', 0.88),
        }}
      >
        <Stack spacing={1.2}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            证据状态
          </Typography>
          {report.metricCards.map((item) => (
            <Stack key={item.label} direction="row" justifyContent="space-between" spacing={1}>
              <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
                {item.label}
              </Typography>
              <Typography variant="body2" fontWeight={800} sx={{ color: researchWorkbenchColors.text }}>
                {item.value}
              </Typography>
            </Stack>
          ))}
        </Stack>
      </Paper>

      {exportButton ? (
        <Paper
          sx={{
            ...researchWorkbenchInnerCardSx,
            p: 2,
            borderRadius: 3.5,
            bgcolor: alpha('#ffffff', 0.88),
          }}
        >
          {exportButton}
        </Paper>
      ) : null}
    </>
  );

  return (
    <ResearchShell hero={model.hero} railSteps={model.railSteps} actions={actions} aside={aside}>
      <Paper
        sx={{
          ...researchWorkbenchInnerCardSx,
          p: { xs: 2.25, md: 2.75 },
          borderRadius: 3.5,
          bgcolor: alpha('#ffffff', 0.86),
        }}
      >
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={2}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', md: 'center' }}
        >
          <Stack spacing={0.65}>
            <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
              报告摘要
            </Typography>
            <Typography
              variant="h4"
              sx={{ fontFamily: researchDisplayFont, fontWeight: 800, color: researchWorkbenchColors.text }}
            >
              研究报告
            </Typography>
            <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
              {report.summary}
            </Typography>
          </Stack>
        </Stack>
      </Paper>

      {report.metricCards.length > 0 ? (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(3, minmax(0, 1fr))' },
            gap: 1.25,
          }}
        >
          {report.metricCards.map((item) => (
            <Paper
              key={item.label}
              sx={{
                ...researchWorkbenchInnerCardSx,
                p: 2,
                borderRadius: 3,
                bgcolor: alpha('#ffffff', 0.84),
              }}
            >
              <Stack spacing={0.45}>
                <Typography variant="caption" sx={{ color: researchWorkbenchColors.subtleText }}>
                  {item.label}
                </Typography>
                <Typography variant="h5" fontWeight={800}>
                  {item.value}
                </Typography>
              </Stack>
            </Paper>
          ))}
        </Box>
      ) : null}

      <Paper
        sx={{
          ...researchWorkbenchInnerCardSx,
          p: { xs: 2.25, md: 3 },
          borderRadius: 3.5,
          bgcolor: alpha('#ffffff', 0.92),
        }}
      >
        <MarkdownContent content={report.markdown} />
      </Paper>

      <ResearchEvidenceLedger {...model.evidenceDrawer} />
    </ResearchShell>
  );
}
