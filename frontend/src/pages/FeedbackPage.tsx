/**
 * 反馈管理页面
 */

import { useEffect, useState } from 'react';
import {
  Feedback,
  FeedbackStatus,
  listFeedback,
  updateFeedback,
} from '../services/feedback';

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
  const [items, setItems] = useState<Feedback[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterStatus, setFilterStatus] = useState<FeedbackStatus | ''>('');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editStatus, setEditStatus] = useState<FeedbackStatus>('pending');
  const [editNote, setEditNote] = useState('');

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await listFeedback(filterStatus ? { status: filterStatus } : undefined);
      setItems(res.items);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [filterStatus]);

  const handleUpdate = async (id: string) => {
    await updateFeedback(id, { status: editStatus, resolution_note: editNote || undefined });
    setEditingId(null);
    fetchData();
  };

  return (
    <div style={{ padding: 24 }}>
      <h1 style={{ marginBottom: 16 }}>反馈管理</h1>

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
