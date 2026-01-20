/**
 * Sparkle Loading 组件
 * Gemini 风格的加载动画，支持星光旋转渐变效果
 */
import { Box, Typography, keyframes } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';

// 品牌渐变色
const BRAND_GRADIENT = 'linear-gradient(135deg, #4285F4, #9B72CB, #D96570)';

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

// 星光旋转渐变动画
const sparkleRotate = keyframes`
  0% {
    background-position: 0% 50%;
  }
  50% {
    background-position: 100% 50%;
  }
  100% {
    background-position: 0% 50%;
  }
`;

// 星形图标脉冲旋转动画
const starPulse = keyframes`
  0%, 100% {
    transform: scale(1) rotate(0deg);
    filter: brightness(1);
  }
  25% {
    transform: scale(1.1) rotate(90deg);
    filter: brightness(1.3);
  }
  50% {
    transform: scale(1) rotate(180deg);
    filter: brightness(1);
  }
  75% {
    transform: scale(1.1) rotate(270deg);
    filter: brightness(1.3);
  }
`;

// 呼吸文字动画
const breathe = keyframes`
  0%, 100% {
    opacity: 0.6;
  }
  50% {
    opacity: 1;
  }
`;

interface SparkleLoadingProps {
  variant?: 'shimmer' | 'dots' | 'pulse' | 'sparkle';
  width?: number | string;
  height?: number;
}

export function SparkleLoading({ variant = 'shimmer', width = '100%', height = 20 }: SparkleLoadingProps) {
  // Gemini Sparkle 星光变体（默认用于思考状态）
  if (variant === 'sparkle') {
    return (
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          py: 1,
        }}
        role="status"
        aria-label="正在思考"
        aria-live="polite"
      >
        {/* 星光图标 */}
        <Box
          sx={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: BRAND_GRADIENT,
            backgroundSize: '200% 200%',
            animation: `${sparkleRotate} 3s ease infinite`,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            '@media (prefers-reduced-motion: reduce)': {
              animation: 'none',
            },
          }}
        >
          <AutoAwesomeIcon
            sx={{
              fontSize: 16,
              color: 'white',
              animation: `${starPulse} 2.4s ease-in-out infinite`,
              '@media (prefers-reduced-motion: reduce)': {
                animation: 'none',
              },
            }}
          />
        </Box>

        {/* 呼吸文字 */}
        <Typography
          variant="body2"
          sx={{
            color: 'text.secondary',
            fontSize: 14,
            animation: `${breathe} 2s ease-in-out infinite`,
            '@media (prefers-reduced-motion: reduce)': {
              animation: 'none',
              opacity: 0.8,
            },
          }}
        >
          正在思考...
        </Typography>
      </Box>
    );
  }

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
        animation: `${shimmer} 1.5s ease-in-out infinite, ${pulse} 2.4s ease-in-out infinite`,
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
