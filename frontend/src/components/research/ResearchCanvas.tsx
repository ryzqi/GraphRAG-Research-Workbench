import type { ReactNode } from 'react';
import { Box, Chip, Link, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type {
  ResearchEvidenceDrawerModel,
  ResearchTimelineItem,
} from '../../services/researchWorkbench';
import { StatusBadge } from '../ui/StatusBadge';
import { MarkdownContent } from '../chat/MarkdownContent';
import { ResearchEvidenceLedger } from './ResearchEvidenceLedger';
import {
  researchWorkbenchColors,
  researchWorkbenchEyebrowSx,
  researchWorkbenchInnerCardSx,
  researchWorkbenchOpenPanelSx,
  researchWorkbenchSectionDividerSx,
} from './researchWorkbenchStyles';

interface ResearchCanvasModel {
  surface: 'live-research' | 'final-report';
  title: string;
  statusLabel: string;
  statusTone: 'pending' | 'queued' | 'running' | 'succeeded' | 'canceled' | 'failed';
  coverageLabel: string;
  timelineItems: ResearchTimelineItem[];
  evidenceDrawer: ResearchEvidenceDrawerModel;
  report?: {
    markdown: string;
  };
}

const longFormTextSx = {
  minWidth: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowWrap: 'anywhere',
} as const;

const timelineCardSx = {
  ...researchWorkbenchInnerCardSx,
  p: { xs: 2.25, md: 2.5 },
  minWidth: 0,
} as const;

function formatDomain(url: string | null): string | null {
  if (!url) {
    return null;
  }

  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

function renderTimelineMeta(item: ResearchTimelineItem) {
  const tokens = [item.phaseLabel, item.providerLabel].filter(Boolean);
  if (!item.url && tokens.length === 0) {
    return null;
  }

  return (
    <Stack
      direction={{ xs: 'column', sm: 'row' }}
      spacing={1}
      useFlexGap
      flexWrap="wrap"
      sx={{ minWidth: 0 }}
    >
      {tokens.length > 0 ? (
        <Typography
          variant="caption"
          sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
        >
          {tokens.join(' · ')}
        </Typography>
      ) : null}
      {item.url ? (
        <Link
          href={item.url}
          target="_blank"
          rel="noreferrer"
          variant="caption"
          underline="hover"
          sx={{ ...longFormTextSx, color: researchWorkbenchColors.primary }}
        >
          {item.url}
        </Link>
      ) : null}
    </Stack>
  );
}

function renderLiveItem(item: ResearchTimelineItem) {
  const accent =
    item.kind === 'web_visit'
      ? '#1a73e8'
      : item.kind === 'thought_summary'
        ? '#7c3aed'
        : item.kind === 'intermediate_result'
          ? '#0f9d58'
          : '#5f6368';
  const chipLabel =
    item.kind === 'web_visit'
      ? '网页访问'
      : item.kind === 'thought_summary'
        ? '摘要思考'
        : item.kind === 'intermediate_result'
          ? '中间产出'
          : '系统状态';
  const domain = formatDomain(item.url);

  return (
    <Box
      key={item.id}
      sx={{
        position: 'relative',
        minWidth: 0,
        pl: { xs: 4.5, md: 5.75 },
        '&:before': {
          content: '""',
          position: 'absolute',
          left: { xs: 9, md: 13 },
          top: 4,
          bottom: -12,
          width: 2,
          borderRadius: 999,
          background: alpha(accent, 0.16),
        },
        '&:after': {
          content: '""',
          position: 'absolute',
          left: { xs: 0, md: 4 },
          top: 16,
          width: 20,
          height: 20,
          borderRadius: 999,
          background: accent,
          border: `4px solid ${researchWorkbenchColors.pageBackground}`,
          boxShadow: `0 0 0 6px ${alpha(accent, 0.12)}`,
        },
      }}
    >
      <Paper
        variant="outlined"
        sx={{
          ...timelineCardSx,
          borderColor: alpha(accent, 0.18),
          background:
            item.kind === 'intermediate_result'
              ? `linear-gradient(180deg, ${alpha('#ffffff', 0.96)} 0%, ${alpha(
                  accent,
                  0.08
                )} 100%)`
              : `linear-gradient(180deg, ${alpha('#ffffff', 0.96)} 0%, ${alpha(
                  researchWorkbenchColors.surfaceMuted,
                  0.92
                )} 100%)`,
          boxShadow: `0 16px 40px ${alpha('#3c4043', 0.08)}`,
        }}
      >
        <Stack spacing={1.25} sx={{ minWidth: 0 }}>
          <Stack
            direction={{ xs: 'column', lg: 'row' }}
            justifyContent="space-between"
            spacing={1.25}
            sx={{ minWidth: 0 }}
          >
            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ minWidth: 0 }}>
              <Chip
                label={chipLabel}
                size="small"
                variant="outlined"
                sx={{
                  alignSelf: 'flex-start',
                  color: accent,
                  borderColor: alpha(accent, 0.16),
                  background: alpha(accent, 0.08),
                  fontWeight: 700,
                }}
              />
              {domain ? (
                <Chip
                  label={domain}
                  size="small"
                  variant="outlined"
                  sx={{
                    alignSelf: 'flex-start',
                    color: researchWorkbenchColors.mutedText,
                    borderColor: researchWorkbenchColors.border,
                    background: alpha('#ffffff', 0.92),
                  }}
                />
              ) : null}
            </Stack>
            <Box sx={{ minWidth: 0 }}>{renderTimelineMeta(item)}</Box>
          </Stack>

          <Stack spacing={0.55} sx={{ minWidth: 0 }}>
            <Typography
              variant="caption"
              sx={{
                color: researchWorkbenchColors.subtleText,
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
              }}
            >
              {item.kind === 'web_visit'
                ? '来源轨迹'
                : item.kind === 'thought_summary'
                  ? '思考过程'
                  : item.kind === 'intermediate_result'
                    ? '阶段产出'
                    : '会话状态'}
            </Typography>
            <Typography variant="subtitle1" sx={{ ...longFormTextSx, fontWeight: 700 }}>
              {item.title}
            </Typography>
          </Stack>

          {item.body ? (
            <Typography
              variant="body2"
              sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.72 }}
            >
              {item.body}
            </Typography>
          ) : null}
        </Stack>
      </Paper>
    </Box>
  );
}

