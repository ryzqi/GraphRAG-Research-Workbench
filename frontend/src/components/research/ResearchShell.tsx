import type { ReactNode } from 'react';
import { Box, Chip, Stack, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';

import type { ResearchHeroModel, ResearchRailStepModel } from '../../services/researchWorkbench';
import {
  researchBodyFont,
  researchDisplayFont,
  researchWorkbenchColors,
  researchWorkbenchInnerCardSx,
  researchWorkbenchOpenPanelSx,
} from './researchWorkbenchStyles';

function getCurrentStep(railSteps: ResearchRailStepModel[]) {
  const currentIndex = railSteps.findIndex((step) => step.state === 'current');
  if (currentIndex >= 0) {
    return { index: currentIndex, step: railSteps[currentIndex] };
  }

  let fallbackIndex = 0;
  for (let index = railSteps.length - 1; index >= 0; index -= 1) {
    if (railSteps[index]?.state === 'complete') {
      fallbackIndex = index;
      break;
    }
  }

  return { index: fallbackIndex, step: railSteps[fallbackIndex] ?? null };
}

function getDisplayStageLabel(step: ResearchRailStepModel | null): string {
  if (!step) {
    return '研究流程';
  }

  switch (step.key) {
    case 'clarify':
      return '需求澄清';
    case 'run':
      return '进度跟踪';
    case 'report':
      return '研究报告';
    default:
      return step.label;
  }
}

export function ResearchShell({
  hero,
  railSteps,
  actions = null,
  aside = null,
  children,
}: {
  hero: ResearchHeroModel;
  railSteps: ResearchRailStepModel[];
  actions?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
}) {
  const { index: currentIndex, step: currentStep } = getCurrentStep(railSteps);

  return (
    <Stack spacing={3.5} sx={{ width: '100%', minWidth: 0 }}>
      <Box
        sx={{
          ...researchWorkbenchOpenPanelSx,
          position: 'relative',
          overflow: 'hidden',
          p: { xs: 2.5, md: 3.25 },
          borderRadius: 4,
          background: `linear-gradient(145deg, ${alpha('#ffffff', 0.98)} 0%, ${alpha(
            researchWorkbenchColors.surfaceTint,
            0.92
          )} 100%)`,
        }}
      >
        <Box
          sx={{
            position: 'absolute',
            top: -88,
            right: -54,
            width: 220,
            height: 220,
            borderRadius: '50%',
            background: `radial-gradient(circle, ${alpha(
              researchWorkbenchColors.primaryContainer,
              0.16
            )} 0%, rgba(39, 113, 223, 0) 72%)`,
            pointerEvents: 'none',
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            bottom: -72,
            left: -40,
            width: 180,
            height: 180,
            borderRadius: '50%',
            background: `radial-gradient(circle, ${alpha(
              researchWorkbenchColors.secondary,
              0.14
            )} 0%, rgba(0, 110, 44, 0) 72%)`,
            pointerEvents: 'none',
          }}
        />
        <Stack spacing={2.5} sx={{ position: 'relative', zIndex: 1, minWidth: 0 }}>
          <Stack
            direction={{ xs: 'column', lg: 'row' }}
            justifyContent="space-between"
            alignItems={{ xs: 'flex-start', lg: 'flex-start' }}
            spacing={2}
            sx={{ minWidth: 0 }}
          >
            <Stack spacing={1.15} sx={{ minWidth: 0, maxWidth: 920 }}>
              <Stack direction="row" spacing={1} flexWrap="wrap" alignItems="center">
                <Typography
                  variant="caption"
                  sx={{
                    px: 1.2,
                    py: 0.55,
                    borderRadius: 999,
                    bgcolor: alpha(researchWorkbenchColors.text, 0.06),
                    color: researchWorkbenchColors.mutedText,
                    fontWeight: 700,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    fontFamily: researchBodyFont,
                  }}
                >
                  阶段 {String(currentIndex + 1).padStart(2, '0')}
                </Typography>
                {currentStep ? (
                  <Chip
                    size="small"
                    label={getDisplayStageLabel(currentStep)}
                    sx={{
                      bgcolor: alpha(researchWorkbenchColors.primary, 0.1),
                      color: researchWorkbenchColors.primary,
                      fontWeight: 700,
                    }}
                  />
                ) : null}
                <Typography
                  variant="caption"
                  sx={{
                    color: researchWorkbenchColors.subtleText,
                    letterSpacing: '0.14em',
                    textTransform: 'uppercase',
                    fontWeight: 700,
                    fontFamily: researchBodyFont,
                  }}
                >
                  {hero.eyebrow}
                </Typography>
              </Stack>
              <Typography
                variant="h2"
                sx={{
                  fontFamily: researchDisplayFont,
                  fontWeight: 800,
                  lineHeight: 1.04,
                  letterSpacing: '-0.04em',
                  color: researchWorkbenchColors.text,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  overflowWrap: 'anywhere',
                }}
              >
                {hero.title}
              </Typography>
              <Typography
                variant="body1"
                sx={{
                  maxWidth: 820,
                  color: researchWorkbenchColors.mutedText,
                  lineHeight: 1.75,
                  fontFamily: researchBodyFont,
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                  overflowWrap: 'anywhere',
                }}
              >
                {hero.subtitle}
              </Typography>
            </Stack>
            {actions}
          </Stack>

          {railSteps.length > 0 ? (
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
              {railSteps.map((step, index) => {
                const tone =
                  step.state === 'current'
                    ? {
                        background: alpha(researchWorkbenchColors.primary, 0.1),
                        color: researchWorkbenchColors.primary,
                      }
                    : step.state === 'complete'
                      ? {
                          background: alpha(researchWorkbenchColors.secondary, 0.12),
                          color: researchWorkbenchColors.secondary,
                        }
                      : {
                          background: alpha(researchWorkbenchColors.text, 0.05),
                          color: researchWorkbenchColors.subtleText,
                        };

                return (
                  <Box
                    key={step.key}
                    sx={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 1,
                      px: 1.25,
                      py: 0.85,
                      borderRadius: 999,
                      bgcolor: tone.background,
                      color: tone.color,
                    }}
                  >
                    <Box
                      sx={{
                        width: 24,
                        height: 24,
                        borderRadius: '50%',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        bgcolor: alpha('#ffffff', 0.72),
                        fontWeight: 800,
                        fontSize: '0.75rem',
                      }}
                    >
                      {index + 1}
                    </Box>
                    <Typography
                      variant="body2"
                      sx={{ fontWeight: 700, fontFamily: researchBodyFont }}
                    >
                      {step.label}
                    </Typography>
                  </Box>
                );
              })}
            </Stack>
          ) : null}
        </Stack>
      </Box>

      {aside ? (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', xl: 'minmax(0, 1.7fr) minmax(300px, 0.9fr)' },
            gap: 2.5,
            minWidth: 0,
            alignItems: 'start',
          }}
        >
          <Stack spacing={2.5} sx={{ minWidth: 0 }}>
            {children}
          </Stack>
          <Stack spacing={2} sx={{ minWidth: 0, position: { xl: 'sticky' }, top: { xl: 24 } }}>
            {aside}
          </Stack>
        </Box>
      ) : (
        <Stack spacing={2.5} sx={{ minWidth: 0 }}>
          {children}
        </Stack>
      )}
    </Stack>
  );
}
