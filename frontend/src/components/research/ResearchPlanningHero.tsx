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
        py: { xs: 3, md: 5 },
        borderRadius: 8,
        overflow: 'hidden',
        background: 'linear-gradient(180deg, #f8fbff 0%, #eef4ff 48%, #f8fbff 100%)',
        '&::before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background:
            'radial-gradient(circle at 50% 18%, rgba(66, 133, 244, 0.16), transparent 34%)',
          pointerEvents: 'none',
        },
        '&::after': {
          content: '""',
          position: 'absolute',
          inset: 'auto auto -24% -10%',
          width: '46%',
          height: '54%',
          background:
            'radial-gradient(circle, rgba(15, 157, 88, 0.12) 0%, rgba(15, 157, 88, 0) 72%)',
          pointerEvents: 'none',
        },
      }}
    >
      <Box sx={{ position: 'relative', width: '100%', maxWidth: 880 }}>{children}</Box>
    </Box>
  );
}
