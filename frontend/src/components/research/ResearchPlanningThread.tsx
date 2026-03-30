import { Paper, Stack, TextField, Typography } from '@mui/material';

import type {
  ResearchClarificationRequest,
  ResearchPlanSnapshot,
  ResearchSessionStatus,
} from '../../types/researchEvents';
import { Button } from '../ui/Button';
import { PlanPreviewPanel } from './PlanPreviewPanel';

interface ResearchPlanningThreadProps {
  question: string;
  status: ResearchSessionStatus;
  clarificationRequest?: ResearchClarificationRequest | null;
  planSnapshot?: ResearchPlanSnapshot | null;
  clarificationDraft?: string;
  clarificationSubmitPending?: boolean;
  onClarificationDraftChange?: ((value: string) => void) | undefined;
  onSubmitClarification?: (() => void | Promise<void>) | undefined;
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
  clarificationDraft = '',
  clarificationSubmitPending = false,
  onClarificationDraftChange,
  onSubmitClarification,
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
            <Stack spacing={1.25}>
              <Typography variant="body2" sx={{ color: 'rgba(226, 232, 240, 0.78)' }}>
                补充你的回答
              </Typography>
              <TextField
                fullWidth
                multiline
                minRows={4}
                value={clarificationDraft}
                onChange={(event) => onClarificationDraftChange?.(event.target.value)}
                placeholder="补充研究范围、目标读者、输出形式或关键约束。"
                slotProps={{
                  input: {
                    sx: {
                      color: '#f8fafc',
                      alignItems: 'flex-start',
                      bgcolor: 'rgba(15, 23, 42, 0.72)',
                      borderRadius: 3,
                    },
                  },
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    alignItems: 'flex-start',
                    borderRadius: 3,
                    '& fieldset': {
                      borderColor: 'rgba(148, 163, 184, 0.24)',
                    },
                    '&:hover fieldset': {
                      borderColor: 'rgba(226, 232, 240, 0.42)',
                    },
                    '&.Mui-focused fieldset': {
                      borderColor: 'rgba(248, 250, 252, 0.72)',
                    },
                  },
                  '& .MuiInputBase-input::placeholder': {
                    color: 'rgba(226, 232, 240, 0.42)',
                    opacity: 1,
                  },
                }}
              />
              <Button
                variant="contained"
                onClick={() => {
                  void onSubmitClarification?.();
                }}
                loading={clarificationSubmitPending}
                sx={{
                  alignSelf: 'flex-start',
                  minHeight: 40,
                  px: 2,
                  borderRadius: 999,
                  bgcolor: '#f8fafc',
                  color: '#020617',
                  '&:hover': {
                    bgcolor: '#e2e8f0',
                  },
                }}
              >
                提交补充信息
              </Button>
            </Stack>
          </Stack>
        </Paper>
      ) : null}

      {status === 'awaiting_confirmation' && planSnapshot ? (
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
