import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import type { ReactNode } from 'react';
import { Box, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import {
  researchBodyFont,
  researchDisplayFont,
  researchWorkbenchColors,
} from './researchWorkbenchStyles';

export function ResearchShell({
  headline,
  subheadline = null,
  badgeLabel = null,
  heroIcon = null,
  topSlot = null,
  footer = null,
  topSlotMaxWidth = 1120,
  heroMaxWidth = 1120,
  bodyMaxWidth = 1120,
  footerMaxWidth = 1120,
  children,
}: {
  headline: string;
  subheadline?: string | null;
  badgeLabel?: string | null;
  heroIcon?: ReactNode;
  topSlot?: ReactNode;
  footer?: ReactNode;
  topSlotMaxWidth?: number;
  heroMaxWidth?: number;
  bodyMaxWidth?: number;
  footerMaxWidth?: number;
  children: ReactNode;
}) {
  return (
    <Stack
      spacing={{ xs: 4, md: 5 }}
      sx={{
        width: '100%',
        minWidth: 0,
        minHeight: '100%',
        justifyContent: 'space-between',
        px: { xs: 2, md: 3.5, xl: 4.5 },
        py: { xs: 2.5, md: 3.5 },
      }}
    >
      <Stack spacing={{ xs: 3.25, md: 4 }} sx={{ width: '100%', minWidth: 0 }}>
        {topSlot ? (
          <Box sx={{ width: '100%', maxWidth: topSlotMaxWidth, mx: 'auto' }}>
            {topSlot}
          </Box>
        ) : null}

        <Stack
          spacing={1.35}
          alignItems="center"
          sx={{ width: '100%', maxWidth: heroMaxWidth, mx: 'auto', textAlign: 'center' }}
        >
          {badgeLabel ? (
            <Stack
              direction="row"
              spacing={0.8}
              alignItems="center"
              justifyContent="center"
              sx={{
                color: researchWorkbenchColors.primary,
                fontFamily: researchBodyFont,
                fontSize: '0.88rem',
                fontWeight: 700,
              }}
            >
              <AutoAwesomeRoundedIcon sx={{ fontSize: 15 }} />
              <Typography
                component="span"
                sx={{
                  color: 'inherit',
                  font: 'inherit',
                }}
              >
                {badgeLabel}
              </Typography>
            </Stack>
          ) : null}

          {heroIcon ? (
            <Box
              sx={{
                width: 44,
                height: 44,
                borderRadius: 2.5,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: researchWorkbenchColors.primary,
                bgcolor: alpha(researchWorkbenchColors.primary, 0.1),
                boxShadow: `0 12px 24px ${alpha(researchWorkbenchColors.primary, 0.12)}`,
              }}
            >
              {heroIcon}
            </Box>
          ) : null}

          <Typography
            variant="h2"
            sx={{
              maxWidth: 920,
              fontFamily: researchDisplayFont,
              fontWeight: 800,
              fontSize: { xs: '2.25rem', md: '3.2rem' },
              lineHeight: { xs: 1.16, md: 1.08 },
              letterSpacing: '-0.045em',
              color: researchWorkbenchColors.text,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
              overflowWrap: 'anywhere',
            }}
          >
            {headline}
          </Typography>

          {subheadline ? (
            <Typography
              variant="body1"
              sx={{
                maxWidth: 760,
                color: researchWorkbenchColors.mutedText,
                lineHeight: 1.8,
                fontFamily: researchBodyFont,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                overflowWrap: 'anywhere',
              }}
            >
              {subheadline}
            </Typography>
          ) : null}
        </Stack>

        <Stack spacing={{ xs: 2.5, md: 3 }} sx={{ width: '100%', maxWidth: bodyMaxWidth, mx: 'auto' }}>
          {children}
        </Stack>
      </Stack>

      {footer ? (
        <Box sx={{ width: '100%', maxWidth: footerMaxWidth, mx: 'auto' }}>
          {footer}
        </Box>
      ) : null}
    </Stack>
  );
}
