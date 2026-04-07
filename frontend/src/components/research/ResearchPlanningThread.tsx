import { Chip, Paper, Stack, TextField, Typography } from '@mui/material';

import type {
  ResearchClarificationRequest,
  ResearchPlanSnapshot,
  ResearchSessionStatus,
} from '../../types/researchEvents';
import { Button } from '../ui/Button';

interface ResearchPlanningThreadProps {
  question: string;
  status: ResearchSessionStatus;
  clarificationRequest?: ResearchClarificationRequest | null;
  planSnapshot?: ResearchPlanSnapshot | null;
  clarificationDraft?: string;
  clarificationSubmitPending?: boolean;
  planFeedbackDraft?: string;
  planUpdatePending?: boolean;
  startPending?: boolean;
  onClarificationDraftChange?: ((value: string) => void) | undefined;
  onSubmitClarification?: (() => void | Promise<void>) | undefined;
  onPlanFeedbackDraftChange?: ((value: string) => void) | undefined;
  onUpdatePlan?: (() => void | Promise<void>) | undefined;
  onStartExecution?: (() => void | Promise<void>) | undefined;
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
  planSnapshot = null,
  clarificationDraft = '',
  clarificationSubmitPending = false,
  planFeedbackDraft = '',
  planUpdatePending = false,
  startPending = false,
  onClarificationDraftChange,
  onSubmitClarification,
  onPlanFeedbackDraftChange,
  onUpdatePlan,
  onStartExecution,
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

      {status === 'plan_ready' && planSnapshot ? (
        <Paper variant="outlined" sx={messageCardSx}>
          <Stack spacing={1.5} sx={{ p: 2 }}>
            <Stack spacing={0.75}>
              <Typography variant="h6" fontWeight={700}>
                研究计划
              </Typography>
              <Typography variant="body2" sx={{ color: '#5f6368' }}>
                {planSnapshot.summary}
              </Typography>
            </Stack>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              {planSnapshot.target_sources.map((item) => (
                <Chip
                  key={item}
                  size="small"
                  label={item === 'paper' ? '论文' : item === 'web' ? '网页' : item}
                  variant="outlined"
                />
              ))}
            </Stack>
            <Stack component="ol" spacing={1.25} sx={{ pl: 2.5, m: 0 }}>
              {planSnapshot.subtasks.map((item) => (
                <Typography component="li" key={item.title} variant="body2">
                  <Typography component="span" variant="body2" fontWeight={600}>
                    {item.title}
                  </Typography>
                  <Typography
                    component="span"
                    variant="body2"
                    sx={{ display: 'block', mt: 0.5, color: '#5f6368' }}
                  >
                    {item.description}
                  </Typography>
                </Typography>
              ))}
            </Stack>
            <TextField
              fullWidth
              multiline
              minRows={3}
              value={planFeedbackDraft}
              onChange={(event) => onPlanFeedbackDraftChange?.(event.target.value)}
              placeholder="如需更新计划，可补充新的关注点、输出要求或边界。"
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
                },
              }}
            />
            <Stack direction="row" spacing={1.25}>
              <Button
                variant="outlined"
                onClick={() => {
                  void onUpdatePlan?.();
                }}
                loading={planUpdatePending}
              >
                更新计划
              </Button>
              <Button
                variant="contained"
                onClick={() => {
                  void onStartExecution?.();
                }}
                loading={startPending}
                sx={{
                  minHeight: 40,
                  px: 2.5,
                  borderRadius: 999,
                  bgcolor: '#111111',
                  color: '#ffffff',
                  '&:hover': {
                    bgcolor: '#000000',
                  },
                }}
              >
                开始
              </Button>
            </Stack>
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );
}
