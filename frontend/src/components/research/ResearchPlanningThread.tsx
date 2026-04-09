import type { ReactNode } from 'react';
import { Box, Paper, Stack, TextField, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchPageViewModel } from '../../services/researchWorkbench';
import {
  researchBodyFont,
  researchDisplayFont,
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

const panelSx = {
  ...researchWorkbenchInnerCardSx,
  p: { xs: 2.25, md: 2.75 },
  borderRadius: 3.5,
} as const;

const asidePanelSx = {
  ...researchWorkbenchInnerCardSx,
  p: 2.25,
  borderRadius: 3.5,
  bgcolor: alpha(researchWorkbenchColors.surfaceMuted, 0.74),
} as const;

function renderToneChip(label: string) {
  return (
    <Box
      sx={{
        px: 1.1,
        py: 0.55,
        borderRadius: 999,
        bgcolor: alpha(researchWorkbenchColors.primary, 0.08),
        color: researchWorkbenchColors.primary,
        fontSize: '0.78rem',
        fontWeight: 700,
      }}
    >
      {label}
    </Box>
  );
}

export function ResearchPlanningThread({
  model,
  actions = null,
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

  const clarificationAside = clarification ? (
    <>
      <Paper sx={asidePanelSx}>
        <Stack spacing={1}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            研究输入摘要
          </Typography>
          <Typography
            variant="body2"
            sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.75 }}
          >
            {clarification.knownContext}
          </Typography>
        </Stack>
      </Paper>
      <Paper sx={asidePanelSx}>
        <Stack spacing={1.2}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            本轮将影响
          </Typography>
          <Stack direction="row" flexWrap="wrap" useFlexGap gap={0.9}>
            {renderToneChip('边界收敛')}
            {renderToneChip('搜索路径')}
            {renderToneChip('报告结构')}
          </Stack>
          <Typography
            variant="body2"
            sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.75 }}
          >
            这些补充信息会直接改变后续研究来源、对比维度与最终报告的重点。
          </Typography>
        </Stack>
      </Paper>
    </>
  ) : null;

  const planSourceLabels =
    plan?.steps.flatMap((item) => item.targetSources).filter((value, index, items) => items.indexOf(value) === index) ??
    [];

  const planningAside = plan ? (
    <>
      <Paper sx={asidePanelSx}>
        <Stack spacing={1.2}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            来源焦点
          </Typography>
          <Stack direction="row" flexWrap="wrap" useFlexGap gap={0.9}>
            {planSourceLabels.length > 0
              ? planSourceLabels.map((item) => (
                  <Box
                    key={item}
                    sx={{
                      px: 1.1,
                      py: 0.6,
                      borderRadius: 999,
                      bgcolor: alpha(researchWorkbenchColors.primary, 0.08),
                      color: researchWorkbenchColors.primary,
                      fontSize: '0.78rem',
                      fontWeight: 700,
                    }}
                  >
                    {item}
                  </Box>
                ))
              : renderToneChip('待补来源')}
          </Stack>
        </Stack>
      </Paper>
      <Paper sx={asidePanelSx}>
        <Stack spacing={1}>
          <Typography variant="subtitle2" sx={{ color: researchWorkbenchColors.subtleText }}>
            执行约束
          </Typography>
          <Typography
            variant="body2"
            sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.75 }}
          >
            计划确认后再执行，避免在高成本搜索和报告生成阶段重复返工。
          </Typography>
        </Stack>
      </Paper>
    </>
  ) : null;

  return (
    <ResearchShell
      hero={model.hero}
      railSteps={model.railSteps}
      actions={actions}
      aside={model.surface === 'clarifying' ? clarificationAside : planningAside}
    >
      {model.surface === 'clarifying' && clarification ? (
        <>
          <Paper sx={panelSx}>
            <Stack spacing={2} sx={{ minWidth: 0 }}>
              <Typography
                variant="h4"
                sx={{
                  fontFamily: researchDisplayFont,
                  fontWeight: 800,
                  color: researchWorkbenchColors.text,
                }}
              >
                待确认的研究维度
              </Typography>
              <Typography
                variant="body1"
                sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.8, fontFamily: researchBodyFont }}
              >
                {clarification.summary}
              </Typography>
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: { xs: '1fr', md: 'repeat(2, minmax(0, 1fr))' },
                  gap: 1.5,
                }}
              >
                {clarification.questionCards.map((item, index) => (
                  <Paper
                    key={item.id}
                    sx={{
                      p: 2.15,
                      borderRadius: 3,
                      bgcolor: alpha('#ffffff', 0.88),
                      boxShadow: '0 12px 24px rgba(25, 28, 29, 0.04)',
                    }}
                  >
                    <Stack spacing={0.95}>
                      <Typography
                        variant="caption"
                        sx={{ color: researchWorkbenchColors.subtleText, letterSpacing: '0.14em' }}
                      >
                        Q0{index + 1}
                      </Typography>
                      <Typography variant="subtitle1" fontWeight={700} sx={longFormTextSx}>
                        {item.title}
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.75 }}
                      >
                        {item.description}
                      </Typography>
                    </Stack>
                  </Paper>
                ))}
              </Box>
            </Stack>
          </Paper>

          <Paper sx={{ ...panelSx, p: { xs: 1.7, md: 1.85 } }}>
            <Stack spacing={1.15}>
              <Typography variant="subtitle1" fontWeight={800}>
                回复澄清问题
              </Typography>
              <TextField
                fullWidth
                multiline
                minRows={3}
                value={clarificationDraft}
                onChange={(event) => onClarificationDraftChange?.(event.target.value)}
                placeholder={clarification.inputPlaceholder}
                slotProps={{
                  input: {
                    sx: {
                      ...longFormTextSx,
                      color: researchWorkbenchColors.text,
                      alignItems: 'flex-start',
                      bgcolor: alpha('#ffffff', 0.94),
                      borderRadius: 2.5,
                    },
                  },
                }}
              />
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25} justifyContent="flex-end">
                <Button
                  variant="contained"
                  loading={clarificationSubmitPending}
                  onClick={() => {
                    void onSubmitClarification?.();
                  }}
                  sx={{
                    minWidth: { md: 168 },
                    minHeight: 46,
                    borderRadius: 999,
                    background: `linear-gradient(135deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
                    color: '#fff',
                    boxShadow: 'none',
                  }}
                >
                  {clarification.submitLabel}
                </Button>
              </Stack>
            </Stack>
          </Paper>
        </>
      ) : null}

      {model.surface === 'planning' && plan ? (
        <>
          <Paper sx={panelSx}>
            <Stack spacing={1.6} sx={{ minWidth: 0 }}>
              <Typography
                variant="h4"
                sx={{
                  fontFamily: researchDisplayFont,
                  fontWeight: 800,
                  color: researchWorkbenchColors.text,
                }}
              >
                拟定研究计划
              </Typography>
              {plan.researchBrief ? (
                <Typography
                  variant="body2"
                  sx={{ ...longFormTextSx, color: researchWorkbenchColors.subtleText, lineHeight: 1.75 }}
                >
                  {plan.researchBrief}
                </Typography>
              ) : null}
              <Typography
                variant="body1"
                sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.8 }}
              >
                {plan.summary}
              </Typography>
              <Stack spacing={1.5}>
                {plan.steps.map((item) => (
                  <Paper
                    key={`${item.index}-${item.title}`}
                    sx={{
                      p: 2,
                      borderRadius: 3,
                      bgcolor: alpha('#ffffff', 0.84),
                      boxShadow: '0 12px 24px rgba(25, 28, 29, 0.04)',
                    }}
                  >
                    <Stack spacing={1.05} sx={{ minWidth: 0 }}>
                      <Stack direction="row" spacing={1.2} alignItems="center">
                        <Box
                          sx={{
                            width: 30,
                            height: 30,
                            borderRadius: '50%',
                            bgcolor: alpha(researchWorkbenchColors.primary, 0.12),
                            color: researchWorkbenchColors.primary,
                            fontWeight: 800,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            flexShrink: 0,
                          }}
                        >
                          {item.index}
                        </Box>
                        <Typography variant="subtitle1" fontWeight={700} sx={longFormTextSx}>
                          {item.title}
                        </Typography>
                      </Stack>
                      <Typography
                        variant="body2"
                        sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                      >
                        {item.description}
                      </Typography>
                      <Stack direction="row" spacing={0.9} flexWrap="wrap" useFlexGap>
                        {item.targetSources.map((target) => (
                          <Box
                            key={`${item.index}-${target}`}
                            sx={{
                              px: 1.1,
                              py: 0.55,
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
                  </Paper>
                ))}
              </Stack>
            </Stack>
          </Paper>

          <Paper sx={{ ...panelSx, p: { xs: 1.8, md: 1.95 } }}>
            <Stack spacing={1.25}>
              <Typography variant="subtitle1" fontWeight={800}>
                微调计划后再执行
              </Typography>
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
                      ...longFormTextSx,
                      color: researchWorkbenchColors.text,
                      alignItems: 'flex-start',
                      bgcolor: alpha('#ffffff', 0.94),
                      borderRadius: 2.5,
                    },
                  },
                }}
              />
              <Stack direction={{ xs: 'column', md: 'row' }} spacing={1.25} justifyContent="flex-end">
                <Button
                  variant="outlined"
                  loading={planUpdatePending}
                  onClick={() => {
                    void onUpdatePlan?.();
                  }}
                  sx={{
                    minHeight: 44,
                    borderRadius: 999,
                    borderColor: alpha(researchWorkbenchColors.text, 0.12),
                    color: researchWorkbenchColors.text,
                    backgroundColor: alpha('#ffffff', 0.72),
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
                  sx={{
                    minHeight: 44,
                    px: 2.75,
                    borderRadius: 999,
                    background: `linear-gradient(135deg, ${researchWorkbenchColors.primary} 0%, ${researchWorkbenchColors.primaryContainer} 100%)`,
                    color: '#fff',
                    boxShadow: 'none',
                  }}
                >
                  {plan.primaryActionLabel}
                </Button>
              </Stack>
            </Stack>
          </Paper>
        </>
      ) : null}
    </ResearchShell>
  );
}
