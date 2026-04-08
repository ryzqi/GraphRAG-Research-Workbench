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
  researchWorkbenchCardSx,
  researchWorkbenchColors,
  researchWorkbenchEyebrowSx,
  researchWorkbenchInnerCardSx,
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

const panelSx = {
  ...researchWorkbenchCardSx,
  p: { xs: 2.5, md: 3 },
} as const;

const finalBackground =
  'linear-gradient(180deg,rgba(255,255,255,1) 0%,rgba(248,249,250,1) 100%)';

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
    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
      {tokens.length > 0 ? (
        <Typography variant="caption" color="text.secondary">
          {tokens.join(' · ')}
        </Typography>
      ) : null}
      {item.url ? (
        <Link href={item.url} target="_blank" rel="noreferrer" variant="caption" underline="hover">
          {item.url}
        </Link>
      ) : null}
    </Stack>
  );
}

function renderLiveItem(item: ResearchTimelineItem) {
  const accent =
    item.kind === 'web_visit' ? '#1a73e8' : item.kind === 'thought_summary' ? '#7c3aed' : item.kind === 'intermediate_result' ? '#0f9d58' : '#5f6368';
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
        pl: { xs: 2.5, md: 3.25 },
        '&:before': {
          content: '""',
          position: 'absolute',
          left: { xs: 10, md: 14 },
          top: 6,
          bottom: -10,
          width: 2,
          borderRadius: 999,
          background: alpha(researchWorkbenchColors.primary, 0.14),
        },
        '&:after': {
          content: '""',
          position: 'absolute',
          left: { xs: 4, md: 8 },
          top: 18,
          width: 14,
          height: 14,
          borderRadius: 999,
          background: accent,
          border: `3px solid ${researchWorkbenchColors.surface}`,
          boxShadow: `0 0 0 4px ${alpha(accent, 0.12)}`,
        },
      }}
    >
      <Paper
        variant="outlined"
        sx={{
          ...researchWorkbenchInnerCardSx,
          p: 2.25,
          borderColor: alpha(accent, 0.18),
          color: researchWorkbenchColors.text,
          background:
            item.kind === 'intermediate_result'
              ? `linear-gradient(180deg, ${alpha('#ffffff', 1)} 0%, ${alpha(accent, 0.06)} 100%)`
              : researchWorkbenchColors.surface,
          boxShadow: `0 8px 20px ${alpha('#3c4043', 0.06)}`,
        }}
      >
        <Stack spacing={1.1}>
          <Stack direction={{ xs: 'column', sm: 'row' }} justifyContent="space-between" spacing={1}>
            <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
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
                    background: researchWorkbenchColors.surface,
                  }}
                />
              ) : null}
            </Stack>
            {renderTimelineMeta(item)}
          </Stack>
          <Stack spacing={0.55}>
            <Typography
              variant="caption"
              sx={{
                color: '#5f6368',
                letterSpacing: '0.14em',
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
            <Typography variant="subtitle1" fontWeight={700}>
              {item.title}
            </Typography>
          </Stack>
          {item.body ? (
            <Typography variant="body2" sx={{ color: '#3c4043', lineHeight: 1.72 }}>
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
    <Stack spacing={0.5}>
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

  const headerSx = isLive
    ? {
        ...panelSx,
        background: finalBackground,
      }
    : {
        ...panelSx,
        background: finalBackground,
      };

  return (
    <Stack spacing={3} sx={{ width: '100%' }}>
      <Paper variant="outlined" sx={headerSx}>
        <Stack spacing={2.5}>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', md: 'center' }}
            spacing={1.5}
          >
            <Stack spacing={0.75}>
              <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
                {isLive ? 'Research Workbench' : 'Final Report'}
              </Typography>
              <Typography
                variant="h4"
                sx={{ fontWeight: 700, color: researchWorkbenchColors.text, maxWidth: 760 }}
              >
                {model.title || '未命名研究任务'}
              </Typography>
            </Stack>
            {actions}
          </Stack>

          <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} useFlexGap flexWrap="wrap">
            <StatusBadge status={model.statusTone} label={model.statusLabel} />
            <Typography
              component="span"
              variant="body2"
              sx={{
                display: 'inline-flex',
                alignItems: 'center',
                minHeight: 34,
                px: 1.75,
                borderRadius: 999,
                bgcolor: researchWorkbenchColors.accentBackground,
                color: researchWorkbenchColors.primary,
                fontWeight: 600,
                border: `1px solid ${alpha(researchWorkbenchColors.primary, 0.14)}`,
              }}
            >
              {model.coverageLabel}
            </Typography>
          </Stack>
        </Stack>
      </Paper>

      {model.surface === 'final-report' ? (
        <Paper
          variant="outlined"
          sx={{
            ...panelSx,
            background: finalBackground,
            boxShadow: '0 10px 28px rgba(60, 64, 67, 0.08)',
          }}
        >
          <Stack spacing={2}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1.5}>
              {renderSectionHeading('报告输出', '最终报告')}
              {exportButton}
            </Stack>
            <MarkdownContent content={model.report?.markdown ?? ''} />
          </Stack>
        </Paper>
      ) : (
        <Stack spacing={2.5}>
          <Paper
            variant="outlined"
            sx={{
              ...panelSx,
              overflow: 'hidden',
              background: finalBackground,
            }}
          >
            <Stack spacing={2}>
              {renderSectionHeading('研究过程', '研究时间流')}
              {model.timelineItems.length > 0 ? (
                <Stack spacing={1.75} sx={{ position: 'relative', py: 0.25 }}>
                  {model.timelineItems.map(renderLiveItem)}
                </Stack>
              ) : (
                <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
                  正在等待第一条研究事件…
                </Typography>
              )}
            </Stack>
          </Paper>
        </Stack>
      )}

      <ResearchEvidenceLedger {...model.evidenceDrawer} tone={isLive ? 'dark' : 'light'} />
    </Stack>
  );
}
