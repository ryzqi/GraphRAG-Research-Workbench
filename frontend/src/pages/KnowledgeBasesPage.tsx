/**
 * 知识库管理页
 * 列表 + 新建/编辑/归档/删除
 */
import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Chip,
  IconButton,
  Menu,
  MenuItem,
  Stack,
  Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import EditIcon from '@mui/icons-material/Edit';
import ArchiveIcon from '@mui/icons-material/Archive';
import DeleteIcon from '@mui/icons-material/Delete';
import VisibilityIcon from '@mui/icons-material/Visibility';

import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  ErrorAlert,
  LoadingSpinner,
  Modal,
  PageHeader,
} from '../components/ui';
import { KnowledgeBaseForm } from '../components/KnowledgeBaseForm';
import {
  useKnowledgeBases,
  useCreateKnowledgeBase,
  useUpdateKnowledgeBase,
  useDeleteKnowledgeBase,
  useArchiveKnowledgeBase,
} from '../hooks/queries';
import { getErrorMessage } from '../lib/errorHandler';
import type { KnowledgeBase, KnowledgeBaseCreate, KnowledgeBaseUpdate } from '../services/knowledgeBases';

type ModalType = 'create' | 'edit' | 'delete' | 'archive' | null;

export default function KnowledgeBasesPage() {
  const navigate = useNavigate();
  const [modalType, setModalType] = useState<ModalType>(null);
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null);
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; kb: KnowledgeBase } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  // React Query hooks
  const { data: kbs = [], isLoading, error, refetch } = useKnowledgeBases();
  const createMutation = useCreateKnowledgeBase();
  const updateMutation = useUpdateKnowledgeBase();
  const deleteMutation = useDeleteKnowledgeBase();
  const archiveMutation = useArchiveKnowledgeBase();

  const openModal = useCallback((type: ModalType, kb?: KnowledgeBase) => {
    setModalType(type);
    setSelectedKb(kb ?? null);
    setMenuAnchor(null);
    setActionError(null);
  }, []);

  const closeModal = useCallback(() => {
    setModalType(null);
    setSelectedKb(null);
    setActionError(null);
  }, []);

  const handleCreate = useCallback(async (data: KnowledgeBaseCreate) => {
    await createMutation.mutateAsync(data);
    closeModal();
  }, [createMutation, closeModal]);

  const handleUpdate = useCallback(async (data: KnowledgeBaseUpdate) => {
    if (!selectedKb) return;
    await updateMutation.mutateAsync({ id: selectedKb.id, data });
    closeModal();
  }, [selectedKb, updateMutation, closeModal]);

  const handleDelete = useCallback(async () => {
    if (!selectedKb) return;
    try {
      await deleteMutation.mutateAsync(selectedKb.id);
      closeModal();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [selectedKb, deleteMutation, closeModal]);

  const handleArchive = useCallback(async () => {
    if (!selectedKb) return;
    try {
      await archiveMutation.mutateAsync(selectedKb.id);
      closeModal();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [selectedKb, archiveMutation, closeModal]);

  const handleMenuOpen = useCallback((event: React.MouseEvent<HTMLElement>, kb: KnowledgeBase) => {
    event.stopPropagation();
    setMenuAnchor({ el: event.currentTarget, kb });
  }, []);

  const handleMenuClose = useCallback(() => {
    setMenuAnchor(null);
  }, []);

  const actionLoading = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending || archiveMutation.isPending;

  return (
    <Box>
      <PageHeader
        title="知识库管理"
        subtitle="创建和管理您的知识库"
        action={
          <Button
            variant="contained"
            startIcon={<AddIcon />}
            onClick={() => openModal('create')}
          >
            新建知识库
          </Button>
        }
      />

      <ErrorAlert
        error={error instanceof Error ? error.message : error ? '加载失败' : null}
        onClose={() => refetch()}
        sx={{ mb: 2 }}
      />

      {isLoading ? (
        <LoadingSpinner text="加载知识库列表..." />
      ) : kbs.length === 0 ? (
        <EmptyState
          title="暂无知识库"
          description="点击上方按钮创建您的第一个知识库"
          action={
            <Button
              variant="contained"
              startIcon={<AddIcon />}
              onClick={() => openModal('create')}
            >
              新建知识库
            </Button>
          }
        />
      ) : (
        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
            gap: 2,
          }}
        >
          {kbs.map((kb) => (
            <Card
              key={kb.id}
              sx={{
                cursor: 'pointer',
                transition: 'box-shadow 0.2s',
                '&:hover': {
                  boxShadow: 3,
                },
              }}
              onClick={() => navigate(`/knowledge-bases/${kb.id}`)}
            >
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                <Typography variant="h6" fontWeight={500}>
                  {kb.name}
                </Typography>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Chip
                    label={kb.status === 'active' ? '活跃' : '已归档'}
                    size="small"
                    color={kb.status === 'active' ? 'primary' : 'default'}
                    variant="outlined"
                  />
                  <IconButton
                    size="small"
                    onClick={(e) => handleMenuOpen(e, kb)}
                    aria-label="更多操作"
                  >
                    <MoreVertIcon fontSize="small" />
                  </IconButton>
                </Box>
              </Box>

              {kb.description && (
                <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
                  {kb.description}
                </Typography>
              )}

              {kb.tags && kb.tags.length > 0 && (
                <Stack direction="row" spacing={0.5} flexWrap="wrap" useFlexGap>
                  {kb.tags.map((tag) => (
                    <Chip key={tag} label={tag} size="small" variant="outlined" />
                  ))}
                </Stack>
              )}
            </Card>
          ))}
        </Box>
      )}

      {/* 操作菜单 */}
      <Menu
        anchorEl={menuAnchor?.el}
        open={Boolean(menuAnchor)}
        onClose={handleMenuClose}
        onClick={(e) => e.stopPropagation()}
      >
        <MenuItem onClick={() => menuAnchor && navigate(`/knowledge-bases/${menuAnchor.kb.id}`)}>
          <VisibilityIcon fontSize="small" sx={{ mr: 1 }} />
          查看详情
        </MenuItem>
        <MenuItem onClick={() => menuAnchor && openModal('edit', menuAnchor.kb)}>
          <EditIcon fontSize="small" sx={{ mr: 1 }} />
          编辑
        </MenuItem>
        <MenuItem onClick={() => menuAnchor && openModal('archive', menuAnchor.kb)}>
          <ArchiveIcon fontSize="small" sx={{ mr: 1 }} />
          归档
        </MenuItem>
        <MenuItem
          onClick={() => menuAnchor && openModal('delete', menuAnchor.kb)}
          sx={{ color: 'error.main' }}
        >
          <DeleteIcon fontSize="small" sx={{ mr: 1 }} />
          删除
        </MenuItem>
      </Menu>

      {/* 创建/编辑模态框 */}
      <Modal
        open={modalType === 'create'}
        onClose={closeModal}
        title="新建知识库"
        maxWidth="sm"
      >
        <KnowledgeBaseForm
          mode="create"
          onSubmit={handleCreate}
          onCancel={closeModal}
          loading={actionLoading}
        />
      </Modal>

      <Modal
        open={modalType === 'edit' && selectedKb !== null}
        onClose={closeModal}
        title="编辑知识库"
        maxWidth="sm"
      >
        {selectedKb && (
          <KnowledgeBaseForm
            mode="edit"
            initialData={selectedKb}
            onSubmit={handleUpdate}
            onCancel={closeModal}
            loading={actionLoading}
          />
        )}
      </Modal>

      {/* 删除确认对话框 */}
      <ConfirmDialog
        open={modalType === 'delete' && selectedKb !== null}
        title="删除知识库"
        message={
          <>
            确定要删除知识库 <strong>{selectedKb?.name}</strong> 吗？此操作不可恢复。
          </>
        }
        confirmText="确认删除"
        variant="destructive"
        onConfirm={handleDelete}
        onCancel={closeModal}
        loading={deleteMutation.isPending}
        error={actionError}
      />

      {/* 归档确认对话框 */}
      <ConfirmDialog
        open={modalType === 'archive' && selectedKb !== null}
        title="归档知识库"
        message={
          <>
            确定要归档知识库 <strong>{selectedKb?.name}</strong> 吗？归档后将不再出现在列表中。
          </>
        }
        confirmText="确认归档"
        onConfirm={handleArchive}
        onCancel={closeModal}
        loading={archiveMutation.isPending}
        error={actionError}
      />
    </Box>
  );
}
