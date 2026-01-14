import { useState, useCallback } from 'react';
import {
  createChatSession,
  resumeToolApproval,
  sendMessage,
  type ChatMessageResponse,
  type ChatSession,
  type EvidenceItem,
  type AgentRun,
  type PendingToolCall,
} from '../services/chats';
import type { ToolInvocationSummary } from '../services/extensions';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  evidence?: EvidenceItem[];
  run?: AgentRun;
  invocations?: ToolInvocationSummary[];
  pendingToolApproval?: {
    threadId: string;
    interruptId: string | null;
    message: string | null;
    toolCalls: PendingToolCall[];
  };
}

export function GeneralChatPage() {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allowExternal, setAllowExternal] = useState(false);

  const hasPendingApproval = messages.some((m) => Boolean(m.pendingToolApproval));

  const startSession = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const newSession = await createChatSession({
        session_type: 'general_chat',
        allow_external: allowExternal,
        mode: 'single_agent',
      });
      setSession(newSession);
      setMessages([]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建会话失败');
    } finally {
      setLoading(false);
    }
  }, [allowExternal]);

  const handleSend = useCallback(async () => {
    if (!session || !input.trim() || loading || hasPendingApproval) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: 'user',
      content: input.trim(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setError(null);

    try {
      const response: ChatMessageResponse = await sendMessage(session.id, userMessage.content);

      if (response.status === 'pending_tool_approval') {
        const pendingMessage: Message = {
          id: `pending-${response.run.id}`,
          role: 'assistant',
          content: response.message ?? '需要你确认将要执行的工具调用。',
          run: response.run,
          pendingToolApproval: {
            threadId: response.thread_id,
            interruptId: response.interrupt_id,
            message: response.message,
            toolCalls: response.pending_tool_calls,
          },
        };
        setMessages((prev) => [...prev, pendingMessage]);
        return;
      }

      const invocations =
        (response.run.stage_summaries?.extensions as { invocations?: ToolInvocationSummary[] })
          ?.invocations ?? [];

      setMessages((prev) => [
        ...prev,
        {
          id: response.assistant_message.id,
          role: 'assistant',
          content: response.assistant_message.content,
          evidence: response.evidence,
          run: response.run,
          invocations,
        },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : '发送消息失败');
    } finally {
      setLoading(false);
    }
  }, [session, input, loading, hasPendingApproval]);

  const handleToolApproval = useCallback(
    async (pendingMessageId: string, runId: string, approved: boolean) => {
      if (!session || loading) return;
      setLoading(true);
      setError(null);
      try {
        const response: ChatMessageResponse = await resumeToolApproval(session.id, runId, approved);

        if (response.status === 'pending_tool_approval') {
          setMessages((prev) =>
            prev.map((m) =>
              m.id === pendingMessageId
                ? {
                    ...m,
                    content: response.message ?? '仍需要审批工具调用。',
                    run: response.run,
                    pendingToolApproval: {
                      threadId: response.thread_id,
                      interruptId: response.interrupt_id,
                      message: response.message,
                      toolCalls: response.pending_tool_calls,
                    },
                  }
                : m
            )
          );
          return;
        }

        const invocations =
          (response.run.stage_summaries?.extensions as { invocations?: ToolInvocationSummary[] })
            ?.invocations ?? [];

        setMessages((prev) =>
          prev.map((m) =>
            m.id === pendingMessageId
              ? {
                  id: response.assistant_message.id,
                  role: 'assistant',
                  content: response.assistant_message.content,
                  evidence: response.evidence,
                  run: response.run,
                  invocations,
                }
              : m
          )
        );
      } catch (e) {
        setError(e instanceof Error ? e.message : '恢复执行失败');
      } finally {
        setLoading(false);
      }
    },
    [session, loading]
  );

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 900, margin: '0 auto' }}>
      <h1 style={{ marginBottom: 16 }}>全能代理</h1>
      <p style={{ color: '#6b7280', marginBottom: 24 }}>
        通用对话助手，可选启用 MCP 扩展增强能力
      </p>

      {!session ? (
        <div style={{ marginBottom: 24 }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <input
              type="checkbox"
              checked={allowExternal}
              onChange={(e) => setAllowExternal(e.target.checked)}
            />
            <span>启用外部扩展（MCP）</span>
          </label>
          <button
            onClick={startSession}
            disabled={loading}
            style={{
              padding: '10px 20px',
              background: '#111827',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor: loading ? 'not-allowed' : 'pointer',
            }}
          >
            {loading ? '创建中...' : '开始对话'}
          </button>
        </div>
      ) : (
        <>
          <div
            style={{
              background: '#f9fafb',
              borderRadius: 8,
              padding: 16,
              marginBottom: 16,
              minHeight: 400,
              maxHeight: 500,
              overflowY: 'auto',
            }}
          >
            {messages.length === 0 ? (
              <p style={{ color: '#9ca3af', textAlign: 'center', marginTop: 100 }}>
                开始提问吧...
              </p>
            ) : (
              messages.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    marginBottom: 16,
                    padding: 12,
                    background: msg.role === 'user' ? '#e0e7ff' : '#fff',
                    borderRadius: 8,
                    border: '1px solid #e5e7eb',
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 4 }}>
                    {msg.role === 'user' ? '你' : '助手'}
                  </div>
                  <div style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</div>

                  {msg.pendingToolApproval && (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 10,
                        background: '#fff7ed',
                        borderRadius: 6,
                        border: '1px solid #fed7aa',
                        fontSize: 13,
                      }}
                    >
                      <div style={{ fontWeight: 600, marginBottom: 6 }}>待审批工具：</div>
                      {msg.pendingToolApproval.toolCalls.length === 0 ? (
                        <div style={{ color: '#6b7280' }}>（无）</div>
                      ) : (
                        msg.pendingToolApproval.toolCalls.map((t, idx) => (
                          <div key={idx} style={{ marginLeft: 8, marginBottom: 4 }}>
                            • {t.tool_name}
                            {t.extension_name ? ` (${t.extension_name})` : ''}
                          </div>
                        ))
                      )}
                      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
                        <button
                          onClick={() =>
                            msg.run?.id &&
                            handleToolApproval(msg.id, msg.run.id, true)
                          }
                          disabled={loading || !msg.run?.id}
                          style={{
                            padding: '6px 10px',
                            background: '#111827',
                            color: '#fff',
                            border: 'none',
                            borderRadius: 6,
                            cursor: loading ? 'not-allowed' : 'pointer',
                          }}
                        >
                          允许执行
                        </button>
                        <button
                          onClick={() =>
                            msg.run?.id &&
                            handleToolApproval(msg.id, msg.run.id, false)
                          }
                          disabled={loading || !msg.run?.id}
                          style={{
                            padding: '6px 10px',
                            background: '#e5e7eb',
                            color: '#111827',
                            border: 'none',
                            borderRadius: 6,
                            cursor: loading ? 'not-allowed' : 'pointer',
                          }}
                        >
                          拒绝执行
                        </button>
                      </div>
                    </div>
                  )}

                  {/* 扩展调用摘要 */}
                  {msg.invocations && msg.invocations.length > 0 && (
                    <div
                      style={{
                        marginTop: 12,
                        padding: 8,
                        background: '#fef3c7',
                        borderRadius: 4,
                        fontSize: 13,
                      }}
                    >
                      <div style={{ fontWeight: 600, marginBottom: 4 }}>扩展调用：</div>
                      {msg.invocations.map((inv, idx) => (
                        <div key={idx} style={{ marginLeft: 8 }}>
                          • {inv.tool_name}
                          {inv.extension_name && ` (${inv.extension_name})`}
                          {' - '}
                          <span
                            style={{
                              color: inv.status === 'succeeded' ? '#059669' : '#dc2626',
                            }}
                          >
                            {inv.status === 'succeeded' ? '成功' : '失败'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* 运行信息 */}
                  {msg.run && (
                    <div style={{ marginTop: 8, fontSize: 12, color: '#6b7280' }}>
                      耗时: {msg.run.metrics?.latency_ms ?? '-'}ms | 扩展调用:{' '}
                      {msg.run.metrics?.extension_calls ?? 0}
                    </div>
                  )}
                </div>
              ))
            )}
            {loading && (
              <div style={{ textAlign: 'center', color: '#6b7280' }}>思考中...</div>
            )}
          </div>

          {error && (
            <div
              style={{
                padding: 12,
                background: '#fef2f2',
                color: '#dc2626',
                borderRadius: 8,
                marginBottom: 16,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="输入问题..."
              disabled={loading || hasPendingApproval}
              style={{
                flex: 1,
                padding: 12,
                borderRadius: 8,
                border: '1px solid #d1d5db',
                resize: 'none',
                minHeight: 60,
              }}
            />
            <button
              onClick={handleSend}
              disabled={loading || hasPendingApproval || !input.trim()}
              style={{
                padding: '12px 24px',
                background:
                  loading || hasPendingApproval || !input.trim() ? '#9ca3af' : '#111827',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                cursor: loading || hasPendingApproval || !input.trim() ? 'not-allowed' : 'pointer',
              }}
            >
              发送
            </button>
          </div>

          <div style={{ marginTop: 16, fontSize: 13, color: '#6b7280' }}>
            会话 ID: {session.id} | 外部扩展: {session.allow_external ? '已启用' : '未启用'}
          </div>
        </>
      )}
    </div>
  );
}

export default GeneralChatPage;
