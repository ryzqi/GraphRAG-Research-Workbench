/**
 * 证据清单组件
 */

import { useEffect, useMemo } from 'react';
import { Box, Chip, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';
import type { EvidenceItem } from '../services/chats';
import {
  buildCitationAnchorId,
  normalizeCitationId,
} from '../services/kbChatCitationAnchors';
import { resolveEvidenceCardItems } from '../services/kbChatEvidenceDisplay';

interface EvidenceListProps {
  evidence: EvidenceItem[];
  activeCitationId?: string | null;
  onCitationHandled?: (citationId: string) => void;
  citationAnchorScopeId?: string;
}

function getCitationAnchorId(citationId: string, scopeId?: string): string {
  return buildCitationAnchorId(citationId, scopeId);
}

function isExternalHttpSourceDetail(
  sourceKind: EvidenceItem['source_kind'],
  detail: string | null
): detail is string {
  return sourceKind === 'external' && typeof detail === 'string' && /^https?:\/\//i.test(detail);
}

export function EvidenceList({
  evidence,
  activeCitationId,
  onCitationHandled,
  citationAnchorScopeId,
}: EvidenceListProps) {
  const displayItems = useMemo(() => resolveEvidenceCardItems(evidence), [evidence]);

  const normalizedActiveCitationId = useMemo(
    () => normalizeCitationId(activeCitationId),
    [activeCitationId]
  );

  useEffect(() => {
    if (!normalizedActiveCitationId) {
      return;
    }
    const target = displayItems.find((item) => item.citationId === normalizedActiveCitationId);
    if (!target) {
      return;
    }

    if (typeof window !== 'undefined') {
      window.requestAnimationFrame(() => {
        const element = document.getElementById(getCitationAnchorId(target.citationId, citationAnchorScopeId));
        element?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    }
    onCitationHandled?.(normalizedActiveCitationId);
  }, [citationAnchorScopeId, displayItems, normalizedActiveCitationId, onCitationHandled]);

  if (evidence.length === 0) {
    return (
      <Typography variant='body2' color='text.secondary' sx={{ py: 1 }}>
        暂无相关证据
      </Typography>
    );
  }

  return (
    <Stack spacing={1.25}>
      <Stack direction='row' spacing={0.75} alignItems='center' useFlexGap flexWrap='wrap'>
        <Typography variant='body2' fontWeight={700} color='text.primary'>
          参考来源
        </Typography>
        <Chip
          size='small'
          variant='outlined'
          label={`${evidence.length}`}
          sx={{
            height: 22,
            borderRadius: 999,
            fontWeight: 700,
          }}
        />
      </Stack>
      {displayItems.map((entry) => {
        const anchorId = getCitationAnchorId(entry.citationId, citationAnchorScopeId);
        const isActive = entry.citationId === normalizedActiveCitationId;
        const sourceDetail = entry.sourceDetail;
        const isExternalHttpLink = isExternalHttpSourceDetail(entry.sourceKind, sourceDetail);

        return (
          <Paper
            id={anchorId}
            data-citation-card={entry.citationId}
            data-citation-anchor={anchorId}
            data-active={isActive ? 'true' : 'false'}
            elevation={0}
            key={entry.key}
            variant='outlined'
            sx={{
              p: 1.5,
              borderRadius: 3,
              scrollMarginTop: 24,
              borderColor: (theme) =>
                isActive
                  ? alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.42 : 0.62)
                  : alpha(theme.palette.divider, 0.9),
              bgcolor: (theme) =>
                isActive
                  ? alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.06 : 0.16)
                  : alpha(theme.palette.background.paper, theme.palette.mode === 'light' ? 0.9 : 0.68),
              boxShadow: (theme) =>
                isActive
                  ? `0 0 0 1px ${alpha(theme.palette.primary.main, 0.12)}, 0 14px 34px ${alpha(
                      theme.palette.primary.main,
                      theme.palette.mode === 'light' ? 0.12 : 0.24
                    )}`
                  : '0 8px 24px rgba(15, 23, 42, 0.05)',
              transition: 'border-color 180ms ease, background-color 180ms ease, box-shadow 180ms ease',
            }}
          >
            <Stack spacing={1.1}>
              <Stack direction='row' justifyContent='space-between' alignItems='flex-start' gap={1.25}>
                <Stack direction='row' spacing={0.75} useFlexGap flexWrap='wrap'>
                  <Chip
                    size='small'
                    label={entry.citationChipLabel}
                    sx={{
                      borderRadius: 999,
                      bgcolor: (theme) =>
                        theme.palette.mode === 'light'
                          ? alpha(theme.palette.primary.main, 0.12)
                          : alpha(theme.palette.primary.main, 0.28),
                      color: 'primary.main',
                      border: 1,
                      borderColor: (theme) => alpha(theme.palette.primary.main, 0.28),
                      fontWeight: 700,
                    }}
                  />
                  <Chip
                    size='small'
                    variant='outlined'
                    label={entry.sourceTypeLabel}
                    sx={{
                      borderRadius: 999,
                      fontWeight: 600,
                    }}
                  />
                </Stack>
                {entry.pageHint ? (
                  <Typography variant='caption' color='text.secondary' sx={{ fontWeight: 700 }}>
                    {entry.pageHint}
                  </Typography>
                ) : null}
              </Stack>

              <Stack spacing={0.25}>
                <Typography variant='subtitle2' color='text.primary' sx={{ fontWeight: 700 }}>
                  {entry.sourceTitle}
                </Typography>
                {sourceDetail ? (
                  isExternalHttpLink ? (
                    <Typography
                      component='a'
                      variant='caption'
                      color='text.secondary'
                      href={sourceDetail}
                      target='_blank'
                      rel='noreferrer'
                      sx={{ overflowWrap: 'anywhere' }}
                    >
                      {sourceDetail}
                    </Typography>
                  ) : (
                    <Typography
                      variant='caption'
                      color='text.secondary'
                      sx={{ overflowWrap: 'anywhere' }}
                    >
                      {sourceDetail}
                    </Typography>
                  )
                ) : null}
              </Stack>

              <Box
                sx={{
                  borderRadius: 2,
                  px: 1.25,
                  py: 1,
                  border: 1,
                  borderColor: (theme) =>
                    alpha(theme.palette.divider, theme.palette.mode === 'light' ? 0.9 : 0.65),
                  bgcolor: (theme) =>
                    theme.palette.mode === 'light'
                      ? alpha(theme.palette.common.black, 0.018)
                      : alpha(theme.palette.common.white, 0.03),
                }}
              >
                <Typography
                  variant='body2'
                  sx={{
                    color: 'text.primary',
                    lineHeight: 1.65,
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {entry.excerpt}
                </Typography>
              </Box>
            </Stack>
          </Paper>
        );
      })}
    </Stack>
  );
}