function renderSectionHeading(eyebrow: string, title: string) {
  return (
    <Stack spacing={0.5} sx={{ minWidth: 0 }}>
      <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
        {eyebrow}
      </Typography>
      <Typography variant="h6" fontWeight={700}>
        {title}
      </Typography>
    </Stack>
  );
}

export function ResearchCanvas({
  model,
  exportButton,
  actions,
}: {
  model: ResearchCanvasModel;
  exportButton: ReactNode;
  actions: ReactNode;
}) {
  const isLive = model.surface === 'live-research';

  return (
    <Stack spacing={0} sx={{ width: '100%', minWidth: 0 }}>
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', xl: 'minmax(0, 1fr) auto' },
          gap: 2.5,
          minWidth: 0,
          pb: { xs: 2.75, md: 3.25 },
          borderBottom: `1px solid ${researchWorkbenchColors.softBorder}`,
        }}
      >
        <Stack spacing={1.25} sx={{ minWidth: 0 }}>
          <Stack spacing={0.75} sx={{ minWidth: 0 }}>
            <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
              {isLive ? 'Research Workbench' : 'Final Report'}
            </Typography>
            <Typography
              variant="h3"
              sx={{
                ...longFormTextSx,
                fontWeight: 700,
                color: researchWorkbenchColors.text,
                lineHeight: 1.12,
                fontSize: { xs: '2rem', md: '2.7rem' },
              }}
            >
              {model.title || '未命名研究任务'}
            </Typography>
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
            <StatusBadge status={model.statusTone} label={model.statusLabel} />
            <Typography
              component="span"
              variant="body2"
              sx={{
                display: 'inline-flex',
                alignItems: 'center',
                minHeight: 36,
                px: 1.75,
                borderRadius: 2.5,
                bgcolor: researchWorkbenchColors.accentBackground,
                color: researchWorkbenchColors.primary,
                fontWeight: 700,
                border: `1px solid ${alpha(researchWorkbenchColors.primary, 0.14)}`,
              }}
            >
              {model.coverageLabel}
            </Typography>
          </Stack>
        </Stack>

        <Stack
          direction="row"
          spacing={1}
          useFlexGap
          flexWrap="wrap"
          justifyContent={{ xl: 'flex-end' }}
          sx={{ alignItems: 'flex-start' }}
        >
          {actions}
        </Stack>
      </Box>

      {model.surface === 'final-report' ? (
        <Box sx={researchWorkbenchSectionDividerSx}>
          <Box sx={{ ...researchWorkbenchOpenPanelSx, p: { xs: 2.5, md: 3 }, minWidth: 0 }}>
            <Stack spacing={2} sx={{ minWidth: 0 }}>
              <Stack
                direction={{ xs: 'column', sm: 'row' }}
                justifyContent="space-between"
                alignItems={{ xs: 'flex-start', sm: 'center' }}
                spacing={1.5}
                sx={{ minWidth: 0 }}
              >
                {renderSectionHeading('报告输出', '最终报告')}
                {exportButton}
              </Stack>
              <MarkdownContent content={model.report?.markdown ?? ''} />
            </Stack>
          </Box>
        </Box>
      ) : (
        <Stack spacing={2.5} sx={{ ...researchWorkbenchSectionDividerSx, width: '100%' }}>
          {renderSectionHeading('研究过程', '研究时间流')}
          {model.timelineItems.length > 0 ? (
            <Stack spacing={2} sx={{ position: 'relative', py: 0.25, minWidth: 0 }}>
              {model.timelineItems.map(renderLiveItem)}
            </Stack>
          ) : (
            <Box sx={{ ...researchWorkbenchOpenPanelSx, px: 2.5, py: 2.25, minWidth: 0 }}>
              <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
                正在等待第一条研究事件…
              </Typography>
            </Box>
          )}
        </Stack>
      )}

      <Box sx={researchWorkbenchSectionDividerSx}>
        <ResearchEvidenceLedger {...model.evidenceDrawer} />
      </Box>
    </Stack>
  );
}
