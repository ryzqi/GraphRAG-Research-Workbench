import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import type { ReactNode } from 'react';
import { Box, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchPageViewModel } from '../../services/researchWorkbench';
import { MarkdownContent } from '../chat/MarkdownContent';
import { ResearchShell } from './ResearchShell';
import {
  researchBodyFont,
  researchDisplayFont,
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
} from './researchWorkbenchStyles';

export function ResearchReportReader({
  model,
  actions: _actions = null,
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

  const chartAccentMap = {
    primary: researchWorkbenchColors.primary,
    secondary: researchWorkbenchColors.secondary,
    tertiary: researchWorkbenchColors.tertiary,
    neutral: researchWorkbenchColors.subtleText,
  } as const;

  return (
    <ResearchShell
      badgeLabel="深度研究结果已生成"
      headline={model.hero.title}
      subheadline={null}
      heroIcon={<AutoAwesomeRoundedIcon sx={{ fontSize: 22 }} />}
      heroMaxWidth={1320}
      bodyMaxWidth={1580}
    >
      <Stack direction={{ xs: 'column', xl: 'row' }} spacing={{ xs: 2.5, xl: 4.5 }} alignItems="flex-start">
        {report.outline.length > 0 ? (
          <Paper
            sx={{
              ...researchWorkbenchInnerCardSx,
              width: { xs: '100%', xl: 216 },
              p: { xs: 1.5, md: 1.8 },
              borderRadius: 3.25,
              bgcolor: alpha('#ffffff', 0.9),
              position: { xl: 'sticky' },
              top: { xl: 20 },
            }}
          >
            <Stack spacing={1}>
              {report.outline.map((item) => (
                <Typography
                  key={item.id}
                  variant="body2"
                  sx={{
                    color: researchWorkbenchColors.mutedText,
                    fontFamily: researchBodyFont,
                    lineHeight: 1.6,
                  }}
                >
                  {item.title}
                </Typography>
              ))}
            </Stack>
          </Paper>
        ) : null}

        <Box sx={{ flex: 1, minWidth: 0, display: 'flex', justifyContent: 'center' }}>
          <Paper
            sx={{
              ...researchWorkbenchInnerCardSx,
              width: '100%',
              maxWidth: 620,
              borderRadius: 4,
              p: { xs: 2.1, md: 2.6 },
              bgcolor: '#ffffff',
            }}
          >
            <Stack spacing={2.2}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1.5}>
                <Stack spacing={0.75}>
                  <Typography
                    variant="caption"
                    sx={{
                      color: researchWorkbenchColors.primary,
                      fontWeight: 800,
                      letterSpacing: '0.08em',
                    }}
                  >
                    {report.badgeLabel ?? '已生成研究报告'}
                  </Typography>
                  <Typography
                    variant="h3"
                    sx={{
                      fontFamily: researchDisplayFont,
                      fontWeight: 800,
                      color: researchWorkbenchColors.text,
                      lineHeight: 1.03,
                      letterSpacing: '-0.05em',
                    }}
                  >
                    {model.hero.title}
                  </Typography>
                </Stack>
                {exportButton}
              </Stack>

              {report.lead ? (
                <Typography
                  variant="body2"
                  sx={{
                    color: researchWorkbenchColors.mutedText,
                    lineHeight: 1.85,
                    fontFamily: researchBodyFont,
                  }}
                >
                  {report.lead}
                </Typography>
              ) : null}

              {report.metricCards.length > 0 ? (
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
                    gap: 1,
                  }}
                >
                  {report.metricCards.slice(0, 3).map((item, index) => (
                    <Paper
                      key={item.label}
                      sx={{
                        borderRadius: 2.5,
                        p: 1.5,
                        boxShadow: 'none',
                        border: 'none',
                        bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.85),
                        borderLeft: `3px solid ${
                          index === 0
                            ? researchWorkbenchColors.primary
                            : index === 1
                              ? researchWorkbenchColors.secondary
                              : researchWorkbenchColors.tertiary
                        }`,
                      }}
                    >
                      <Stack spacing={0.35}>
                        <Typography variant="caption" sx={{ color: researchWorkbenchColors.subtleText }}>
                          {item.label}
                        </Typography>
                        <Typography variant="h6" sx={{ fontWeight: 800, color: researchWorkbenchColors.text }}>
                          {item.value}
                        </Typography>
                      </Stack>
                    </Paper>
                  ))}
                </Box>
              ) : null}

              {report.summary ? (
                <Typography
                  variant="body2"
                  sx={{
                    color: researchWorkbenchColors.mutedText,
                    lineHeight: 1.8,
                    fontFamily: researchBodyFont,
                  }}
                >
                  {report.summary}
                </Typography>
              ) : null}

              {report.chart ? (
                <Paper
                  sx={{
                    borderRadius: 3,
                    p: 1.6,
                    boxShadow: 'none',
                    bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.9),
                  }}
                >
                  <Stack spacing={1.1}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700, color: researchWorkbenchColors.text }}>
                      {report.chart.title}
                    </Typography>
                    <Stack direction="row" spacing={1.1} alignItems="flex-end" sx={{ minHeight: 150 }}>
                      {report.chart.bars.map((item) => (
                        <Stack key={item.label} spacing={0.6} alignItems="center" sx={{ flex: 1 }}>
                          <Box
                            sx={{
                              width: '100%',
                              maxWidth: 72,
                              height: `${Math.max(20, item.value)}px`,
                              borderRadius: '14px 14px 10px 10px',
                              bgcolor: alpha(chartAccentMap[item.accent], 0.24),
                              border: `1px solid ${alpha(chartAccentMap[item.accent], 0.2)}`,
                            }}
                          />
                          <Typography variant="caption" sx={{ color: researchWorkbenchColors.mutedText }}>
                            {item.label}
                          </Typography>
                        </Stack>
                      ))}
                    </Stack>
                  </Stack>
                </Paper>
              ) : null}

              {report.spotlightCards.length > 0 ? (
                <Stack spacing={1.15}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 800, color: researchWorkbenchColors.text }}>
                    关键参与者
                  </Typography>
                  {report.spotlightCards.map((item) => (
                    <Paper
                      key={`${item.eyebrow ?? 'card'}-${item.description}`}
                      sx={{
                        borderRadius: 3,
                        p: 1.4,
                        boxShadow: 'none',
                        bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.72),
                      }}
                    >
                      <Stack spacing={0.55}>
                        {item.eyebrow ? (
                          <Typography variant="caption" sx={{ color: researchWorkbenchColors.subtleText }}>
                            {item.eyebrow}
                          </Typography>
                        ) : null}
                        <Typography variant="subtitle2" sx={{ fontWeight: 800, color: researchWorkbenchColors.text }}>
                          {item.title}
                        </Typography>
                        <Typography
                          variant="body2"
                          sx={{
                            color: researchWorkbenchColors.mutedText,
                            lineHeight: 1.8,
                            fontFamily: researchBodyFont,
                          }}
                        >
                          {item.description}
                        </Typography>
                      </Stack>
                    </Paper>
                  ))}
                </Stack>
              ) : null}

              {report.outlookCards.length > 0 ? (
                <Stack spacing={1}>
                  <Typography variant="subtitle1" sx={{ fontWeight: 800, color: researchWorkbenchColors.text }}>
                    未来展望
                  </Typography>
                  <Box
                    sx={{
                      display: 'grid',
                      gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
                      gap: 1,
                    }}
                  >
                    {report.outlookCards.map((item) => (
                      <Paper
                        key={item.title}
                        sx={{
                          borderRadius: 3,
                          p: 1.35,
                          boxShadow: 'none',
                          bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.72),
                        }}
                      >
                        <Stack spacing={0.55}>
                          <Typography variant="subtitle2" sx={{ fontWeight: 800, color: researchWorkbenchColors.text }}>
                            {item.title}
                          </Typography>
                          <Typography
                            variant="body2"
                            sx={{
                              color: researchWorkbenchColors.mutedText,
                              lineHeight: 1.75,
                              fontFamily: researchBodyFont,
                            }}
                          >
                            {item.description}
                          </Typography>
                        </Stack>
                      </Paper>
                    ))}
                  </Box>
                </Stack>
              ) : null}

              <MarkdownContent content={report.markdown} />

              {report.references.length > 0 ? (
                <Stack spacing={0.7}>
                  <Typography variant="subtitle2" sx={{ fontWeight: 700, color: researchWorkbenchColors.text }}>
                    参考资料
                  </Typography>
                  {report.references.map((item) => (
                    <Typography
                      key={item}
                      variant="body2"
                      sx={{
                        color: researchWorkbenchColors.mutedText,
                        lineHeight: 1.75,
                        fontFamily: researchBodyFont,
                      }}
                    >
                      {item}
                    </Typography>
                  ))}
                </Stack>
              ) : null}
            </Stack>
          </Paper>
        </Box>
      </Stack>
    </ResearchShell>
  );
}
