import type { ReactNode } from 'react';
import { Box } from '@mui/material';

export function ResearchPlanningHero({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        position: 'relative',
        width: '100%',
        minHeight: { xs: 'calc(100vh - 180px)', md: 'calc(100vh - 220px)' },
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        px: { xs: 1, md: 2 },
        '&::before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(circle at center, rgba(66, 133, 244, 0.08), transparent 34%)',
          pointerEvents: 'none',
        },
      }}
    >
      <Box sx={{ position: 'relative', width: '100%', maxWidth: 780 }}>{children}</Box>
    </Box>
  );
}
