'use client';

/**
 * 知识库管理页
 * 列表 + 编辑/归档/删除
 */
import { useMemo, useState, useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import {
  Box,
  Chip,
  IconButton,
  Menu,
  MenuItem,
  Paper,
  Stack,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
  InputAdornment,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import EditIcon from '@mui/icons-material/Edit';
import ArchiveIcon from '@mui/icons-material/Archive';
import DeleteIcon from '@mui/icons-material/Delete';
import VisibilityIcon from '@mui/icons-material/Visibility';
import SearchIcon from '@mui/icons-material/Search';

import { Button } from '../components/ui/Button';
import { Card } from '../components/ui/Card';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { LoadingSpinner } from '../components/ui/LoadingSpinner';
import { Modal } from '../components/ui/Modal';
import { PageHeader } from '../components/ui/PageHeader';
import { KnowledgeBaseForm } from '../components/KnowledgeBaseForm';
import {
  useKnowledgeBases,
  useUpdateKnowledgeBase,
  useDeleteKnowledgeBase,
  useArchiveKnowledgeBase,
} from '../hooks/queries/useKnowledgeBases';
import { getErrorMessage } from '../lib/errorHandler';
import {
  type KnowledgeBase,
  type KnowledgeBaseUpdate,
} from '../services/knowledgeBases';
import { StaggerGrid } from '../components/ui/StaggerList';

type ModalType = 'edit' | 'delete' | 'archive' | null;
type StatusFilter = 'all' | 'active' | 'archived';

export default function KnowledgeBasesPage() {
  const router = useRouter();
  const [modalType, setModalType] = useState<ModalType>(null);
  const [selectedKb, setSelectedKb] = useState<KnowledgeBase | null>(null);
  const [menuAnchor, setMenuAnchor] = useState<{ el: HTMLElement; kb: KnowledgeBase } | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [optimisticallyHiddenKbIds, setOptimisticallyHiddenKbIds] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all');

  const { data: kbs = [], isLoading, error, refetch } = useKnowledgeBases({ status: 'all' });
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

  const handleUpdate = useCallback(async (data: KnowledgeBaseUpdate) => {
    if (!selectedKb) {
      return;
    }
    try {
      await updateMutation.mutateAsync({ id: selectedKb.id, data });
      closeModal();
    } catch (err) {
      setActionError(getErrorMessage(err));
    }
  }, [selectedKb, updateMutation, closeModal]);

  const handleDelete = useCallback(async () => {
    if (!selectedKb) {
      return;
    }

    const deletingKbId = selectedKb.id;
    setOptimisticallyHiddenKbIds((prev) => {
      const next = new Set(prev);
      next.add(deletingKbId);
      return next;
    });

    try {
      await deleteMutation.mutateAsync(deletingKbId);
      closeModal();
    } catch (err) {
      setOptimisticallyHiddenKbIds((prev) => {
        const next = new Set(prev);
        next.delete(deletingKbId);
        return next;
      });
      setActionError(getErrorMessage(err));
    }
  }, [selectedKb, deleteMutation, closeModal]);

  const handleArchive = useCallback(async () => {
    if (!selectedKb) {
      return;
    }
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

  const actionLoading =
    updateMutation.isPending || deleteMutation.isPending || archiveMutation.isPending;

  useEffect(() => {
    setOptimisticallyHiddenKbIds((prev) => {
      if (prev.size === 0) {
        return prev;
      }

      const currentKbIds = new Set(kbs.map((kb) => kb.id));
      const next = new Set<string>();
      prev.forEach((id) => {
        if (currentKbIds.has(id)) {
          next.add(id);
        }
      });

      return next.size === prev.size ? prev : next;
    });
  }, [kbs]);

  const visibleKbs = useMemo(() => {
    return kbs.filter((kb) => !optimisticallyHiddenKbIds.has(kb.id));
  }, [kbs, optimisticallyHiddenKbIds]);

  const filteredKbs = useMemo(() => {
    const q = query.trim().toLowerCase();
    return visibleKbs.filter((kb) => {
      if (statusFilter !== 'all' && kb.status !== statusFilter) {
        return false;
      }
      if (!q) {
        return true;
      }
      const haystack = [kb.name, kb.description ?? '', ...(kb.tags ?? [])]
        .join(' ')
        .toLowerCase();
      return haystack.includes(q);
    });
  }, [visibleKbs, query, statusFilter]);

  return (
    <Box>
      <PageHeader
        title='知识库管理'
        subtitle='创建向导、增量处理与可用性状态统一管理'
        action={
          <Button variant='contained' startIcon={<AddIcon />} onClick={() => router.push('/knowledge-bases/new')}>
            新建知识库
          </Button>
        }
      />

      <Paper
        elevation={0}
        sx={{
          p: 2,
          mb: 2,
          borderRadius: 3,
          border: 1,
          borderColor: 'divider',
          display: 'flex',
          alignItems: 'center',
          gap: 1.5,
          flexWrap: 'wrap',
        }}
      >
        <TextField
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder='搜索知识库（名称/描述/标签）'
          size='small'
          sx={{ minWidth: { xs: '100%', sm: 360 }, flex: 1 }}
          InputProps={{
            startAdornment: (
              <InputAdornment position='start'>
                <SearchIcon fontSize='small' />
              </InputAdornment>
            ),
          }}
        />

        <ToggleButtonGroup
          value={statusFilter}
          exclusive
          onChange={(_, next) => next && setStatusFilter(next)}
          size='small'
          aria-label='按状态筛选'
          sx={{
            '& .MuiToggleButton-root': {
              textTransform: 'none',
              borderRadius: 999,
              px: 2,
            },
          }}
        >
          <ToggleButton value='all'>全部</ToggleButton>
          <ToggleButton value='active'>活跃</ToggleButton>
          <ToggleButton value='archived'>已归档</ToggleButton>
        </ToggleButtonGroup>

        <Typography variant='caption' color='text.secondary' sx={{ ml: 'auto' }}>
          {filteredKbs.length} / {visibleKbs.length}
        </Typography>
      </Paper>

      <ErrorAlert
        error={error instanceof Error ? error.message : error ? '加载失败' : null}
        onClose={() => refetch()}
        sx={{ mb: 2 }}
      />

      {isLoading ? (
        <LoadingSpinner text='加载知识库列表...' />
      ) : visibleKbs.length === 0 ? (
        <EmptyState
          title='暂无知识库'
          description='点击上方按钮开始三步创建向导'
          action={
            <Button variant='contained' startIcon={<AddIcon />} onClick={() => router.push('/knowledge-bases/new')}>
              新建知识库
            </Button>
          }
        />
      ) : filteredKbs.length === 0 ? (
        <EmptyState
          title='未找到匹配的知识库'
          description='尝试更换关键词或切换筛选条件。'
          action={
            <Button variant='outlined' onClick={() => { setQuery(''); setStatusFilter('all'); }}>
              清空筛选
            </Button>
          }
        />
      ) : (
        <StaggerGrid spacing={2} columns={{ xs: 1, sm: 2, md: 2, lg: 3 }}>
          {filteredKbs.map((kb) => (
            <Card
              key={kb.id}
              sx={{
                cursor: 'pointer',
                border: 1,
                borderColor: 'divider',
                overflow: 'hidden',
              }}
              onClick={() => router.push('/knowledge-bases/' + kb.id)}
            >
              <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
                <Stack direction='row' spacing={1.25} sx={{ minWidth: 0 }} alignItems='center'>
                  <Box
                    sx={{
                      width: 40,
                      height: 40,
                      borderRadius: '50%',
                      display: 'grid',
                      placeItems: 'center',
                      bgcolor: 'action.selected',
                      color: 'primary.main',
                      fontWeight: 800,
                      flexShrink: 0,
                    }}
                  >
                    {(kb.name || 'K').trim().slice(0, 1).toUpperCase()}
                  </Box>
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant='h6' fontWeight={600} noWrap>
                      {kb.name}
                    </Typography>
                    {kb.description && (
                      <Typography variant='body2' color='text.secondary' noWrap>
                        {kb.description}
                      </Typography>
                    )}
                  </Box>
                </Stack>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexShrink: 0 }}>
                  <Chip
                    label={kb.status === 'active' ? '活跃' : '已归档'}
                    size='small'
                    color={kb.status === 'active' ? 'primary' : 'default'}
                    variant='outlined'
                  />
                  <IconButton
                    size='small'
                    onClick={(e) => handleMenuOpen(e, kb)}
                    aria-label={'更多操作：' + kb.name}
                  >
                    <MoreVertIcon fontSize='small' />
                  </IconButton>
                </Box>
              </Box>

              <Stack direction='row' spacing={0.5} flexWrap='wrap' useFlexGap>
                <Chip
                  label={kb.readiness === 'ready' ? '可用' : '未就绪'}
                  size='small'
                  color={kb.readiness === 'ready' ? 'success' : 'warning'}
                  variant='outlined'
                />
                {kb.tags?.map((tag) => (
                  <Chip key={tag} label={tag} size='small' variant='outlined' />
                ))}
              </Stack>
            </Card>
          ))}
        </StaggerGrid>
      )}

      <Menu
        anchorEl={menuAnchor?.el}
        open={Boolean(menuAnchor)}
        onClose={handleMenuClose}
        onClick={(e) => e.stopPropagation()}
      >
        <MenuItem onClick={() => menuAnchor && router.push('/knowledge-bases/' + menuAnchor.kb.id)}>
          <VisibilityIcon fontSize='small' sx={{ mr: 1 }} />
          查看详情
        </MenuItem>
        <MenuItem onClick={() => menuAnchor && openModal('edit', menuAnchor.kb)}>
          <EditIcon fontSize='small' sx={{ mr: 1 }} />
          编辑
        </MenuItem>
        <MenuItem onClick={() => menuAnchor && openModal('archive', menuAnchor.kb)}>
          <ArchiveIcon fontSize='small' sx={{ mr: 1 }} />
          归档
        </MenuItem>
        <MenuItem
          onClick={() => menuAnchor && openModal('delete', menuAnchor.kb)}
          sx={{ color: 'error.main' }}
        >
          <DeleteIcon fontSize='small' sx={{ mr: 1 }} />
          删除
        </MenuItem>
      </Menu>

      <Modal
        open={modalType === 'edit' && selectedKb !== null}
        onClose={closeModal}
        title='编辑知识库'
        maxWidth='sm'
      >
        {selectedKb && (
          <KnowledgeBaseForm
            mode='edit'
            initialData={selectedKb}
            onSubmit={handleUpdate}
            onCancel={closeModal}
            loading={actionLoading}
          />
        )}
      </Modal>

      <ConfirmDialog
        open={modalType === 'delete' && selectedKb !== null}
        title='删除知识库'
        message={
          <>
            确定要删除知识库 <strong>{selectedKb?.name}</strong> 吗？此操作不可恢复。
          </>
        }
        confirmText='确认删除'
        variant='destructive'
        onConfirm={handleDelete}
        onCancel={closeModal}
        loading={deleteMutation.isPending}
        error={actionError}
      />

      <ConfirmDialog
        open={modalType === 'archive' && selectedKb !== null}
        title='归档知识库'
        message={
          <>
            确定要归档知识库 <strong>{selectedKb?.name}</strong> 吗？归档后将不再出现在可选入口中。
          </>
        }
        confirmText='确认归档'
        onConfirm={handleArchive}
        onCancel={closeModal}
        loading={archiveMutation.isPending}
        error={actionError}
      />
    </Box>
  );
}


