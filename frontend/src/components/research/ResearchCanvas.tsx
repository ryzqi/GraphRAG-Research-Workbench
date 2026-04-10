import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import InsertChartOutlinedRoundedIcon from '@mui/icons-material/InsertChartOutlinedRounded';
import RotateRightRoundedIcon from '@mui/icons-material/RotateRightRounded';
import SearchRoundedIcon from '@mui/icons-material/SearchRounded';
import type { ReactNode } from 'react';
import { Box, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchPageViewModel } from '../../services/researchWorkbench';
import { ResearchShell } from './ResearchShell';
import {
  researchBodyFont,
  researchDisplayFont,
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
} from './researchWorkbenchStyles';

function resolveActivityIcon(tone: string | undefined) {
  switch (tone) {
    case 'success':
      return <CheckCircleRoundedIcon sx={{ fontSize: 18, color: researchWorkbenchColors.secondary }} />;
    case 'live':
      return <RotateRightRoundedIcon sx={{ fontSize: 18, color: researchWorkbenchColors.primary }} />;
    case 'warning':
      return <InsertChartOutlinedRoundedIcon sx={{ fontSize: 18, color: researchWorkbenchColors.tertiary }} />;
    default:
      return <SearchRoundedIcon sx={{ fontSize: 18, color: researchWorkbenchColors.primary }} />;
  }
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

  return (
    <ResearchShell
      badgeLabel="正在执行深度研究任务"
      headline={model.hero.title}
      footer={
        <Stack
          direction={{ xs: 'column', md: 'row' }}
          spacing={1.5}
          justifyContent="space-between"
          alignItems={{ xs: 'stretch', md: 'center' }}
        >
          <Stack direction="row" spacing={1} alignItems="center">
            <Box
              sx={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                bgcolor: researchWorkbenchColors.secondary,
                flexShrink: 0,
              }}
            />
            <Typography
              variant="body2"
              sx={{
                color: researchWorkbenchColors.mutedText,
                fontFamily: researchBodyFont,
              }}
            >
              {live.footerStatus ?? `系统运行正常，${live.coverageLabel}`}
            </Typography>
          </Stack>
          {actions ? (
            <Stack direction="row" spacing={1.1} justifyContent={{ xs: 'flex-start', md: 'flex-end' }}>
              {actions}
            </Stack>
          ) : null}
        </Stack>
      }
    >
      <Paper
        sx={{
          ...researchWorkbenchInnerCardSx,
          borderRadius: 4,
          p: { xs: 2.2, md: 2.8 },
        }}
      >
        <Stack spacing={2.1}>
          <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.5} justifyContent="space-between">
            <Stack direction="row" spacing={1.05} alignItems="center">
              <AutoAwesomeRoundedIcon sx={{ fontSize: 20, color: researchWorkbenchColors.primary }} />
              <Typography
                variant="h4"
                sx={{
                  fontFamily: researchDisplayFont,
                  fontWeight: 800,
                  color: researchWorkbenchColors.text,
                }}
              >
                研究进度实时追踪
              </Typography>
            </Stack>

            <Box
              sx={{
                alignSelf: { xs: 'flex-start', md: 'center' },
                px: 1.4,
                py: 0.65,
                borderRadius: 999,
                bgcolor: alpha(researchWorkbenchColors.primary, 0.12),
                color: researchWorkbenchColors.primary,
                fontWeight: 800,
              }}
            >
              {live.progress.percent}%
            </Box>
          </Stack>

          <Box
            sx={{
              height: 10,
              borderRadius: 999,
              bgcolor: alpha(researchWorkbenchColors.text, 0.08),
              overflow: 'hidden',
            }}
          >
            <Box
              sx={{
                width: `${live.progress.percent}%`,
                height: '100%',
                borderRadius: 999,
                background: `linear-gradient(90deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
              }}
            />
          </Box>

          <Typography
            variant="body2"
            sx={{
              color: researchWorkbenchColors.subtleText,
              fontFamily: researchBodyFont,
            }}
          >
            当前计划步骤：{live.progress.currentStageLabel}
          </Typography>

          {live.currentAgentLabel || live.currentTaskLabel ? (
            <Paper
              sx={{
                borderRadius: 3,
                px: { xs: 1.4, md: 1.65 },
                py: { xs: 1.25, md: 1.4 },
                bgcolor: alpha(researchWorkbenchColors.primary, 0.05),
                boxShadow: 'none',
              }}
            >
              <Stack spacing={0.7}>
                {live.currentAgentLabel ? (
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    当前代理：{live.currentAgentLabel}
                  </Typography>
                ) : null}
                {live.currentTaskLabel ? (
                  <Typography
                    variant="body2"
                    sx={{
                      color: researchWorkbenchColors.mutedText,
                      fontFamily: researchBodyFont,
                    }}
                  >
                    当前任务：{live.currentTaskLabel}
                  </Typography>
                ) : null}
              </Stack>
            </Paper>
          ) : null}

          <Stack direction="row" justifyContent="space-between" spacing={1.1}>
            {live.planSteps.map((step) => (
              <Typography
                key={step.key}
                variant="caption"
                sx={{
                  flex: 1,
                  textAlign:
                    live.planSteps.length <= 1
                      ? 'left'
                      : step === live.planSteps[0]
                        ? 'left'
                        : step === live.planSteps[live.planSteps.length - 1]
                          ? 'right'
                          : 'center',
                  color:
                    step.state === 'current'
                      ? researchWorkbenchColors.primary
                      : step.state === 'failed' || step.state === 'canceled'
                        ? researchWorkbenchColors.tertiary
                      : step.state === 'complete'
                        ? researchWorkbenchColors.mutedText
                        : alpha(researchWorkbenchColors.subtleText, 0.72),
                  fontWeight: step.state === 'current' ? 800 : 600,
                }}
              >
                {step.label}
              </Typography>
            ))}
          </Stack>

          {live.parallelTasks.length > 0 ? (
            <Paper
              sx={{
                borderRadius: 3,
                px: { xs: 1.4, md: 1.65 },
                py: { xs: 1.3, md: 1.45 },
                bgcolor: alpha(researchWorkbenchColors.primaryContainer, 0.18),
                boxShadow: 'none',
              }}
            >
              <Stack spacing={0.95}>
                <Typography variant="subtitle2" sx={{ fontWeight: 800 }}>
                  并行任务
                </Typography>
                {live.parallelTasks.map((task) => (
                  <Typography
                    key={task.id}
                    variant="body2"
                    sx={{
                      color: researchWorkbenchColors.mutedText,
                      fontFamily: researchBodyFont,
                    }}
                  >
                    {task.agentLabel ? `${task.agentLabel} · ` : ''}
                    {task.label}
                  </Typography>
                ))}
              </Stack>
            </Paper>
          ) : null}

          {live.agentRuns && live.agentRuns.length > 0 ? (
            <Stack direction={{ xs: 'column', md: 'row' }} spacing={1}>
              {live.agentRuns.map((agentRun) => (
                <Paper
                  key={agentRun.agentLabel}
                  sx={{
                    flex: 1,
                    borderRadius: 2.8,
                    px: 1.3,
                    py: 1.15,
                    bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.85),
                    boxShadow: 'none',
                  }}
                >
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    {`${agentRun.agentLabel}${agentRun.status === 'running' ? '运行中' : agentRun.status ?? ''}${agentRun.completedTaskCount}/${agentRun.completedTaskCount + agentRun.activeTaskCount}`}
                  </Typography>
                </Paper>
              ))}
            </Stack>
          ) : null}

          <Paper
            sx={{
              borderRadius: 3,
              px: { xs: 1.4, md: 1.65 },
              py: { xs: 1.3, md: 1.45 },
              bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.9),
              boxShadow: 'none',
            }}
          >
            <Stack spacing={1.25}>
              {live.activity.slice(0, 3).map((item, index) => (
                <Stack
                  key={item.id}
                  direction="row"
                  spacing={1.15}
                  alignItems="flex-start"
                  sx={{
                    pb: index === live.activity.slice(0, 3).length - 1 ? 0 : 1.25,
                    borderBottom:
                      index === live.activity.slice(0, 3).length - 1
                        ? 'none'
                        : `1px solid ${alpha(researchWorkbenchColors.text, 0.06)}`,
                  }}
                >
                  <Box
                    sx={{
                      width: 30,
                      height: 30,
                      borderRadius: '50%',
                      flexShrink: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      bgcolor: alpha(researchWorkbenchColors.primary, 0.08),
                    }}
                  >
                    {resolveActivityIcon(item.tone)}
                  </Box>

                  <Stack spacing={0.32} sx={{ flex: 1, minWidth: 0 }}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                      {item.title}
                    </Typography>
                    {item.body ? (
                      <Typography
                        variant="body2"
                        sx={{
                          color: researchWorkbenchColors.mutedText,
                          lineHeight: 1.7,
                          fontFamily: researchBodyFont,
                        }}
                      >
                        {item.body}
                      </Typography>
                    ) : null}
                  </Stack>

                  <Typography
                    variant="caption"
                    sx={{
                      flexShrink: 0,
                      color: item.timeLabel === 'LIVE' ? researchWorkbenchColors.primary : researchWorkbenchColors.subtleText,
                      fontWeight: item.timeLabel === 'LIVE' ? 800 : 600,
                    }}
                  >
                    {item.timeLabel ?? 'Just now'}
                  </Typography>
                </Stack>
              ))}
            </Stack>
          </Paper>
        </Stack>
      </Paper>
    </ResearchShell>
  );
}
