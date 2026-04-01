import { Divider, Paper, Stack, Typography } from '@mui/material';

import { MarkdownContent } from '../chat/MarkdownContent';
import type {
  ResearchClaimMapEntry,
  ResearchConflictEntry,
  ResearchCoverageMatrix,
  ResearchSourceLedgerEntry,
} from '../../types/researchEvents';

const sectionSx = {
  p: 2,
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
}: {
  contractErrors: string[];
  coverageMarkdown: string | null;
  coverageMatrix: ResearchCoverageMatrix;
  sources: ResearchSourceLedgerEntry[];
  claims: ResearchClaimMapEntry[];
  conflicts: ResearchConflictEntry[];
}) {
  return (
    <Stack spacing={1.5}>
      {contractErrors.length > 0 ? (
        <Paper variant="outlined" sx={{ ...sectionSx, borderColor: 'rgba(211, 47, 47, 0.32)' }}>
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

      <Paper variant="outlined" sx={sectionSx}>
        <Stack spacing={1.25}>
          <Typography variant="overline" sx={{ color: '#80868b', letterSpacing: '0.18em' }}>
            Evidence Ledger
          </Typography>
          <Typography variant="subtitle1" fontWeight={700}>
            来源账本
          </Typography>
          {sources.length > 0 ? (
            sources.map((source, index) => (
              <Stack key={`${source.origin_url ?? source.title ?? 'source'}-${index}`} spacing={0.25}>
                <Typography variant="body2" fontWeight={600}>
                  {source.title ?? source.origin_url ?? `来源 ${index + 1}`}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {[source.provider, source.source_type, source.origin_url].filter(Boolean).join(' · ')}
                </Typography>
              </Stack>
            ))
          ) : (
            <Typography variant="body2" color="text.secondary">
              暂无来源账本，等待检索结果回填。
            </Typography>
          )}
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={sectionSx}>
        <Stack spacing={1.25}>
          <Typography variant="subtitle1" fontWeight={700}>
            Claims
          </Typography>
          {claims.length > 0 ? (
            claims.map((claim, index) => (
              <Stack key={`${claim.claim}-${index}`} spacing={0.25}>
                <Typography variant="body2" fontWeight={600}>
                  {claim.claim}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {formatVerdict(claim.verdict)}
                  {claim.citation_indices.length > 0
                    ? ` · 引用 #${claim.citation_indices.join(', #')}`
                    : ''}
                </Typography>
              </Stack>
            ))
          ) : (
            <Typography variant="body2" color="text.secondary">
              暂无 claim map。
            </Typography>
          )}
        </Stack>
      </Paper>

      <Paper variant="outlined" sx={sectionSx}>
        <Stack spacing={1.25}>
          <Typography variant="subtitle1" fontWeight={700}>
            冲突与覆盖缺口
          </Typography>
          {conflicts.length > 0 ? (
            conflicts.map((conflict, index) => (
              <Stack key={`${conflict.claim ?? conflict.reason}-${index}`} spacing={0.25}>
                <Typography variant="body2" fontWeight={600}>
                  {conflict.claim ?? '未绑定 claim 的冲突'}
                </Typography>
                <Typography variant="body2" color="text.secondary">
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
            <Typography variant="body2" color="text.secondary">
              当前未检测到显式冲突。
            </Typography>
          )}
          <Divider />
          <Stack spacing={0.5}>
            <Typography variant="body2" fontWeight={600}>
              Coverage Matrix
            </Typography>
            {Object.keys(coverageMatrix.provider_counts).length > 0 ? (
              Object.entries(coverageMatrix.provider_counts).map(([provider, count]) => (
                <Typography key={provider} variant="caption" color="text.secondary">
                  {provider}: {count}
                </Typography>
              ))
            ) : (
              <Typography variant="caption" color="text.secondary">
                provider 计数尚未生成。
              </Typography>
            )}
            {coverageMatrix.missing_providers.length > 0 ? (
              <Typography variant="caption" color="warning.main">
                待补 provider：{coverageMatrix.missing_providers.join('、')}
              </Typography>
            ) : null}
          </Stack>
          {coverageMarkdown ? <MarkdownContent content={coverageMarkdown} /> : null}
        </Stack>
      </Paper>
    </Stack>
  );
}
