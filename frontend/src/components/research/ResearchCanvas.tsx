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
  p: { xs: 2.25, md: 3 },
  borderRadius: 5,
  borderColor: 'rgba(223, 225, 229, 0.92)',
  bgcolor: '#ffffff',
  boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
} as const;

const liveBackground = 'linear-gradient(180deg,#08101f 0%,#0f172a 52%,#111827 100%)';
const liveGlow = 'radial-gradient(circle at top,rgba(96,165,250,0.28) 0%,rgba(96,165,250,0) 38%)';
const finalBackground =
  'linear-gradient(180deg,rgba(255,255,255,0.96) 0%,rgba(248,250,252,0.98) 100%)';

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
    item.kind === 'web_visit'
      ? '#60a5fa'
      : item.kind === 'thought_summary'
        ? '#c084fc'
        : item.kind === 'intermediate_result'
          ? '#34d399'
          : '#94a3b8';
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
        pl: { xs: 2.75, md: 3.5 },
        '&:before': {
          content: '""',
          position: 'absolute',
          left: { xs: 9, md: 14 },
          top: 0,
          bottom: -14,
          width: 1,
          background: alpha('#94a3b8', 0.24),
        },
        '&:after': {
          content: '""',
          position: 'absolute',
          left: { xs: 4, md: 9 },
          top: 18,
          width: 11,
          height: 11,
          borderRadius: 999,
          background: accent,
          boxShadow: `0 0 0 6px ${alpha(accent, 0.14)}`,
        },
      }}
    >
      <Paper
        variant="outlined"
        sx={{
          ...panelSx,
          p: 2.25,
          borderRadius: 4,
          borderColor: alpha(accent, 0.22),
          color: '#e5eefc',
          background:
            item.kind === 'intermediate_result'
              ? `linear-gradient(180deg, ${alpha(accent, 0.18)} 0%, rgba(15, 23, 42, 0.92) 100%)`
              : `linear-gradient(180deg, rgba(15, 23, 42, 0.96) 0%, ${alpha(accent, 0.08)} 100%)`,
          backdropFilter: 'blur(20px)',
          boxShadow: `0 24px 60px ${alpha('#020617', 0.34)}, inset 0 1px 0 ${alpha('#ffffff', 0.08)}`,
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
                  borderColor: alpha(accent, 0.32),
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
                    color: alpha('#e2e8f0', 0.92),
                    borderColor: alpha('#94a3b8', 0.24),
                    background: 'rgba(255,255,255,0.04)',
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
                color: alpha('#cbd5e1', 0.72),
                letterSpacing: '0.14em',
                textTransform: 'uppercase',
              }}
            >
              {item.kind === 'web_visit'
                ? 'source trace'
                : item.kind === 'thought_summary'
                  ? 'thinking'
                  : item.kind === 'intermediate_result'
                    ? 'working answer'
                    : 'session state'}
            </Typography>
            <Typography variant="subtitle1" fontWeight={700}>
              {item.title}
            </Typography>
          </Stack>
          {item.body ? (
            <Typography variant="body2" sx={{ color: alpha('#cbd5e1', 0.86), lineHeight: 1.65 }}>
              {item.body}
            </Typography>
          ) : null}
        </Stack>
      </Paper>
    </Box>
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
  const rootSurfaceSx = isLive
    ? {
        position: 'relative',
        overflow: 'hidden',
        p: { xs: 1.25, md: 1.75 },
        borderRadius: 6,
        background: liveBackground,
        boxShadow: '0 36px 120px rgba(2, 6, 23, 0.38)',
        '&:before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background: liveGlow,
          pointerEvents: 'none',
        },
      }
    : {
        p: { xs: 0.25, md: 0.5 },
      };

  const headerSx = isLive
    ? {
        ...panelSx,
        position: 'relative',
        borderColor: 'rgba(148, 163, 184, 0.18)',
        background: 'linear-gradient(180deg, rgba(15, 23, 42, 0.86) 0%, rgba(15, 23, 42, 0.72) 100%)',
        color: '#f8fafc',
        backdropFilter: 'blur(20px)',
        boxShadow: '0 24px 80px rgba(2, 6, 23, 0.34), inset 0 1px 0 rgba(255,255,255,0.08)',
      }
    : {
        ...panelSx,
        background: finalBackground,
        borderColor: 'rgba(226, 232, 240, 0.92)',
      };

  return (
    <Stack spacing={2.5} sx={{ maxWidth: 1040, mx: 'auto', ...rootSurfaceSx }}>
      <Paper variant="outlined" sx={headerSx}>
        <Stack spacing={2}>
          <Stack
            direction={{ xs: 'column', md: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', md: 'center' }}
            spacing={1.5}
          >
            <Stack spacing={0.75}>
              <Typography
                variant="overline"
                sx={{
                  color: isLive ? alpha('#cbd5e1', 0.72) : '#64748b',
                  letterSpacing: '0.18em',
                }}
              >
                {isLive ? 'live research' : 'final report'}
              </Typography>
              <Typography
                variant="h4"
                sx={{ fontWeight: 700, color: isLive ? '#f8fafc' : '#0f172a', maxWidth: 680 }}
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
                minHeight: 32,
                px: 1.5,
                borderRadius: 999,
                bgcolor: isLive ? 'rgba(96, 165, 250, 0.12)' : 'rgba(26, 115, 232, 0.08)',
                color: isLive ? '#bfdbfe' : '#1967d2',
                fontWeight: 600,
                border: isLive ? '1px solid rgba(96, 165, 250, 0.18)' : '1px solid rgba(26, 115, 232, 0.12)',
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
            borderColor: 'rgba(226, 232, 240, 0.92)',
            boxShadow: '0 24px 60px rgba(148, 163, 184, 0.12)',
          }}
        >
          <Stack spacing={1.5}>
            <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1.5}>
              <Typography variant="h5" fontWeight={700}>
                最终报告
              </Typography>
              {exportButton}
            </Stack>
            <MarkdownContent content={model.report?.markdown ?? ''} />
          </Stack>
        </Paper>
      ) : (
        <Stack spacing={2}>
          <Paper
            variant="outlined"
            sx={{
              ...panelSx,
              position: 'relative',
              overflow: 'hidden',
              borderColor: 'rgba(148, 163, 184, 0.14)',
              background: 'linear-gradient(180deg, rgba(8, 15, 31, 0.96) 0%, rgba(15, 23, 42, 0.88) 100%)',
              color: '#e5eefc',
              boxShadow: '0 28px 80px rgba(2, 6, 23, 0.42)',
            }}
          >
            <Stack spacing={1.5}>
              <Stack spacing={0.45}>
                <Typography
                  variant="overline"
                  sx={{ color: alpha('#cbd5e1', 0.7), letterSpacing: '0.18em' }}
                >
                  deep research stream
                </Typography>
                <Typography variant="h6" fontWeight={700}>
                  研究时间流
                </Typography>
              </Stack>
              {model.timelineItems.length > 0 ? (
                <Stack spacing={1.5} sx={{ position: 'relative', py: 0.5 }}>
                  {model.timelineItems.map(renderLiveItem)}
                </Stack>
              ) : (
                <Typography variant="body2" sx={{ color: alpha('#cbd5e1', 0.82) }}>
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
