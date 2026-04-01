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
  borderRadius: 6,
  borderColor: 'rgba(210, 227, 252, 0.92)',
  bgcolor: '#ffffff',
  boxShadow: '0 16px 40px rgba(94, 129, 244, 0.08)',
} as const;

const liveBackground = 'linear-gradient(180deg,#f7faff 0%,#eef4ff 45%,#f8fbff 100%)';
const liveGlow = 'radial-gradient(circle at top,rgba(66,133,244,0.18) 0%,rgba(66,133,244,0) 42%)';
const finalBackground =
  'linear-gradient(180deg,rgba(255,255,255,0.98) 0%,rgba(245,249,255,0.98) 100%)';

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
        pl: { xs: 2.75, md: 3.5 },
        '&:before': {
          content: '""',
          position: 'absolute',
          left: { xs: 9, md: 14 },
          top: 0,
          bottom: -14,
          width: 1,
          background: alpha('#1a73e8', 0.18),
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
          boxShadow: `0 0 0 6px ${alpha(accent, 0.12)}`,
        },
      }}
    >
      <Paper
        variant="outlined"
        sx={{
          ...panelSx,
          p: 2.25,
          borderRadius: 5,
          borderColor: alpha(accent, 0.16),
          color: '#202124',
          background:
            item.kind === 'intermediate_result'
              ? `linear-gradient(180deg, ${alpha('#ffffff', 0.98)} 0%, ${alpha(accent, 0.08)} 100%)`
              : `linear-gradient(180deg, rgba(255,255,255,0.98) 0%, ${alpha(accent, 0.04)} 100%)`,
          backdropFilter: 'blur(14px)',
          boxShadow: `0 18px 44px ${alpha('#1a73e8', 0.08)}`,
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
                    color: '#5f6368',
                    borderColor: 'rgba(210, 227, 252, 0.92)',
                    background: '#ffffff',
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
        p: { xs: 1.5, md: 2 },
        borderRadius: 7,
        background: liveBackground,
        boxShadow: '0 28px 90px rgba(66, 133, 244, 0.12)',
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
        borderColor: 'rgba(210, 227, 252, 0.96)',
        background: 'linear-gradient(180deg, rgba(255,255,255,0.96) 0%, rgba(244,248,255,0.98) 100%)',
        color: '#202124',
        backdropFilter: 'blur(18px)',
        boxShadow: '0 18px 44px rgba(66, 133, 244, 0.08)',
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
                  color: isLive ? '#5f6368' : '#64748b',
                  letterSpacing: '0.18em',
                }}
              >
                {isLive ? '研究工作台' : '报告视图'}
              </Typography>
              <Typography
                variant="h4"
                sx={{ fontWeight: 700, color: isLive ? '#202124' : '#0f172a', maxWidth: 680 }}
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
                bgcolor: isLive ? 'rgba(26, 115, 232, 0.08)' : 'rgba(26, 115, 232, 0.08)',
                color: '#1967d2',
                fontWeight: 600,
                border: '1px solid rgba(26, 115, 232, 0.12)',
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
            boxShadow: '0 20px 48px rgba(148, 163, 184, 0.12)',
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
              borderColor: 'rgba(210, 227, 252, 0.96)',
              background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(244,248,255,0.98) 100%)',
              color: '#202124',
              boxShadow: '0 18px 44px rgba(66, 133, 244, 0.08)',
            }}
          >
            <Stack spacing={1.5}>
              <Stack spacing={0.45}>
                <Typography
                  variant="overline"
                  sx={{ color: '#5f6368', letterSpacing: '0.18em' }}
                >
                  研究过程
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
                <Typography variant="body2" sx={{ color: '#5f6368' }}>
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
