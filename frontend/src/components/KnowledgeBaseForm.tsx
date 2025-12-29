/**
 * 知识库表单组件（创建/编辑/归档/删除确认）
 */

import { useState, useEffect } from 'react';
import type { KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate } from '../services/knowledgeBases';

interface KnowledgeBaseFormProps {
  mode: 'create' | 'edit';
  initialData?: KnowledgeBase;
  onSubmit: (data: KnowledgeBaseCreate | KnowledgeBaseUpdate) => Promise<void>;
  onCancel: () => void;
  loading?: boolean;
}

export function KnowledgeBaseForm({
  mode,
  initialData,
  onSubmit,
  onCancel,
  loading = false,
}: KnowledgeBaseFormProps) {
  const [name, setName] = useState(initialData?.name ?? '');
  const [description, setDescription] = useState(initialData?.description ?? '');
  const [tagsInput, setTagsInput] = useState(initialData?.tags?.join(', ') ?? '');
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError('名称不能为空');
      return;
    }

    const tags = tagsInput
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    try {
      await onSubmit({
        name: name.trim(),
        description: description.trim() || undefined,
        tags: tags.length > 0 ? tags : undefined,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
    }
  };

  return (
    <form onSubmit={handleSubmit} style={styles.form}>
      <h3 style={styles.title}>{mode === 'create' ? '创建知识库' : '编辑知识库'}</h3>

      {error && <div style={styles.error}>{error}</div>}

      <div style={styles.field}>
        <label style={styles.label}>名称 *</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="输入知识库名称"
          maxLength={64}
          style={styles.input}
          disabled={loading}
        />
      </div>

      <div style={styles.field}>
        <label style={styles.label}>描述</label>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="输入知识库描述（可选）"
          maxLength={500}
          rows={3}
          style={styles.textarea}
          disabled={loading}
        />
      </div>

      <div style={styles.field}>
        <label style={styles.label}>标签</label>
        <input
          type="text"
          value={tagsInput}
          onChange={(e) => setTagsInput(e.target.value)}
          placeholder="用逗号分隔多个标签"
          style={styles.input}
          disabled={loading}
        />
      </div>

      <div style={styles.actions}>
        <button type="button" onClick={onCancel} style={styles.cancelBtn} disabled={loading}>
          取消
        </button>
        <button type="submit" style={styles.submitBtn} disabled={loading}>
          {loading ? '处理中...' : mode === 'create' ? '创建' : '保存'}
        </button>
      </div>
    </form>
  );
}

interface DeleteConfirmProps {
  kbName: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
  loading?: boolean;
}

export function DeleteConfirm({ kbName, onConfirm, onCancel, loading = false }: DeleteConfirmProps) {
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : '删除失败');
    }
  };

  return (
    <div style={styles.form}>
      <h3 style={styles.title}>确认删除</h3>
      <p style={styles.text}>
        确定要删除知识库 <strong>{kbName}</strong> 吗？此操作不可恢复。
      </p>
      {error && <div style={styles.error}>{error}</div>}
      <div style={styles.actions}>
        <button type="button" onClick={onCancel} style={styles.cancelBtn} disabled={loading}>
          取消
        </button>
        <button type="button" onClick={handleConfirm} style={styles.dangerBtn} disabled={loading}>
          {loading ? '删除中...' : '确认删除'}
        </button>
      </div>
    </div>
  );
}

interface ArchiveConfirmProps {
  kbName: string;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
  loading?: boolean;
}

export function ArchiveConfirm({ kbName, onConfirm, onCancel, loading = false }: ArchiveConfirmProps) {
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : '归档失败');
    }
  };

  return (
    <div style={styles.form}>
      <h3 style={styles.title}>确认归档</h3>
      <p style={styles.text}>
        确定要归档知识库 <strong>{kbName}</strong> 吗？归档后将不再出现在列表中。
      </p>
      {error && <div style={styles.error}>{error}</div>}
      <div style={styles.actions}>
        <button type="button" onClick={onCancel} style={styles.cancelBtn} disabled={loading}>
          取消
        </button>
        <button type="button" onClick={handleConfirm} style={styles.submitBtn} disabled={loading}>
          {loading ? '归档中...' : '确认归档'}
        </button>
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  form: {
    background: '#fff',
    borderRadius: 8,
    padding: 24,
    maxWidth: 480,
  },
  title: {
    margin: '0 0 16px',
    fontSize: 18,
    fontWeight: 600,
  },
  field: {
    marginBottom: 16,
  },
  label: {
    display: 'block',
    marginBottom: 6,
    fontSize: 14,
    fontWeight: 500,
    color: '#374151',
  },
  input: {
    width: '100%',
    padding: '8px 12px',
    fontSize: 14,
    border: '1px solid #d1d5db',
    borderRadius: 6,
    outline: 'none',
  },
  textarea: {
    width: '100%',
    padding: '8px 12px',
    fontSize: 14,
    border: '1px solid #d1d5db',
    borderRadius: 6,
    outline: 'none',
    resize: 'vertical',
  },
  actions: {
    display: 'flex',
    gap: 12,
    justifyContent: 'flex-end',
    marginTop: 20,
  },
  cancelBtn: {
    padding: '8px 16px',
    fontSize: 14,
    border: '1px solid #d1d5db',
    borderRadius: 6,
    background: '#fff',
    cursor: 'pointer',
  },
  submitBtn: {
    padding: '8px 16px',
    fontSize: 14,
    border: 'none',
    borderRadius: 6,
    background: '#3b82f6',
    color: '#fff',
    cursor: 'pointer',
  },
  dangerBtn: {
    padding: '8px 16px',
    fontSize: 14,
    border: 'none',
    borderRadius: 6,
    background: '#ef4444',
    color: '#fff',
    cursor: 'pointer',
  },
  error: {
    padding: '8px 12px',
    marginBottom: 16,
    background: '#fef2f2',
    color: '#dc2626',
    borderRadius: 6,
    fontSize: 14,
  },
  text: {
    margin: '0 0 16px',
    fontSize: 14,
    color: '#4b5563',
  },
};
