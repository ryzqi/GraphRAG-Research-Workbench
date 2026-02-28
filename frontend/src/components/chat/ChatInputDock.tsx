import type { ReactNode, RefObject } from 'react';
import { Box } from '@mui/material';
import { alpha } from '@mui/material/styles';

type ChatInputDockVariant = 'general' | 'kb';

interface ChatInputDockProps {
  children: ReactNode;
  composerRef?: RefObject<HTMLDivElement | null>;
  maxWidth?: number;
  variant?: ChatInputDockVariant;
}

export function ChatInputDock({
  children,
  composerRef,
  maxWidth = 900,
  variant = 'general',
}: ChatInputDockProps) {
  const variantStyle =
    variant === 'kb'
      ? {
          p: { xs: 1, md: 1.25 },
          bgcolor: (theme: { palette: { mode: 'light' | 'dark'; background: { paper: string } } }) =>
            theme.palette.mode === 'light'
              ? alpha(theme.palette.background.paper, 0.88)
              : alpha(theme.palette.background.paper, 0.58),
          borderTop: 1,
          borderColor: (theme: { palette: { divider: string } }) =>
            alpha(theme.palette.divider, 0.75),
          backdropFilter: 'blur(10px)',
          WebkitBackdropFilter: 'blur(10px)',
        }
      : {
          px: { xs: 1.25, md: 2 },
          pb: { xs: 1.25, md: 1.75 },
          pt: { xs: 0.75, md: 1.25 },
          borderTop: 1,
          borderColor: (theme: { palette: { divider: string } }) =>
            alpha(theme.palette.divider, 0.3),
          backdropFilter: 'blur(14px)',
          WebkitBackdropFilter: 'blur(14px)',
          background: (theme: { palette: { background: { default: string } } }) =>
            `linear-gradient(to top, ${theme.palette.background.default} 38%, rgba(0,0,0,0) 100%)`,
        };

  return (
    <Box
      ref={composerRef}
      sx={{
        position: 'sticky',
        bottom: 0,
        zIndex: 10,
        ...variantStyle,
      }}
    >
      <Box sx={{ maxWidth, mx: 'auto' }}>{children}</Box>
    </Box>
  );
}
