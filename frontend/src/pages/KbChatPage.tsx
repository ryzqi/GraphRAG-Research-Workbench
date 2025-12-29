/**
 * 知识库代理页面
 */

import { useCallback, useEffect, useState } from 'react';
import { EvidenceList } from '../components/EvidenceList';
import {
  type AgentMode,
  type ChatAnswerResponse,
  type ChatMessage,
  type ChatSession,
  type EvidenceItem,
  createChatSession,
  sendMessage,
} from '../services/chats';
import { type KnowledgeBase, listKnowledgeBases } from '../services/knowledgeBases';

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
      .catch((e) => setError(e.message));
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
    } catch (e: any) {
      setError(e.message);
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
      const response: ChatAnswerResponse = await sendMessage(session.id, userContent);
      const assistantMsg: MessageWithEvidence = {
        message: response.assistant_message,
        evidence: response.evidence,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (e: any) {
      setError(e.message);
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
    <div style={{ maxWidth: 900, margin: '0 auto', padding: 24 }}>
      <h1 style={{ fontSize: 24, fontWeight: 600, marginBottom: 24 }}>
        知识库代理
      </h1>

      {!session ? (
        // 知识库选择界面
        <div>
          <h2 style={{ fontSize: 16, fontWeight: 500, marginBottom: 16 }}>
            选择知识库
          </h2>

          {knowledgeBases.length === 0 ? (
            <div style={{ color: '#6b7280', padding: 16 }}>
              暂无可用知识库，请先创建知识库并导入资料
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
              {knowledgeBases.map((kb) => (
                <label
                  key={kb.id}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 12,
                    padding: 12,
                    border: '1px solid #e5e7eb',
                    borderRadius: 8,
                    cursor: 'pointer',
                    background: selectedKbIds.includes(kb.id) ? '#eff6ff' : '#fff',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={selectedKbIds.includes(kb.id)}
                    onChange={() => toggleKb(kb.id)}
                    style={{ marginTop: 2 }}
                  />
                  <div>
                    <div style={{ fontWeight: 500 }}>{kb.name}</div>
                    {kb.description && (
                      <div style={{ fontSize: 14, color: '#6b7280', marginTop: 4 }}>
                        {kb.description}
                      </div>
                    )}
                    {kb.tags && kb.tags.length > 0 && (
                      <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
                        {kb.tags.map((tag) => (
                          <span
                            key={tag}
                            style={{
                              fontSize: 12,
                              padding: '2px 8px',
                              background: '#e5e7eb',
                              borderRadius: 4,
                            }}
                          >
                            {tag}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                </label>
              ))}
            </div>
          )}

          <button
            onClick={startSession}
            disabled={selectedKbIds.length === 0 || loading}
            style={{
              padding: '10px 20px',
              background: selectedKbIds.length === 0 ? '#9ca3af' : '#3b82f6',
              color: '#fff',
              border: 'none',
              borderRadius: 8,
              cursor: selectedKbIds.length === 0 ? 'not-allowed' : 'pointer',
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {loading ? '创建中...' : '开始对话'}
          </button>
        </div>
      ) : (
        // 对话界面
        <div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 16,
              padding: 12,
              background: '#f3f4f6',
              borderRadius: 8,
            }}
          >
            <div style={{ fontSize: 14, color: '#6b7280' }}>
              已选择 {session.selected_kb_ids?.length || 0} 个知识库
            </div>
            <button
              onClick={resetSession}
              style={{
                padding: '6px 12px',
                background: '#fff',
                border: '1px solid #d1d5db',
                borderRadius: 6,
                cursor: 'pointer',
                fontSize: 14,
              }}
            >
              重新选择
            </button>
          </div>

          {/* 消息列表 */}
          <div
            style={{
              minHeight: 400,
              maxHeight: 600,
              overflowY: 'auto',
              marginBottom: 16,
              padding: 16,
              border: '1px solid #e5e7eb',
              borderRadius: 8,
            }}
          >
            {messages.length === 0 ? (
              <div style={{ color: '#9ca3af', textAlign: 'center', padding: 40 }}>
                开始提问吧
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                {messages.map((item, index) => (
                  <div key={index}>
                    <div
                      style={{
                        display: 'flex',
                        justifyContent:
                          item.message.role === 'user' ? 'flex-end' : 'flex-start',
                      }}
                    >
                      <div
                        style={{
                          maxWidth: '80%',
                          padding: 12,
                          borderRadius: 12,
                          background:
                            item.message.role === 'user' ? '#3b82f6' : '#f3f4f6',
                          color: item.message.role === 'user' ? '#fff' : '#111827',
                          whiteSpace: 'pre-wrap',
                        }}
                      >
                        {item.message.content}
                      </div>
                    </div>
                    {item.evidence && item.evidence.length > 0 && (
                      <div style={{ marginTop: 12, marginLeft: 16 }}>
                        <EvidenceList evidence={item.evidence} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* 输入框 */}
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && handleSend()}
              placeholder="输入你的问题..."
              disabled={loading}
              style={{
                flex: 1,
                padding: '10px 14px',
                border: '1px solid #d1d5db',
                borderRadius: 8,
                fontSize: 14,
                outline: 'none',
              }}
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || loading}
              style={{
                padding: '10px 20px',
                background: !input.trim() || loading ? '#9ca3af' : '#3b82f6',
                color: '#fff',
                border: 'none',
                borderRadius: 8,
                cursor: !input.trim() || loading ? 'not-allowed' : 'pointer',
                fontSize: 14,
                fontWeight: 500,
              }}
            >
              {loading ? '思考中...' : '发送'}
            </button>
          </div>
        </div>
      )}

      {error && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 8,
            color: '#dc2626',
            fontSize: 14,
          }}
        >
          {error}
        </div>
      )}
    </div>
  );
}
