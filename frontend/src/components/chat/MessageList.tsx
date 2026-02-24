/**
 * 消息列表组件
 * 管理消息滚动、窗口化渲染与底部锚点语义
 */
import { memo, useRef, useEffect, useCallback, useMemo, useState } from 'react';
import { Box, Fade, IconButton, Paper, Stack, Tooltip } from '@mui/material';
import { alpha } from '@mui/material/styles';
import KeyboardArrowDownIcon from '@mui/icons-material/KeyboardArrowDown';
import { ClarificationCard, MessageItem, ToolApprovalCard } from './MessageItem';
import { SparkleLoading } from './SparkleLoading';
import type {
  ChatNodeIoEvent,
  ChatRunStateEvent,
  EvidenceItem,
  ToolApprovalRequest,
} from '../../services/chats';
import { EvidenceList } from '../EvidenceList';
import { stripTrailingReferenceSection } from '../../lib/kbChatContent';
import { calculateMessageListVirtualWindow } from '../../services/messageListVirtualization';
import { PipelineProgress, type PipelineStep, type PipelineTimelineEvent } from './PipelineProgress';

const VIRTUALIZATION_THRESHOLD = 60;
const VIRTUAL_OVERSCAN = 4;
const DEFAULT_ROW_HEIGHT = 220;

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  think?: string;
  isStreaming?: boolean;
  thinkStartTime?: number;
  evidence?: EvidenceItem[];
  toolSteps?: Array<{
    tool_call_id?: string;
    tool_name: string;
    tool_args?: Record<string, unknown>;
    tool_output?: string;
    status: 'pending' | 'completed' | 'failed';
  }>;
  pipelineSteps?: PipelineStep[];
  nodeTimeline?: PipelineTimelineEvent[];
  nodeIoEvents?: ChatNodeIoEvent[];
  pendingToolApproval?: {
    interrupts: Array<{
      interrupt_id: string;
      message?: string | null;
      toolCalls: Array<{
        tool_name: string;
        extension_name?: string;
      }>;
    }>;
  };
  pendingClarification?: {
    message: string;
  };
  runId?: string;
  runState?: ChatRunStateEvent;
  stagedContent?: string;
  answerRevealReady?: boolean;
}

interface MessageListProps {
  messages: ChatMessage[];
  loading?: boolean;
  onToolApprovalSubmit?: (
    messageId: string,
    runId: string,
    approval: ToolApprovalRequest
  ) => void;
  onClarificationSubmit?: (messageId: string, runId: string, content: string) => void;
  approvalLoading?: boolean;
  bottomInset?: number;
  showPipeline?: boolean;
  showEvidence?: boolean;
  selectedAssistantId?: string | null;
  onAssistantSelect?: (messageId: string) => void;
  normalizeInlineEvidenceSection?: boolean;
  scrollButtonAlign?: 'center' | 'right';
  showScrollToBottom?: boolean;
}

interface MessageRowProps {
  message: ChatMessage;
  onToolApprovalSubmit?: (
    messageId: string,
    runId: string,
    approval: ToolApprovalRequest
  ) => void;
  onClarificationSubmit?: (messageId: string, runId: string, content: string) => void;
  approvalLoading: boolean;
  showPipeline: boolean;
  showEvidence: boolean;
  selectedAssistantId?: string | null;
  onAssistantSelect?: (messageId: string) => void;
  normalizeInlineEvidenceSection: boolean;
}

