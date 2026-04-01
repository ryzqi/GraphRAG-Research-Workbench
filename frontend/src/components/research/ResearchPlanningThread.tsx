import { Paper, Stack, TextField, Typography } from '@mui/material';

import type {
  ResearchClarificationRequest,
  ResearchSessionStatus,
} from '../../types/researchEvents';
import { Button } from '../ui/Button';

interface ResearchPlanningThreadProps {
  question: string;
  status: ResearchSessionStatus;
  clarificationRequest?: ResearchClarificationRequest | null;
  clarificationDraft?: string;
  clarificationSubmitPending?: boolean;
  onClarificationDraftChange?: ((value: string) => void) | undefined;
  onSubmitClarification?: (() => void | Promise<void>) | undefined;
}

const messageCardSx = {
  borderRadius: 6,
  borderColor: 'rgba(210, 227, 252, 0.92)',
  bgcolor: '#ffffff',
  color: '#202124',
  boxShadow: '0 16px 40px rgba(66, 133, 244, 0.08)',
} as const;

export function ResearchPlanningThread({
  question,
  status,
  clarificationRequest = null,
  clarificationDraft = '',
  clarificationSubmitPending = false,
  onClarificationDraftChange,
  onSubmitClarification,
}: ResearchPlanningThreadProps) {
  const trimmedQuestion = question.trim();

  return (
    <Stack spacing={1.5}>
      {trimmedQuestion ? (
        <Paper
          variant="outlined"
          sx={{
            borderRadius: 6,
            borderColor: 'rgba(210, 227, 252, 0.92)',
            bgcolor: '#ffffff',
            color: '#202124',
            boxShadow: '0 18px 44px rgba(66, 133, 244, 0.08)',
            maxWidth: 860,
            mx: 'auto',
          }}
        >
          <Stack spacing={0.5} sx={{ px: 2.5, py: 1.75 }}>
            <Typography variant="body1">{trimmedQuestion}</Typography>
          </Stack>
        </Paper>
      ) : null}

      {status === 'clarifying' && clarificationRequest ? (
        <Paper variant="outlined" sx={messageCardSx}>
          <Stack spacing={1.25} sx={{ p: 2 }}>
            <Typography variant="body2" sx={{ color: '#5f6368' }}>
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
                    sx={{ display: 'block', mt: 0.5, color: '#5f6368' }}
                  >
                    {item.why_it_matters}
                  </Typography>
                </Typography>
              ))}
            </Stack>
            <Stack spacing={1.25}>
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
                      color: '#202124',
                      alignItems: 'flex-start',
                      bgcolor: '#ffffff',
                      borderRadius: 3,
                    },
                  },
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    alignItems: 'flex-start',
                    borderRadius: 3,
                    '& fieldset': {
                      borderColor: 'rgba(223, 225, 229, 0.92)',
                    },
                    '&:hover fieldset': {
                      borderColor: 'rgba(154, 160, 166, 0.72)',
                    },
                    '&.Mui-focused fieldset': {
                      borderColor: '#1a73e8',
                    },
                  },
                  '& .MuiInputBase-input::placeholder': {
                    color: '#80868b',
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
                  px: 2.5,
                  borderRadius: 999,
                  bgcolor: '#1a73e8',
                  color: '#ffffff',
                  '&:hover': {
                    bgcolor: '#1765cc',
                  },
                }}
              >
                提交补充信息
              </Button>
            </Stack>
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );
}
