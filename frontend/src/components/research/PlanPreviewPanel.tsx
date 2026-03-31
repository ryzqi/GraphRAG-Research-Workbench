import { Box, Chip, Paper, Stack, Typography } from '@mui/material';

import type { ResearchPlanSnapshot } from '../../types/researchEvents';

interface PlanPreviewPanelProps {
  planSnapshot: ResearchPlanSnapshot | null;
}

export function PlanPreviewPanel({ planSnapshot }: PlanPreviewPanelProps) {
  if (!planSnapshot) {
    return null;
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        p: { xs: 2, md: 2.5 },
        borderRadius: 4,
        borderColor: 'rgba(223, 225, 229, 0.92)',
        bgcolor: '#ffffff',
        color: '#202124',
        boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
      }}
    >
      <Stack spacing={1.75}>
        <Stack spacing={0.5}>
          <Typography
            variant="overline"
            sx={{
              letterSpacing: '0.18em',
              color: '#80868b',
            }}
          >
            assistant
          </Typography>
          <Typography variant="subtitle1" fontWeight={600}>
            计划草案
          </Typography>
          <Typography variant="body2" sx={{ color: '#5f6368' }}>
            以下是开始研究前由系统生成的执行计划。
          </Typography>
        </Stack>

        <Typography variant="body2">{planSnapshot.research_brief}</Typography>
        <Typography variant="body2" sx={{ color: '#5f6368' }}>
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
                color: '#3c4043',
                borderColor: 'rgba(223, 225, 229, 0.92)',
                bgcolor: '#f8f9fa',
              }}
            />
          ))}
        </Stack>

        {planSnapshot.budget_guidance ? (
          <Typography variant="body2" sx={{ color: '#5f6368' }}>
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
                  <Typography variant="body2" sx={{ color: '#5f6368' }}>
                    {item.description}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </Box>
        ) : null}

      </Stack>
    </Paper>
  );
}