const MessageRow = memo(
  function MessageRow({
    message,
    onToolApprovalSubmit,
    onClarificationSubmit,
    approvalLoading,
    showPipeline,
    showEvidence,
    selectedAssistantId,
    onAssistantSelect,
    normalizeInlineEvidenceSection,
  }: MessageRowProps) {
    const [activeCitationId, setActiveCitationId] = useState<string | null>(null);

    useEffect(() => {
      setActiveCitationId(null);
    }, [message.id]);

    const handleCitationClick = useCallback((citationId: string) => {
      setActiveCitationId(citationId);
    }, []);

    const handleCitationHandled = useCallback((citationId: string) => {
      setActiveCitationId((current) => (current === citationId ? null : current));
    }, []);

    const isEmptyStreamingAssistant =
      message.role === 'assistant' &&
      message.isStreaming &&
      !message.content &&
      !message.think;

    if (isEmptyStreamingAssistant) {
      return null;
    }

    const isSelected = message.role === 'assistant' && selectedAssistantId === message.id;
    const content =
      normalizeInlineEvidenceSection &&
      message.role === 'assistant' &&
      (message.evidence?.length ?? 0) > 0
        ? stripTrailingReferenceSection(message.content)
        : message.content;

    return (
      <Box
        sx={{
          contentVisibility: 'auto',
          containIntrinsicSize: '1px 220px',
          borderRadius: 2,
          p: 0.5,
          border: isSelected ? 1 : 0,
          borderColor: isSelected ? 'primary.main' : 'transparent',
          cursor: message.role === 'assistant' && onAssistantSelect ? 'pointer' : 'default',
        }}
        onClick={() => {
          if (message.role === 'assistant' && onAssistantSelect) {
            onAssistantSelect(message.id);
          }
        }}
      >
        {showPipeline &&
          message.role === 'assistant' &&
          ((message.nodeTimeline?.length ?? 0) > 0 || Boolean(message.runState)) && (
            <Box sx={{ ml: 7, mb: 1.5 }}>
              <PipelineProgress
                timeline={message.nodeTimeline ?? []}
                isStreaming={Boolean(message.isStreaming)}
                runState={message.runState}
              />
            </Box>
          )}

        <MessageItem
          role={message.role}
          content={content}
          think={message.think}
          isStreaming={message.isStreaming}
          thinkStartTime={message.thinkStartTime}
          onCitationClick={message.role === 'assistant' ? handleCitationClick : undefined}
        />

        {message.pendingToolApproval && onToolApprovalSubmit && message.runId && (
          <Box sx={{ mt: 2, ml: 7 }}>
            <ToolApprovalCard
              interrupts={message.pendingToolApproval.interrupts}
              loading={approvalLoading}
              onSubmit={(approval) => onToolApprovalSubmit(message.id, message.runId!, approval)}
            />
          </Box>
        )}

        {message.pendingClarification && onClarificationSubmit && message.runId && (
          <Box sx={{ mt: 2, ml: 7 }}>
            <ClarificationCard
              message={message.pendingClarification.message}
              loading={approvalLoading}
              onSubmit={(contentText) =>
                onClarificationSubmit(message.id, message.runId!, contentText)
              }
            />
          </Box>
        )}

        {showEvidence && message.evidence && message.evidence.length > 0 && (
          <Box sx={{ mt: 2, ml: 7 }}>
            <EvidenceList
              evidence={message.evidence}
              activeCitationId={activeCitationId}
              onCitationHandled={handleCitationHandled}
              citationAnchorScopeId={message.id}
            />
          </Box>
        )}
      </Box>
    );
  },
  (prev, next) =>
    prev.message === next.message &&
    prev.onToolApprovalSubmit === next.onToolApprovalSubmit &&
    prev.onClarificationSubmit === next.onClarificationSubmit &&
    prev.approvalLoading === next.approvalLoading &&
    prev.showPipeline === next.showPipeline &&
    prev.showEvidence === next.showEvidence &&
    prev.selectedAssistantId === next.selectedAssistantId &&
    prev.onAssistantSelect === next.onAssistantSelect &&
    prev.normalizeInlineEvidenceSection === next.normalizeInlineEvidenceSection
);

