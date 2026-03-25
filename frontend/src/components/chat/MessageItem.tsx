/**
 * 消息项组件
 * Gemini 风格：左对齐布局，实心圆点光标，透气设计
 */
import { Suspense, lazy, memo, useState, useCallback, useEffect, useRef } from 'react';
import { Box, Paper, Stack, Tooltip, Typography, Chip, TextField, keyframes } from '@mui/material';
import { alpha } from '@mui/material/styles';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import PersonIcon from '@mui/icons-material/Person';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import HelpOutlineRoundedIcon from '@mui/icons-material/HelpOutlineRounded';
import SendRoundedIcon from '@mui/icons-material/SendRounded';
import { useTypewriterStream } from './useTypewriterStream';
import { ThinkingContainer } from './ThinkingContainer';
import { Button } from '../ui/Button';
import type { PendingClarification, ToolApprovalRequest } from '../../services/chats';

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
  const assistantRevealSx = !isUser
    ? {
        opacity: hasAnswerContent ? 1 : 0.72,
        transform: hasAnswerContent ? 'translateY(0)' : 'translateY(4px)',
        transition: 'opacity 220ms cubic-bezier(0.2, 0, 0, 1), transform 220ms cubic-bezier(0.2, 0, 0, 1)',
        '@media (prefers-reduced-motion: reduce)': {
          transition: 'none',
          transform: 'none',
          opacity: hasAnswerContent ? 1 : 0.82,
        },
      }
    : undefined;

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
          '&:hover .assistant-message-actions, &:focus-within .assistant-message-actions': {
            opacity: 1,
            transform: 'translateY(0)',
          },
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
          {/* 消息气泡样式 */}
          {isUser ? (
            // 用户消息：偏 tonal 的气泡样式
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
            <Box sx={{ py: 1, ...assistantRevealSx }}>
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
            <Stack
              direction="row"
              spacing={0.5}
              className="assistant-message-actions"
              sx={{
                mt: 0.75,
                ml: 0.25,
                opacity: { xs: 1, sm: copied ? 1 : 0.08 },
                transform: { xs: 'translateY(0)', sm: copied ? 'translateY(0)' : 'translateY(3px)' },
                transition: (theme) =>
                  theme.transitions.create(['opacity', 'transform'], {
                    duration: theme.transitions.duration.shorter,
                  }),
              }}
            >
              <Tooltip title={copied ? '已复制' : '复制'}>
                <Button
                  size="small"
                  variant={copied ? 'contained' : 'text'}
                  onClick={handleCopy}
                  aria-label={copied ? '已复制' : '复制回复'}
                  startIcon={copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
                  sx={(theme) => ({
                    color: copied ? 'success.main' : 'text.secondary',
                    border: '1px solid',
                    borderColor: copied ? 'success.light' : 'divider',
                    borderRadius: 999,
                    minWidth: 'auto',
                    px: 1.15,
                    py: 0.45,
                    bgcolor:
                      theme.palette.mode === 'light'
                        ? alpha(theme.palette.background.paper, 0.92)
                        : alpha(theme.palette.background.paper, 0.24),
                    boxShadow:
                      theme.palette.mode === 'light'
                        ? '0 8px 24px rgba(15, 23, 42, 0.08)'
                        : '0 10px 28px rgba(0, 0, 0, 0.28)',
                    transition: theme.transitions.create(
                      ['background-color', 'border-color', 'color', 'transform', 'box-shadow'],
                      { duration: theme.transitions.duration.shorter }
                    ),
                    '&:hover': {
                      color: copied ? 'success.main' : 'primary.main',
                      borderColor: copied ? 'success.main' : 'primary.light',
                      bgcolor:
                        theme.palette.mode === 'light'
                          ? alpha(theme.palette.primary.main, 0.06)
                          : alpha(theme.palette.primary.main, 0.16),
                      transform: 'translateY(-1px)',
                      boxShadow:
                        theme.palette.mode === 'light'
                          ? '0 12px 28px rgba(15, 23, 42, 0.12)'
                          : '0 14px 32px rgba(0, 0, 0, 0.36)',
                    },
                  })}
                >
                  {copied ? '已复制' : '复制'}
                </Button>
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
  pendingClarification?: PendingClarification | null;
  loading?: boolean;
  onSubmit: (content: string) => void;
}

export function ClarificationCard({
  message,
  pendingClarification,
  loading,
  onSubmit,
}: ClarificationCardProps) {
  const [content, setContent] = useState('');
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | null>(null);
  const displayQuestion = pendingClarification?.question?.trim() || message;
  const suggestedAnswers = pendingClarification?.suggested_answers ?? [];
  const slotLabels =
    pendingClarification?.slots
      ?.map((slot) => slot.label.trim())
      .filter((label) => label.length > 0) ?? [];
  const hasContent = content.trim().length > 0;

  const handleSubmit = () => {
    const value = content.trim();
    if (!value || loading) {
      return;
    }
    onSubmit(value);
    setContent('');
  };

  const handleSuggestionPick = (suggestion: string) => {
    setContent(suggestion);
    inputRef.current?.focus();
  };

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2.25,
        borderRadius: 4,
        borderColor: (theme) => alpha(theme.palette.info.main, theme.palette.mode === 'light' ? 0.34 : 0.5),
        background: (theme) =>
          theme.palette.mode === 'light'
            ? 'linear-gradient(180deg, rgba(244,249,255,0.96) 0%, rgba(255,255,255,0.98) 100%)'
            : 'linear-gradient(180deg, rgba(20,38,58,0.96) 0%, rgba(12,20,33,0.98) 100%)',
        maxWidth: 560,
        boxShadow: (theme) =>
          theme.palette.mode === 'light'
            ? '0 16px 36px rgba(59, 130, 246, 0.10)'
            : '0 22px 40px rgba(2, 8, 23, 0.38)',
      }}
    >
      <Stack spacing={1.75}>
        <Stack direction="row" spacing={1.25} alignItems="flex-start">
          <Box
            sx={(theme) => ({
              width: 32,
              height: 32,
              borderRadius: '50%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
              color: 'info.main',
              bgcolor:
                theme.palette.mode === 'light'
                  ? alpha(theme.palette.info.main, 0.12)
                  : alpha(theme.palette.info.light, 0.16),
              border: '1px solid',
              borderColor: alpha(theme.palette.info.main, theme.palette.mode === 'light' ? 0.18 : 0.3),
            })}
          >
            <HelpOutlineRoundedIcon sx={{ fontSize: 18 }} />
          </Box>
          <Stack spacing={0.5} sx={{ minWidth: 0 }}>
            <Stack direction="row" spacing={0.75} alignItems="center" useFlexGap flexWrap="wrap">
              <Typography variant="subtitle2" fontWeight={700}>
                需要补充信息
              </Typography>
              <Chip
                size="small"
                color="info"
                variant="outlined"
                label="等待你的补充"
                sx={{ borderRadius: 999 }}
              />
            </Stack>
            <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.6 }}>
              请先补充必要上下文，再继续完成这次回答。
            </Typography>
          </Stack>
        </Stack>

        <Typography
          variant="body2"
          color="text.primary"
          sx={{
            lineHeight: 1.7,
            px: 1.25,
            py: 1,
            borderRadius: 2.5,
            bgcolor: (theme) =>
              theme.palette.mode === 'light'
                ? alpha(theme.palette.common.white, 0.84)
                : alpha(theme.palette.common.white, 0.04),
            border: '1px solid',
            borderColor: 'divider',
          }}
        >
          {displayQuestion}
        </Typography>
        {slotLabels.length > 0 && (
          <Stack spacing={0.75}>
            <Typography variant="caption" color="text.secondary">
              建议补充维度
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
              {slotLabels.map((label) => (
                <Chip
                  key={label}
                  size="small"
                  variant="outlined"
                  label={label}
                  sx={{ borderRadius: 999, bgcolor: (theme) => alpha(theme.palette.info.main, 0.04) }}
                />
              ))}
            </Stack>
          </Stack>
        )}
        {suggestedAnswers.length > 0 && (
          <Stack spacing={0.9}>
            <Typography variant="caption" color="text.secondary">
              可直接选择推荐补充项
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: 'wrap' }}>
              {suggestedAnswers.map((suggestion) => (
                <Button
                  key={suggestion}
                  size="small"
                  variant={content.trim() === suggestion ? 'contained' : 'outlined'}
                  color={content.trim() === suggestion ? 'primary' : 'inherit'}
                  disabled={loading}
                  onClick={() => handleSuggestionPick(suggestion)}
                  sx={{
                    borderRadius: 999,
                    px: 1.4,
                    justifyContent: 'flex-start',
                    textAlign: 'left',
                  }}
                >
                  {suggestion}
                </Button>
              ))}
            </Stack>
          </Stack>
        )}
        <TextField
          multiline
          minRows={2}
          maxRows={5}
          value={content}
          onChange={(event) => setContent(event.target.value)}
          placeholder="例如：按 2025 年、华东区域统计"
          size="small"
          disabled={loading}
          inputRef={inputRef}
          sx={{
            '& .MuiOutlinedInput-root': {
              borderRadius: 2.5,
              alignItems: 'flex-start',
              bgcolor: (theme) =>
                theme.palette.mode === 'light'
                  ? alpha(theme.palette.common.white, 0.88)
                  : alpha(theme.palette.common.white, 0.03),
            },
          }}
        />
        <Box
          sx={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: 1,
            flexWrap: 'wrap',
          }}
        >
          <Typography variant="caption" color="text.secondary">
            补充后会继续沿着当前问题执行，不会新开一轮会话。
          </Typography>
          <Button
            variant="contained"
            onClick={handleSubmit}
            loading={loading}
            disabled={!hasContent}
            startIcon={<SendRoundedIcon fontSize="small" />}
            sx={{ borderRadius: 999, px: 1.8, ml: 'auto' }}
          >
            继续回答
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}


