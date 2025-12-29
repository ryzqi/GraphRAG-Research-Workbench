/**
 * 提交沉淀组件
 */

import { useState } from 'react';
import { createProposal, type ProposalCreate } from '../services/knowledgeUpdates';

interface KnowledgeUpdateSubmitProps {
  runId: string;
  kbIds: string[];
  reportContent?: string;
  onSuccess?: () => void;
}

export function KnowledgeUpdateSubmit({
  runId,
  kbIds,
  reportContent,
  onSuccess,
}: KnowledgeUpdateSubmitProps) {
  const [selectedKbId, setSelectedKbId] = useState(kbIds[0] || '');
  const [summary, setSummary] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const handleSubmit = async () => {
    if (!selectedKbId || !summary.trim()) {
      setError('请选择知识库并填写摘要');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const data: ProposalCreate = {
        kb_id: selectedKbId,
        source_run_id: runId,
        summary: summary.trim(),
        payload: {
          report_excerpt: reportContent?.slice(0, 1000) || '',
        },
      };
      await createProposal(data);
      setSuccess(true);
      onSuccess?.();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  if (success) {
    return (
      <div
        style={{
          padding: 16,
          background: '#f0fdf4',
          border: '1px solid #bbf7d0',
          borderRadius: 8,
          color: '#166534',
        }}
      >
        候选沉淀已提交，等待审核
      </div>
    );
  }

  return (
    <div
      style={{
        padding: 16,
        border: '1px solid #e5e7eb',
        borderRadius: 8,
        background: '#fafafa',
      }}
    >
      <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12 }}>
        提交候选沉淀
      </h3>

      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>
          目标知识库
        </label>
        <select
          value={selectedKbId}
          onChange={(e) => setSelectedKbId(e.target.value)}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid #d1d5db',
            borderRadius: 6,
            fontSize: 14,
          }}
        >
          {kbIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginBottom: 12 }}>
        <label style={{ display: 'block', fontSize: 13, marginBottom: 4 }}>
          变更摘要
        </label>
        <textarea
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder="描述拟沉淀的内容..."
          rows={3}
          style={{
            width: '100%',
            padding: '8px 12px',
            border: '1px solid #d1d5db',
            borderRadius: 6,
            fontSize: 14,
            resize: 'vertical',
          }}
        />
      </div>

      {error && (
        <div
          style={{
            marginBottom: 12,
            padding: 8,
            background: '#fef2f2',
            border: '1px solid #fecaca',
            borderRadius: 6,
            color: '#dc2626',
            fontSize: 13,
          }}
        >
          {error}
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={loading || !summary.trim()}
        style={{
          padding: '8px 16px',
          background: loading || !summary.trim() ? '#9ca3af' : '#3b82f6',
          color: '#fff',
          border: 'none',
          borderRadius: 6,
          cursor: loading || !summary.trim() ? 'not-allowed' : 'pointer',
          fontSize: 14,
        }}
      >
        {loading ? '提交中...' : '提交沉淀'}
      </button>
    </div>
  );
}
