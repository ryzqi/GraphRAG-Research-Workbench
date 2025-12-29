/**
 * 知识库管理页（列表 + 新建/编辑/归档/删除）
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  KnowledgeBase,
  listKnowledgeBases,
  createKnowledgeBase,
  updateKnowledgeBase,
  deleteKnowledgeBase,
  archiveKnowledgeBase,
} from '../services/knowledgeBases';
import {
  KnowledgeBaseForm,
  DeleteConfirm,
  ArchiveConfirm,
} from '../components/KnowledgeBaseForm';
import { useModalAccessibility } from '../hooks/useModalAccessibility';

type ModalType = 'create' | 'edit' | 'delete' | 'archive' | null;

export default function KnowledgeBasesPage() {
  const navigate = useNavigate();
  const [kbs, setKbs] = useState<KnowledgeBase[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalType, setModalType] = useState<ModalType>(null);
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const { modalRef } = useModalAccessibility(modalType !== null, () => setModalType(null));

  const fetchKbs = useCallback(async () => {
    try {
      setLoading(true);
      const res = await listKnowledgeBases();
      setKbs(res.items);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchKbs();
  }, [fetchKbs]);

  const openModal = (type: ModalType, kb?: KnowledgeBase) => {
    setModalType(type);
    setSelectedKb(kb ?? null);
  };

  const closeModal = () => {
    setModalType(null);
    setSelectedKb(null);
  };

  const handleCreate = async (data: any) => {
    setActionLoading(true);
    try {
      await createKnowledgeBase(data);
      closeModal();
      fetchKbs();
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdate = async (data: any) => {
    if (!selectedKb) return;
    setActionLoading(true);
    try {
      await updateKnowledgeBase(selectedKb.id, data);
      closeModal();
      fetchKbs();
    } finally {
      setActionLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedKb) return;
    setActionLoading(true);
    try {
      await deleteKnowledgeBase(selectedKb.id);
      closeModal();
      fetchKbs();
    } finally {
      setActionLoading(false);
    }
  };

  const handleArchive = async () => {
    if (!selectedKb) return;
    setActionLoading(true);
    try {
      await archiveKnowledgeBase(selectedKb.id);
      closeModal();
      fetchKbs();
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <h1 style={styles.title}>知识库管理</h1>
        <button
          style={styles.primaryBtn}
          onClick={() => openModal('create')}
          aria-label="新建知识库"
        >
          + 新建知识库
        </button>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {loading ? (
        <div style={styles.loading}>加载中...</div>
      ) : kbs.length === 0 ? (
        <div style={styles.empty}>暂无知识库，点击上方按钮创建</div>
      ) : (
        <div style={styles.grid}>
          {kbs.map((kb) => (
            <div key={kb.id} style={styles.card}>
              <div style={styles.cardHeader}>
                <h3 style={styles.cardTitle}>{kb.name}</h3>
                <span style={styles.badge}>{kb.status}</span>
              </div>
              {kb.description && <p style={styles.cardDesc}>{kb.description}</p>}
              {kb.tags && kb.tags.length > 0 && (
                <div style={styles.tags}>
                  {kb.tags.map((tag) => (
                    <span key={tag} style={styles.tag}>
                      {tag}
                    </span>
                  ))}
                </div>
              )}
              <div style={styles.cardActions}>
                <button
                  style={styles.linkBtn}
                  onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
                >
                  查看详情
                </button>
                <button style={styles.linkBtn} onClick={() => openModal('edit', kb)}>
                  编辑
                </button>
                <button style={styles.linkBtn} onClick={() => openModal('archive', kb)}>
                  归档
                </button>
                <button
                  style={{ ...styles.linkBtn, color: '#ef4444' }}
                  onClick={() => openModal('delete', kb)}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 模态框 */}
      {modalType && (
        <div style={styles.overlay} onClick={closeModal} role="presentation">
          <div
            ref={modalRef}
            style={styles.modal}
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
            tabIndex={-1}
          >
            {modalType === 'create' && (
              <KnowledgeBaseForm
                mode="create"
                onSubmit={handleCreate}
                onCancel={closeModal}
                loading={actionLoading}
              />
            )}
            {modalType === 'edit' && selectedKb && (
              <KnowledgeBaseForm
                mode="edit"
                initialData={selectedKb}
                onSubmit={handleUpdate}
                onCancel={closeModal}
                loading={actionLoading}
              />
            )}
            {modalType === 'delete' && selectedKb && (
              <DeleteConfirm
                kbName={selectedKb.name}
                onConfirm={handleDelete}
                onCancel={closeModal}
                loading={actionLoading}
              />
            )}
            {modalType === 'archive' && selectedKb && (
              <ArchiveConfirm
                kbName={selectedKb.name}
                onConfirm={handleArchive}
                onCancel={closeModal}
                loading={actionLoading}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: 24,
    maxWidth: 1200,
    margin: '0 auto',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 24,
  },
  title: {
    margin: 0,
    fontSize: 24,
    fontWeight: 600,
  },
  primaryBtn: {
    padding: '10px 20px',
    fontSize: 14,
    fontWeight: 500,
    border: 'none',
    borderRadius: 6,
    background: '#3b82f6',
    color: '#fff',
    cursor: 'pointer',
  },
  error: {
    padding: '12px 16px',
    marginBottom: 16,
    background: '#fef2f2',
    color: '#dc2626',
    borderRadius: 6,
  },
  loading: {
    textAlign: 'center',
    padding: 48,
    color: '#6b7280',
  },
  empty: {
    textAlign: 'center',
    padding: 48,
    color: '#6b7280',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: 16,
  },
  card: {
    background: '#fff',
    borderRadius: 8,
    padding: 20,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  cardTitle: {
    margin: 0,
    fontSize: 16,
    fontWeight: 600,
  },
  badge: {
    padding: '2px 8px',
    fontSize: 12,
    borderRadius: 4,
    background: '#dbeafe',
    color: '#1d4ed8',
  },
  cardDesc: {
    margin: '0 0 12px',
    fontSize: 14,
    color: '#6b7280',
    lineHeight: 1.5,
  },
  tags: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    marginBottom: 12,
  },
  tag: {
    padding: '2px 8px',
    fontSize: 12,
    borderRadius: 4,
    background: '#f3f4f6',
    color: '#374151',
  },
  cardActions: {
    display: 'flex',
    gap: 12,
    borderTop: '1px solid #e5e7eb',
    paddingTop: 12,
    marginTop: 12,
  },
  linkBtn: {
    padding: 0,
    fontSize: 14,
    border: 'none',
    background: 'none',
    color: '#3b82f6',
    cursor: 'pointer',
  },
  overlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: 'rgba(0,0,0,0.5)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  modal: {
    maxHeight: '90vh',
    overflow: 'auto',
  },
};
