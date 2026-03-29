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
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1" fontWeight={600}>
          研究计划
        </Typography>

        <Typography variant="body2">{planSnapshot.research_brief}</Typography>
        <Typography variant="body2" color="text.secondary">
          {planSnapshot.summary}
        </Typography>

        <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
          {planSnapshot.target_sources.map((item) => (
            <Chip key={item} label={item} size="small" variant="outlined" />
          ))}
        </Stack>

        {planSnapshot.budget_guidance ? (
          <Typography variant="body2" color="text.secondary">
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
                  <Typography variant="body2" color="text.secondary">
                    {item.description}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Box>
        ) : null}

        {status === 'awaiting_confirmation' ? (
          <Stack spacing={1}>
            <Typography variant="body2" color="warning.main" fontWeight={500}>
              等待确认
            </Typography>
            {onConfirm ? (
              <Button
                variant="contained"
                onClick={() => {
                  void onConfirm();
                }}
                loading={confirmPending}
                sx={{ alignSelf: 'flex-start' }}
              >
                继续执行
              </Button>
            ) : null}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}
