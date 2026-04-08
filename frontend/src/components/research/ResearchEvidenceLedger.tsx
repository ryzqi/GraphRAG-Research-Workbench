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
import {
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
  researchWorkbenchOpenPanelSx,
} from './researchWorkbenchStyles';

const longFormTextSx = {
  minWidth: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowWrap: 'anywhere',
} as const;

const sectionSx = {
  ...researchWorkbenchOpenPanelSx,
  borderRadius: 28,
  minWidth: 0,
  overflow: 'hidden',
  background: `linear-gradient(180deg, ${alpha('#ffffff', 0.92)} 0%, ${alpha(
    researchWorkbenchColors.surfaceMuted,
    0.92
  )} 100%)`,
} as const;

const cardSx = {
  ...researchWorkbenchInnerCardSx,
  p: 2.25,
  minWidth: 0,
  background: `linear-gradient(180deg, ${alpha('#ffffff', 0.96)} 0%, ${alpha(
    researchWorkbenchColors.surfaceMuted,
    0.92
  )} 100%)`,
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

function formatSourceType(sourceType: ResearchSourceLedgerEntry['source_type']): string | null {
  switch (sourceType) {
    case 'web':
      return '网页';
    case 'paper':
      return '论文';
    default:
      return null;
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
}: {
  contractErrors: string[];
  coverageMarkdown: string | null;
  coverageMatrix: ResearchCoverageMatrix;
  sources: ResearchSourceLedgerEntry[];
  claims: ResearchClaimMapEntry[];
  conflicts: ResearchConflictEntry[];
  coverageGap?: string | null;
}) {
  const summaryParts = [
    `${sources.length} 个来源`,
    `${claims.length} 条结论`,
    conflicts.length > 0 ? `${conflicts.length} 个冲突` : null,
  ].filter(Boolean);

  return (
    <Accordion
      disableGutters
      defaultExpanded={contractErrors.length > 0}
      sx={{
        ...sectionSx,
        '&:before': {
          display: 'none',
        },
      }}
    >
      <AccordionSummary
        expandIcon={<ExpandMoreIcon sx={{ color: researchWorkbenchColors.mutedText }} />}
        sx={{
          px: { xs: 2.25, md: 2.75 },
          py: 0.25,
          '& .MuiAccordionSummary-content': {
            my: 1.5,
            minWidth: 0,
          },
        }}
      >
        <Stack spacing={0.5} sx={{ minWidth: 0 }}>
          <Typography variant="subtitle1" fontWeight={700}>
            查看来源与证据
          </Typography>
          <Typography
            variant="body2"
            sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
          >
            {summaryParts.join(' · ')}
          </Typography>
          {coverageGap ? (
            <Typography variant="caption" color="warning.main" sx={longFormTextSx}>
              {coverageGap}
            </Typography>
          ) : null}
        </Stack>
      </AccordionSummary>
      <AccordionDetails sx={{ px: { xs: 2.25, md: 2.75 }, pb: { xs: 2.25, md: 2.75 }, pt: 0 }}>
        <Stack spacing={1.5} sx={{ minWidth: 0 }}>
          {contractErrors.length > 0 ? (
            <Paper
              variant="outlined"
              sx={{
                ...cardSx,
                borderColor: 'rgba(211, 47, 47, 0.28)',
                background: 'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(255,235,238,0.94) 100%)',
              }}
            >
              <Stack spacing={1} sx={{ minWidth: 0 }}>
                <Typography variant="subtitle1" fontWeight={700} color="error.main">
                  证据工件格式错误
                </Typography>
                {contractErrors.map((item) => (
                  <Typography key={item} variant="body2" color="error.main" sx={longFormTextSx}>
                    {item}
                  </Typography>
                ))}
              </Stack>
            </Paper>
          ) : null}

          <Paper variant="outlined" sx={cardSx}>
            <Stack spacing={1.25} sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" fontWeight={700}>
                已访问来源
              </Typography>
              {sources.length > 0 ? (
                sources.map((source, index) => (
                  <Stack key={`${source.origin_url ?? source.title ?? 'source'}-${index}`} spacing={0.25} sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={600} sx={longFormTextSx}>
                      {source.title ?? source.origin_url ?? `来源 ${index + 1}`}
                    </Typography>
                    <Typography
                      variant="caption"
                      sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                    >
                      {[source.provider, formatSourceType(source.source_type), source.origin_url]
                        .filter(Boolean)
                        .join(' · ')}
                    </Typography>
                  </Stack>
                ))
              ) : (
                <Typography
                  variant="body2"
                  sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                >
                  暂无来源账本，等待检索结果回填。
                </Typography>
              )}
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={cardSx}>
            <Stack spacing={1.25} sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" fontWeight={700}>
                结论与冲突
              </Typography>
              {claims.length > 0 ? (
                claims.map((claim, index) => (
                  <Stack key={`${claim.claim}-${index}`} spacing={0.25} sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={600} sx={longFormTextSx}>
                      {claim.claim}
                    </Typography>
                    <Typography
                      variant="caption"
                      sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                    >
                      {formatVerdict(claim.verdict)}
                      {claim.citation_indices.length > 0
                        ? ` · 引用 #${claim.citation_indices.join(', #')}`
                        : ''}
                    </Typography>
                  </Stack>
                ))
              ) : (
                <Typography
                  variant="body2"
                  sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                >
                  暂无 claim map。
                </Typography>
              )}

              <Divider sx={{ borderColor: researchWorkbenchColors.softBorder }} />

              {conflicts.length > 0 ? (
                conflicts.map((conflict, index) => (
                  <Stack key={`${conflict.claim ?? conflict.reason}-${index}`} spacing={0.25} sx={{ minWidth: 0 }}>
                    <Typography variant="body2" fontWeight={600} sx={longFormTextSx}>
                      {conflict.claim ?? '未绑定 claim 的冲突'}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                    >
                      {conflict.reason}
                    </Typography>
                    {conflict.coverage_gaps.length > 0 ? (
                      <Typography variant="caption" color="warning.main" sx={longFormTextSx}>
                        缺口：{conflict.coverage_gaps.join('、')}
                      </Typography>
                    ) : null}
                  </Stack>
                ))
              ) : (
                <Typography
                  variant="body2"
                  sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                >
                  当前未检测到显式冲突。
                </Typography>
              )}
            </Stack>
          </Paper>

          <Paper variant="outlined" sx={cardSx}>
            <Stack spacing={1.25} sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" fontWeight={700}>
                覆盖情况
              </Typography>
              {Object.keys(coverageMatrix.provider_counts).length > 0 ? (
                Object.entries(coverageMatrix.provider_counts).map(([provider, count]) => (
                  <Typography
                    key={provider}
                    variant="caption"
                    sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                  >
                    {provider}: {count}
                  </Typography>
                ))
              ) : (
                <Typography
                  variant="caption"
                  sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                >
                  来源覆盖统计尚未生成。
                </Typography>
              )}
              {coverageMatrix.missing_providers.length > 0 ? (
                <Typography variant="caption" color="warning.main" sx={longFormTextSx}>
                  待补来源：{coverageMatrix.missing_providers.join('、')}
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
