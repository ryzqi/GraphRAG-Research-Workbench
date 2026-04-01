import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Divider,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { alpha } from '@mui/material/styles';

import { MarkdownContent } from '../chat/MarkdownContent';
import type {
  ResearchClaimMapEntry,
  ResearchConflictEntry,
  ResearchCoverageMatrix,
  ResearchSourceLedgerEntry,
} from '../../types/researchEvents';

const sectionSx = {
  borderRadius: 4,
  borderColor: 'rgba(223, 225, 229, 0.92)',
  bgcolor: '#ffffff',
  boxShadow: '0 1px 3px rgba(32, 33, 36, 0.08)',
} as const;

function formatVerdict(verdict: ResearchClaimMapEntry['verdict']) {
  switch (verdict) {
    case 'supported':
      return '已支持';
    case 'contested':
      return '有冲突';
    case 'insufficient':
    default:
      return '证据不足';
  }
}

export function ResearchEvidenceLedger({
  contractErrors,
  coverageMarkdown,
  coverageMatrix,
  sources,
  claims,
  conflicts,
  coverageGap = null,
  tone = 'light',
}: {
  contractErrors: string[];
  coverageMarkdown: string | null;
  coverageMatrix: ResearchCoverageMatrix;
  sources: ResearchSourceLedgerEntry[];
  claims: ResearchClaimMapEntry[];
  conflicts: ResearchConflictEntry[];
  coverageGap?: string | null;
  tone?: 'light' | 'dark';
}) {
  const isDark = tone === 'dark';
  const summaryParts = [
    `${sources.length} 个来源`,
    `${claims.length} 条 claim`,
    conflicts.length > 0 ? `${conflicts.length} 个冲突` : null,
  ].filter(Boolean);

  const shellSx = {
    ...sectionSx,
    borderColor: isDark ? 'rgba(148, 163, 184, 0.18)' : 'rgba(223, 225, 229, 0.92)',
    bgcolor: isDark ? 'rgba(12, 18, 32, 0.82)' : '#ffffff',
    color: isDark ? '#e5eefc' : '#111827',
    backdropFilter: isDark ? 'blur(18px)' : undefined,
    boxShadow: isDark ? '0 30px 80px rgba(2, 6, 23, 0.32)' : '0 1px 3px rgba(32, 33, 36, 0.08)',
  } as const;

  const cardSx = {
    ...shellSx,
    p: 2,
    background: isDark
      ? 'linear-gradient(180deg, rgba(15, 23, 42, 0.88) 0%, rgba(15, 23, 42, 0.68) 100%)'
      : '#ffffff',
  } as const;

  return (
    <Accordion
      disableGutters
      defaultExpanded={contractErrors.length > 0}
      sx={{
        ...shellSx,
        '&:before': {
          display: 'none',
        },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Stack spacing={0.5} sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={700}>
            查看来源与证据
          </Typography>
          <Typography variant="body2" color={isDark ? alpha('#e2e8f0', 0.76) : 'text.secondary'}>
            {summaryParts.join(' · ')}
          </Typography>
          {coverageGap ? (
            <Typography variant="caption" color="warning.main">
              {coverageGap}
            </Typography>
          ) : null}
        </Stack>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1.5}>
          {contractErrors.length > 0 ? (
            <Paper
              variant="outlined"
              sx={{
                ...cardSx,
                borderColor: isDark ? 'rgba(248, 113, 113, 0.28)' : 'rgba(211, 47, 47, 0.32)',
              }}
            >
              <Stack spacing={1}>
                <Typography variant="subtitle1" fontWeight={700} color="error.main">
                  证据工件格式错误
                </Typography>
                {contractErrors.map((item) => (
                  <Typography key={item} variant="body2" color="error.main">
                    {item}
                  </Typography>
                ))}
              </Stack>
            </Paper>
          ) : null}

          <Paper variant="outlined" sx={cardSx}>
            <Stack spacing={1.25}>
              <Typography variant="subtitle1" fontWeight={700}>
                已访问来源
              </Typography>
              {sources.length > 0 ? (
                sources.map((source, index) => (
                  <Stack key={`${source.origin_url ?? source.title ?? 'source'}-${index}`} spacing={0.25}>
                    <Typography variant="body2" fontWeight={600}>
                      {source.title ?? source.origin_url ?? `来源 ${index + 1}`}
                    </Typography>
                    <Typography variant="caption" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                      {[source.provider, source.source_type, source.origin_url].filter(Boolean).join(' · ')}
                    </Typography>
                  </Stack>
                ))
              ) : (
                <Typography variant="body2" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                  暂无来源账本，等待检索结果回填。
                </Typography>
              )}
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={cardSx}>
            <Stack spacing={1.25}>
              <Typography variant="subtitle1" fontWeight={700}>
                结论与冲突
              </Typography>
              {claims.length > 0 ? (
                claims.map((claim, index) => (
                  <Stack key={`${claim.claim}-${index}`} spacing={0.25}>
                    <Typography variant="body2" fontWeight={600}>
                      {claim.claim}
                    </Typography>
                    <Typography variant="caption" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                      {formatVerdict(claim.verdict)}
                      {claim.citation_indices.length > 0
                        ? ` · 引用 #${claim.citation_indices.join(', #')}`
                        : ''}
                    </Typography>
                  </Stack>
                ))
              ) : (
                <Typography variant="body2" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                  暂无 claim map。
                </Typography>
              )}

              <Divider />

              {conflicts.length > 0 ? (
                conflicts.map((conflict, index) => (
                  <Stack key={`${conflict.claim ?? conflict.reason}-${index}`} spacing={0.25}>
                    <Typography variant="body2" fontWeight={600}>
                      {conflict.claim ?? '未绑定 claim 的冲突'}
                    </Typography>
                    <Typography variant="body2" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                      {conflict.reason}
                    </Typography>
                    {conflict.coverage_gaps.length > 0 ? (
                      <Typography variant="caption" color="warning.main">
                        缺口：{conflict.coverage_gaps.join('、')}
                      </Typography>
                    ) : null}
                  </Stack>
                ))
              ) : (
                <Typography variant="body2" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                  当前未检测到显式冲突。
                </Typography>
              )}
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={cardSx}>
            <Stack spacing={1.25}>
              <Typography variant="subtitle1" fontWeight={700}>
                覆盖情况
              </Typography>
              {Object.keys(coverageMatrix.provider_counts).length > 0 ? (
                Object.entries(coverageMatrix.provider_counts).map(([provider, count]) => (
                  <Typography key={provider} variant="caption" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                    {provider}: {count}
                  </Typography>
                ))
              ) : (
                <Typography variant="caption" color={isDark ? alpha('#cbd5e1', 0.82) : 'text.secondary'}>
                  provider 计数尚未生成。
                </Typography>
              )}
              {coverageMatrix.missing_providers.length > 0 ? (
                <Typography variant="caption" color="warning.main">
                  待补 provider：{coverageMatrix.missing_providers.join('、')}
                </Typography>
              ) : null}
              {coverageMarkdown ? <MarkdownContent content={coverageMarkdown} /> : null}
            </Stack>
          </Paper>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
