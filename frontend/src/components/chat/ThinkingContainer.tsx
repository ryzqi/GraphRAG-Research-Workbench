/**
 * 思考容器组件
 * 模仿 Claude/Gemini 风格：流式时淡化显示带脉冲动画，完成后自动收起为可展开的摘要
 */
import { useState, useEffect, useRef } from 'react';
import { Box, Typography, Collapse, keyframes } from '@mui/material';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';

// 品牌渐变色
const BRAND_GRADIENT = 'linear-gradient(135deg, #4285F4, #9B72CB, #D96570)';

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

// 星形图标脉冲动画
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

// 呼吸动画
const breathe = keyframes`
  0%, 100% {
    opacity: 0.5;
  }
  50% {
    opacity: 0.8;
  }
`;

interface ThinkingContainerProps {
  /** 思考内容 */
  content: string;
  /** 是否正在流式输出 */
  isStreaming: boolean;
  /** 是否处于思考阶段（用于控制星光图标显示） */
  isThinking?: boolean;
  /** 初始展开状态 */
  defaultExpanded?: boolean;
  /** 思考开始时间戳 */
  startTime?: number;
}

export function ThinkingContainer({
  content,
  isStreaming,
  isThinking,
  defaultExpanded = false,
  startTime,
}: ThinkingContainerProps) {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const [thinkDuration, setThinkDuration] = useState(0);
  const [isTransitioning, setIsTransitioning] = useState(false);
  const prevStreamingRef = useRef(isStreaming);
  const showThinkingIcon = isThinking ?? isStreaming;
  const contentIndent = showThinkingIcon ? 4.5 : 0;

  // 计算思考时长
  useEffect(() => {
    if (!startTime) return;

    if (isStreaming) {
      // 流式时，每秒更新时长
      const interval = setInterval(() => {
        setThinkDuration(Math.floor((Date.now() - startTime) / 1000));
      }, 1000);
      return () => clearInterval(interval);
    }

    // 完成时，固定时长
    setThinkDuration(Math.floor((Date.now() - startTime) / 1000));
  }, [startTime, isStreaming]);

  // 检测流式结束，触发过渡动画并自动收起
  useEffect(() => {
    if (prevStreamingRef.current && !isStreaming) {
      setIsTransitioning(true);
      // 等待淡出动画完成后收起
      const timer = setTimeout(() => {
        setIsTransitioning(false);
        setIsExpanded(false);
      }, 300);
      return () => clearTimeout(timer);
    }
    prevStreamingRef.current = isStreaming;
  }, [isStreaming]);

  // 流式阶段始终展开
  useEffect(() => {
    if (isStreaming) {
      setIsExpanded(true);
    }
  }, [isStreaming]);

  const handleToggle = () => {
    if (!isStreaming) {
      setIsExpanded(!isExpanded);
    }
  };

  const formatDuration = (seconds: number) => {
    if (seconds < 60) {
      return `${seconds} 秒`;
    }
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return remainingSeconds > 0 ? `${minutes} 分 ${remainingSeconds} 秒` : `${minutes} 分`;
  };

  return (
    <Box sx={{ mb: 1.5 }}>
      {/* 标题栏 */}
      <Box
        onClick={handleToggle}
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          py: 0.75,
          cursor: isStreaming ? 'default' : 'pointer',
          userSelect: 'none',
          borderRadius: 2,
          transition: 'background-color 0.2s',
          '&:hover': {
            bgcolor: isStreaming ? 'transparent' : 'action.hover',
          },
        }}
        role={isStreaming ? 'status' : 'button'}
        aria-expanded={isExpanded}
        aria-label={isStreaming ? '正在思考' : `已思考 ${formatDuration(thinkDuration)}`}
      >
        {/* 星光图标（仅思考中显示） */}
        {showThinkingIcon && (
          <Box
            sx={{
              width: 24,
              height: 24,
              borderRadius: '50%',
              background: BRAND_GRADIENT,
              backgroundSize: '200% 200%',
              animation: isStreaming ? `${sparkleRotate} 3s ease infinite` : 'none',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              opacity: isStreaming ? 1 : 0.7,
              transition: 'opacity 0.3s',
              '@media (prefers-reduced-motion: reduce)': {
                animation: 'none',
              },
            }}
          >
            <AutoAwesomeIcon
              sx={{
                fontSize: 14,
                color: 'white',
                animation: isStreaming ? `${starPulse} 2.4s ease-in-out infinite` : 'none',
                '@media (prefers-reduced-motion: reduce)': {
                  animation: 'none',
                },
              }}
            />
          </Box>
        )}

        {/* 标题文字 */}
        <Typography
          variant="body2"
          sx={{
            color: 'text.secondary',
            fontSize: 13,
            fontWeight: 500,
            animation: isStreaming ? `${breathe} 2s ease-in-out infinite` : 'none',
            '@media (prefers-reduced-motion: reduce)': {
              animation: 'none',
              opacity: 0.8,
            },
          }}
        >
          {isStreaming ? '正在思考...' : `已思考 ${formatDuration(thinkDuration)}`}
        </Typography>

        {/* 展开/收起箭头（仅完成后显示） */}
        {!isStreaming && (
          <Box sx={{ display: 'flex', opacity: 1, transition: 'opacity 0.2s' }}>
            <ExpandMoreIcon
              sx={{
                fontSize: 18,
                color: 'text.secondary',
                transform: isExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s ease',
              }}
            />
          </Box>
        )}
      </Box>

      {/* 思考内容 */}
      <Collapse in={isExpanded} timeout={200}>
        <Box
          sx={{
            opacity: isStreaming ? 1 : isTransitioning ? 0 : 1,
            transition: 'opacity 0.3s ease',
          }}
        >
          <Box
            sx={{
              mt: 0.5,
              ml: contentIndent,
              pl: 2,
              borderLeft: 2,
              borderColor: 'divider',
            }}
          >
            <Typography
              variant="body2"
              sx={{
                fontSize: 13,
                whiteSpace: 'pre-wrap',
                color: 'text.secondary',
                opacity: isStreaming ? 0.7 : 0.85,
                animation: isStreaming ? `${breathe} 2.5s ease-in-out infinite` : 'none',
                lineHeight: 1.6,
                '@media (prefers-reduced-motion: reduce)': {
                  animation: 'none',
                  opacity: 0.7,
                },
              }}
            >
              {content}
            </Typography>
          </Box>
        </Box>
      </Collapse>
    </Box>
  );
}
