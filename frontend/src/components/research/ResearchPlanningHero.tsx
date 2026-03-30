import { Box, Paper, Stack, Typography } from '@mui/material';

const planningSteps = ['问题', '澄清', '计划'];

export function ResearchPlanningHero() {
  return (
    <Paper
      variant="outlined"
      sx={{
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 6,
        borderColor: 'rgba(148, 163, 184, 0.16)',
        bgcolor: '#0b1015',
        color: '#f8fafc',
        px: { xs: 2.5, md: 4 },
        py: { xs: 3, md: 4 },
      }}
    >
      <Box
        aria-hidden
        sx={{
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(circle at top right, rgba(148, 163, 184, 0.12), transparent 38%), linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(2, 6, 23, 0.96))',
        }}
      />
      <Stack spacing={2.5} sx={{ position: 'relative' }}>
        <Stack spacing={1}>
          <Typography
            variant="overline"
            sx={{
              letterSpacing: '0.24em',
              color: 'rgba(226, 232, 240, 0.62)',
            }}
          >
            deep research
          </Typography>
          <Typography variant="h3" fontWeight={600} sx={{ letterSpacing: '-0.03em' }}>
            先规划，再开始研究
          </Typography>
          <Typography variant="body1" sx={{ maxWidth: 760, color: 'rgba(226, 232, 240, 0.74)' }}>
            把问题说清楚，系统会先收敛范围、提出必要澄清，再给出一份可确认的研究计划。
          </Typography>
        </Stack>
        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25}>
          {planningSteps.map((item, index) => (
            <Paper
              key={item}
              variant="outlined"
              sx={{
                flex: 1,
                minHeight: 76,
                px: 2,
                py: 1.75,
                borderRadius: 4,
                borderColor: 'rgba(148, 163, 184, 0.18)',
                bgcolor: 'rgba(15, 23, 42, 0.72)',
              }}
            >
              <Typography variant="caption" sx={{ color: 'rgba(226, 232, 240, 0.46)' }}>
                0{index + 1}
              </Typography>
              <Typography variant="subtitle2" sx={{ mt: 0.75 }}>
                {item}
              </Typography>
            </Paper>
          ))}
        </Stack>
      </Stack>
    </Paper>
  );
}
