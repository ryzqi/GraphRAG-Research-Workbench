/**
 * 消息列表组件
 * 管理消息滚动和布局
 */
import { useRef, useEffect, useCallback, useMemo, useState } from 'react';
import { Box, Fade, IconButton, Paper, Stack, Tooltip } from '@mui/material';
import { alpha } from '@mui/material/styles';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import { MessageItem, ToolApprovalCard } from './MessageItem';
import { SparkleLoading } from './SparkleLoading';
import type { EvidenceItem } from '../../services/chats';
import { EvidenceList } from '../EvidenceList';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  think?: string;
  isStreaming?: boolean;
  /** 思考开始时间戳 */
  thinkStartTime?: number;
  evidence?: EvidenceItem[];
  toolSteps?: Array<{
    tool_call_id?: string;
    tool_name: string;
    tool_args?: Record<string, unknown>;
    tool_output?: string;
    status: 'pending' | 'completed' | 'failed';
  }>;
  pendingToolApproval?: {
    message?: string | null;
    toolCalls: Array<{
      tool_name: string;
      extension_name?: string;
    }>;
  };
  runId?: string;
}

interface MessageListProps {
  messages: ChatMessage[];
  loading?: boolean;
  onToolApprove?: (messageId: string, runId: string) => void;
  onToolReject?: (messageId: string, runId: string) => void;
  approvalLoading?: boolean;
}

export function MessageList({
  messages,
  loading = false,
  onToolApprove,
  onToolReject,
  approvalLoading = false,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);

  const hasStreaming = useMemo(() => messages.some((msg) => msg.isStreaming), [messages]);
  const hasStreamingContent = useMemo(
    () =>
      messages.some(
        (msg) => msg.isStreaming && ((msg.content?.length ?? 0) > 0 || (msg.think?.length ?? 0) > 0)
      ),
    [messages]
  );
  const showThinking = loading && !hasStreamingContent;
  const lastMessage = messages[messages.length - 1];
  const lastMessageContentSize =
    (lastMessage?.content?.length ?? 0) + (lastMessage?.think?.length ?? 0);

  const updateIsAtBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const threshold = 120;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
    setIsAtBottom(atBottom);
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, []);

  // 初始化和消息变更时重新计算
  useEffect(() => {
    updateIsAtBottom();
  }, [messages.length, loading, updateIsAtBottom]);

  // 仅在用户位于底部时自动跟随
  useEffect(() => {
    if (!isAtBottom) return;
    const behavior = hasStreaming || showThinking ? 'smooth' : 'auto';
    bottomRef.current?.scrollIntoView({ behavior, block: 'end' });
  }, [
    messages.length,
    lastMessage?.id,
    lastMessageContentSize,
    hasStreaming,
    showThinking,
    isAtBottom,
  ]);

  if (messages.length === 0 && !loading) {
    return null;
  }

  return (
    <Box
      ref={containerRef}
      onScroll={updateIsAtBottom}
      sx={{
        flex: 1,
        overflowY: 'auto',
        px: { xs: 2, sm: 3, md: 4 },
        py: 3,
        position: 'relative',
      }}
    >
      <Stack spacing={3} sx={{ maxWidth: 900, mx: 'auto' }}>
        {messages.map((msg) => {
          // 跳过空内容的流式助手消息（此时显示 SparkleLoading）
          const isEmptyStreamingAssistant =
            msg.role === 'assistant' &&
            msg.isStreaming &&
            !msg.content &&
            !msg.think;

          if (isEmptyStreamingAssistant) return null;

          return (
            <Box key={msg.id} sx={{ contentVisibility: 'auto', containIntrinsicSize: '1px 220px' }}>
              <MessageItem
                role={msg.role}
                content={msg.content}
                think={msg.think}
                isStreaming={msg.isStreaming}
                thinkStartTime={msg.thinkStartTime}
              />

              {/* 工具审批卡片 */}
              {msg.pendingToolApproval && onToolApprove && onToolReject && msg.runId && (
                <Box sx={{ mt: 2, ml: 7 }}>
                  <ToolApprovalCard
                    message={msg.pendingToolApproval.message}
                    toolCalls={msg.pendingToolApproval.toolCalls}
                    loading={approvalLoading}
                    onApprove={() => onToolApprove(msg.id, msg.runId!)}
                    onReject={() => onToolReject(msg.id, msg.runId!)}
                  />
                </Box>
              )}

              {/* 证据列表 */}
              {msg.evidence && msg.evidence.length > 0 && (
                <Box sx={{ mt: 2, ml: 7 }}>
                  <EvidenceList evidence={msg.evidence} />
                </Box>
              )}
            </Box>
          );
        })}

        {/* 思考占位（首个 delta 到达前）- Gemini Sparkle 风格 */}
        {showThinking && (
          <Box sx={{ ml: 7 }}>
            <SparkleLoading variant="sparkle" />
          </Box>
        )}

        <div ref={bottomRef} />
      </Stack>

      {/* “回到底部”按钮：仅当用户离开底部时出现 */}
      <Box
        sx={{
          position: 'sticky',
          bottom: 16,
          mt: 2,
          display: 'flex',
          justifyContent: 'center',
          pointerEvents: 'none',
        }}
      >
        <Fade in={!isAtBottom} timeout={180} mountOnEnter unmountOnExit>
          <Box
            sx={{
              pointerEvents: 'auto',
              transform: !isAtBottom ? 'translateY(0)' : 'translateY(8px)',
              transition: 'transform 180ms cubic-bezier(0.2, 0, 0, 1)',
            }}
          >
            <Tooltip title="回到底部" placement="top">
              <Paper
                elevation={0}
                sx={{
                  borderRadius: 999,
                  border: 1,
                  borderColor: 'divider',
                  bgcolor: (theme) => alpha(theme.palette.background.paper, 0.88),
                  backdropFilter: 'blur(14px)',
                  WebkitBackdropFilter: 'blur(14px)',
                  boxShadow: (theme) =>
                    theme.palette.mode === 'light'
                      ? '0 10px 30px rgba(0,0,0,0.10)'
                      : '0 14px 40px rgba(0,0,0,0.40)',
                }}
              >
                <IconButton onClick={scrollToBottom} aria-label="回到底部">
                  <KeyboardArrowDownIcon />
                </IconButton>
              </Paper>
            </Tooltip>
          </Box>
        </Fade>
      </Box>
    </Box>
  );
}
