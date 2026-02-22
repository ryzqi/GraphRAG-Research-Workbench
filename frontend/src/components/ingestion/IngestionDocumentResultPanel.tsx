import { useMemo, useState } from 'react';
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import {
  docPresentationColor,
  docPresentationLabel,
  type DocPresentationStatus,
  type IngestionChipColor,
} from './statusPresentation';

export interface IngestionDocumentRow {
  id: string;
  title: string;
  sourceLabel: string;
  retryCount: number;
  contextFailedChunks: number;
  status: DocPresentationStatus;
  statusLabel?: string;
  statusColor?: IngestionChipColor;
  errorMessage?: string | null;
}

interface IngestionDocumentResultPanelProps {
  title?: string;
  summaryText: string;
  docs: IngestionDocumentRow[];
  emptyMessage?: string;
  defaultExpanded?: boolean;
}

const GROUP_ORDER: DocPresentationStatus[] = ['failed', 'processing', 'succeeded', 'canceled'];

export function IngestionDocumentResultPanel({
  title = '文档处理结果',
  summaryText,
  docs,
  emptyMessage = '当前暂无文档处理明细。',
  defaultExpanded = false,
}: IngestionDocumentResultPanelProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const [expandedErrorIds, setExpandedErrorIds] = useState<Record<string, true>>({});

  const grouped = useMemo(() => {
    const groups: Record<DocPresentationStatus, IngestionDocumentRow[]> = {
      failed: [],
      processing: [],
      succeeded: [],
      canceled: [],
    };
    for (const item of docs) {
      groups[item.status].push(item);
    }
    return groups;
  }, [docs]);

  return (
    <Paper variant='outlined' sx={{ borderRadius: 3, borderColor: 'divider' }}>
      <Accordion
        disableGutters
        expanded={expanded}
        onChange={(_, nextExpanded) => setExpanded(nextExpanded)}
        sx={{
          borderRadius: 3,
          '&::before': { display: 'none' },
        }}
      >
        <AccordionSummary expandIcon={<ExpandMoreIcon fontSize='small' />} sx={{ px: 2 }}>
          <Stack spacing={0.4} sx={{ width: '100%' }}>
            <Stack
              direction='row'
              spacing={1}
              alignItems='center'
              justifyContent='space-between'
              flexWrap='wrap'
              useFlexGap
            >
              <Typography variant='subtitle1' fontWeight={650}>
                {title}
              </Typography>
              <Stack direction='row' spacing={0.75} flexWrap='wrap' useFlexGap>
                {GROUP_ORDER.map((status) => {
                  const count = grouped[status].length;
                  if (count === 0) {
                    return null;
                  }
                  return (
                    <Chip
                      key={status}
                      size='small'
                      variant='outlined'
                      color={docPresentationColor(status)}
                      label={`${docPresentationLabel(status)} ${count}`}
                    />
                  );
                })}
              </Stack>
            </Stack>
            <Typography variant='body2' color='text.secondary'>
              {summaryText}
            </Typography>
          </Stack>
        </AccordionSummary>

        <AccordionDetails sx={{ px: 2, pt: 0, pb: 2 }}>
          {docs.length === 0 ? (
            <Typography variant='body2' color='text.secondary'>
              {emptyMessage}
            </Typography>
          ) : (
            <Box sx={{ maxHeight: 460, overflowY: 'auto', pr: 0.5 }}>
              <Stack spacing={1.25}>
                {GROUP_ORDER.map((status) => {
                  const items = grouped[status];
                  if (items.length === 0) {
                    return null;
                  }
                  return (
                    <Stack key={status} spacing={0.75}>
                      <Typography variant='overline' color='text.secondary'>
                        {docPresentationLabel(status)}
                      </Typography>

                      {items.map((doc) => {
                        const showError = Boolean(expandedErrorIds[doc.id]);
                        return (
                          <Paper
                            key={doc.id}
                            variant='outlined'
                            sx={{ p: 1.2, borderRadius: 2, borderColor: 'divider' }}
                          >
                            <Stack spacing={0.65}>
                              <Stack
                                direction='row'
                                spacing={1}
                                justifyContent='space-between'
                                alignItems='flex-start'
                              >
                                <Box sx={{ minWidth: 0 }}>
                                  <Typography variant='body2' fontWeight={600} noWrap>
                                    {doc.title}
                                  </Typography>
                                  <Typography variant='caption' color='text.secondary'>
                                    {doc.sourceLabel +
                                      ' · 重试 ' +
                                      doc.retryCount +
                                      ' · 上下文降级 ' +
                                      doc.contextFailedChunks}
                                  </Typography>
                                </Box>

                                <Chip
                                  label={doc.statusLabel ?? docPresentationLabel(doc.status)}
                                  size='small'
                                  variant='outlined'
                                  color={doc.statusColor ?? docPresentationColor(doc.status)}
                                />
                              </Stack>

                              {doc.errorMessage && (
                                <Stack spacing={0.5} alignItems='flex-start'>
                                  <Button
                                    size='small'
                                    variant='text'
                                    onClick={() => {
                                      setExpandedErrorIds((prev) => {
                                        if (prev[doc.id]) {
                                          const next = { ...prev };
                                          delete next[doc.id];
                                          return next;
                                        }
                                        return { ...prev, [doc.id]: true };
                                      });
                                    }}
                                  >
                                    {showError ? '收起错误详情' : '查看错误详情'}
                                  </Button>
                                  {showError && (
                                    <Typography variant='caption' color='error.main' sx={{ whiteSpace: 'pre-wrap' }}>
                                      {doc.errorMessage}
                                    </Typography>
                                  )}
                                </Stack>
                              )}
                            </Stack>
                          </Paper>
                        );
                      })}
                    </Stack>
                  );
                })}
              </Stack>
            </Box>
          )}
        </AccordionDetails>
      </Accordion>
    </Paper>
  );
}
