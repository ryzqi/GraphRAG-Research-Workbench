import { Box, Chip, Paper, Stack, Typography } from '@mui/material';

import type { ResearchPlanSnapshot, ResearchSessionStatus } from '../../types/researchEvents';
import { Button } from '../ui/Button';

interface PlanPreviewPanelProps {
  planSnapshot: ResearchPlanSnapshot | null;
  status: ResearchSessionStatus;
  onConfirm?: (() => void | Promise<void>) | undefined;
  confirmPending?: boolean;
}

export function PlanPreviewPanel({
  planSnapshot,
  status,
  onConfirm,
  confirmPending = false,
}: PlanPreviewPanelProps) {
  if (!planSnapshot) {
    return null;
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderRadius: 4,
        borderColor: 'rgba(148, 163, 184, 0.2)',
        bgcolor: 'rgba(15, 23, 42, 0.82)',
        color: '#f8fafc',
      }}
    >
      <Stack spacing={1.75}>
        <Stack spacing={0.5}>
          <Typography
            variant="overline"
            sx={{
              letterSpacing: '0.22em',
              color: 'rgba(226, 232, 240, 0.58)',
            }}
          >
            assistant
          </Typography>
          <Typography variant="subtitle1" fontWeight={600}>
            计划草案
          </Typography>
          <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.68)' }}>
            先确认方向，研究才会进入正式执行。
          </Typography>
        </Stack>

        <Typography variant="body2">{planSnapshot.research_brief}</Typography>
        <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.72)' }}>
          {planSnapshot.summary}
        </Typography>

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {planSnapshot.target_sources.map((item) => (
            <Chip
              key={item}
              label={item}
              size="small"
              variant="outlined"
              sx={{
                color: 'rgba(248, 250, 252, 0.88)',
                borderColor: 'rgba(148, 163, 184, 0.28)',
                bgcolor: 'rgba(15, 23, 42, 0.72)',
              }}
            />
          ))}
        </Stack>

        {planSnapshot.budget_guidance ? (
          <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.72)' }}>
            预算提示：{planSnapshot.budget_guidance}
          </Typography>
        ) : null}

        {planSnapshot.subtasks.length > 0 ? (
          <Box>
            <Typography variant="body2" fontWeight={500} sx={{ mb: 1 }}>
              子任务
            </Typography>
            <Stack component="ol" spacing={1} sx={{ pl: 2, m: 0 }}>
              {planSnapshot.subtasks.map((item) => (
                <Box component="li" key={item.title}>
                  <Typography variant="body2" fontWeight={500}>
                    {item.title}
                  </Typography>
                  <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.72)' }}>
                    {item.description}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Box>
        ) : null}

        {status === 'awaiting_confirmation' ? (
          <Stack spacing={1}>
            <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.72)' }}>
              计划已准备好。确认后开始研究。
            </Typography>
            {onConfirm ? (
              <Button
                variant="contained"
                onClick={() => {
                  void onConfirm();
                }}
                loading={confirmPending}
                sx={{
                  alignSelf: 'flex-start',
                  minHeight: 40,
                  px: 2,
                  borderRadius: 999,
                  bgcolor: '#f8fafc',
                  color: '#020617',
                  '&:hover': {
                    bgcolor: '#e2e8f0',
                  },
                }}
              >
                确认计划并开始研究
              </Button>
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}
