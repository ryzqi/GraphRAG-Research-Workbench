import type { ReactNode } from 'react';
import { Box } from '@mui/material';

export function ResearchPlanningHero({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        width: '100%',
        minHeight: { xs: 'calc(100vh - 180px)', md: 'calc(100vh - 220px)' },
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        py: { xs: 2, md: 3 },
      }}
    >
      <Box sx={{ width: '100%' }}>{children}</Box>
    </Box>
  );
}
