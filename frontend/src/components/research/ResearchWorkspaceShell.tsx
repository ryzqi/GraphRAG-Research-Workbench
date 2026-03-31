import type { ReactNode } from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { Button } from '../ui/Button';

export function ResearchWorkspaceShell({
  statusLine,
  sidebarOpen,
  onToggleSidebar,
  rail,
  canvas,
}: {
  statusLine: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  rail: ReactNode;
  canvas: ReactNode;
}) {
  return (
    <Stack spacing={2.5}>
      <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={1.5}>
        <Typography
          variant="caption"
          sx={{
            color: '#80868b',
            letterSpacing: '0.14em',
          }}
        >
          {statusLine}
        </Typography>
        <Button
          variant="text"
          size="small"
          onClick={onToggleSidebar}
          sx={{
            minWidth: 'auto',
            px: 1,
            color: '#5f6368',
            borderRadius: 999,
          }}
        >
          {sidebarOpen ? '收起侧栏' : '显示侧栏'}
        </Button>
      </Stack>
      <Box
        sx={{
          display: 'grid',
          gap: 2.5,
          gridTemplateColumns: {
            xs: '1fr',
            lg: sidebarOpen ? 'minmax(0, 1fr) 320px' : 'minmax(0, 1fr)',
          },
          alignItems: 'start',
        }}
      >
        <Box sx={{ minWidth: 0 }}>{canvas}</Box>
        {sidebarOpen ? <Box sx={{ minWidth: 0 }}>{rail}</Box> : null}
      </Box>
    </Stack>
  );
}
