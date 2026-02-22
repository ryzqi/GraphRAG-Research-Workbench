/**
 * 消息项组件
 * Gemini 风格：左对齐布局，实心圆点光标，透气设计
 */
import { Suspense, lazy, memo, useState, useCallback, useEffect, useRef } from 'react';
import { Box, IconButton, Paper, Stack, Tooltip, Typography, Chip, TextField, keyframes } from '@mui/material';
import { alpha } from '@mui/material/styles';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import PersonIcon from '@mui/icons-material/Person';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import { useTypewriterStream } from './useTypewriterStream';
import { ThinkingContainer } from './ThinkingContainer';
import { Button } from '../ui/Button';
import type { ToolApprovalRequest } from '../../services/chats';

// 实心圆点脉冲动画
const cursorPulse = keyframes`
  0%, 100% {
    opacity: 1;
    transform: scale(1);
  }
  50% {
    opacity: 0.6;
    transform: scale(0.9);
  }
`;

// 光标淡出动画
const cursorFadeOut = keyframes`
  from {
    opacity: 1;
  }
  to {
    opacity: 0;
  }
`;

// 品牌渐变色（蓝紫粉）
const BRAND_GRADIENT = 'linear-gradient(135deg, #4285F4, #9B72CB, #D96570)';
const AVATAR_SIZE = 36;

const MarkdownContent = lazy(async () => ({
  default: (await import('./MarkdownContent')).MarkdownContent,
}));

interface MessageItemProps {
  role: 'user' | 'assistant';
  content: string;
  think?: string;
  isStreaming?: boolean;
  timestamp?: string;
  showActions?: boolean;
  /** 思考开始时间戳 */
  thinkStartTime?: number;
  onCitationClick?: (citationId: string) => void;
}

