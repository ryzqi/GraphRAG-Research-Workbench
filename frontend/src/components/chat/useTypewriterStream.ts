import { useEffect, useRef, useState } from 'react';
import { usePrefersReducedMotion } from '../../hooks/usePrefersReducedMotion';

interface TypewriterOptions {
  enabled?: boolean;
  intervalMs?: number;
  maxCharsPerTick?: number;
}

const DEFAULT_INTERVAL = 50;
const DEFAULT_MAX_CHARS = 6;

export function useTypewriterStream(
  targetText: string,
  isStreaming: boolean,
  options: TypewriterOptions = {}
) {
  const {
    enabled = true,
    intervalMs = DEFAULT_INTERVAL,
    maxCharsPerTick = DEFAULT_MAX_CHARS,
  } = options;
  const prefersReducedMotion = usePrefersReducedMotion();
  const shouldAnimate = enabled && isStreaming && !prefersReducedMotion;

  const [renderText, setRenderText] = useState(targetText);
  const pendingRef = useRef('');
  const targetRef = useRef(targetText);

  useEffect(() => {
    if (!shouldAnimate) {
      pendingRef.current = '';
      targetRef.current = targetText;
      setRenderText(targetText);
      return;
    }

    const previousTarget = targetRef.current;
    if (targetText.startsWith(previousTarget)) {
      const delta = targetText.slice(previousTarget.length);
      if (delta) {
        pendingRef.current += delta;
      }
    } else {
      // 发生重写/回退时直接同步，避免错位
      pendingRef.current = '';
      setRenderText(targetText);
    }
    targetRef.current = targetText;
  }, [shouldAnimate, targetText]);

  useEffect(() => {
    if (!shouldAnimate) return;

    let frameId = 0;
    let lastFlushAt = performance.now();

    const tick = (now: number) => {
      if (now - lastFlushAt >= intervalMs) {
        lastFlushAt = now;
        const pending = pendingRef.current;
        if (pending) {
          const backlog = pending.length;
          let step = 1;
          if (backlog > 240) step = 6;
          else if (backlog > 120) step = 4;
          else if (backlog > 60) step = 3;
          else if (backlog > 20) step = 2;

          step = Math.min(step, maxCharsPerTick);
          const chunk = pending.slice(0, step);
          pendingRef.current = pending.slice(step);
          setRenderText((prev) => prev + chunk);
        }
      }

      frameId = window.requestAnimationFrame(tick);
    };

    frameId = window.requestAnimationFrame(tick);
    return () => window.cancelAnimationFrame(frameId);
  }, [intervalMs, maxCharsPerTick, shouldAnimate]);

  const isTyping = isStreaming && renderText.length < targetText.length;
  return { text: renderText, isTyping };
}
