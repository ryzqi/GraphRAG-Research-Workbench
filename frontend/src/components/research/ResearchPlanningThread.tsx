import { Paper, Stack, Typography } from '@mui/material';

import type {
  ResearchClarificationRequest,
  ResearchPlanSnapshot,
  ResearchSessionStatus,
} from '../../types/researchEvents';
import { PlanPreviewPanel } from './PlanPreviewPanel';

interface ResearchPlanningThreadProps {
  question: string;
  status: ResearchSessionStatus;
  clarificationRequest?: ResearchClarificationRequest | null;
  planSnapshot?: ResearchPlanSnapshot | null;
  confirmPending?: boolean;
  onConfirm?: (() => void | Promise<void>) | undefined;
}

const messageCardSx = {
  borderRadius: 4,
  borderColor: 'rgba(148, 163, 184, 0.18)',
  bgcolor: 'rgba(15, 23, 42, 0.82)',
  color: '#f8fafc',
} as const;

export function ResearchPlanningThread({
  question,
  status,
  clarificationRequest = null,
  planSnapshot = null,
  confirmPending = false,
  onConfirm,
}: ResearchPlanningThreadProps) {
  const trimmedQuestion = question.trim();

  return (
    <Stack spacing={1.5}>
      {trimmedQuestion ? (
        <Paper
          variant="outlined"
          sx={{
            ...messageCardSx,
            ml: { xs: 0, md: 8 },
            bgcolor: '#111827',
          }}
        >
          <Stack spacing={0.75} sx={{ p: 2 }}>
            <Typography variant="overline" sx={{ color: 'rgba(226, 232, 240, 0.5)' }}>
              user
            </Typography>
            <Typography variant="body1">{trimmedQuestion}</Typography>
          </Stack>
        </Paper>
      ) : null}

      {status === 'clarifying' && clarificationRequest ? (
        <Paper variant="outlined" sx={messageCardSx}>
          <Stack spacing={1.25} sx={{ p: 2 }}>
            <Typography variant="overline" sx={{ color: 'rgba(226, 232, 240, 0.5)' }}>
              assistant
            </Typography>
            <Typography variant="body1" fontWeight={600}>
              在开始规划前，还需要补充一点信息
            </Typography>
            <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.72)' }}>
              {clarificationRequest.summary}
            </Typography>
            <Stack component="ol" spacing={1.25} sx={{ pl: 2.5, m: 0 }}>
              {clarificationRequest.questions.map((item) => (
                <Typography component="li" key={item.id} variant="body2">
                  <Typography component="span" variant="body2" fontWeight={600}>
                    {item.question}
                  </Typography>
                  <Typography
                    component="span"
                    variant="body2"
                    sx={{ display: 'block', mt: 0.5, color: 'rgba(226, 232, 240, 0.68)' }}
                  >
                    {item.why_it_matters}
                  </Typography>
                </Typography>
              ))}
            </Stack>
          </Stack>
        </Paper>
      ) : null}

      {planSnapshot ? (
        <PlanPreviewPanel
          planSnapshot={planSnapshot}
          status={status}
          onConfirm={onConfirm}
          confirmPending={confirmPending}
        />
      ) : null}
    </Stack>
  );
}
