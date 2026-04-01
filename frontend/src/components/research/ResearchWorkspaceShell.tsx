import type { ReactNode } from 'react';
import { Box, Stack, Typography } from '@mui/material';

import { Button } from '../ui/Button';

export function ResearchWorkspaceShell({
  statusLine,
  sidebarOpen,
  onToggleSidebar,
  missionControl,
  rail,
  canvas,
  ledger,
}: {
  statusLine: string;
  sidebarOpen: boolean;
  onToggleSidebar: () => void;
  missionControl: ReactNode;
  rail: ReactNode;
  canvas: ReactNode;
  ledger: ReactNode;
}) {
  return (
    <Stack spacing={2.5}>
      <Box sx={{ minWidth: 0 }}>{missionControl}</Box>
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
            lg: sidebarOpen
              ? 'minmax(260px, 300px) minmax(0, 1fr) minmax(300px, 340px)'
              : 'minmax(0, 1fr) minmax(300px, 340px)',
          },
          alignItems: 'start',
        }}
      >
        {sidebarOpen ? <Box sx={{ minWidth: 0 }}>{rail}</Box> : null}
        <Box sx={{ minWidth: 0 }}>{canvas}</Box>
        <Box sx={{ minWidth: 0 }}>{ledger}</Box>
      </Box>
    </Stack>
  );
}
