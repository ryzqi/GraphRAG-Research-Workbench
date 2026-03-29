import { Box, Chip, Paper, Stack, Typography } from '@mui/material';

import { mergeResearchEventEnvelopes, type ResearchEventEnvelope } from '../../types/researchEvents';

interface ResearchTimelineProps {
  events: ResearchEventEnvelope[];
}

export function ResearchTimeline({ events }: ResearchTimelineProps) {
  const orderedEvents = mergeResearchEventEnvelopes([], events);

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1" fontWeight={600}>
          研究时间线
        </Typography>

        {orderedEvents.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            暂无事件，等待后端继续推进研究会话。
          </Typography>
        ) : (
          <Stack component="ol" spacing={1.25} sx={{ pl: 2, m: 0 }}>
            {orderedEvents.map((event) => (
              <Box component="li" key={event.event_id}>
                <Stack spacing={0.75}>
                  <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap" useFlexGap>
                    <Typography variant="body2" fontWeight={500}>
                      {event.event_type}
                    </Typography>
                    <Chip size="small" label={`#${event.sequence}`} variant="outlined" />
                    <Chip size="small" label={event.namespace} variant="outlined" />
                    {event.source_provider ? (
                      <Chip size="small" label={event.source_provider} color="primary" />
                    ) : null}
                  </Stack>
                  <Typography variant="body2" color="text.secondary">
                    phase={event.phase}
                    {event.subagent_name ? ` · subagent=${event.subagent_name}` : ''}
                    {event.retrieval_method ? ` · method=${event.retrieval_method}` : ''}
                  </Typography>
                  {event.origin_url ? (
                    <Typography variant="body2" color="text.secondary">
                      {event.origin_url}
                    </Typography>
                  ) : null}
                </Stack>
              </Box>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}
