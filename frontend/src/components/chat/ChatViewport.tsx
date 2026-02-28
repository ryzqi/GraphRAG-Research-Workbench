import type { ReactNode, RefObject } from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Box, useMediaQuery, useTheme } from '@mui/material';

const DEFAULT_BOTTOM_INSET = 140;
const COMPOSER_INSET_OFFSET = 16;

interface ChatViewportLayout {
  composerRef: RefObject<HTMLDivElement | null>;
  bottomInset: number;
}

interface ChatViewportProps {
  header?: ReactNode;
  renderMessages: (layout: ChatViewportLayout) => ReactNode;
  renderComposer: (layout: ChatViewportLayout) => ReactNode;
  lockPageScrollOnDesktop?: boolean;
  minBottomInset?: number;
  sx?: Record<string, unknown>;
  messagesSx?: Record<string, unknown>;
}

export function ChatViewport({
  header,
  renderMessages,
  renderComposer,
  lockPageScrollOnDesktop = true,
  minBottomInset = DEFAULT_BOTTOM_INSET,
  sx,
  messagesSx,
}: ChatViewportProps) {
  const theme = useTheme();
  const isTabletOrDown = useMediaQuery(theme.breakpoints.down('md'));
  const composerRef = useRef<HTMLDivElement | null>(null);
  const [bottomInset, setBottomInset] = useState(minBottomInset);

  const layout = useMemo(
    () => ({
      composerRef,
      bottomInset,
    }),
    [bottomInset]
  );
  useEffect(() => {
    const element = composerRef.current;
    if (!element) {
      return;
    }

    const updateInset = () => {
      const next = Math.max(
        minBottomInset,
        Math.ceil(element.getBoundingClientRect().height) + COMPOSER_INSET_OFFSET
      );
      setBottomInset(next);
    };

    updateInset();
    if (typeof ResizeObserver === 'undefined') {
      return;
    }

    const observer = new ResizeObserver(updateInset);
    observer.observe(element);
    return () => observer.disconnect();
  }, [minBottomInset]);

  useEffect(() => {
    if (!lockPageScrollOnDesktop || isTabletOrDown || typeof document === 'undefined') {
      return;
    }

    const { documentElement, body } = document;
    const prevHtmlOverflow = documentElement.style.overflow;
    const prevBodyOverflow = body.style.overflow;
    const prevBodyOverscrollY = body.style.overscrollBehaviorY;

    documentElement.style.overflow = 'hidden';
    body.style.overflow = 'hidden';
    body.style.overscrollBehaviorY = 'none';

    return () => {
      documentElement.style.overflow = prevHtmlOverflow;
      body.style.overflow = prevBodyOverflow;
      body.style.overscrollBehaviorY = prevBodyOverscrollY;
    };
  }, [isTabletOrDown, lockPageScrollOnDesktop]);

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        overflow: 'hidden',
        ...sx,
      }}
    >
      {header}

      <Box
        sx={{
          flex: 1,
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          ...messagesSx,
        }}
      >
        {renderMessages(layout)}
      </Box>

      {renderComposer(layout)}
    </Box>
  );
}
