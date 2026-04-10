import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import type { ReactNode } from 'react';
import { useEffect, useEffectEvent, useMemo, useState } from 'react';
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

type ReportOutlineItem = NonNullable<ResearchPageViewModel['report']>['outline'][number];
type ReportOutlineAnchor = ReportOutlineItem & { anchorId: string };

const ACTIVE_SECTION_TOP = 160;

export function buildReportOutlineAnchors(outline: ReportOutlineItem[]): ReportOutlineAnchor[] {
  return outline.map((item) => ({
    ...item,
    anchorId: `report-${item.id}`,
  }));
}

export function resolveActiveReportSection(
  sections: Array<{ anchorId: string; top: number }>,
  threshold = ACTIVE_SECTION_TOP
): string | null {
  if (sections.length === 0) {
    return null;
  }

  let activeAnchorId = sections[0]?.anchorId ?? null;
  for (const section of sections) {
    if (section.top <= threshold) {
      activeAnchorId = section.anchorId;
    }
  }
  return activeAnchorId;
}

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

  const outlineAnchors = useMemo(() => buildReportOutlineAnchors(report.outline), [report.outline]);
  const [activeSectionId, setActiveSectionId] = useState<string | null>(outlineAnchors[0]?.anchorId ?? null);

  useEffect(() => {
    setActiveSectionId(outlineAnchors[0]?.anchorId ?? null);
  }, [outlineAnchors]);

  const syncActiveSection = useEffectEvent(() => {
    if (typeof document === 'undefined' || outlineAnchors.length === 0) {
      return;
    }

    const measuredSections = outlineAnchors.flatMap((item) => {
      const element = document.getElementById(item.anchorId);
      if (!element) {
        return [];
      }
      return [{ anchorId: item.anchorId, top: element.getBoundingClientRect().top }];
    });

    const nextActiveSectionId = resolveActiveReportSection(measuredSections);
    if (!nextActiveSectionId) {
      return;
    }

    setActiveSectionId((current) => (current === nextActiveSectionId ? current : nextActiveSectionId));
  });

  useEffect(() => {
    if (typeof window === 'undefined' || outlineAnchors.length === 0) {
      return;
    }

    let frame = 0;
    const scheduleSync = () => {
      if (frame) {
        return;
      }
      frame = window.requestAnimationFrame(() => {
        frame = 0;
        syncActiveSection();
      });
    };

    scheduleSync();
    window.addEventListener('scroll', scheduleSync, { passive: true });
    window.addEventListener('resize', scheduleSync);
    return () => {
      if (frame) {
        window.cancelAnimationFrame(frame);
      }
      window.removeEventListener('scroll', scheduleSync);
      window.removeEventListener('resize', scheduleSync);
    };
  }, [outlineAnchors, syncActiveSection]);

  const handleOutlineClick = useEffectEvent((anchorId: string) => {
    if (typeof document === 'undefined') {
      return;
    }
    const target = document.getElementById(anchorId);
    if (!target) {
      return;
    }
    setActiveSectionId(anchorId);
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  });

  return (
    <ResearchShell
      badgeLabel={null}
      headline={model.hero.title}
      subheadline={null}
      heroIcon={<AutoAwesomeRoundedIcon sx={{ fontSize: 22 }} />}
      heroMaxWidth={1320}
      bodyMaxWidth={2200}
    >
      <Stack direction={{ xs: 'column', xl: 'row' }} spacing={{ xs: 2.5, xl: 3.2 }} alignItems="stretch">
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Paper
            sx={{
              ...researchWorkbenchInnerCardSx,
              width: '100%',
              borderRadius: 4,
              p: { xs: 2.1, md: 2.8, xl: 3.25 },
              bgcolor: '#ffffff',
            }}
          >
            <Stack spacing={2.4}>
              <Stack direction="row" justifyContent="space-between" alignItems="flex-start" spacing={1.5}>
                <Stack spacing={0.75} sx={{ minWidth: 0 }}>
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
                      overflowWrap: 'anywhere',
                    }}
                  >
                    {model.hero.title}
                  </Typography>
                </Stack>
                {exportButton}
              </Stack>

              {report.summary ? (
                <Typography
                  variant="body2"
                  sx={{
                    color: researchWorkbenchColors.mutedText,
                    lineHeight: 1.85,
                    fontFamily: researchBodyFont,
                  }}
                >
                  {report.summary}
                </Typography>
              ) : null}

              {report.metricCards.length > 0 ? (
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: { xs: '1fr', sm: 'repeat(3, minmax(0, 1fr))' },
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

              <MarkdownContent content={report.markdown} h2Ids={outlineAnchors.map((item) => item.anchorId)} />
            </Stack>
          </Paper>
        </Box>

        {outlineAnchors.length > 0 ? (
          <Paper
            sx={{
              ...researchWorkbenchInnerCardSx,
              width: { xs: '100%', xl: 296 },
              flexShrink: 0,
              p: { xs: 1.5, md: 1.8 },
              borderRadius: 3.25,
              bgcolor: alpha('#ffffff', 0.9),
              position: { xl: 'sticky' },
              top: { xl: 24 },
              alignSelf: { xl: 'flex-start' },
            }}
          >
            <Stack spacing={1.2}>
              <Typography
                variant="caption"
                sx={{
                  color: researchWorkbenchColors.subtleText,
                  letterSpacing: '0.08em',
                  fontWeight: 800,
                }}
              >
                报告目录
              </Typography>

              {outlineAnchors.map((item) => {
                const isActive = item.anchorId === activeSectionId;
                return (
                  <Box
                    key={item.anchorId}
                    component="button"
                    type="button"
                    onClick={() => handleOutlineClick(item.anchorId)}
                    aria-current={isActive ? 'true' : undefined}
                    sx={{
                      width: '100%',
                      border: 'none',
                      outline: 'none',
                      textAlign: 'left',
                      cursor: 'pointer',
                      borderRadius: 2.4,
                      px: 1.15,
                      py: 1,
                      bgcolor: isActive ? alpha(researchWorkbenchColors.primary, 0.1) : 'transparent',
                      boxShadow: 'none',
                      transition: 'background-color 120ms ease, color 120ms ease',
                      '&:hover': {
                        bgcolor: alpha(researchWorkbenchColors.primary, 0.08),
                      },
                    }}
                  >
                    <Typography
                      variant="body2"
                      sx={{
                        color: isActive ? researchWorkbenchColors.text : researchWorkbenchColors.mutedText,
                        fontFamily: researchBodyFont,
                        fontWeight: isActive ? 700 : 500,
                        lineHeight: 1.6,
                      }}
                    >
                      {item.title}
                    </Typography>
                  </Box>
                );
              })}
            </Stack>
          </Paper>
        ) : null}
      </Stack>
    </ResearchShell>
  );
}
