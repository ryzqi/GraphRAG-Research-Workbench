/**
 * 消息项组件
 * Gemini 风格：左对齐布局，实心圆点光标，透气设计
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { Box, IconButton, Paper, Stack, Tooltip, Typography, Chip, keyframes } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import PersonIcon from '@mui/icons-material/Person';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import { motion } from 'framer-motion';
import { MarkdownContent } from './MarkdownContent';
import { useTypewriterStream } from './useTypewriterStream';

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

interface MessageItemProps {
  role: 'user' | 'assistant';
  content: string;
  think?: string;
  isStreaming?: boolean;
  timestamp?: string;
  showActions?: boolean;
}

export function MessageItem({
  role,
  content,
  think,
  isStreaming = false,
  showActions = true,
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
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: [0.2, 0, 0, 1] }}
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
            width: 36,
            height: 36,
            borderRadius: '50%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
            bgcolor: isUser ? 'text.secondary' : 'transparent',
            background: isUser ? undefined : BRAND_GRADIENT,
            color: 'white',
          }}
        >
          {isUser ? <PersonIcon fontSize="small" /> : <AutoAwesomeIcon fontSize="small" />}
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
            // 用户消息：灰色背景气泡
            <Paper
              elevation={0}
              sx={{
                p: 2,
                borderRadius: '24px',
                bgcolor: (theme) => (theme.palette.mode === 'light' ? '#F2F2F2' : '#303134'),
                color: 'text.primary',
                display: 'inline-block',
              }}
            >
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                {displayContent}
              </Typography>
            </Paper>
          ) : (
            // 助手消息：透明背景直接显示
            <Box sx={{ py: 1 }}>
              {think && (
                <Box sx={{ mb: 1 }}>
                  {isStreaming ? (
                    <Typography
                      variant="body2"
                      sx={{ opacity: 0.6, fontSize: 13, whiteSpace: 'pre-wrap' }}
                    >
                      {think}
                    </Typography>
                  ) : (
                    <Box
                      component="details"
                      sx={{
                        bgcolor: 'action.hover',
                        borderRadius: 2,
                        p: 1,
                        '& summary': { cursor: 'pointer', fontSize: 13 },
                      }}
                    >
                      <Box component="summary" sx={{ listStyle: 'none' }}>
                        思考过程
                      </Box>
                      <Typography
                        variant="body2"
                        sx={{ mt: 1, fontSize: 13, whiteSpace: 'pre-wrap' }}
                      >
                        {think}
                      </Typography>
                    </Box>
                  )}
                </Box>
              )}
              <Box sx={cursorSx}>
                <MarkdownContent content={displayContent} isStreaming={isStreaming} />
              </Box>
            </Box>
          )}

          {/* 操作按钮 */}
          {showActions && !isUser && (
            <Stack direction="row" spacing={0.5} sx={{ mt: 1, ml: 1 }}>
              <Tooltip title={copied ? '已复制' : '复制'}>
                <IconButton size="small" onClick={handleCopy} sx={{ color: 'text.secondary' }}>
                  {copied ? <CheckIcon fontSize="small" /> : <ContentCopyIcon fontSize="small" />}
                </IconButton>
              </Tooltip>
            </Stack>
          )}
        </Box>
      </Box>
    </motion.div>
  );
}

// 工具审批卡片
interface ToolApprovalCardProps {
  message?: string | null;
  toolCalls: Array<{
    tool_name: string;
    extension_name?: string;
  }>;
  loading?: boolean;
  onApprove: () => void;
  onReject: () => void;
}

export function ToolApprovalCard({
  message,
  toolCalls,
  loading,
  onApprove,
  onReject,
}: ToolApprovalCardProps) {
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
        {message && (
          <Typography variant="body2" color="text.secondary">
            {message}
          </Typography>
        )}
        {toolCalls.length > 0 && (
          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            {toolCalls.map((t, idx) => (
              <Chip
                key={idx}
                label={`${t.tool_name}${t.extension_name ? ` (${t.extension_name})` : ''}`}
                size="small"
                variant="outlined"
              />
            ))}
          </Stack>
        )}
        <Stack direction="row" spacing={1}>
          <Box
            component="button"
            onClick={onApprove}
            disabled={loading}
            sx={{
              px: 2,
              py: 1,
              borderRadius: 2,
              border: 'none',
              bgcolor: 'success.main',
              color: 'white',
              fontWeight: 500,
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.6 : 1,
              '&:hover': { bgcolor: 'success.dark' },
            }}
          >
            允许执行
          </Box>
          <Box
            component="button"
            onClick={onReject}
            disabled={loading}
            sx={{
              px: 2,
              py: 1,
              borderRadius: 2,
              border: 1,
              borderColor: 'error.main',
              bgcolor: 'transparent',
              color: 'error.main',
              fontWeight: 500,
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.6 : 1,
              '&:hover': { bgcolor: 'error.50' },
            }}
          >
            拒绝执行
          </Box>
        </Stack>
      </Stack>
    </Paper>
  );
}

// 扩展调用摘要
interface ExtensionSummaryProps {
  invocations: Array<{
    tool_name: string;
    extension_name?: string;
    status: 'succeeded' | 'failed';
  }>;
}

export function ExtensionSummary({ invocations }: ExtensionSummaryProps) {
  if (invocations.length === 0) return null;

  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.5,
        borderRadius: 2,
        bgcolor: 'background.paper',
        maxWidth: 400,
      }}
    >
      <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: 'block' }}>
        扩展调用
      </Typography>
      <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
        {invocations.map((inv, idx) => (
          <Chip
            key={idx}
            label={inv.tool_name}
            size="small"
            color={inv.status === 'succeeded' ? 'success' : 'error'}
            variant="outlined"
          />
        ))}
      </Stack>
    </Paper>
  );
}
