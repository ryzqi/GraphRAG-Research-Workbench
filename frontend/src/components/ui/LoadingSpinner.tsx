/**
 * Loading indicator with optional full-page overlay and screen-reader semantics.
 */
import { Box, CircularProgress, Typography } from '@mui/material';

interface LoadingSpinnerProps {
  text?: string;
  size?: number;
  fullPage?: boolean;
  ariaLabel?: string;
}

export function LoadingSpinner({
  text = '加载中...',
  size = 32,
  fullPage = false,
  ariaLabel,
}: LoadingSpinnerProps) {
  const accessibleLabel = ariaLabel ?? text;

  const content = (
    <Box
      role='status'
      aria-live='polite'
      aria-busy='true'
      aria-label={accessibleLabel}
      sx={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 2,
        py: fullPage ? 0 : 4,
      }}
    >
      <CircularProgress size={size} aria-hidden='true' />
      {text && (
        <Typography variant='body2' color='text.secondary'>
          {text}
        </Typography>
      )}
    </Box>
  );

  if (fullPage) {
    return (
      <Box
        sx={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          bgcolor: 'background.default',
          zIndex: 9999,
        }}
      >
        {content}
      </Box>
    );
  }

  return content;
}
