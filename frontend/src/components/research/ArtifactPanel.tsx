import { Box, Chip, Divider, Paper, Stack, Typography } from '@mui/material';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import {
  buildResearchArtifactsByKey,
  type ResearchArtifactRead,
  type ResearchCanonicalCitation,
} from '../../types/researchEvents';

interface ArtifactPanelProps {
  reportMd: string | null;
  reportJson: Record<string, unknown> | null;
  artifacts: ResearchArtifactRead[];
}

function asCitationList(value: unknown): ResearchCanonicalCitation[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value as ResearchCanonicalCitation[];
}

export function ArtifactPanel({ reportMd, reportJson, artifacts }: ArtifactPanelProps) {
  const artifactByKey = buildResearchArtifactsByKey(artifacts);
  const interimSummary = artifactByKey.interim_summary?.content_text;
  const coverageGaps = Array.isArray(artifactByKey.coverage_gaps?.content_json)
    ? (artifactByKey.coverage_gaps?.content_json as unknown[])
    : [];
  const citations = asCitationList(reportJson?.citations);
  const webCitations = citations.filter((item) => item.source_type === 'web');
  const paperCitations = citations.filter((item) => item.source_type === 'paper');

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={2}>
        <Typography variant="subtitle1" fontWeight={600}>
          研究工件
        </Typography>

        {(interimSummary || coverageGaps.length > 0) ? (
          <Stack spacing={1}>
            <Typography variant="body2" fontWeight={500}>
              中间研究收口
            </Typography>
            {interimSummary ? (
              <Typography variant="body2" color="text.secondary">
                {interimSummary}
              </Typography>
            ) : null}
            {coverageGaps.length > 0 ? (
              <Stack component="ul" spacing={0.5} sx={{ pl: 2, m: 0 }}>
                {coverageGaps.map((item, index) => (
                  <Box component="li" key={`${String(item)}-${index}`}>
                    <Typography variant="body2" color="text.secondary">
                      {String(item)}
                    </Typography>
                  </Box>
                ))}
              </Stack>
            ) : null}
          </Stack>
        ) : null}

        {reportMd ? (
          <>
            <Divider />
            <Stack spacing={1}>
              <Typography variant="body2" fontWeight={500}>
                Markdown
              </Typography>
              <Paper variant="outlined" sx={{ p: 2, bgcolor: 'grey.50' }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
                  {reportMd}
                </ReactMarkdown>
              </Paper>
            </Stack>
          </>
        ) : null}

        {reportJson ? (
          <>
            <Divider />
            <Stack spacing={1}>
              <Typography variant="body2" fontWeight={500}>
                JSON
              </Typography>
              <Paper
                variant="outlined"
                sx={{
                  p: 2,
                  bgcolor: 'grey.50',
                  overflowX: 'auto',
                  fontFamily: 'monospace',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {JSON.stringify(reportJson, null, 2)}
              </Paper>
            </Stack>
          </>
        ) : null}

        {webCitations.length > 0 ? (
          <Stack spacing={1}>
            <Typography variant="body2" fontWeight={500}>
              网页证据
            </Typography>
            {webCitations.map((item) => (
              <Paper key={item.source_id} variant="outlined" sx={{ p: 1.5 }}>
                <Stack spacing={0.75}>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip size="small" label={item.source_provider} color="primary" />
                    <Chip size="small" label={item.retrieval_method} variant="outlined" />
                  </Stack>
                  <Typography variant="body2" fontWeight={500}>
                    {item.title ?? item.source_id}
                  </Typography>
                  {item.origin_url ? (
                    <Typography variant="body2" color="text.secondary">
                      {item.origin_url}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
            ))}
          </Stack>
        ) : null}

        {paperCitations.length > 0 ? (
          <Stack spacing={1}>
            <Typography variant="body2" fontWeight={500}>
              论文证据
            </Typography>
            {paperCitations.map((item) => (
              <Paper key={item.source_id} variant="outlined" sx={{ p: 1.5 }}>
                <Stack spacing={0.75}>
                  <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
                    <Chip size="small" label={item.source_provider} color="secondary" />
                    {item.arxiv_id ? <Chip size="small" label={item.arxiv_id} variant="outlined" /> : null}
                  </Stack>
                  <Typography variant="body2" fontWeight={500}>
                    {item.title ?? item.source_id}
                  </Typography>
                  {item.authors.length > 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      作者：{item.authors.join(', ')}
                    </Typography>
                  ) : null}
                  {item.published_at ? (
                    <Typography variant="body2" color="text.secondary">
                      发布：{item.published_at}
                    </Typography>
                  ) : null}
                  {item.pdf_url ? (
                    <Typography variant="body2" color="text.secondary">
                      PDF：{item.pdf_url}
                    </Typography>
                  ) : null}
                </Stack>
              </Paper>
            ))}
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}
