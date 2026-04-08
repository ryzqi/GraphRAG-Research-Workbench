import { Chip, Paper, Stack, TextField, Typography } from '@mui/material';

import type {
  ResearchClarificationRequest,
  ResearchPlanSnapshot,
  ResearchSessionStatus,
} from '../../types/researchEvents';
import {
  researchWorkbenchCardSx,
  researchWorkbenchColors,
  researchWorkbenchEyebrowSx,
} from './researchWorkbenchStyles';
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
  ...researchWorkbenchCardSx,
  overflow: 'hidden',
} as const;

const longFormTextSx = {
  minWidth: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowWrap: 'anywhere',
} as const;

const messageCardContentSx = {
  px: { xs: 2.5, md: 3.5 },
  py: { xs: 2.25, md: 3 },
  minWidth: 0,
} as const;

const orderedListSx = {
  pl: 2.5,
  m: 0,
  minWidth: 0,
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
    <Stack spacing={2}>
      {trimmedQuestion ? (
        <Paper variant="outlined" sx={messageCardSx}>
          <Stack spacing={1} sx={messageCardContentSx}>
            <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
              研究问题
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700 }}>
              {trimmedQuestion}
            </Typography>
          </Stack>
        </Paper>
      ) : null}

      {status === 'clarifying' && clarificationRequest ? (
        <Paper variant="outlined" sx={messageCardSx}>
          <Stack spacing={2} sx={messageCardContentSx}>
            <Stack spacing={0.75}>
              <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
                待补充信息
              </Typography>
              <Typography variant="h6" fontWeight={700}>
                补齐研究边界
              </Typography>
            </Stack>
            <Typography variant="body2" sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}>
              {clarificationRequest.summary}
            </Typography>
            <Stack component="ol" spacing={1.25} sx={orderedListSx}>
              {clarificationRequest.questions.map((item) => (
                <Typography component="li" key={item.id} variant="body2" sx={longFormTextSx}>
                  <Typography
                    component="span"
                    variant="body2"
                    fontWeight={600}
                    sx={longFormTextSx}
                  >
                    {item.question}
                  </Typography>
                  <Typography
                    component="span"
                    variant="body2"
                    sx={{
                      ...longFormTextSx,
                      display: 'block',
                      mt: 0.5,
                      color: researchWorkbenchColors.mutedText,
                    }}
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
                      color: researchWorkbenchColors.text,
                      alignItems: 'flex-start',
                      bgcolor: researchWorkbenchColors.surface,
                      borderRadius: 2.5,
                    },
                  },
                }}
                sx={{
                  '& .MuiOutlinedInput-root': {
                    alignItems: 'flex-start',
                    borderRadius: 2.5,
                    '& fieldset': {
                      borderColor: researchWorkbenchColors.border,
                    },
                    '&:hover fieldset': {
                      borderColor: researchWorkbenchColors.softBorder,
                    },
                    '&.Mui-focused fieldset': {
                      borderColor: researchWorkbenchColors.primary,
                    },
                  },
                  '& .MuiInputBase-input::placeholder': {
                    color: researchWorkbenchColors.subtleText,
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
                  minHeight: 42,
                  px: 2.75,
                  borderRadius: 999,
                  bgcolor: researchWorkbenchColors.primary,
                  color: '#ffffff',
                  '&:hover': {
                    bgcolor: researchWorkbenchColors.primaryHover,
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
          <Stack spacing={2} sx={messageCardContentSx}>
            <Stack spacing={0.75} sx={{ minWidth: 0 }}>
              <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
                研究计划
              </Typography>
              <Typography variant="h6" fontWeight={700}>
                研究计划
              </Typography>
              <Typography
                variant="body2"
                sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
              >
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
                  sx={{
                    borderColor: researchWorkbenchColors.border,
                    color: researchWorkbenchColors.mutedText,
                    backgroundColor: researchWorkbenchColors.surface,
                  }}
                />
              ))}
            </Stack>
            <Stack component="ol" spacing={1.25} sx={orderedListSx}>
              {planSnapshot.subtasks.map((item) => (
                <Typography component="li" key={item.title} variant="body2" sx={longFormTextSx}>
                  <Typography
                    component="span"
                    variant="body2"
                    fontWeight={600}
                    sx={longFormTextSx}
                  >
                    {item.title}
                  </Typography>
                  <Typography
                    component="span"
                    variant="body2"
                    sx={{
                      ...longFormTextSx,
                      display: 'block',
                      mt: 0.5,
                      color: researchWorkbenchColors.mutedText,
                    }}
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
                    color: researchWorkbenchColors.text,
                    alignItems: 'flex-start',
                    bgcolor: researchWorkbenchColors.surface,
                    borderRadius: 2.5,
                  },
                },
              }}
              sx={{
                '& .MuiOutlinedInput-root': {
                  alignItems: 'flex-start',
                  borderRadius: 2.5,
                  '& fieldset': {
                    borderColor: researchWorkbenchColors.border,
                  },
                  '&:hover fieldset': {
                    borderColor: researchWorkbenchColors.softBorder,
                  },
                  '&.Mui-focused fieldset': {
                    borderColor: researchWorkbenchColors.primary,
                  },
                },
              }}
            />
            <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25}>
              <Button
                variant="outlined"
                onClick={() => {
                  void onUpdatePlan?.();
                }}
                loading={planUpdatePending}
                sx={{
                  minHeight: 42,
                  borderRadius: 999,
                  borderColor: researchWorkbenchColors.border,
                  color: researchWorkbenchColors.text,
                }}
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
                  minHeight: 42,
                  px: 2.75,
                  borderRadius: 999,
                  bgcolor: researchWorkbenchColors.primary,
                  color: '#ffffff',
                  '&:hover': {
                    bgcolor: researchWorkbenchColors.primaryHover,
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
