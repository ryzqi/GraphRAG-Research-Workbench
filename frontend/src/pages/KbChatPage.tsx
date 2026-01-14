/**
 * 知识库代理页面
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Box,
  Container,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import SendIcon from '@mui/icons-material/Send';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import { EvidenceList } from '../components/EvidenceList';
import { KnowledgeBaseSelector } from '../components/KnowledgeBaseSelector';
import { Button, ErrorAlert, PageHeader } from '../components/ui';
import {
  type AgentMode,
  type ChatMessage,
  type ChatSession,
  type ChatMessageResponse,
  type EvidenceItem,
  createChatSession,
  sendMessage,
} from '../services/chats';
import { type KnowledgeBase, listKnowledgeBases } from '../services/knowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';

interface MessageWithEvidence {
  message: ChatMessage;
  evidence?: EvidenceItem[];
}

export function KbChatPage() {
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedKbIds, setSelectedKbIds] = useState<string[]>([]);
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<MessageWithEvidence[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // 加载知识库列表
  useEffect(() => {
    listKnowledgeBases()
      .then((res) => setKnowledgeBases(res.items))
      .catch((e) => setError(getErrorMessage(e)));
  }, []);

  // 切换知识库选择
  const toggleKb = useCallback((kbId: string) => {
    setSelectedKbIds((prev) =>
      prev.includes(kbId) ? prev.filter((id) => id !== kbId) : [...prev, kbId]
    );
  }, []);

  // 开始新会话
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
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [selectedKbIds]);

  // 发送消息
  const handleSend = useCallback(async () => {
    if (!session || !input.trim() || loading) return;

    const userContent = input.trim();
    setInput('');
    setLoading(true);
    setError(null);

    // 先添加用户消息
    const userMsg: MessageWithEvidence = {
      message: {
        id: crypto.randomUUID(),
        role: 'user',
        content: userContent,
        created_at: new Date().toISOString(),
      },
    };
    setMessages((prev) => [...prev, userMsg]);

    try {
      const response: ChatMessageResponse = await sendMessage(session.id, userContent);
      if (response.status !== 'succeeded') {
        throw new Error('知识库对话不支持工具审批流程');
      }
      setMessages((prev) => [
        ...prev,
        { message: response.assistant_message, evidence: response.evidence },
      ]);
    } catch (e) {
      setError(getErrorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [session, input, loading]);

  // 重置会话
  const resetSession = useCallback(() => {
    setSession(null);
    setMessages([]);
    setError(null);
  }, []);

  return (
    <Container maxWidth="md" sx={{ py: 3 }}>
      <PageHeader title="知识库代理" />

      {!session ? (
        // 知识库选择界面
        <Stack spacing={3}>
          <Typography variant="subtitle1" fontWeight={500}>
            选择知识库
          </Typography>

          <KnowledgeBaseSelector
            knowledgeBases={knowledgeBases}
            selectedIds={selectedKbIds}
            onToggle={toggleKb}
            loading={loading}
          />

          <Button
            variant="contained"
            onClick={startSession}
            disabled={selectedKbIds.length === 0}
            loading={loading}
            sx={{ alignSelf: 'flex-start' }}
          >
            开始对话
          </Button>
        </Stack>
      ) : (
        // 对话界面
        <Stack spacing={2}>
          <Paper
            variant="outlined"
            sx={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              p: 1.5,
              bgcolor: 'grey.50',
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
          </Paper>

          {/* 消息列表 */}
          <Paper
            variant="outlined"
            sx={{
              minHeight: 400,
              maxHeight: 600,
              overflowY: 'auto',
              p: 2,
            }}
          >
            {messages.length === 0 ? (
              <Box sx={{ color: 'text.disabled', textAlign: 'center', py: 5 }}>
                开始提问吧
              </Box>
            ) : (
              <Stack spacing={2}>
                {messages.map((item) => (
                  <Box key={item.message.id}>
                    <Box
                      sx={{
                        display: 'flex',
                        justifyContent: item.message.role === 'user' ? 'flex-end' : 'flex-start',
                      }}
                    >
                      <Paper
                        sx={{
                          maxWidth: '80%',
                          p: 1.5,
                          bgcolor: item.message.role === 'user' ? 'primary.main' : 'grey.100',
                          color: item.message.role === 'user' ? 'primary.contrastText' : 'text.primary',
                          borderRadius: 3,
                          whiteSpace: 'pre-wrap',
                        }}
                        elevation={0}
                      >
                        {item.message.content}
                      </Paper>
                    </Box>
                    {item.evidence && item.evidence.length > 0 && (
                      <Box sx={{ mt: 1.5, ml: 2 }}>
                        <EvidenceList evidence={item.evidence} />
                      </Box>
                    )}
                  </Box>
                ))}
              </Stack>
            )}
          </Paper>

          {/* 输入框 */}
          <Stack direction="row" spacing={1}>
            <TextField
              fullWidth
              size="small"
              placeholder="输入你的问题..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
              disabled={loading}
            />
            <IconButton
              color="primary"
              onClick={handleSend}
              disabled={!input.trim() || loading}
              sx={{
                bgcolor: 'primary.main',
                color: 'primary.contrastText',
                '&:hover': { bgcolor: 'primary.dark' },
                '&.Mui-disabled': { bgcolor: 'action.disabledBackground' },
              }}
            >
              <SendIcon />
            </IconButton>
          </Stack>
        </Stack>
      )}

      <ErrorAlert error={error} onClose={() => setError(null)} />
    </Container>
  );
}
