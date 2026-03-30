import { Box, Paper, Stack, Typography } from '@mui/material';

interface ResearchProgressItem {
  id: string;
  title: string;
  phaseLabel: string;
  providerLabel: string | null;
  sourceLabel: string | null;
  finding: string | null;
}

export function ResearchProgressFeed({ items }: { items: ResearchProgressItem[] }) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 3 }}>
      <Stack spacing={1.25}>
        <Typography variant="subtitle1" fontWeight={600}>
          研究进度
        </Typography>
        {items.map((item) => (
          <Box key={item.id}>
            <Typography fontWeight={500}>{item.title}</Typography>
            <Typography variant="body2" color="text.secondary">
              {item.phaseLabel}
              {item.providerLabel ? ` · ${item.providerLabel}` : ''}
            </Typography>
            {item.finding ? <Typography variant="body2">{item.finding}</Typography> : null}
          </Box>
        ))}
      </Stack>
    </Paper>
  );
}
