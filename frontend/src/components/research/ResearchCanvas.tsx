import type { ReactNode } from 'react';
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchPageViewModel, ResearchTimelineItem } from '../../services/researchWorkbench';
import { ResearchEvidenceLedger } from './ResearchEvidenceLedger';
import { ResearchShell } from './ResearchShell';
import {
  researchBodyFont,
  researchDisplayFont,
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
  researchWorkbenchOpenPanelSx,
} from './researchWorkbenchStyles';

const longFormTextSx = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowWrap: 'anywhere',
} as const;

function renderLiveItem(item: ResearchTimelineItem) {
  const accent =
    item.kind === 'web_visit'
      ? researchWorkbenchColors.primary
      : item.kind === 'intermediate_result'
        ? researchWorkbenchColors.secondary
        : item.kind === 'system_status'
          ? '#b06a00'
          : researchWorkbenchColors.subtleText;
  return (
    <Paper
      key={item.id}
      sx={{
        ...researchWorkbenchInnerCardSx,
        p: 2.1,
        borderRadius: 3,
        bgcolor: alpha('#ffffff', 0.86),
      }}
    >
      <Stack spacing={0.85}>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1} justifyContent="space-between">
          <Chip
            size="small"
            label={item.phaseLabel}
            sx={{
              alignSelf: 'flex-start',
              bgcolor: alpha(accent, 0.12),
              color: accent,
              fontWeight: 700,
            }}
          />
          {item.providerLabel ? (
            <Typography variant="caption" sx={{ color: researchWorkbenchColors.subtleText }}>
              {item.providerLabel}
            </Typography>
          ) : null}
        </Stack>
        <Typography variant="subtitle1" fontWeight={700} sx={longFormTextSx}>
          {item.title}
        </Typography>
        {item.body ? (
          <Typography
            variant="body2"
            sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.7 }}
          >
            {item.body}
          </Typography>
        ) : null}
      </Stack>
    </Paper>
  );
}

export function ResearchCanvas({
  model,
  actions = null,
}: {
  model: ResearchPageViewModel;
  actions?: ReactNode;
}) {
  const live = model.live;
  if (!live) {
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
        <Stack spacing={1}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            运行状态
          </Typography>
          <Typography variant="h6" sx={{ fontFamily: researchDisplayFont, fontWeight: 800 }}>
            {live.progress.label}
          </Typography>
          <Typography
            variant="body2"
            sx={{ color: researchWorkbenchColors.mutedText, lineHeight: 1.75, fontFamily: researchBodyFont }}
          >
            当前阶段：{live.progress.currentStageLabel}
          </Typography>
          <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
            {live.coverageLabel}
          </Typography>
        </Stack>
      </Paper>
      <Stack spacing={1.2}>
        <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText, px: 0.5 }}>
          来源与证据
        </Typography>
        <ResearchEvidenceLedger {...model.evidenceDrawer} />
      </Stack>
    </>
  );

  return (
    <ResearchShell hero={model.hero} railSteps={model.railSteps} actions={actions} aside={aside}>
      <Paper
        sx={{
          ...researchWorkbenchOpenPanelSx,
          p: { xs: 2.25, md: 2.75 },
          borderRadius: 3.5,
        }}
      >
        <Stack spacing={2}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={2} justifyContent="space-between">
            <Stack spacing={0.55}>
              <Typography
                variant="h4"
                sx={{ fontFamily: researchDisplayFont, fontWeight: 800, color: researchWorkbenchColors.text }}
              >
                进度跟踪
              </Typography>
              <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
                {live.progress.currentStageLabel}
              </Typography>
            </Stack>
            <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.primary, fontWeight: 800 }}>
              总体进度 {live.progress.percent}%
            </Typography>
          </Stack>
          <Box
            sx={{
              height: 12,
              borderRadius: 999,
              bgcolor: alpha(researchWorkbenchColors.primary, 0.1),
              overflow: 'hidden',
            }}
          >
            <Box
              sx={{
                width: `${live.progress.percent}%`,
                height: '100%',
                borderRadius: 999,
                background: `linear-gradient(135deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
              }}
            />
          </Box>
          <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
            {live.coverageLabel}
          </Typography>
        </Stack>
      </Paper>

      {live.activity.length > 0 ? (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' },
            gap: 1.5,
          }}
        >
          {live.activity.map((item) => (
            <Paper
              key={item.id}
              sx={{
                ...researchWorkbenchInnerCardSx,
                p: 2.1,
                borderRadius: 3,
                bgcolor: alpha('#ffffff', 0.84),
              }}
            >
              <Stack spacing={0.8}>
                <Typography variant="caption" sx={{ color: researchWorkbenchColors.subtleText, letterSpacing: '0.14em' }}>
                  实时研究流
                </Typography>
                <Typography variant="subtitle1" fontWeight={700} sx={longFormTextSx}>
                  {item.title}
                </Typography>
                {item.body ? (
                  <Typography
                    variant="body2"
                    sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.7 }}
                  >
                    {item.body}
                  </Typography>
                ) : null}
              </Stack>
            </Paper>
          ))}
        </Box>
      ) : null}

      <Stack spacing={1.5}>
        <Typography variant="h6" fontWeight={800}>
          研究时间流
        </Typography>
        {live.timelineItems.length > 0 ? (
          <Stack spacing={1.5}>{live.timelineItems.map(renderLiveItem)}</Stack>
        ) : (
          <Paper sx={{ ...researchWorkbenchInnerCardSx, p: 2.1, borderRadius: 3 }}>
            <Typography variant="body2" sx={{ color: researchWorkbenchColors.mutedText }}>
              正在等待第一条研究事件…
            </Typography>
          </Paper>
        )}
      </Stack>
    </ResearchShell>
  );
}
