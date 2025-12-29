/**
 * 反馈表单组件
 */

import { useState } from 'react';
import { createFeedback } from '../services/feedback';

interface FeedbackFormProps {
  runId: string;
  onSuccess?: () => void;
}

export function FeedbackForm({ runId, onSuccess }: FeedbackFormProps) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await createFeedback({ run_id: runId, rating, comment: comment || undefined });
      setSubmitted(true);
      onSuccess?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : '提交失败');
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return <div style={{ color: '#059669', padding: 8 }}>感谢您的反馈！</div>;
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <label style={{ display: 'block', marginBottom: 4, fontWeight: 500 }}>评分</label>
        <div style={{ display: 'flex', gap: 4 }}>
          {[1, 2, 3, 4, 5].map((n) => (
            <button
              key={n}
              type="button"
              onClick={() => setRating(n)}
              style={{
                width: 32,
                height: 32,
                borderRadius: 4,
                border: 'none',
                background: n <= rating ? '#fbbf24' : '#e5e7eb',
                cursor: 'pointer',
                fontSize: 16,
              }}
            >
              ★
            </button>
          ))}
        </div>
      </div>
      <div>
        <label style={{ display: 'block', marginBottom: 4, fontWeight: 500 }}>反馈内容（可选）</label>
        <textarea
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="请输入您的反馈..."
          rows={3}
          style={{ width: '100%', padding: 8, borderRadius: 4, border: '1px solid #d1d5db' }}
        />
      </div>
      {error && <div style={{ color: '#dc2626' }}>{error}</div>}
      <button
        type="submit"
        disabled={submitting}
        style={{
          padding: '8px 16px',
          background: '#111827',
          color: '#fff',
          border: 'none',
          borderRadius: 4,
          cursor: submitting ? 'not-allowed' : 'pointer',
          opacity: submitting ? 0.6 : 1,
        }}
      >
        {submitting ? '提交中...' : '提交反馈'}
      </button>
    </form>
  );
}
