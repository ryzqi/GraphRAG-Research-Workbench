/**
 * 列表交错动画组件
 * 实现列表项依次淡入上浮效果
 */
import { type ReactNode, Children, useEffect, useState } from 'react';
import { Box, type SxProps, type Theme } from '@mui/material';
import { md3Easing, md3Duration, staggerDelay } from '../../utils/motion';

interface StaggerListProps {
  children: ReactNode;
  /** 每项之间的延迟（毫秒） */
  staggerMs?: number;
  /** 最大延迟上限（毫秒） */
  maxDelayMs?: number;
  /** 容器样式 */
  sx?: SxProps<Theme>;
  /** 是否启用动画 */
  animate?: boolean;
}

export function StaggerList({
  children,
  staggerMs = 50,
  maxDelayMs = 400,
  sx,
  animate = true,
}: StaggerListProps) {
  const [isVisible, setIsVisible] = useState(!animate);

  useEffect(() => {
    if (animate) {
      // 延迟触发以确保初始渲染完成
      const timer = requestAnimationFrame(() => setIsVisible(true));
      return () => cancelAnimationFrame(timer);
    }
  }, [animate]);

  const items = Children.toArray(children);

  return (
    <Box sx={sx}>
      {items.map((child, index) => {
        const delay = staggerDelay(index, staggerMs, maxDelayMs);

        return (
          <Box
            key={index}
            sx={{
              opacity: isVisible ? 1 : 0,
              transform: isVisible ? 'translateY(0)' : 'translateY(16px)',
              transition: `opacity ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate} ${delay}ms, transform ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate} ${delay}ms`,
            }}
          >
            {child}
          </Box>
        );
      })}
    </Box>
  );
}

// ============================================================================
// Grid 版本 - 用于卡片网格布局
// ============================================================================

interface StaggerGridProps {
  children: ReactNode;
  /** 每项之间的延迟（毫秒） */
  staggerMs?: number;
  /** 最大延迟上限（毫秒） */
  maxDelayMs?: number;
  /** Grid 列数配置 */
  columns?: {
    xs?: number;
    sm?: number;
    md?: number;
    lg?: number;
  };
  /** 间距 */
  spacing?: number;
  /** 是否启用动画 */
  animate?: boolean;
}

export function StaggerGrid({
  children,
  staggerMs = 50,
  maxDelayMs = 400,
  columns = { xs: 1, sm: 2, md: 3 },
  spacing = 3,
  animate = true,
}: StaggerGridProps) {
  const [isVisible, setIsVisible] = useState(!animate);

  useEffect(() => {
    if (animate) {
      const timer = requestAnimationFrame(() => setIsVisible(true));
      return () => cancelAnimationFrame(timer);
    }
  }, [animate]);

  const items = Children.toArray(children);

  return (
    <Box
      sx={{
        display: 'grid',
        gridTemplateColumns: {
          xs: `repeat(${columns.xs ?? 1}, 1fr)`,
          sm: `repeat(${columns.sm ?? 2}, 1fr)`,
          md: `repeat(${columns.md ?? 3}, 1fr)`,
          lg: `repeat(${columns.lg ?? columns.md ?? 3}, 1fr)`,
        },
        gap: spacing,
      }}
    >
      {items.map((child, index) => {
        const delay = staggerDelay(index, staggerMs, maxDelayMs);

        return (
          <Box
            key={index}
            sx={{
              opacity: isVisible ? 1 : 0,
              transform: isVisible ? 'translateY(0)' : 'translateY(16px)',
              transition: `opacity ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate} ${delay}ms, transform ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate} ${delay}ms`,
            }}
          >
            {child}
          </Box>
        );
      })}
    </Box>
  );
}
