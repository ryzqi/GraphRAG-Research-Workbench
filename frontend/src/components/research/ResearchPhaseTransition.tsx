import type { CSSProperties, ReactNode } from 'react';

import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion';
import { md3Motion } from '../../theme/md3Theme';

function buildPhaseTransitionStyle({
  reducedMotion,
  index,
  emphasis,
  animationName,
}: {
  reducedMotion: boolean;
  index: number;
  emphasis: boolean;
  animationName: string;
}): CSSProperties {
  if (reducedMotion) {
    return {
      opacity: 1,
      transform: 'none',
      transition: 'none',
    };
  }

  const delayMs = Math.min(index * 40, 120);
  const durationMs = emphasis ? md3Motion.duration.medium3 : md3Motion.duration.medium2;
  const easing = emphasis ? md3Motion.easing.emphasizedDecelerate : md3Motion.easing.standard;
  const transition = [
    `opacity ${durationMs}ms ${easing} ${delayMs}ms`,
    `transform ${durationMs}ms ${easing} ${delayMs}ms`,
  ].join(', ');

  return {
    opacity: 1,
    transform: 'translateY(0)',
    transition,
    animation: `${animationName} ${durationMs}ms ${easing} ${delayMs}ms both`,
    willChange: 'opacity, transform',
  };
}

export function ResearchPhaseTransition({
  children,
  phaseKey,
  index,
  emphasis = false,
  forceReducedMotion,
}: {
  children: ReactNode;
  phaseKey: 'current-step' | 'findings' | 'final-report';
  index: number;
  emphasis?: boolean;
  forceReducedMotion?: boolean;
}) {
  const prefersReducedMotion = usePrefersReducedMotion();
  const reducedMotion = forceReducedMotion ?? prefersReducedMotion;
  const animationName = `researchPhaseEnter-${phaseKey}`;
  const translateFrom = emphasis ? 16 : 12;

  return (
    <>
      {reducedMotion ? null : (
        <style>{`
          @keyframes ${animationName} {
            from {
              opacity: 0;
              transform: translateY(${translateFrom}px);
            }
            to {
              opacity: 1;
              transform: translateY(0);
            }
          }
        `}</style>
      )}
      <div
        data-research-phase={phaseKey}
        data-reduced-motion={reducedMotion ? 'true' : 'false'}
        style={buildPhaseTransitionStyle({
          reducedMotion,
          index,
          emphasis,
          animationName,
        })}
      >
        {children}
      </div>
    </>
  );
}
