/**
 * 消息项组件
 * 支持用户/助手消息展示，Markdown 渲染，复制按钮
 */
import { useState, useCallback } from 'react';
import { Box, IconButton, Paper, Stack, Tooltip, Typography, Chip } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import CheckIcon from '@mui/icons-material/Check';
import PersonIcon from '@mui/icons-material/Person';
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome';
import { motion } from 'framer-motion';
import { MarkdownContent } from './MarkdownContent';

interface MessageItemProps {
  role: 'user' | 'assistant';
  content: string;
  timestamp?: string;
  showActions?: boolean;
}

export function MessageItem({ role, content, showActions = true }: MessageItemProps) {
  const [copied, setCopied] = useState(false);
  const isUser = role === 'user';

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
          flexDirection: isUser ? 'row-reverse' : 'row',
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
            bgcolor: isUser ? 'primary.main' : 'transparent',
            background: isUser
              ? undefined
              : 'linear-gradient(135deg, #4285f4 0%, #34a853 50%, #fbbc04 100%)',
            color: 'white',
          }}
        >
          {isUser ? <PersonIcon fontSize="small" /> : <AutoAwesomeIcon fontSize="small" />}
        </Box>

        {/* 消息内容 */}
        <Box sx={{ flex: 1, minWidth: 0, maxWidth: isUser ? '70%' : '85%' }}>
          {/* 角色标签 */}
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ mb: 0.5, display: 'block', textAlign: isUser ? 'right' : 'left' }}
          >
            {isUser ? '你' : '助手'}
          </Typography>

          {/* 消息气泡 */}
          <Paper
            elevation={0}
            sx={{
              p: 2,
              borderRadius: 4,
              bgcolor: isUser
                ? 'primary.main'
                : (theme) => (theme.palette.mode === 'light' ? '#f0f4f9' : '#1e1f20'),
              color: isUser ? 'primary.contrastText' : 'text.primary',
              position: 'relative',
            }}
          >
            {isUser ? (
              <Typography variant="body1" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                {content}
              </Typography>
            ) : (
              <MarkdownContent content={content} />
            )}
          </Paper>

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
