import ArrowUpwardRoundedIcon from '@mui/icons-material/ArrowUpwardRounded';
import AssignmentTurnedInRoundedIcon from '@mui/icons-material/AssignmentTurnedInRounded';
import AutoAwesomeRoundedIcon from '@mui/icons-material/AutoAwesomeRounded';
import EditNoteRoundedIcon from '@mui/icons-material/EditNoteRounded';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import PlayArrowRoundedIcon from '@mui/icons-material/PlayArrowRounded';
import type { ReactNode } from 'react';
import { Box, IconButton, InputBase, Paper, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchPageViewModel } from '../../services/researchWorkbench';
import {
  researchBodyFont,
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
} from './researchWorkbenchStyles';
import { ResearchShell } from './ResearchShell';
import { Button } from '../ui/Button';

const longFormTextSx = {
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowWrap: 'anywhere',
} as const;

function renderQuestionBubble(question: string) {
  return (
    <Stack spacing={1.1} sx={{ maxWidth: 720, mx: 'auto' }}>
      <Stack direction="row" spacing={1.1} alignItems="center">
        <Box
          sx={{
            px: 0.95,
            py: 0.38,
            borderRadius: 999,
            bgcolor: alpha(researchWorkbenchColors.text, 0.08),
            color: researchWorkbenchColors.subtleText,
            fontSize: '0.72rem',
            fontWeight: 800,
            letterSpacing: '0.06em',
          }}
        >
          YOU
        </Box>
        <Typography sx={{ color: researchWorkbenchColors.subtleText, fontSize: '0.84rem' }}>
          刚刚提出 · 深度研究模式
        </Typography>
      </Stack>

      <Paper
        sx={{
          ...researchWorkbenchInnerCardSx,
          px: { xs: 2.1, md: 2.4 },
          py: { xs: 1.4, md: 1.55 },
          borderRadius: 2.5,
          bgcolor: alpha('#eef1f6', 0.96),
        }}
      >
        <Typography
          variant="body1"
          sx={{
            color: researchWorkbenchColors.text,
            lineHeight: 1.75,
            fontFamily: researchBodyFont,
            ...longFormTextSx,
          }}
        >
          {question}
        </Typography>
      </Paper>
    </Stack>
  );
}

function renderBottomDock({
  value,
  placeholder,
  onChange,
  onSubmit,
  disabled = false,
}: {
  value: string;
  placeholder: string;
  onChange?: (value: string) => void;
  onSubmit?: () => void | Promise<void>;
  disabled?: boolean;
}) {
  return (
    <Paper
      sx={{
        ...researchWorkbenchInnerCardSx,
        width: '100%',
        px: { xs: 1.25, md: 1.5 },
        py: 0.95,
        borderRadius: 999,
        bgcolor: '#ffffff',
        boxShadow: '0 20px 40px rgba(32, 48, 86, 0.1)',
      }}
    >
      <Stack direction="row" spacing={1.25} alignItems="center">
        <InputBase
          fullWidth
          multiline
          minRows={1}
          maxRows={3}
          value={value}
          onChange={(event) => onChange?.(event.target.value)}
          placeholder={placeholder}
          sx={{
            fontSize: 15,
            lineHeight: 1.7,
            color: researchWorkbenchColors.text,
            fontFamily: researchBodyFont,
            '& textarea': {
              resize: 'none',
            },
            '& .MuiInputBase-input::placeholder': {
              color: researchWorkbenchColors.subtleText,
              opacity: 1,
            },
          }}
        />
        <IconButton
          disabled={disabled}
          onClick={() => {
            void onSubmit?.();
          }}
          sx={{
            width: 40,
            height: 40,
            flexShrink: 0,
            bgcolor: researchWorkbenchColors.primary,
            color: '#ffffff',
            '&:hover': {
              bgcolor: researchWorkbenchColors.primaryHover,
            },
            '&.Mui-disabled': {
              bgcolor: alpha(researchWorkbenchColors.primary, 0.32),
              color: '#ffffff',
            },
          }}
        >
          <ArrowUpwardRoundedIcon fontSize="small" />
        </IconButton>
      </Stack>
    </Paper>
  );
}

