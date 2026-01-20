/**
 * 普通代理聊天页面（Gemini 风格重构）
 */
import { useCallback, useState } from 'react';
import { Box, Chip, FormControlLabel, Stack, Switch, Typography } from '@mui/material';
import {
  createChatSession,
  resumeToolApproval,
  sendMessage,
  streamChatMessage,
  streamResumeToolApproval,
  type ChatMessageResponse,
  type ChatSession,
} from '../services/chats';
import type { ToolInvocationSummary } from '../services/extensions';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { parseSseJson } from '../lib/sse';
import { createThinkParser } from '../lib/thinkParser';
import {
  WelcomeScreen,
  MessageList,
  InputComposer,
  type ChatMessage,
} from '../components/chat';
import { useRecentHistory } from '../hooks/useRecentHistory';

const quickPrompts = [
  { label: '总结要点', value: '请帮我总结以下内容：' },
  { label: '生成清单', value: '请把目标拆成可执行的行动清单：' },
  { label: '优化表达', value: '请把下面内容润色成更专业的表达：' },
  { label: '风险与下一步', value: '请列出潜在风险与下一步建议：' },
];

export function GeneralChatPage() {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowExternal, setAllowExternal] = useState(false);

  const { upsertSession } = useRecentHistory();

  const hasPendingApproval = messages.some((m) => Boolean(m.pendingToolApproval));
  const isInputDisabled = loading || hasPendingApproval;

  const updateMessage = useCallback(
    (id: string, updater: (msg: ChatMessage) => ChatMessage) => {
      setMessages((prev) => prev.map((msg) => (msg.id === id ? updater(msg) : msg)));
    },
    []
  );

  const createSession = useCallback(async () => {
    const newSession = await createChatSession({
      session_type: 'general_chat',
      allow_external: allowExternal,
      mode: 'single_agent',
    });
    setSession(newSession);

    // 更新 Recent 历史
    upsertSession({
      sessionId: newSession.id,
      title: '新对话',
      type: 'general_chat',
      updatedAt: new Date().toISOString(),
    });

    return newSession;
  }, [allowExternal, upsertSession]);

  const handleNewChat = useCallback(() => {
    setSession(null);
    setMessages([]);
    setError(null);
  }, []);

  const handleSend = useCallback(async () => {
    const content = input.trim();
    if (!content || loading || hasPendingApproval) return;

    const userMessage: ChatMessage = {
      id: `user-${Date.now()}`,
      role: 'user',
      content,
    };
    const assistantId = `assistant-${Date.now()}`;
    const thinkParser = createThinkParser();

    setMessages((prev) => [
      ...prev,
      userMessage,
      {
        id: assistantId,
        role: 'assistant',
        content: '',
        think: '',
        isStreaming: true,
      },
    ]);
    setInput('');
    setLoading(true);
    setError(null);

    let activeSession: ChatSession;
    try {
      activeSession = session ?? (await createSession());
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建会话失败');
      setLoading(false);
      return;
    }

    // 更新会话标题
    upsertSession({
      sessionId: activeSession.id,
      title: content.slice(0, 30) + (content.length > 30 ? '...' : ''),
      type: 'general_chat',
      updatedAt: new Date().toISOString(),
    });

    const fallbackToJson = async () => {
      const response: ChatMessageResponse = await sendMessage(activeSession.id, content);
      if (response.status === 'pending_tool_approval') {
        updateMessage(assistantId, (msg) => ({
          ...msg,
          content: response.message ?? '需要你确认将要执行的工具调用。',
          runId: response.run.id,
          pendingToolApproval: {
            message: response.message,
            toolCalls: response.pending_tool_calls.map((call) => ({
              tool_name: call.tool_name,
              extension_name: call.extension_name ?? undefined,
            })),
          },
          think: '',
          isStreaming: false,
        }));
        return;
      }

      const invocations =
        (response.run.stage_summaries?.extensions as { invocations?: ToolInvocationSummary[] })
          ?.invocations ?? [];

      updateMessage(assistantId, () => ({
        id: response.assistant_message.id,
        role: 'assistant',
        content: response.assistant_message.content,
        evidence: response.evidence,
        runId: response.run.id,
        invocations: invocations.map((inv) => ({
          tool_name: inv.tool_name,
          extension_name: inv.extension_name ?? undefined,
          status: inv.status === 'succeeded' ? 'succeeded' : 'failed',
        })),
        isStreaming: false,
      }));
    };

    let hadStreamEvent = false;

    try {
      const stream = await streamChatMessage(activeSession.id, content);
      for await (const event of stream) {
        hadStreamEvent = true;
        if (event.event === 'meta') {
          const meta = parseSseJson<{ run_id?: string }>(event.data);
          if (meta.run_id) {
            updateMessage(assistantId, (msg) => ({ ...msg, runId: meta.run_id }));
          }
        }

        if (event.event === 'delta') {
          const data = parseSseJson<{ text: string }>(event.data);
          const { answerDelta, thinkDelta } = thinkParser.feed(data.text || '');
          if (answerDelta || thinkDelta) {
            updateMessage(assistantId, (msg) => ({
              ...msg,
              content: msg.content + answerDelta,
              think: (msg.think ?? '') + thinkDelta,
              isStreaming: true,
            }));
          }
        }

        if (event.event === 'interrupt') {
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (data.status === 'pending_tool_approval') {
            updateMessage(assistantId, (msg) => ({
              ...msg,
              content: data.message ?? '需要你确认将要执行的工具调用。',
              runId: data.run.id,
              pendingToolApproval: {
                message: data.message,
                toolCalls: data.pending_tool_calls.map((call) => ({
                  tool_name: call.tool_name,
                  extension_name: call.extension_name ?? undefined,
                })),
              },
              think: '',
              isStreaming: false,
            }));
            setLoading(false);
            return;
          }
        }

        if (event.event === 'final') {
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (data.status === 'succeeded') {
            const invocations =
              (data.run.stage_summaries?.extensions as { invocations?: ToolInvocationSummary[] })
                ?.invocations ?? [];
            updateMessage(assistantId, (msg) => ({
              ...msg,
              id: data.assistant_message.id,
              content: data.assistant_message.content,
              evidence: data.evidence,
              runId: data.run.id,
              invocations: invocations.map((inv) => ({
                tool_name: inv.tool_name,
                extension_name: inv.extension_name ?? undefined,
                status: inv.status === 'succeeded' ? 'succeeded' : 'failed',
              })),
              isStreaming: false,
            }));
          }
          setLoading(false);
          return;
        }

        if (event.event === 'error') {
          const err = parseSseJson<{ message?: string }>(event.data);
          throw new Error(err?.message ?? '流式响应失败');
        }
      }

      const flushed = thinkParser.flush();
      if (flushed.answerDelta || flushed.thinkDelta) {
        updateMessage(assistantId, (msg) => ({
          ...msg,
          content: msg.content + flushed.answerDelta,
          think: (msg.think ?? '') + flushed.thinkDelta,
        }));
      }
    } catch (e) {
      if (hadStreamEvent) {
        setError(e instanceof Error ? e.message : '发送消息失败');
        setLoading(false);
        return;
      }
      try {
        await fallbackToJson();
      } catch (fallbackError) {
        setError(fallbackError instanceof Error ? fallbackError.message : '发送消息失败');
      }
    } finally {
      setLoading(false);
    }
  }, [
    input,
    loading,
    hasPendingApproval,
    session,
    createSession,
    upsertSession,
    updateMessage,
  ]);

  const handleToolApproval = useCallback(
    async (pendingMessageId: string, runId: string, approved: boolean) => {
      if (!session || loading) return;
      setLoading(true);
      setError(null);

      const thinkParser = createThinkParser();
      updateMessage(pendingMessageId, (msg) => ({
        ...msg,
        content: '',
        think: '',
        pendingToolApproval: undefined,
        isStreaming: true,
      }));

      const fallbackToJson = async () => {
        const response: ChatMessageResponse = await resumeToolApproval(session.id, runId, approved);
        if (response.status === 'pending_tool_approval') {
          updateMessage(pendingMessageId, (msg) => ({
            ...msg,
            content: response.message ?? '仍需要审批工具调用。',
            runId: response.run.id,
            pendingToolApproval: {
              message: response.message,
              toolCalls: response.pending_tool_calls.map((call) => ({
                tool_name: call.tool_name,
                extension_name: call.extension_name ?? undefined,
              })),
            },
            think: '',
            isStreaming: false,
          }));
          return;
        }

        const invocations =
          (response.run.stage_summaries?.extensions as { invocations?: ToolInvocationSummary[] })
            ?.invocations ?? [];

        updateMessage(pendingMessageId, () => ({
          id: response.assistant_message.id,
          role: 'assistant' as const,
          content: response.assistant_message.content,
          evidence: response.evidence,
          runId: response.run.id,
          invocations: invocations.map((inv) => ({
            tool_name: inv.tool_name,
            extension_name: inv.extension_name ?? undefined,
            status: inv.status === 'succeeded' ? 'succeeded' : 'failed',
          })),
          isStreaming: false,
        }));
      };

      let hadStreamEvent = false;

      try {
        const stream = await streamResumeToolApproval(session.id, runId, approved);
        for await (const event of stream) {
          hadStreamEvent = true;
          if (event.event === 'meta') {
            const meta = parseSseJson<{ run_id?: string }>(event.data);
            if (meta.run_id) {
              updateMessage(pendingMessageId, (msg) => ({ ...msg, runId: meta.run_id }));
            }
          }

          if (event.event === 'delta') {
            const data = parseSseJson<{ text: string }>(event.data);
            const { answerDelta, thinkDelta } = thinkParser.feed(data.text || '');
            if (answerDelta || thinkDelta) {
              updateMessage(pendingMessageId, (msg) => ({
                ...msg,
                content: msg.content + answerDelta,
                think: (msg.think ?? '') + thinkDelta,
                isStreaming: true,
              }));
            }
          }

          if (event.event === 'interrupt') {
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (data.status === 'pending_tool_approval') {
              updateMessage(pendingMessageId, (msg) => ({
                ...msg,
                content: data.message ?? '仍需要审批工具调用。',
                runId: data.run.id,
                pendingToolApproval: {
                  message: data.message,
                  toolCalls: data.pending_tool_calls.map((call) => ({
                    tool_name: call.tool_name,
                    extension_name: call.extension_name ?? undefined,
                  })),
                },
                think: '',
                isStreaming: false,
              }));
              setLoading(false);
              return;
            }
          }

          if (event.event === 'final') {
            const data = parseSseJson<ChatMessageResponse>(event.data);
            if (data.status === 'succeeded') {
              const invocations =
                (data.run.stage_summaries?.extensions as { invocations?: ToolInvocationSummary[] })
                  ?.invocations ?? [];
              updateMessage(pendingMessageId, (msg) => ({
                ...msg,
                id: data.assistant_message.id,
                content: data.assistant_message.content,
                evidence: data.evidence,
                runId: data.run.id,
                invocations: invocations.map((inv) => ({
                  tool_name: inv.tool_name,
                  extension_name: inv.extension_name ?? undefined,
                  status: inv.status === 'succeeded' ? 'succeeded' : 'failed',
                })),
                isStreaming: false,
              }));
            }
            setLoading(false);
            return;
          }

          if (event.event === 'error') {
            const err = parseSseJson<{ message?: string }>(event.data);
            throw new Error(err?.message ?? '恢复执行失败');
          }
        }

        const flushed = thinkParser.flush();
        if (flushed.answerDelta || flushed.thinkDelta) {
          updateMessage(pendingMessageId, (msg) => ({
            ...msg,
            content: msg.content + flushed.answerDelta,
            think: (msg.think ?? '') + flushed.thinkDelta,
          }));
        }
      } catch (e) {
        if (hadStreamEvent) {
          setError(e instanceof Error ? e.message : '恢复执行失败');
          setLoading(false);
          return;
        }
        try {
          await fallbackToJson();
        } catch (fallbackError) {
          setError(fallbackError instanceof Error ? fallbackError.message : '恢复执行失败');
        }
      } finally {
        setLoading(false);
      }
    },
    [session, loading, updateMessage]
  );

  const handleSuggestionClick = (value: string) => {
    setInput(value);
  };

  const sessionBadgeLabel = session
    ? session.allow_external
      ? 'MCP 已启用'
      : 'MCP 未启用'
    : allowExternal
      ? 'MCP 将启用'
      : 'MCP 已关闭';

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 'calc(100vh - 64px)',
      }}
    >
      {/* 设置栏 */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 2,
          px: { xs: 2, md: 4 },
          py: 1.5,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <FormControlLabel
          control={
            <Switch
              size="small"
              checked={allowExternal}
              onChange={(event) => setAllowExternal(event.target.checked)}
              disabled={!!session}
            />
          }
          label={
            <Typography variant="body2" color="text.secondary">
              MCP 扩展
            </Typography>
          }
        />
        <Chip label={sessionBadgeLabel} size="small" variant="outlined" />
      </Box>

      {/* 消息区域 */}
      {messages.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="你好，需要我为你做些什么？"
            subtitle="输入你的目标，我会拆解步骤并提供可执行的建议。"
            suggestions={quickPrompts}
            onSuggestionClick={handleSuggestionClick}
            disabled={isInputDisabled}
          />
        </Box>
      ) : (
        <MessageList
          messages={messages}
          loading={loading}
          onToolApprove={(msgId, runId) => handleToolApproval(msgId, runId, true)}
          onToolReject={(msgId, runId) => handleToolApproval(msgId, runId, false)}
          approvalLoading={loading}
        />
      )}

      {/* 错误提示 */}
      <ErrorAlert error={error} onClose={() => setError(null)} />

      {/* 底部输入区 - Sticky 定位 */}
      <Box
        sx={{
          position: 'sticky',
          bottom: 0,
          p: { xs: 2, md: 3 },
          zIndex: 10,
        }}
      >
        <Box sx={{ maxWidth: 800, mx: 'auto' }}>
          <InputComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={isInputDisabled}
            loading={loading}
            placeholder={hasPendingApproval ? '等待工具审批完成...' : '输入消息...'}
          />
        </Box>
      </Box>

    </Box>
  );
}

export default GeneralChatPage;
