/**
 * 知识库问答页面（Gemini 风格重构）
 */
import { useCallback, useState } from 'react';
import { Box, Stack, Typography } from '@mui/material';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { Button } from '../components/ui/Button';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { KnowledgeBaseSelector } from '../components/KnowledgeBaseSelector';
import {
  WelcomeScreen,
  MessageList,
  InputComposer,
  type ChatMessage,
} from '../components/chat';
import {
  type AgentMode,
  type ChatSession,
  type ChatMessageResponse,
  createChatSession,
  sendMessage,
  streamChatMessage,
} from '../services/chats';
import { useKnowledgeBases } from '../hooks/queries';
import { useRecentHistory } from '../hooks/useRecentHistory';
import { getErrorMessage } from '../lib/errorHandler';
import { parseSseJson } from '../lib/sse';
import { createThinkParser } from '../lib/thinkParser';

export function KbChatPage() {
  const knowledgeBasesQuery = useKnowledgeBases();
  const knowledgeBases = knowledgeBasesQuery.data ?? [];

  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { upsertSession } = useRecentHistory();

  const mergedError =
    error ?? (knowledgeBasesQuery.error ? getErrorMessage(knowledgeBasesQuery.error) : null);

  const updateMessage = useCallback(
    (id: string, updater: (msg: ChatMessage) => ChatMessage) => {
      setMessages((prev) => prev.map((msg) => (msg.id === id ? updater(msg) : msg)));
    },
    []
  );

  const handleCloseError = () => {
    if (error) {
      setError(null);
      return;
    }
    knowledgeBasesQuery.refetch();
  };

  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  const startSession = useCallback(async () => {
    if (selectedKbIds.length === 0) {
      setError('请至少选择一个知识库');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const newSession = await createChatSession({
        session_type: 'kb_chat',
        selected_kb_ids: selectedKbIds,
        allow_external: false,
        mode: 'single_agent' as AgentMode,
      });
      setSession(newSession);
      setMessages([]);

      // 更新 Recent 历史
      upsertSession({
        sessionId: newSession.id,
        title: '知识库问答',
        type: 'kb_chat',
        updatedAt: new Date().toISOString(),
      });
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds, upsertSession]);

  const handleSend = useCallback(async () => {
    if (!session || !input.trim() || loading) return;

    const userContent = input.trim();
    const assistantId = `assistant-${Date.now()}`;
    const thinkParser = createThinkParser();
    setInput('');
    setLoading(true);
    setError(null);

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: userContent,
    };
    setMessages((prev) => [
      ...prev,
      userMsg,
      { id: assistantId, role: 'assistant', content: '', think: '', isStreaming: true },
    ]);

    // 更新会话标题
    upsertSession({
      sessionId: session.id,
      title: userContent.slice(0, 30) + (userContent.length > 30 ? '...' : ''),
      type: 'kb_chat',
      updatedAt: new Date().toISOString(),
    });

    const fallbackToJson = async () => {
      const response: ChatMessageResponse = await sendMessage(session.id, userContent);
      if (response.status !== 'succeeded') {
        throw new Error('知识库对话不支持工具审批流程');
      }
      updateMessage(assistantId, () => ({
        id: response.assistant_message.id,
        role: 'assistant',
        content: response.assistant_message.content,
        evidence: response.evidence,
        isStreaming: false,
      }));
    };

    let hadStreamEvent = false;

    try {
      const stream = await streamChatMessage(session.id, userContent);
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

        if (event.event === 'final') {
          const data = parseSseJson<ChatMessageResponse>(event.data);
          if (data.status === 'succeeded') {
            updateMessage(assistantId, (msg) => ({
              ...msg,
              id: data.assistant_message.id,
              content: data.assistant_message.content,
              evidence: data.evidence,
              runId: data.run.id,
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
        setError(getErrorMessage(e));
        setLoading(false);
        return;
      }
      try {
        await fallbackToJson();
      } catch (fallbackError) {
        setError(getErrorMessage(fallbackError));
      }
    } finally {
      setLoading(false);
    }
  }, [session, input, loading, upsertSession, updateMessage]);

  const resetSession = useCallback(() => {
    setSession(null);
    setMessages([]);
    setError(null);
  }, []);

  // 知识库选择界面
  if (!session) {
    return (
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          minHeight: 'calc(100vh - 64px)',
        }}
      >
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="知识库问答"
            subtitle="选择知识库，开始基于您的文档进行智能问答"
            suggestions={[]}
          />

          <Box sx={{ maxWidth: 800, mx: 'auto', px: 3, width: '100%' }}>
            <Stack spacing={3}>
              <Typography variant="subtitle1" fontWeight={500}>
                选择知识库
              </Typography>

              <KnowledgeBaseSelector
                knowledgeBases={knowledgeBases}
                selectedIds={selectedKbIds}
                onToggle={toggleKb}
                loading={loading || knowledgeBasesQuery.isLoading}
              />

              <Button
                variant="contained"
                onClick={startSession}
                disabled={knowledgeBasesQuery.isLoading || selectedKbIds.length === 0}
                loading={loading}
                sx={{ alignSelf: 'flex-start' }}
              >
                开始对话
              </Button>
            </Stack>
          </Box>
        </Box>

        <ErrorAlert error={mergedError} onClose={handleCloseError} />
      </Box>
    );
  }

  // 对话界面
  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 'calc(100vh - 64px)',
      }}
    >
      {/* 顶部栏 */}
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          px: { xs: 2, md: 4 },
          py: 1.5,
          borderBottom: 1,
          borderColor: 'divider',
        }}
      >
        <Typography variant="body2" color="text.secondary">
          已选择 {session.selected_kb_ids?.length || 0} 个知识库
        </Typography>
        <Button
          variant="outlined"
          size="small"
          startIcon={<RestartAltIcon />}
          onClick={resetSession}
        >
          重新选择
        </Button>
      </Box>

      {/* 消息区域 */}
      {messages.length === 0 ? (
        <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <WelcomeScreen
            title="开始提问吧"
            subtitle="基于您选择的知识库，我会为您提供精准的回答"
            suggestions={[]}
          />
        </Box>
      ) : (
        <MessageList messages={messages} loading={loading} />
      )}

      {/* 错误提示 */}
      <ErrorAlert error={mergedError} onClose={handleCloseError} />

      {/* 底部输入区 */}
      <Box
        sx={{
          p: { xs: 2, md: 3 },
          bgcolor: 'background.default',
          borderTop: messages.length > 0 ? 1 : 0,
          borderColor: 'divider',
        }}
      >
        <Box sx={{ maxWidth: 800, mx: 'auto' }}>
          <InputComposer
            value={input}
            onChange={setInput}
            onSend={handleSend}
            disabled={loading}
            loading={loading}
            placeholder="输入你的问题..."
          />
        </Box>
      </Box>
    </Box>
  );
}
