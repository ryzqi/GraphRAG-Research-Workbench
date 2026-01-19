/**
 * 消息列表组件
 * 管理消息滚动和布局
 */
import { useRef, useEffect } from 'react';
import { Box, Stack } from '@mui/material';
import { MessageItem, ToolApprovalCard, ExtensionSummary } from './MessageItem';
import { SparkleLoading } from './SparkleLoading';
import type { EvidenceItem } from '../../services/chats';
import { EvidenceList } from '../EvidenceList';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
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
  const bottomRef = useRef<HTMLDivElement>(null);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  if (messages.length === 0 && !loading) {
    return null;
  }

  return (
    <Box
      sx={{
        flex: 1,
        overflowY: 'auto',
        px: { xs: 2, sm: 3, md: 4 },
        py: 3,
      }}
    >
      <Stack spacing={3} sx={{ maxWidth: 900, mx: 'auto' }}>
        {messages.map((msg) => (
          <Box key={msg.id}>
            <MessageItem role={msg.role} content={msg.content} />

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
        ))}

        {/* 加载状态 */}
        {loading && (
          <Box sx={{ display: 'flex', gap: 2, alignItems: 'flex-start' }}>
            <Box
              sx={{
                width: 36,
                height: 36,
                borderRadius: '50%',
                background: 'linear-gradient(135deg, #4285f4 0%, #34a853 50%, #fbbc04 100%)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
              }}
            />
            <Box sx={{ flex: 1, pt: 1 }}>
              <SparkleLoading variant="dots" />
            </Box>
          </Box>
        )}

        <div ref={bottomRef} />
      </Stack>
    </Box>
  );
}
