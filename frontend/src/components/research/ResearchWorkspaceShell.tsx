import type { ReactNode } from 'react';
import { Box, Stack, Typography } from '@mui/material';

export function ResearchWorkspaceShell({
  rail,
  canvas,
}: {
  rail: ReactNode;
  canvas: ReactNode;
}) {
  return (
    <Stack spacing={2}>
      <Stack spacing={0.75}>
        <Typography variant="h5" fontWeight={700}>
          研究工作台
        </Typography>
        <Typography variant="body2" color="text.secondary">
          计划已确认，下面展示执行进度、发现与产物。
        </Typography>
      </Stack>
      <Box
        sx={{
          display: 'grid',
          gap: 2,
          gridTemplateColumns: { xs: '1fr', lg: '360px minmax(0, 1fr)' },
          alignItems: 'start',
        }}
      >
        <Box>{rail}</Box>
        <Box>{canvas}</Box>
      </Box>
    </Stack>
  );
}