export function ResearchPlanningThread({
  model,
  actions: _actions = null,
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
}: {
  model: ResearchPageViewModel;
  actions?: ReactNode;
  clarificationDraft?: string;
  clarificationSubmitPending?: boolean;
  planFeedbackDraft?: string;
  planUpdatePending?: boolean;
  startPending?: boolean;
  onClarificationDraftChange?: (value: string) => void;
  onSubmitClarification?: () => void | Promise<void>;
  onPlanFeedbackDraftChange?: (value: string) => void;
  onUpdatePlan?: () => void | Promise<void>;
  onStartExecution?: () => void | Promise<void>;
}) {
  const clarification = model.clarification;
  const plan = model.plan;

  if (model.surface === 'clarifying' && clarification) {
    return (
      <ResearchShell
        topSlot={renderQuestionBubble(model.hero.title)}
        heroIcon={<AutoAwesomeRoundedIcon sx={{ fontSize: 22 }} />}
        headline="待确认的研究维度"
        footer={renderBottomDock({
          value: clarificationDraft,
          placeholder: clarification.inputPlaceholder,
          onChange: onClarificationDraftChange,
          onSubmit: onSubmitClarification,
          disabled: clarificationSubmitPending,
        })}
      >
        <Paper
          sx={{
            ...researchWorkbenchInnerCardSx,
            borderRadius: 4,
            p: { xs: 2.25, md: 2.9 },
          }}
        >
          <Stack spacing={2.3}>
            <Typography
              variant="body1"
              sx={{
                color: researchWorkbenchColors.mutedText,
                lineHeight: 1.85,
                fontFamily: researchBodyFont,
                ...longFormTextSx,
              }}
            >
              {clarification.summary}
            </Typography>

            <Stack direction="row" spacing={1} alignItems="center">
              <Box
                sx={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  bgcolor: researchWorkbenchColors.primary,
                }}
              />
              <Typography
                variant="subtitle2"
                sx={{
                  color: researchWorkbenchColors.primary,
                  letterSpacing: '0.08em',
                  fontWeight: 800,
                }}
              >
                待确认的研究维度
              </Typography>
            </Stack>

            <Box
              sx={{
                display: 'grid',
                gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' },
                gap: 1.5,
              }}
            >
              {clarification.questionCards.map((item) => (
                <Paper
                  key={item.id}
                  sx={{
                    borderRadius: 3,
                    p: { xs: 1.8, md: 2.1 },
                    bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.8),
                    boxShadow: 'none',
                  }}
                >
                  <Stack spacing={0.9}>
                    <Typography
                      variant="caption"
                      sx={{
                        color: researchWorkbenchColors.subtleText,
                        letterSpacing: '0.08em',
                        textTransform: 'uppercase',
                        fontWeight: 700,
                      }}
                    >
                      {item.id}
                    </Typography>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, ...longFormTextSx }}>
                      {item.title}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{
                        color: researchWorkbenchColors.mutedText,
                        lineHeight: 1.75,
                        fontFamily: researchBodyFont,
                        ...longFormTextSx,
                      }}
                    >
                      {item.description}
                    </Typography>
                  </Stack>
                </Paper>
              ))}
            </Box>
          </Stack>
        </Paper>

        <Paper
          sx={{
            ...researchWorkbenchInnerCardSx,
            borderRadius: 3.5,
            p: { xs: 2, md: 2.3 },
            borderLeft: `4px solid ${researchWorkbenchColors.primary}`,
          }}
        >
          <Stack spacing={0.9}>
            <Stack direction="row" spacing={1} alignItems="center">
              <InfoOutlinedIcon sx={{ fontSize: 18, color: researchWorkbenchColors.primary }} />
              <Typography variant="subtitle1" sx={{ fontWeight: 800, color: researchWorkbenchColors.text }}>
                当前的初步认知
              </Typography>
            </Stack>
            <Typography
              variant="body2"
              sx={{
                color: researchWorkbenchColors.mutedText,
                lineHeight: 1.8,
                fontFamily: researchBodyFont,
                ...longFormTextSx,
              }}
            >
              {clarification.knownContext}
            </Typography>
          </Stack>
        </Paper>
      </ResearchShell>
    );
  }

  if (model.surface === 'planning' && plan) {
    return (
      <ResearchShell
        topSlot={renderQuestionBubble(model.hero.title)}
        heroIcon={<AssignmentTurnedInRoundedIcon sx={{ fontSize: 22 }} />}
        headline="拟定研究计划"
        footer={renderBottomDock({
          value: planFeedbackDraft,
          placeholder: '提问或修改研究计划...',
          onChange: onPlanFeedbackDraftChange,
          onSubmit: onUpdatePlan,
          disabled: planUpdatePending,
        })}
      >
        <Paper
          sx={{
            ...researchWorkbenchInnerCardSx,
            overflow: 'hidden',
            borderRadius: 4,
            border: `1px solid ${alpha(researchWorkbenchColors.primary, 0.22)}`,
            boxShadow: '0 24px 52px rgba(32, 48, 86, 0.08)',
          }}
        >
          <Box
            sx={{
              height: 3,
              width: '100%',
              background: `linear-gradient(90deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
            }}
          />
          <Stack spacing={2.5} sx={{ px: { xs: 2.1, md: 3 }, py: { xs: 2.25, md: 2.8 } }}>
            <Stack spacing={0.95} alignItems="center" sx={{ textAlign: 'center' }}>
              <Typography
                variant="subtitle2"
                sx={{
                  color: researchWorkbenchColors.subtleText,
                  letterSpacing: '0.08em',
                  fontWeight: 700,
                }}
              >
                研究步骤详细方案
              </Typography>
              {plan.researchBrief ? (
                <Typography
                  variant="body2"
                  sx={{
                    maxWidth: 760,
                    color: researchWorkbenchColors.mutedText,
                    lineHeight: 1.75,
                    fontFamily: researchBodyFont,
                    ...longFormTextSx,
                  }}
                >
                  {plan.researchBrief}
                </Typography>
              ) : null}
            </Stack>

            <Stack spacing={2.2}>
              {plan.steps.map((item) => (
                <Stack key={`${item.index}-${item.title}`} direction="row" spacing={1.5} alignItems="flex-start">
                  <Box
                    sx={{
                      width: 28,
                      height: 28,
                      borderRadius: '50%',
                      flexShrink: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      bgcolor: alpha(researchWorkbenchColors.primary, 0.12),
                      color: researchWorkbenchColors.primary,
                      fontWeight: 800,
                      fontSize: '0.88rem',
                    }}
                  >
                    {item.index}
                  </Box>
                  <Stack spacing={0.6}>
                    <Typography variant="subtitle1" sx={{ fontWeight: 700, ...longFormTextSx }}>
                      {item.title}
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{
                        color: researchWorkbenchColors.mutedText,
                        lineHeight: 1.8,
                        fontFamily: researchBodyFont,
                        ...longFormTextSx,
                      }}
                    >
                      {item.description}
                    </Typography>
                    <Stack direction="row" spacing={0.85} flexWrap="wrap" useFlexGap>
                      {item.targetSources.map((target) => (
                        <Box
                          key={`${item.index}-${target}`}
                          sx={{
                            px: 1.05,
                            py: 0.45,
                            borderRadius: 999,
                            bgcolor: alpha(researchWorkbenchColors.primary, 0.08),
                            color: researchWorkbenchColors.primary,
                            fontSize: '0.78rem',
                            fontWeight: 700,
                          }}
                        >
                          {target}
                        </Box>
                      ))}
                    </Stack>
                  </Stack>
                </Stack>
              ))}
            </Stack>
          </Stack>

          <Stack
            direction={{ xs: 'column', sm: 'row' }}
            spacing={1.25}
            justifyContent="center"
            sx={{
              px: { xs: 2.1, md: 3 },
              py: { xs: 2, md: 2.25 },
              borderTop: `1px solid ${alpha(researchWorkbenchColors.text, 0.08)}`,
              bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.54),
            }}
          >
            <Button
              variant="outlined"
              loading={planUpdatePending}
              onClick={() => {
                void onUpdatePlan?.();
              }}
              startIcon={<EditNoteRoundedIcon sx={{ fontSize: 18 }} />}
              sx={{
                minHeight: 44,
                px: 2.5,
                borderRadius: 2.6,
                borderColor: alpha(researchWorkbenchColors.text, 0.12),
                color: researchWorkbenchColors.text,
                backgroundColor: '#ffffff',
              }}
            >
              {plan.secondaryActionLabel}
            </Button>
            <Button
              variant="contained"
              loading={startPending}
              onClick={() => {
                void onStartExecution?.();
              }}
              startIcon={<PlayArrowRoundedIcon sx={{ fontSize: 18 }} />}
              sx={{
                minHeight: 44,
                px: 2.75,
                borderRadius: 2.6,
                background: `linear-gradient(135deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
                color: '#fff',
                boxShadow: 'none',
              }}
            >
              {plan.primaryActionLabel}
            </Button>
          </Stack>
        </Paper>
      </ResearchShell>
    );
  }

  return null;
}
