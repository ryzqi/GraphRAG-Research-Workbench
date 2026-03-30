import { Accordion, AccordionDetails, AccordionSummary, Stack, Typography } from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import type { ResearchEventEnvelope } from '../../types/researchEvents';
import { ResearchTimeline } from './ResearchTimeline';

export function ResearchAdvancedEventsPanel({ events }: { events: ResearchEventEnvelope[] }) {
  return (
    <Accordion disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 3 }}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography fontWeight={600}>高级事件</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1}>
          <Typography variant="body2" color="text.secondary">
            这里保留技术事件明细，默认不作为主进度视图。
          </Typography>
          <ResearchTimeline events={events} />
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
