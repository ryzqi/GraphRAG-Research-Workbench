import type { ReactNode } from 'react';
import {
  Box,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';

interface KbDetailHeroProps {
  name: string;
  description: string | null;
  documentCount: number | string;
  chunkCount: number | string;
  readinessLabel: string;
  readinessColor: 'default' | 'success' | 'warning' | 'error' | 'info';
  actions?: ReactNode;
}

interface SummaryStatCardProps {
  label: string;
  value: string;
  tone?: 'default' | 'primary' | 'success' | 'warning';
}

function SummaryStatCard({
  label,
  value,
  tone = 'default',
}: SummaryStatCardProps) {
  return (
    <Paper
      variant='outlined'
      sx={{
        minWidth: { xs: '100%', sm: 148 },
        p: 1.5,
        borderRadius: 3,
        borderColor: 'divider',
        bgcolor: (theme) =>
          tone === 'default'
            ? alpha(theme.palette.background.paper, 0.88)
            : alpha(theme.palette[tone].main, theme.palette.mode === 'light' ? 0.08 : 0.18),
      }}
    >
      <Typography variant='caption' color='text.secondary'>
        {label}
      </Typography>
      <Typography variant='h6' fontWeight={700} sx={{ mt: 0.35 }}>
        {value}
      </Typography>
    </Paper>
  );
}

export function KbDetailHero({
  name,
  description,
  documentCount,
  chunkCount,
  readinessLabel,
  readinessColor,
  actions,
}: KbDetailHeroProps) {
  return (
    <Paper
      variant='outlined'
      sx={{
        p: { xs: 2, md: 2.5 },
        borderRadius: 4,
        borderColor: 'divider',
        background: (theme) =>
          theme.palette.mode === 'light'
            ? `linear-gradient(135deg, ${alpha(theme.palette.primary.light, 0.1)} 0%, ${alpha(theme.palette.background.paper, 0.98)} 72%)`
            : `linear-gradient(135deg, ${alpha(theme.palette.primary.dark, 0.22)} 0%, ${alpha(theme.palette.background.paper, 0.98)} 72%)`,
      }}
    >
      <Stack spacing={2}>
        <Stack
          direction={{ xs: 'column', lg: 'row' }}
          spacing={2}
          justifyContent='space-between'
          alignItems={{ xs: 'flex-start', lg: 'center' }}
        >
          <Stack spacing={0.85} sx={{ minWidth: 0, flex: 1 }}>
            <Typography
              variant='overline'
              color='text.secondary'
              sx={{ letterSpacing: '0.08em' }}
            >
              知识库概览
            </Typography>
            <Typography
              variant='h4'
              component='h1'
              fontWeight={700}
              sx={{ lineHeight: 1.15, letterSpacing: '-0.02em' }}
            >
              {name}
            </Typography>
            {description && (
              <Typography
                variant='body2'
                color='text.secondary'
                sx={{ maxWidth: 760, lineHeight: 1.75 }}
              >
                {description}
              </Typography>
            )}
          </Stack>

          {actions && (
            <Box sx={{ flexShrink: 0, width: { xs: '100%', lg: 'auto' } }}>{actions}</Box>
          )}
        </Stack>

        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          spacing={1.25}
          flexWrap='wrap'
          useFlexGap
        >
          <SummaryStatCard
            label='文档总数'
            value={String(documentCount)}
            tone='primary'
          />
          <SummaryStatCard
            label='分块总数'
            value={String(chunkCount)}
            tone='default'
          />
          <SummaryStatCard
            label='就绪状态'
            value={readinessLabel}
            tone={readinessColor === 'success' ? 'success' : 'warning'}
          />
        </Stack>
      </Stack>
    </Paper>
  );
}
