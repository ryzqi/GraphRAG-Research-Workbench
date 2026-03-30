import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

import type { ResearchSessionStatus } from '../../types/researchEvents';
import { Button } from '../ui/Button';

interface InterruptDecisionPanelProps {
  status: ResearchSessionStatus;
  resumeIdempotencyKey: string;
  decisionDraft: string;
  onResumeIdempotencyKeyChange: (value: string) => void;
  onDecisionDraftChange: (value: string) => void;
  onResume: (() => void | Promise<void>) | undefined;
  resumePending?: boolean;
}

export function InterruptDecisionPanel({
  status,
  resumeIdempotencyKey,
  decisionDraft,
  onResumeIdempotencyKeyChange,
  onDecisionDraftChange,
  onResume,
  resumePending = false,
}: InterruptDecisionPanelProps) {
  if (status !== 'interrupted') {
    return null;
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack spacing={1.5}>
        <Typography variant="subtitle1" fontWeight={600}>
          中断决策
        </Typography>
        <Typography variant="body2" color="text.secondary">
          当前会话已进入 interrupted 状态。可先直接继续研究，只有在需要时再展开高级决策。
        </Typography>
        <Button
          variant="contained"
          onClick={() => {
            void onResume?.();
          }}
          loading={resumePending}
          sx={{ alignSelf: 'flex-start' }}
        >
          继续研究
        </Button>
        <Accordion disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: 2 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="body2" fontWeight={500}>
              高级决策
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1.5}>
              <TextField
                label="Resume Idempotency Key"
                size="small"
                value={resumeIdempotencyKey}
                onChange={(event) => onResumeIdempotencyKeyChange(event.target.value)}
              />
              <TextField
                label="决策 JSON"
                multiline
                minRows={3}
                value={decisionDraft}
                onChange={(event) => onDecisionDraftChange(event.target.value)}
              />
            </Stack>
          </AccordionDetails>
        </Accordion>
      </Stack>
    </Paper>
  );
}
