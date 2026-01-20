/**
 * 消息列表组件
 * 管理消息滚动和布局
 */
import { useRef, useEffect, useCallback, useMemo, useState } from 'react';
import { Box, Stack } from '@mui/material';
import { MessageItem, ToolApprovalCard, ExtensionSummary } from './MessageItem';
import { SparkleLoading } from './SparkleLoading';
import type { EvidenceItem } from '../../services/chats';
import { EvidenceList } from '../EvidenceList';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  think?: string;
  isStreaming?: boolean;
  evidence?: EvidenceItem[];
  invocations?: Array<{
    tool_name: string;
    extension_name?: string;
    status: 'succeeded' | 'failed';
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

  const updateIsAtBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const threshold = 120;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
    setIsAtBottom(atBottom);
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
  }, [messages, hasStreaming, showThinking, isAtBottom]);

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
          <Box key={msg.id}>
            <MessageItem
              role={msg.role}
              content={msg.content}
              think={msg.think}
              isStreaming={msg.isStreaming}
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

            {/* 扩展调用摘要 */}
            {msg.invocations && msg.invocations.length > 0 && (
              <Box sx={{ mt: 2, ml: 7 }}>
                <ExtensionSummary invocations={msg.invocations} />
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
    </Box>
  );
}
