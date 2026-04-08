import type { ReactNode } from 'react';
import { Box, Chip, Stack, TextField, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type {
  ResearchClarificationRequest,
  ResearchPlanSnapshot,
  ResearchSessionStatus,
} from '../../types/researchEvents';
import {
  researchWorkbenchColors,
  researchWorkbenchEyebrowSx,
  researchWorkbenchInnerCardSx,
  researchWorkbenchOpenPanelSx,
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

const longFormTextSx = {
  minWidth: 0,
  whiteSpace: 'pre-wrap',
  wordBreak: 'break-word',
  overflowWrap: 'anywhere',
} as const;

const orderedListSx = {
  pl: 2.5,
  m: 0,
  minWidth: 0,
} as const;

const railSectionSx = {
  position: 'relative',
  minWidth: 0,
  pl: { xs: 4.5, md: 5.75 },
} as const;

const primaryPanelSx = {
  ...researchWorkbenchOpenPanelSx,
  px: { xs: 2.25, md: 2.75 },
  py: { xs: 2.25, md: 2.75 },
  minWidth: 0,
  background: `linear-gradient(180deg, ${alpha('#ffffff', 0.94)} 0%, ${alpha(
    researchWorkbenchColors.surfaceTint,
    0.9
  )} 100%)`,
} as const;

const secondaryPanelSx = {
  ...researchWorkbenchInnerCardSx,
  px: { xs: 2, md: 2.25 },
  py: { xs: 1.75, md: 2 },
  minWidth: 0,
  background: `linear-gradient(180deg, ${alpha('#ffffff', 0.94)} 0%, ${alpha(
    researchWorkbenchColors.surfaceMuted,
    0.92
  )} 100%)`,
} as const;

const chipSx = {
  borderColor: researchWorkbenchColors.border,
  color: researchWorkbenchColors.mutedText,
  backgroundColor: alpha('#ffffff', 0.92),
} as const;

function buildPlanningStatusLabel(status: ResearchSessionStatus): string {
  switch (status) {
    case 'clarifying':
      return '待补充信息';
    case 'plan_ready':
      return '规划已完成';
    case 'planning':
      return '正在规划';
    default:
      return '研究准备中';
  }
}

function formatSourceLabel(source: string): string {
  return source === 'paper' ? '论文' : source === 'web' ? '网页' : source;
}

function renderStageShell(params: {
  accent: string;
  eyebrow: string;
  title: string;
  tag: string;
  children: ReactNode;
}) {
  const { accent, eyebrow, title, tag, children } = params;

  return (
    <Box sx={railSectionSx}>
      <Box
        sx={{
          position: 'absolute',
          left: { xs: 9, md: 13 },
          top: 4,
          bottom: 18,
          width: 2,
          borderRadius: 999,
          background: alpha(accent, 0.18),
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          left: { xs: 0, md: 4 },
          top: 12,
          width: 20,
          height: 20,
          borderRadius: 999,
          background: accent,
          border: `4px solid ${researchWorkbenchColors.pageBackground}`,
          boxShadow: `0 0 0 6px ${alpha(accent, 0.12)}`,
        }}
      />

      <Stack spacing={2.25} sx={{ minWidth: 0 }}>
        <Stack
          direction={{ xs: 'column', sm: 'row' }}
          justifyContent="space-between"
          alignItems={{ xs: 'flex-start', sm: 'flex-start' }}
          spacing={1.25}
          sx={{ minWidth: 0 }}
        >
          <Stack spacing={0.5} sx={{ minWidth: 0 }}>
            <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
              {eyebrow}
            </Typography>
            <Typography variant="h5" sx={{ fontWeight: 700, color: researchWorkbenchColors.text }}>
              {title}
            </Typography>
          </Stack>
          <Chip
            size="small"
            label={tag}
            variant="outlined"
            sx={{
              alignSelf: 'flex-start',
              borderColor: alpha(accent, 0.22),
              color: accent,
              background: alpha(accent, 0.08),
              fontWeight: 700,
            }}
          />
        </Stack>

        {children}
      </Stack>
    </Box>
  );
}

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
    <Stack spacing={3.5} sx={{ minWidth: 0 }}>
      {trimmedQuestion ? (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: {
              xs: '1fr',
              xl: 'minmax(0, 1.5fr) minmax(280px, 0.72fr)',
            },
            gap: 2.25,
            minWidth: 0,
          }}
        >
          <Stack spacing={1} sx={{ minWidth: 0 }}>
            <Typography variant="overline" sx={researchWorkbenchEyebrowSx}>
              研究问题
            </Typography>
            <Typography
              variant="h4"
              sx={{
                ...longFormTextSx,
                fontWeight: 700,
                color: researchWorkbenchColors.text,
                lineHeight: 1.18,
              }}
            >
              {trimmedQuestion}
            </Typography>
          </Stack>

          <Box sx={{ ...primaryPanelSx, alignSelf: 'start' }}>
            <Stack spacing={0.75}>
              <Typography
                variant="caption"
                sx={{
                  color: researchWorkbenchColors.subtleText,
                  letterSpacing: '0.14em',
                  textTransform: 'uppercase',
                }}
              >
                当前阶段
              </Typography>
              <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                {buildPlanningStatusLabel(status)}
              </Typography>
              <Typography
                variant="body2"
                sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.7 }}
              >
                计划、证据和后续研究结果会沿右侧主区连续展开显示，不再被外层大容器挤压。
              </Typography>
            </Stack>
          </Box>
        </Box>
      ) : null}

      {status === 'clarifying' && clarificationRequest
        ? renderStageShell({
            accent: researchWorkbenchColors.primary,
            eyebrow: '待补充信息',
            title: '补齐研究边界',
            tag: '澄清阶段',
            children: (
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: {
                    xs: '1fr',
                    xl: 'minmax(0, 1.35fr) minmax(320px, 0.92fr)',
                  },
                  gap: 2,
                  minWidth: 0,
                }}
              >
                <Stack spacing={2} sx={{ minWidth: 0 }}>
                  <Box sx={primaryPanelSx}>
                    <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                      <Typography
                        variant="body2"
                        sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.72 }}
                      >
                        {clarificationRequest.summary}
                      </Typography>
                      <Stack component="ol" spacing={1.25} sx={orderedListSx}>
                        {clarificationRequest.questions.map((item) => (
                          <Typography component="li" key={item.id} variant="body2" sx={longFormTextSx}>
                            <Typography component="span" variant="body2" fontWeight={700} sx={longFormTextSx}>
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
                    </Stack>
                  </Box>
                </Stack>

                <Box sx={{ ...secondaryPanelSx, alignSelf: 'start' }}>
                  <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle1" fontWeight={700}>
                      回答补充问题
                    </Typography>
                    <TextField
                      fullWidth
                      multiline
                      minRows={5}
                      value={clarificationDraft}
                      onChange={(event) => onClarificationDraftChange?.(event.target.value)}
                      placeholder="补充研究范围、目标读者、输出形式或关键约束。"
                      slotProps={{
                        input: {
                          sx: {
                            color: researchWorkbenchColors.text,
                            alignItems: 'flex-start',
                            bgcolor: alpha('#ffffff', 0.92),
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
                        alignSelf: { xs: 'stretch', sm: 'flex-start' },
                        minHeight: 44,
                        px: 2.75,
                        borderRadius: 2.5,
                        bgcolor: researchWorkbenchColors.primary,
                        color: '#ffffff',
                        boxShadow: 'none',
                        '&:hover': {
                          bgcolor: researchWorkbenchColors.primaryHover,
                          boxShadow: 'none',
                        },
                      }}
                    >
                      提交补充信息
                    </Button>
                  </Stack>
                </Box>
              </Box>
            ),
          })
        : null}

      {status === 'plan_ready' && planSnapshot
        ? renderStageShell({
            accent: '#7c3aed',
            eyebrow: '研究计划',
            title: '规划阶段',
            tag: '规划已完成',
            children: (
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: {
                    xs: '1fr',
                    xl: 'minmax(0, 1.45fr) minmax(320px, 0.95fr)',
                  },
                  gap: 2,
                  minWidth: 0,
                }}
              >
                <Stack spacing={2} sx={{ minWidth: 0 }}>
                  <Box sx={primaryPanelSx}>
                    <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                      <Typography variant="subtitle1" fontWeight={700}>
                        研究摘要
                      </Typography>
                      <Typography
                        variant="body2"
                        sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText, lineHeight: 1.72 }}
                      >
                        {planSnapshot.summary}
                      </Typography>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ minWidth: 0 }}>
                        {planSnapshot.target_sources.map((item) => (
                          <Chip key={item} size="small" label={formatSourceLabel(item)} variant="outlined" sx={chipSx} />
                        ))}
                      </Stack>
                    </Stack>
                  </Box>

                  <Box sx={secondaryPanelSx}>
                    <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                      <Typography variant="subtitle1" fontWeight={700}>
                        子任务拆解
                      </Typography>
                      <Stack component="ol" spacing={1.25} sx={orderedListSx}>
                        {planSnapshot.subtasks.map((item) => (
                          <Typography component="li" key={item.title} variant="body2" sx={longFormTextSx}>
                            <Typography component="span" variant="body2" fontWeight={700} sx={longFormTextSx}>
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
                    </Stack>
                  </Box>
                </Stack>

                <Box sx={{ ...secondaryPanelSx, alignSelf: 'start' }}>
                  <Stack spacing={1.5} sx={{ minWidth: 0 }}>
                    <Typography variant="subtitle1" fontWeight={700}>
                      调整计划或开始执行
                    </Typography>
                    <Typography
                      variant="body2"
                      sx={{ ...longFormTextSx, color: researchWorkbenchColors.mutedText }}
                    >
                      如果有新的重点、边界或输出要求，可以先补充；没有的话可以直接开始研究。
                    </Typography>
                    <TextField
                      fullWidth
                      multiline
                      minRows={4}
                      value={planFeedbackDraft}
                      onChange={(event) => onPlanFeedbackDraftChange?.(event.target.value)}
                      placeholder="如需更新计划，可补充新的关注点、输出要求或边界。"
                      slotProps={{
                        input: {
                          sx: {
                            color: researchWorkbenchColors.text,
                            alignItems: 'flex-start',
                            bgcolor: alpha('#ffffff', 0.92),
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
                    <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.25}>
                      <Button
                        variant="outlined"
                        onClick={() => {
                          void onUpdatePlan?.();
                        }}
                        loading={planUpdatePending}
                        sx={{
                          minHeight: 44,
                          borderRadius: 2.5,
                          borderColor: researchWorkbenchColors.border,
                          color: researchWorkbenchColors.text,
                          backgroundColor: alpha('#ffffff', 0.72),
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
                          minHeight: 44,
                          px: 2.75,
                          borderRadius: 2.5,
                          bgcolor: researchWorkbenchColors.primary,
                          color: '#ffffff',
                          boxShadow: 'none',
                          '&:hover': {
                            bgcolor: researchWorkbenchColors.primaryHover,
                            boxShadow: 'none',
                          },
                        }}
                      >
                        开始
                      </Button>
                    </Stack>
                  </Stack>
                </Box>
              </Box>
            ),
          })
        : null}
    </Stack>
  );
}
