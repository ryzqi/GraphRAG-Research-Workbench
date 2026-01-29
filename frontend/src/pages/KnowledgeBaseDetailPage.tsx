/**
 * 知识库详情页（资料列表/上传/触发导入/状态轮询）
 */

import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import {
  useCreateIngestionJob,
  useCreateTextMaterial,
  useCreateUrlMaterial,
  useIngestionJob,
  useKnowledgeBase,
  useMaterials,
  useUploadMaterial,
  useUpdateKnowledgeBaseIndexConfig,
  useIndexRebuildJob,
} from '../hooks/queries';
import { getErrorMessage } from '../lib/errorHandler';
import { ACCEPTED_FILE_TYPES, validateFile } from '../utils/fileValidation';
import { createDefaultIndexConfig, type IndexConfig } from '../services/knowledgeBases';
import { IndexConfigForm } from '../components/IndexConfigForm';
import { validateIndexConfig } from '../lib/indexConfig';
import { Modal } from '../components/ui/Modal';
import { Button } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';

type AddMode = 'text' | 'url' | 'upload' | null;

export default function KnowledgeBaseDetailPage() {
  const { kbId } = useParams<{ kbId: string }>();
  const navigate = useNavigate();

  const kbQuery = useKnowledgeBase(kbId ?? '');
  const materialsQuery = useMaterials(kbId);

  const kb = kbQuery.data ?? null;
  const materials = materialsQuery.data ?? [];
  const loading = kbQuery.isPending || materialsQuery.isPending;
  const markdownOnly = kb?.index_config?.chunking.general_strategy === 'markdown_heading';

  const [error, setError] = useState<string | null>(null);
  const [indexConfigOpen, setIndexConfigOpen] = useState(false);
  const [indexConfigDraft, setIndexConfigDraft] = useState<IndexConfig | null>(null);
  const [indexConfigError, setIndexConfigError] = useState<string | null>(null);
  const [confirmRebuildOpen, setConfirmRebuildOpen] = useState(false);
  const [rebuildJobId, setRebuildJobId] = useState<string | null>(null);

  const createTextMaterialMutation = useCreateTextMaterial();
  const createUrlMaterialMutation = useCreateUrlMaterial();
  const uploadMaterialMutation = useUploadMaterial();
  const updateIndexConfigMutation = useUpdateKnowledgeBaseIndexConfig();

  // 添加资料状态
  const [addMode, setAddMode] = useState<AddMode>(null);
  const [title, setTitle] = useState('');
  const [textContent, setTextContent] = useState('');
  const [urlContent, setUrlContent] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);

  const addLoading =
    createTextMaterialMutation.isPending ||
    createUrlMaterialMutation.isPending ||
    uploadMaterialMutation.isPending;

  // 导入状态
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [ingestionId, setIngestionId] = useState<string | null>(null);

  const createIngestionMutation = useCreateIngestionJob();
  const ingestionQuery = useIngestionJob(ingestionId ?? undefined);
  const ingestionJob = ingestionQuery.data ?? null;
  const rebuildJobQuery = useIndexRebuildJob(rebuildJobId ?? undefined);
  const rebuildJob = rebuildJobQuery.data ?? null;

  const ingestionInProgress =
    ingestionJob?.status === 'queued' || ingestionJob?.status === 'running';
  const ingestionLoading = createIngestionMutation.isPending || ingestionInProgress;

  const mergedError =
    error ??
    (indexConfigError ?? null) ??
    (updateIndexConfigMutation.error
      ? getErrorMessage(updateIndexConfigMutation.error)
      : null) ??
    (rebuildJobQuery.error ? getErrorMessage(rebuildJobQuery.error) : null) ??
    (createTextMaterialMutation.error
      ? getErrorMessage(createTextMaterialMutation.error)
      : null) ??
    (createUrlMaterialMutation.error
      ? getErrorMessage(createUrlMaterialMutation.error)
      : null) ??
    (uploadMaterialMutation.error
      ? getErrorMessage(uploadMaterialMutation.error)
      : null) ??
    (createIngestionMutation.error
      ? getErrorMessage(createIngestionMutation.error)
      : null) ??
    (ingestionQuery.error ? getErrorMessage(ingestionQuery.error) : null) ??
    (kbQuery.error ? getErrorMessage(kbQuery.error) : null) ??
    (materialsQuery.error ? getErrorMessage(materialsQuery.error) : null);

  useEffect(() => {
    if (!ingestionJob) return;
    if (['succeeded', 'failed', 'canceled'].includes(ingestionJob.status)) {
      setSelectedIds(new Set());
    }
  }, [ingestionJob?.status]);

  const resetAddForm = () => {
    setAddMode(null);
    setTitle('');
    setTextContent('');
    setUrlContent('');
    setFile(null);
    setFileError(null);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0] ?? null;
    setFile(selectedFile);
    setFileError(null);
    if (selectedFile) {
      const result = validateFile(selectedFile);
      if (!result.valid) {
        setFileError(result.error ?? '文件验证失败');
        setFile(null);
        return;
      }
      if (markdownOnly && !selectedFile.name.toLowerCase().endsWith('.md')) {
        setFileError('当前知识库仅支持上传 .md 文件');
        setFile(null);
      }
    }
  };

  const handleAddMaterial = () => {
    if (!kbId || !title.trim()) return;

    setError(null);

    if (addMode === 'text' && textContent.trim()) {
      createTextMaterialMutation.mutate(
        {
          kbId,
          data: {
            source_type: 'text',
            title: title.trim(),
            text: textContent.trim(),
          },
        },
        { onSuccess: resetAddForm }
      );
      return;
    }

    if (addMode === 'url' && urlContent.trim()) {
      createUrlMaterialMutation.mutate(
        {
          kbId,
          data: {
            source_type: 'url',
            title: title.trim(),
            url: urlContent.trim(),
          },
        },
        { onSuccess: resetAddForm }
      );
      return;
    }

    if (addMode === 'upload' && file) {
      uploadMaterialMutation.mutate({ kbId, title: title.trim(), file }, { onSuccess: resetAddForm });
    }
  };

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const selectAll = () => {
    if (selectedIds.size === materials.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(materials.map((m) => m.id)));
    }
  };

  const handleStartIngestion = () => {
    if (!kbId || selectedIds.size === 0) return;

    setError(null);
    setIngestionId(null);

    createIngestionMutation.mutate(
      {
        kb_id: kbId,
        material_ids: Array.from(selectedIds),
      },
      {
        onSuccess: (job) => {
          setIngestionId(job.id);
        },
      }
    );
  };

  if (loading) {
    return <div style={styles.loading}>加载中...</div>;
  }

  if (!kb) {
    return <div style={styles.error}>{mergedError ?? '知识库不存在'}</div>;
  }

  const openIndexConfigModal = () => {
    setIndexConfigError(null);
    setIndexConfigDraft(kb.index_config ?? createDefaultIndexConfig());
    setIndexConfigOpen(true);
  };

  const closeIndexConfigModal = () => {
    setIndexConfigOpen(false);
    setIndexConfigError(null);
    setConfirmRebuildOpen(false);
  };

  const handleSaveIndexConfig = async () => {
    if (!kbId || !indexConfigDraft) return;
    const validationErrors = validateIndexConfig(indexConfigDraft);
    if (validationErrors.length > 0) {
      setIndexConfigError(`索引配置校验失败：${validationErrors.join('；')}`);
      return;
    }
    setConfirmRebuildOpen(true);
  };

  const confirmRebuild = async () => {
    if (!kbId || !indexConfigDraft) return;
    try {
      const res = await updateIndexConfigMutation.mutateAsync({
        id: kbId,
        index_config: indexConfigDraft,
      });
      if (res.rebuild_job) {
        setRebuildJobId(res.rebuild_job.id);
      }
      closeIndexConfigModal();
    } catch (err) {
      setIndexConfigError(getErrorMessage(err));
    }
  };

  const handleIndexConfigChange = (next: IndexConfig) => {
    setIndexConfigDraft(next);
  };

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <button style={styles.backBtn} onClick={() => navigate('/knowledge-bases')}>
          ← 返回列表
        </button>
        <div>
          <h1 style={styles.title}>{kb.name}</h1>
          {kb.description && <p style={styles.desc}>{kb.description}</p>}
        </div>
        <div>
          <Button variant="outlined" onClick={openIndexConfigModal}>
            编辑索引配置
          </Button>
        </div>
      </div>

      {mergedError && <div style={styles.errorBox}>{mergedError}</div>}

      {/* 导入状态 */}
      {ingestionJob && (
        <div style={styles.ingestionStatus}>
          <strong>导入任务：</strong>
          <span style={styles.statusBadge} data-status={ingestionJob.status}>
            {ingestionJob.status}
          </span>
          {ingestionJob.error_message && (
            <span style={styles.errorText}>{ingestionJob.error_message}</span>
          )}
          {ingestionJob.stats && (
            <span style={styles.statsText}>
              {JSON.stringify(ingestionJob.stats)}
            </span>
          )}
        </div>
      )}

      {rebuildJob && (
        <div style={styles.ingestionStatus}>
          <strong>索引重建任务：</strong>
          <span style={styles.statusBadge} data-status={rebuildJob.status}>
            {rebuildJob.status}
          </span>
          {rebuildJob.error_message && (
            <span style={styles.errorText}>{rebuildJob.error_message}</span>
          )}
          {rebuildJob.stats && (
            <span style={styles.statsText}>{JSON.stringify(rebuildJob.stats)}</span>
          )}
        </div>
      )}

      {/* 添加资料 */}
      <div style={styles.section}>
        <div style={styles.sectionHeader}>
          <h2 style={styles.sectionTitle}>资料管理</h2>
          <div style={styles.addBtns}>
            <button style={styles.smallBtn} onClick={() => setAddMode('text')}>
              + 文本
            </button>
            <button style={styles.smallBtn} onClick={() => setAddMode('url')}>
              + URL
            </button>
            <button style={styles.smallBtn} onClick={() => setAddMode('upload')}>
              + 上传
            </button>
          </div>
        </div>

        {/* 添加表单 */}
        {addMode && (
          <div style={styles.addForm}>
            <input
              type="text"
              placeholder="资料标题"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              style={styles.input}
            />
            {addMode === 'text' && (
              <textarea
                placeholder="输入文本内容"
                value={textContent}
                onChange={(e) => setTextContent(e.target.value)}
                rows={4}
                style={styles.textarea}
              />
            )}
            {addMode === 'url' && (
              <input
                type="url"
                placeholder="输入 URL（http:// 或 https://）"
                value={urlContent}
                onChange={(e) => setUrlContent(e.target.value)}
                style={styles.input}
              />
            )}
            {addMode === 'upload' && (
              <>
                <input
                  type="file"
                  accept={markdownOnly ? '.md' : ACCEPTED_FILE_TYPES}
                  onChange={handleFileChange}
                  style={styles.input}
                />
                {markdownOnly && !fileError && (
                  <span style={styles.fileHint}>仅支持 .md 文件</span>
                )}
                {fileError && <span style={styles.fileError}>{fileError}</span>}
              </>
            )}
            <div style={styles.formActions}>
              <button style={styles.cancelBtn} onClick={resetAddForm}>
                取消
              </button>
              <button
                style={styles.submitBtn}
                onClick={handleAddMaterial}
                disabled={addLoading}
              >
                {addLoading ? '添加中...' : '添加'}
              </button>
            </div>
          </div>
        )}

        {/* 资料列表 */}
        {materials.length === 0 ? (
          <div style={styles.empty}>暂无资料，点击上方按钮添加</div>
        ) : (
          <>
            <div style={styles.listHeader}>
              <label style={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={selectedIds.size === materials.length}
                  onChange={selectAll}
                />
                全选 ({selectedIds.size}/{materials.length})
              </label>
              <button
                style={styles.primaryBtn}
                onClick={handleStartIngestion}
                disabled={selectedIds.size === 0 || ingestionLoading}
              >
                {ingestionLoading ? '导入中...' : '开始导入'}
              </button>
            </div>
            <div style={styles.list}>
              {materials.map((m) => (
                <div key={m.id} style={styles.listItem}>
                  <input
                    type="checkbox"
                    checked={selectedIds.has(m.id)}
                    onChange={() => toggleSelect(m.id)}
                  />
                  <div style={styles.itemInfo}>
                    <span style={styles.itemTitle}>{m.title}</span>
                    <span style={styles.itemMeta}>
                      {m.source_type} · {new Date(m.created_at).toLocaleString()}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {indexConfigDraft && (
        <Modal
          open={indexConfigOpen}
          onClose={closeIndexConfigModal}
          title="编辑索引配置"
          maxWidth="md"
        >
          <IndexConfigForm
            value={indexConfigDraft}
            onChange={handleIndexConfigChange}
            disabled={updateIndexConfigMutation.isPending}
          />
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 12, marginTop: 16 }}>
            <Button
              variant="outlined"
              onClick={closeIndexConfigModal}
              disabled={updateIndexConfigMutation.isPending}
            >
              取消
            </Button>
            <Button
              variant="contained"
              onClick={handleSaveIndexConfig}
              loading={updateIndexConfigMutation.isPending}
            >
              保存配置
            </Button>
          </div>
        </Modal>
      )}

      <ConfirmDialog
        open={confirmRebuildOpen}
        title="确认重建索引"
        message="保存后将删除该知识库的旧索引并重新构建，期间检索结果可能不完整。是否继续？"
        confirmText="确认重建"
        cancelText="取消"
        variant="destructive"
        loading={updateIndexConfigMutation.isPending}
        onConfirm={confirmRebuild}
        onCancel={() => setConfirmRebuildOpen(false)}
      />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    padding: 24,
    maxWidth: 900,
    margin: '0 auto',
  },
  header: {
    marginBottom: 24,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 12,
  },
  backBtn: {
    padding: '6px 12px',
    fontSize: 14,
    border: '1px solid #d1d5db',
    borderRadius: 6,
    background: '#fff',
    cursor: 'pointer',
  },
  title: {
    margin: 0,
    fontSize: 24,
    fontWeight: 600,
  },
  desc: {
    margin: '8px 0 0',
    color: '#6b7280',
  },
  loading: {
    textAlign: 'center',
    padding: 48,
    color: '#6b7280',
  },
  error: {
    textAlign: 'center',
    padding: 48,
    color: '#dc2626',
  },
  errorBox: {
    padding: '12px 16px',
    marginBottom: 16,
    background: '#fef2f2',
    color: '#dc2626',
    borderRadius: 6,
  },
  ingestionStatus: {
    padding: '12px 16px',
    marginBottom: 16,
    background: '#f0f9ff',
    borderRadius: 6,
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  statusBadge: {
    padding: '2px 8px',
    fontSize: 12,
    borderRadius: 4,
    background: '#dbeafe',
    color: '#1d4ed8',
  },
  errorText: {
    color: '#dc2626',
    fontSize: 14,
  },
  statsText: {
    color: '#6b7280',
    fontSize: 12,
  },
  section: {
    background: '#fff',
    borderRadius: 8,
    padding: 20,
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  },
  sectionHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  sectionTitle: {
    margin: 0,
    fontSize: 18,
    fontWeight: 600,
  },
  addBtns: {
    display: 'flex',
    gap: 8,
  },
  smallBtn: {
    padding: '6px 12px',
    fontSize: 13,
    border: '1px solid #d1d5db',
    borderRadius: 6,
    background: '#fff',
    cursor: 'pointer',
  },
  addForm: {
    padding: 16,
    marginBottom: 16,
    background: '#f9fafb',
    borderRadius: 6,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  input: {
    padding: '8px 12px',
    fontSize: 14,
    border: '1px solid #d1d5db',
    borderRadius: 6,
  },
  textarea: {
    padding: '8px 12px',
    fontSize: 14,
    border: '1px solid #d1d5db',
    borderRadius: 6,
    resize: 'vertical',
  },
  formActions: {
    display: 'flex',
    gap: 12,
    justifyContent: 'flex-end',
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
  empty: {
    textAlign: 'center',
    padding: 32,
    color: '#6b7280',
  },
  listHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
    paddingBottom: 12,
    borderBottom: '1px solid #e5e7eb',
  },
  checkboxLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontSize: 14,
    cursor: 'pointer',
  },
  primaryBtn: {
    padding: '8px 16px',
    fontSize: 14,
    border: 'none',
    borderRadius: 6,
    background: '#3b82f6',
    color: '#fff',
    cursor: 'pointer',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  listItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '12px 16px',
    background: '#f9fafb',
    borderRadius: 6,
    contentVisibility: 'auto',
    containIntrinsicSize: '1px 64px',
  },
  itemInfo: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  itemTitle: {
    fontSize: 14,
    fontWeight: 500,
  },
  itemMeta: {
    fontSize: 12,
    color: '#6b7280',
  },
  fileError: {
    color: '#dc2626',
    fontSize: 13,
  },
  fileHint: {
    color: '#6b7280',
    fontSize: 13,
  },
};