function MessageItemComponent({
  role,
  content,
  think,
  isStreaming = false,
  showActions = true,
  thinkStartTime,
  onCitationClick,
}: MessageItemProps) {
  const [copied, setCopied] = useState(false);
  const [cursorFading, setCursorFading] = useState(false);
  const prevStreamingRef = useRef(isStreaming);
  const isUser = role === 'user';

  const { text: streamedContent } = useTypewriterStream(content, !isUser && isStreaming, {
    intervalMs: 50,
  });
  const displayContent = isUser ? content : streamedContent;
  const showCursor = !isUser && (isStreaming || cursorFading) && displayContent.length > 0;
  const hasAnswerContent = !isUser && content.trim().length > 0;
  const isThinking = !isUser && isStreaming && !hasAnswerContent;

  // 检测流式结束，触发淡出动画
  useEffect(() => {
    if (prevStreamingRef.current && !isStreaming && !isUser) {
      setCursorFading(true);
      const timer = setTimeout(() => setCursorFading(false), 300);
      return () => clearTimeout(timer);
    }
    prevStreamingRef.current = isStreaming;
  }, [isStreaming, isUser]);

  // Gemini 风格：实心圆点脉冲光标
  const cursorSx = showCursor
    ? {
        '& > :last-child::after': {
          content: '"●"',
          display: 'inline',
          color: '#4285F4',
          marginLeft: '2px',
          fontSize: '0.6em',
          verticalAlign: 'middle',
          animation: cursorFading
            ? `${cursorFadeOut} 0.3s ease-out forwards`
            : `${cursorPulse} 1.2s ease-in-out infinite`,
        },
        '@media (prefers-reduced-motion: reduce)': {
          '& > :last-child::after': {
            animation: 'none',
          },
        },
      }
    : undefined;

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // 静默失败
    }
  }, [content]);

  return (
    <Box
      sx={{
        animation: 'messageEnter 200ms cubic-bezier(0.2, 0, 0, 1)',
        '@keyframes messageEnter': {
          from: {
            opacity: 0,
            transform: 'translateY(10px)',
          },
          to: {
            opacity: 1,
            transform: 'translateY(0)',
          },
        },
        '@media (prefers-reduced-motion: reduce)': {
          animation: 'none',
        },
      }}
    >
      <Box
        sx={{
          display: 'flex',
          gap: 2,
          maxWidth: '100%',
          flexDirection: isUser ? 'row-reverse' : 'row', // 用户消息右对齐，助手消息左对齐
          alignItems: 'flex-start',
        }}
      >
        {/* 头像 */}
        <Box
          sx={{
            width: AVATAR_SIZE,
            height: AVATAR_SIZE,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            position: 'relative',
            overflow: 'hidden',
            bgcolor: isUser
              ? (theme) =>
                  alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.12 : 0.22)
              : 'transparent',
            border: 1,
            borderColor: isUser
              ? (theme) =>
                  alpha(theme.palette.primary.main, theme.palette.mode === 'light' ? 0.18 : 0.28)
              : (theme) =>
                  alpha(theme.palette.common.white, theme.palette.mode === 'light' ? 0.38 : 0.20),
            background: isUser ? undefined : BRAND_GRADIENT,
            boxShadow: (theme) =>
              theme.palette.mode === 'light'
                ? '0 1px 0 rgba(0,0,0,0.02), 0 8px 22px rgba(60,64,67,0.18)'
                : '0 14px 34px rgba(0,0,0,0.55)',
            '&::after': isUser
              ? undefined
              : {
                  content: '""',
                  position: 'absolute',
                  inset: 0,
                  borderRadius: '50%',
                  border: '1px solid',
                  borderColor: (theme) =>
                    alpha(theme.palette.common.white, theme.palette.mode === 'light' ? 0.42 : 0.22),
                  pointerEvents: 'none',
                },
          }}
        >
          {isUser ? (
            <PersonIcon sx={{ fontSize: 18, color: 'primary.main' }} />
          ) : (
            <AutoAwesomeIcon sx={{ fontSize: 18, color: '#ffffff' }} />
          )}
        </Box>

        {/* 消息内容 */}
        <Box
          sx={{
            flex: 1,
            minWidth: 0,
            maxWidth: '85%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: isUser ? 'flex-end' : 'flex-start',
          }}
        >
          {/* 消息气泡 - Gemini 风格 */}
          {isUser ? (
            // 用户消息：Google-ish Tonal bubble
            <Paper
              elevation={0}
              sx={(theme) => {
                const isLight = theme.palette.mode === 'light';
                const baseBg = alpha(theme.palette.primary.main, isLight ? 0.1 : 0.18);
                const hoverBg = alpha(theme.palette.primary.main, isLight ? 0.12 : 0.22);
                const borderColor = alpha(theme.palette.primary.main, isLight ? 0.18 : 0.28);

                return {
                  px: 2,
                  py: 1.5,
                  borderRadius: 20,
                  borderTopRightRadius: 12,
                  borderBottomRightRadius: 12,
                  bgcolor: baseBg,
                  border: 1,
                  borderColor,
                  color: 'text.primary',
                  boxShadow: isLight
                    ? '0 1px 0 rgba(0,0,0,0.02), 0 10px 28px rgba(60,64,67,0.16)'
                    : '0 16px 38px rgba(0,0,0,0.55)',
                  transition: theme.transitions.create(['background-color', 'box-shadow'], {
                    duration: theme.transitions.duration.shorter,
                  }),
                  '&:hover': {
                    bgcolor: hoverBg,
                    boxShadow: isLight
                      ? '0 1px 0 rgba(0,0,0,0.02), 0 14px 36px rgba(60,64,67,0.20)'
                      : '0 18px 44px rgba(0,0,0,0.62)',
                  },
                  display: 'inline-block',
                };
              }}
            >
              <Typography
                variant="body1"
                sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.65, overflowWrap: 'anywhere' }}
              >
                {displayContent}
              </Typography>
            </Paper>
          ) : (
            // 助手消息：透明背景直接显示
            <Box sx={{ py: 1 }}>
              {think && (
                <ThinkingContainer
                  content={think}
                  isStreaming={isStreaming}
                  isThinking={isThinking}
                  startTime={thinkStartTime}
                />
              )}
              <Box sx={cursorSx}>
                <Suspense fallback={<Typography variant="body2" color="text.secondary">加载渲染器...</Typography>}>
                  <MarkdownContent
                    content={displayContent}
                    isStreaming={isStreaming}
                    onCitationClick={onCitationClick}
                  />
                </Suspense>
              </Box>
            </Box>
          )}

          {/* 操作按钮 */}
          {showActions && !isUser && (
            <Stack direction="row" spacing={0.5} sx={{ mt: 1, ml: 1 }}>
              <Tooltip title={copied ? '已复制' : '复制'}>
                <IconButton
                  size="small"
                  onClick={handleCopy}
                  aria-label={copied ? '已复制' : '复制回复'}
                  sx={{ color: 'text.secondary' }}
                >
                  {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
                </IconButton>
              </Tooltip>
            </Stack>
          )}
        </Box>
      </Box>
    </Box>
  );
}

export const MessageItem = memo(
  MessageItemComponent,
  (prev, next) =>
    prev.role === next.role &&
    prev.content === next.content &&
    prev.think === next.think &&
    prev.isStreaming === next.isStreaming &&
    prev.showActions === next.showActions &&
    prev.thinkStartTime === next.thinkStartTime &&
    prev.onCitationClick === next.onCitationClick
);
// 工具审批卡片
interface ToolApprovalCardProps {
  interrupts: Array<{
    interrupt_id: string;
    message?: string | null;
    toolCalls: Array<{
      tool_name: string;
      extension_name?: string;
    }>;
  }>;
  loading?: boolean;
  onSubmit: (approval: ToolApprovalRequest) => void;
}

