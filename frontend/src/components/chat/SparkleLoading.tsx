/**
 * Sparkle Loading 组件
 * Gemini 风格的加载动画，使用渐变 Shimmer 效果
 */
import { Box, keyframes } from '@mui/material';

const shimmer = keyframes`
  0% {
    background-position: -200% 0;
  }
  100% {
    background-position: 200% 0;
  }
`;

const pulse = keyframes`
  0%, 100% {
    opacity: 0.4;
  }
  50% {
    opacity: 1;
  }
`;

interface SparkleLoadingProps {
  variant?: 'shimmer' | 'dots' | 'pulse';
  width?: number | string;
  height?: number;
}

export function SparkleLoading({ variant = 'shimmer', width = '100%', height = 20 }: SparkleLoadingProps) {
  if (variant === 'dots') {
    return (
      <Box
        sx={{
          display: 'flex',
          gap: 0.5,
          alignItems: 'center',
          py: 1,
        }}
        role="status"
        aria-label="加载中"
        aria-live="polite"
      >
        {[0, 1, 2].map((i) => (
          <Box
            key={i}
            sx={{
              width: 8,
              height: 8,
              borderRadius: '50%',
              bgcolor: 'primary.main',
              animation: `${pulse} 1.4s ease-in-out infinite`,
              animationDelay: `${i * 0.2}s`,
            }}
          />
        ))}
      </Box>
    );
  }

  if (variant === 'pulse') {
    return (
      <Box
        sx={{
          width,
          height,
          borderRadius: 2,
          bgcolor: 'action.hover',
          animation: `${pulse} 1.5s ease-in-out infinite`,
        }}
        role="status"
        aria-label="加载中"
        aria-live="polite"
      />
    );
  }

  // shimmer 变体（默认）
  return (
    <Box
      sx={{
        width,
        height,
        borderRadius: 2,
        background: (theme) =>
          theme.palette.mode === 'light'
            ? 'linear-gradient(90deg, #e8eaed 25%, #f8f9fa 50%, #e8eaed 75%)'
            : 'linear-gradient(90deg, #3c4043 25%, #5f6368 50%, #3c4043 75%)',
        backgroundSize: '200% 100%',
        animation: `${shimmer} 1.5s ease-in-out infinite`,
        '@media (prefers-reduced-motion: reduce)': {
          animation: 'none',
          opacity: 0.7,
        },
      }}
      role="status"
      aria-label="加载中"
      aria-live="polite"
    />
  );
}
