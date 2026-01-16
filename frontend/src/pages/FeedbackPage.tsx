/**
 * 反馈管理页面
 */

import { useState } from 'react';
import type { FeedbackStatus } from '../services/feedback';
import { useFeedbackList, useUpdateFeedback } from '../hooks/queries';
import { getErrorMessage } from '../lib/errorHandler';

const STATUS_LABELS: Record<FeedbackStatus, string> = {
  pending: '待处理',
  reviewed: '已查看',
  resolved: '已解决',
  dismissed: '已忽略',
};

const STATUS_COLORS: Record<FeedbackStatus, string> = {
  pending: '#f59e0b',
  reviewed: '#3b82f6',
  resolved: '#10b981',
  dismissed: '#6b7280',
};

export function FeedbackPage() {
  const [filterStatus, setFilterStatus] = useState<FeedbackStatus | ''>('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editStatus, setEditStatus] = useState<FeedbackStatus>('pending');
  const [editNote, setEditNote] = useState('');

  const feedbackQuery = useFeedbackList(filterStatus);
  const updateMutation = useUpdateFeedback();

  const items = feedbackQuery.data ?? [];
  const loading = feedbackQuery.isPending || feedbackQuery.isFetching;

  const mergedError =
    (updateMutation.error ? getErrorMessage(updateMutation.error) : null) ??
    (feedbackQuery.error ? getErrorMessage(feedbackQuery.error) : null);

  const handleCloseError = () => {
    if (updateMutation.error) {
      updateMutation.reset();
      return;
    }
    if (feedbackQuery.error) {
      feedbackQuery.refetch();
    }
  };

  const handleUpdate = (id: string) => {
    updateMutation.mutate(
      { id, data: { status: editStatus, resolution_note: editNote || undefined } },
      { onSuccess: () => setEditingId(null) }
    );
  };

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ marginBottom: 16 }}>反馈管理</h1>

      {mergedError && (
        <div
          style={{
            padding: 12,
            background: '#fef2f2',
            color: '#dc2626',
            borderRadius: 8,
            marginBottom: 16,
          }}
        >
          {mergedError}
          <button onClick={handleCloseError} style={{ marginLeft: 8, cursor: 'pointer' }}>
            ×
          </button>
        </div>
      )}

      <div style={{ marginBottom: 16 }}>
        <label style={{ marginRight: 8 }}>状态筛选：</label>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value as FeedbackStatus | '')}
          style={{ padding: '4px 8px', borderRadius: 4, border: '1px solid #d1d5db' }}
        >
          <option value="">全部</option>
          {Object.entries(STATUS_LABELS).map(([k, v]) => (
            <option key={k} value={k}>{v}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <div>加载中...</div>
      ) : items.length === 0 ? (
        <div style={{ color: '#6b7280' }}>暂无反馈记录</div>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
              <th style={{ textAlign: 'left', padding: 8 }}>评分</th>
              <th style={{ textAlign: 'left', padding: 8 }}>反馈内容</th>
              <th style={{ textAlign: 'left', padding: 8 }}>状态</th>
              <th style={{ textAlign: 'left', padding: 8 }}>处理说明</th>
              <th style={{ textAlign: 'left', padding: 8 }}>创建时间</th>
              <th style={{ textAlign: 'left', padding: 8 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                <td style={{ padding: 8 }}>{'★'.repeat(item.rating)}</td>
                <td style={{ padding: 8, maxWidth: 300 }}>{item.comment || '-'}</td>
                <td style={{ padding: 8 }}>
                  <span
                    style={{
                      padding: '2px 8px',
                      borderRadius: 4,
                      background: STATUS_COLORS[item.status],
                      color: '#fff',
                      fontSize: 12,
                    }}
                  >
                    {STATUS_LABELS[item.status]}
                  </span>
                </td>
                <td style={{ padding: 8 }}>{item.resolution_note || '-'}</td>
                <td style={{ padding: 8, fontSize: 12, color: '#6b7280' }}>
                  {new Date(item.created_at).toLocaleString()}
                </td>
                <td style={{ padding: 8 }}>
                  {editingId === item.id ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                      <select
                        value={editStatus}
                        onChange={(e) => setEditStatus(e.target.value as FeedbackStatus)}
                        style={{ padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }}
                      >
                        {Object.entries(STATUS_LABELS).map(([k, v]) => (
                          <option key={k} value={k}>{v}</option>
                        ))}
                      </select>
                      <input
                        type="text"
                        value={editNote}
                        onChange={(e) => setEditNote(e.target.value)}
                        placeholder="处理说明"
                        style={{ padding: 4, borderRadius: 4, border: '1px solid #d1d5db' }}
                      />
                      <div style={{ display: 'flex', gap: 4 }}>
                        <button
                          onClick={() => handleUpdate(item.id)}
                          style={{
                            padding: '4px 8px',
                            background: '#111827',
                            color: '#fff',
                            border: 'none',
                            borderRadius: 4,
                            cursor: 'pointer',
                          }}
                        >
                          保存
                        </button>
                        <button
                          onClick={() => setEditingId(null)}
                          style={{
                            padding: '4px 8px',
                            background: '#e5e7eb',
                            border: 'none',
                            borderRadius: 4,
                            cursor: 'pointer',
                          }}
                        >
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => {
                        setEditingId(item.id);
                        setEditStatus(item.status);
                        setEditNote(item.resolution_note || '');
                      }}
                      style={{
                        padding: '4px 8px',
                        background: '#3b82f6',
                        color: '#fff',
                        border: 'none',
                        borderRadius: 4,
                        cursor: 'pointer',
                      }}
                    >
                      处理
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