export function ToolApprovalCard({
  interrupts,
  loading,
  onSubmit,
}: ToolApprovalCardProps) {
  const [decisions, setDecisions] = useState<Record<string, 'approve' | 'reject'>>({});

  const decisionKeys = interrupts.flatMap((interrupt) =>
    interrupt.toolCalls.map((_, index) => `${interrupt.interrupt_id}:${index}`)
  );
  const allDecided =
    decisionKeys.length > 0 &&
    decisionKeys.every((key) => decisions[key] === 'approve' || decisions[key] === 'reject');

  const setDecision = (key: string, value: 'approve' | 'reject') => {
    setDecisions((prev) => ({ ...prev, [key]: value }));
  };

  const setAllDecisions = (value: 'approve' | 'reject') => {
    const next: Record<string, 'approve' | 'reject'> = {};
    for (const key of decisionKeys) {
      next[key] = value;
    }
    setDecisions(next);
  };

  const handleSubmit = () => {
    if (!allDecided || loading) {
      return;
    }
    const approval: ToolApprovalRequest = {
      interrupts: interrupts.map((interrupt) => ({
        interrupt_id: interrupt.interrupt_id,
        decisions: interrupt.toolCalls.map((_, index) => {
          const key = `${interrupt.interrupt_id}:${index}`;
          const decision = decisions[key];
          if (decision === 'reject') {
            return {
              type: 'reject',
              message: '用户拒绝执行该工具调用。',
            };
          }
          return { type: 'approve' };
        }),
      })),
    };
    onSubmit(approval);
  };

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderRadius: 3,
        borderColor: 'warning.main',
        bgcolor: (theme) => (theme.palette.mode === 'light' ? '#fff8e1' : '#3d2e00'),
        maxWidth: 500,
      }}
    >
      <Stack spacing={1.5}>
        <Typography variant="subtitle2" fontWeight={600}>
          需要审批工具调用
        </Typography>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" color="success" onClick={() => setAllDecisions('approve')} disabled={loading}>
            全部允许
          </Button>
          <Button variant="outlined" color="error" onClick={() => setAllDecisions('reject')} disabled={loading}>
            全部拒绝
          </Button>
        </Stack>
        {interrupts.map((interrupt) => (
          <Paper key={interrupt.interrupt_id} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
            <Stack spacing={1}>
              <Typography variant="caption" color="text.secondary">
                interrupt: {interrupt.interrupt_id}
              </Typography>
              {interrupt.message && (
                <Typography variant="body2" color="text.secondary">
                  {interrupt.message}
                </Typography>
              )}
              {interrupt.toolCalls.map((toolCall, index) => {
                const key = `${interrupt.interrupt_id}:${index}`;
                const current = decisions[key];
                return (
                  <Stack
                    key={key}
                    direction={{ xs: 'column', sm: 'row' }}
                    spacing={1}
                    alignItems={{ xs: 'stretch', sm: 'center' }}
                  >
                    <Chip
                      label={`${toolCall.tool_name}${toolCall.extension_name ? ` (${toolCall.extension_name})` : ''}`}
                      size="small"
                      variant="outlined"
                    />
                    <Stack direction="row" spacing={1}>
                      <Button
                        size="small"
                        variant={current === 'approve' ? 'contained' : 'outlined'}
                        color="success"
                        onClick={() => setDecision(key, 'approve')}
                        disabled={loading}
                      >
                        允许
                      </Button>
                      <Button
                        size="small"
                        variant={current === 'reject' ? 'contained' : 'outlined'}
                        color="error"
                        onClick={() => setDecision(key, 'reject')}
                        disabled={loading}
                      >
                        拒绝
                      </Button>
                    </Stack>
                  </Stack>
                );
              })}
            </Stack>
          </Paper>
        ))}
        <Button variant="contained" onClick={handleSubmit} loading={loading} disabled={!allDecided}>
          提交审批并继续
        </Button>
      </Stack>
    </Paper>
  );
}

interface ClarificationCardProps {
  message: string;
  loading?: boolean;
  onSubmit: (content: string) => void;
}

export function ClarificationCard({
  message,
  loading,
  onSubmit,
}: ClarificationCardProps) {
  const [content, setContent] = useState('');

  const handleSubmit = () => {
    const value = content.trim();
    if (!value || loading) {
      return;
    }
    onSubmit(value);
    setContent('');
  };

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2,
        borderRadius: 3,
        borderColor: 'info.main',
        bgcolor: (theme) => (theme.palette.mode === 'light' ? '#f4f9ff' : '#14263a'),
        maxWidth: 560,
      }}
    >
      <Stack spacing={1.5}>
        <Typography variant="subtitle2" fontWeight={600}>
          需要补充信息
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {message}
        </Typography>
        <TextField
          multiline
          minRows={2}
          maxRows={5}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="补充必要信息后继续..."
          size="small"
          disabled={loading}
        />
        <Box>
          <Button variant="contained" onClick={handleSubmit} loading={loading} disabled={!content.trim()}>
            继续回答
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}


