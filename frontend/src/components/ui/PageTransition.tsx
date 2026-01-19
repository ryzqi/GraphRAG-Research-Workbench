/**
 * 页面转场动画组件
 * 基于 MD3 Shared Axis 模式，实现淡入 + 上浮效果
 */
import { type ReactNode } from 'react';
import { Fade, Box, type SxProps, type Theme } from '@mui/material';
import { md3Easing, md3Duration } from '../../utils/motion';

interface PageTransitionProps {
  children: ReactNode;
  /** 是否显示 */
  in?: boolean;
  /** 自定义样式 */
  sx?: SxProps<Theme>;
}

export function PageTransition({
  children,
  in: inProp = true,
  sx,
}: PageTransitionProps) {
  return (
    <Fade
      in={inProp}
      timeout={md3Duration.medium2}
      style={{
        transitionTimingFunction: md3Easing.emphasizedDecelerate,
      }}
    >
      <Box
        sx={{
          animation: inProp
            ? `pageEnter ${md3Duration.medium2}ms ${md3Easing.emphasizedDecelerate}`
            : undefined,
          '@keyframes pageEnter': {
            from: {
              opacity: 0,
              transform: 'translateY(12px)',
            },
            to: {
              opacity: 1,
              transform: 'translateY(0)',
            },
          },
          ...sx,
        }}
      >
        {children}
      </Box>
    </Fade>
  );
}