export function MessageList({
  messages,
  loading = false,
  onToolApprovalSubmit,
  onClarificationSubmit,
  approvalLoading = false,
  bottomInset = 220,
  showPipeline = true,
  showEvidence = true,
  selectedAssistantId,
  onAssistantSelect,
  normalizeInlineEvidenceSection = false,
  scrollButtonAlign = 'center',
  showScrollToBottom = true,
}: MessageListProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [isAtBottom, setIsAtBottom] = useState(true);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);
  const [rowHeights, setRowHeights] = useState<Record<string, number>>({});

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
  const scrollButtonBottom = Math.max(20, bottomInset - 72);
  const virtualizationEnabled = messages.length > VIRTUALIZATION_THRESHOLD;

  const itemHeights = useMemo(
    () => messages.map((msg) => rowHeights[msg.id] ?? DEFAULT_ROW_HEIGHT),
    [messages, rowHeights]
  );

  const virtualWindow = useMemo(() => {
    if (!virtualizationEnabled) {
      return null;
    }
    return calculateMessageListVirtualWindow({
      itemHeights,
      scrollTop,
      viewportHeight: viewportHeight || 1,
      overscan: VIRTUAL_OVERSCAN,
    });
  }, [itemHeights, scrollTop, viewportHeight, virtualizationEnabled]);

  const visibleMessages = useMemo(() => {
    if (!virtualWindow) {
      return messages;
    }
    return messages.slice(virtualWindow.startIndex, virtualWindow.endIndex + 1);
  }, [messages, virtualWindow]);

  const topSpacerHeight = virtualWindow ? virtualWindow.offsetTop : 0;
  const bottomSpacerHeight = virtualWindow ? virtualWindow.offsetBottom : 0;

  const updateIsAtBottom = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;
    const threshold = 120;
    const atBottom = container.scrollHeight - container.scrollTop - container.clientHeight <= threshold;
    setIsAtBottom(atBottom);
  }, []);

  const measureRow = useCallback((messageId: string, node: HTMLDivElement | null) => {
    if (!node) {
      return;
    }
    const measured = Math.max(1, Math.ceil(node.getBoundingClientRect().height));
    setRowHeights((previous) => {
      if (previous[messageId] === measured) {
        return previous;
      }
      return {
        ...previous,
        [messageId]: measured,
      };
    });
  }, []);

  const scrollToBottom = useCallback(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, []);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    const syncViewport = () => {
      setViewportHeight(container.clientHeight);
      setScrollTop(container.scrollTop);
    };
    syncViewport();
    if (typeof ResizeObserver === 'undefined') {
      return;
    }
    const observer = new ResizeObserver(syncViewport);
    observer.observe(container);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    updateIsAtBottom();
  }, [messages.length, loading, updateIsAtBottom]);

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
      onScroll={(event) => {
        const nextScrollTop = event.currentTarget.scrollTop;
        setScrollTop(nextScrollTop);
        updateIsAtBottom();
      }}
      onWheelCapture={(event) => {
        event.stopPropagation();
      }}
      onTouchMoveCapture={(event) => {
        event.stopPropagation();
      }}
      sx={{
        flex: 1,
        height: '100%',
        minHeight: 0,
        overflowX: 'hidden',
        overflowY: 'auto',
        overscrollBehaviorY: 'contain',
        WebkitOverflowScrolling: 'touch',
        px: { xs: 2, sm: 3, md: 4 },
        pt: 3,
        pb: `${bottomInset}px`,
        scrollPaddingBottom: `${bottomInset + 24}px`,
        position: 'relative',
      }}
    >
      <Stack spacing={3} sx={{ maxWidth: 900, mx: 'auto' }}>
        {topSpacerHeight > 0 && <Box sx={{ height: `${topSpacerHeight}px` }} />}

        {visibleMessages.map((message) => {
          const hasMeasuredHeight = rowHeights[message.id] !== undefined;
          return (
            <Box
              key={message.id}
              ref={(node: HTMLDivElement | null) => {
                measureRow(message.id, node);
              }}
              sx={{
                minHeight:
                  virtualizationEnabled && !hasMeasuredHeight
                    ? `${DEFAULT_ROW_HEIGHT}px`
                    : undefined,
              }}
            >
              <MessageRow
                message={message}
                onToolApprovalSubmit={onToolApprovalSubmit}
                onClarificationSubmit={onClarificationSubmit}
                approvalLoading={approvalLoading}
                showPipeline={showPipeline}
                showEvidence={showEvidence}
                selectedAssistantId={selectedAssistantId}
                onAssistantSelect={onAssistantSelect}
                normalizeInlineEvidenceSection={normalizeInlineEvidenceSection}
              />
            </Box>
          );
        })}

        {bottomSpacerHeight > 0 && <Box sx={{ height: `${bottomSpacerHeight}px` }} />}

        {showThinking && (
          <Box sx={{ ml: 7 }}>
            <SparkleLoading variant="sparkle" />
          </Box>
        )}

        <div ref={bottomRef} />
      </Stack>

      {showScrollToBottom && (
        <Box
          sx={{
            position: 'sticky',
            bottom: `${scrollButtonBottom}px`,
            mt: 2,
            pointerEvents: 'none',
            px: { xs: 2, sm: 3, md: 4 },
          }}
        >
          <Box
            sx={{
              maxWidth: 900,
              mx: 'auto',
              display: 'flex',
              justifyContent: scrollButtonAlign === 'right' ? 'flex-end' : 'center',
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
      )}
    </Box>
  );
}
