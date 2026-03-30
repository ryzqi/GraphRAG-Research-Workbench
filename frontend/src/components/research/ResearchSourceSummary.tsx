import { Paper, Stack, Typography } from '@mui/material';

interface SourceSummary {
  heading: string;
  modeLabel: string;
  helperText: string;
}

export function ResearchSourceSummary({ summary }: { summary: SourceSummary }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3 }}>
      <Stack spacing={1}>
        <Typography variant="subtitle1" fontWeight={600}>
          {summary.heading}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {summary.modeLabel}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {summary.helperText}
        </Typography>
      </Stack>
    </Paper>
  );
}
