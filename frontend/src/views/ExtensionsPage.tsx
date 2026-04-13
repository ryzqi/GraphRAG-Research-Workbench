'use client';

import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import EditOutlinedIcon from '@mui/icons-material/EditOutlined';
import RefreshIcon from '@mui/icons-material/Refresh';
import SyncIcon from '@mui/icons-material/Sync';
import {
  Box,
  Chip,
  Divider,
  Drawer,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material';
import { useState } from 'react';

import { createDefaultExtensionFormState } from '../constants/formDefaults';
import {
  useCreateExtension,
  useDeleteExtension,
  useExtensionTools,
  useExtensions,
  useUpdateExtension,
} from '../hooks/queries/useExtensions';
import { getErrorMessage } from '../lib/errorHandler';
import {
  buildExtensionPayloadFromForm,
  buildFormFromExtension,
  importSingleMcpServerToFormState,
  type ExtensionFormState,
} from '../services/mcpExtensionForm';
import type {
  ExtensionAuthType,
  ExtensionConnectionStatus,
  ExtensionStatus,
  ExtensionTransport,
  ToolExtension,
  ToolExtensionCreate,
  ToolExtensionUpdate,
} from '../services/extensions';
import { Button } from '../components/ui/Button';
import { ConfirmDialog } from '../components/ui/ConfirmDialog';
import { ErrorAlert } from '../components/ui/ErrorAlert';
import { PageHeader } from '../components/ui/PageHeader';

type ListStatusFilter = 'all' | ExtensionStatus;
type EditorMode = 'create' | 'edit';

const EXTENSION_CREATED_AT_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

function getConnectionStatusLabel(status: ExtensionConnectionStatus): string {
  if (status === 'ok') return '连接正常';
  if (status === 'degraded') return '连接退化';
  return '连接失败';
}

function getConnectionStatusColor(
  status: ExtensionConnectionStatus
): 'success' | 'warning' | 'error' {
  if (status === 'ok') return 'success';
  if (status === 'degraded') return 'warning';
  return 'error';
}

export function ExtensionsPage() {
  const [error, setError] = useState<string | null>(null);
  const [selectedExtensionId, setSelectedExtensionId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<ListStatusFilter>('all');
  const [searchText, setSearchText] = useState('');
  const [activeTab, setActiveTab] = useState(0);

  const [editorMode, setEditorMode] = useState<EditorMode>('create');
  const [editingExtensionId, setEditingExtensionId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [formState, setFormState] = useState<ExtensionFormState>(() =>
    createDefaultExtensionFormState()
  );
  const [mcpImportJson, setMcpImportJson] = useState('');
  const [deleteTarget, setDeleteTarget] = useState<ToolExtension | null>(null);

  const extensionsQuery = useExtensions();
  const createMutation = useCreateExtension();
  const updateMutation = useUpdateExtension();
  const deleteMutation = useDeleteExtension();

  const extensions = extensionsQuery.data ?? [];

  const selectedExtension =
    extensions.find((ext) => ext.id === selectedExtensionId) ?? null;
  const selectedExtensionCreatedAtLabel = selectedExtension
    ? EXTENSION_CREATED_AT_FORMATTER.format(new Date(selectedExtension.created_at))
    : null;

  const toolsQuery = useExtensionTools(selectedExtension?.id);
  const toolResponse = toolsQuery.data;
  const tools = toolResponse?.items ?? [];

  const keyword = searchText.trim().toLowerCase();
  const filteredExtensions = extensions.filter((ext) => {
    if (statusFilter !== 'all' && ext.status !== statusFilter) {
      return false;
    }
    if (!keyword) return true;
    return (
      ext.name.toLowerCase().includes(keyword) ||
      ext.transport.toLowerCase().includes(keyword)
    );
  });

  const mergedError =
    error ??
    (extensionsQuery.error ? getErrorMessage(extensionsQuery.error) : null) ??
    (createMutation.error ? getErrorMessage(createMutation.error) : null) ??
    (updateMutation.error ? getErrorMessage(updateMutation.error) : null) ??
    (deleteMutation.error ? getErrorMessage(deleteMutation.error) : null) ??
    (toolsQuery.error ? getErrorMessage(toolsQuery.error) : null);

  const closeError = () => {
    if (error) {
      setError(null);
      return;
    }
    if (createMutation.error) {
      createMutation.reset();
      return;
    }
    if (updateMutation.error) {
      updateMutation.reset();
      return;
    }
    if (deleteMutation.error) {
      deleteMutation.reset();
      return;
    }
    if (extensionsQuery.error) {
      extensionsQuery.refetch();
      return;
    }
    if (toolsQuery.error) {
      toolsQuery.refetch();
    }
  };

  const openCreateDrawer = () => {
    setError(null);
    setEditorMode('create');
    setEditingExtensionId(null);
    setMcpImportJson('');
    setFormState(createDefaultExtensionFormState());
    setDrawerOpen(true);
  };

  const openEditDrawer = (ext: ToolExtension) => {
    setError(null);
    setEditorMode('edit');
    setEditingExtensionId(ext.id);
    setMcpImportJson('');
    setFormState(buildFormFromExtension(ext));
    setDrawerOpen(true);
  };

  const handleSave = () => {
    setError(null);
    let payload: ToolExtensionCreate;
    try {
      payload = buildExtensionPayloadFromForm(formState);
    } catch (caught) {
      setError(getErrorMessage(caught));
      return;
    }

    if (editorMode === 'create') {
      createMutation.mutate(payload, {
        onSuccess: (created) => {
          setDrawerOpen(false);
          setSelectedExtensionId(created.id);
        },
      });
      return;
    }

    if (!editingExtensionId) return;
    updateMutation.mutate(
      {
        id: editingExtensionId,
        data: payload as ToolExtensionUpdate,
      },
      {
        onSuccess: (updated) => {
          setDrawerOpen(false);
          setSelectedExtensionId(updated.id);
        },
      }
    );
  };

  const handleImportMcpJson = () => {
    setError(null);
    try {
      setFormState(importSingleMcpServerToFormState(mcpImportJson));
    } catch (caught) {
      setError(getErrorMessage(caught));
    }
  };

  const toggleExtensionStatus = (ext: ToolExtension) => {
    const nextStatus: ExtensionStatus =
      ext.status === 'enabled' ? 'disabled' : 'enabled';
    setError(null);
    updateMutation.mutate({ id: ext.id, data: { status: nextStatus } });
  };

  const handleDelete = () => {
    if (!deleteTarget) return;
    setError(null);
    deleteMutation.mutate(deleteTarget.id, {
      onSuccess: () => {
        if (selectedExtensionId === deleteTarget.id) {
          setSelectedExtensionId(null);
        }
        setDeleteTarget(null);
      },
    });
  };

  const saving = createMutation.isPending || updateMutation.isPending;

  return (
    <Box sx={{ px: { xs: 2, md: 3 }, py: 3 }}>
      <PageHeader
        title='MCP 扩展控制台'
        subtitle='统一管理 streamable HTTP / STDIO 扩展，创建后默认启用。'
        action={
          <Button variant='contained' startIcon={<AddIcon />} onClick={openCreateDrawer}>
            新建扩展
          </Button>
        }
      />

      <ErrorAlert error={mergedError} onClose={closeError} sx={{ mt: 0, mb: 2 }} />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 4 }}>
          <Paper variant='outlined' sx={{ p: 2, height: '100%' }}>
            <Stack spacing={1.5}>
              <Typography variant='subtitle1' fontWeight={600}>
                扩展列表
              </Typography>
              <Stack direction='row' spacing={1}>
                <TextField
                  size='small'
                  placeholder='搜索扩展名'
                  value={searchText}
                  onChange={(e) => setSearchText(e.target.value)}
                  fullWidth
                />
                <FormControl size='small' sx={{ minWidth: 120 }}>
                  <InputLabel id='extensions-status-filter-label'>状态</InputLabel>
                  <Select
                    labelId='extensions-status-filter-label'
                    label='状态'
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value as ListStatusFilter)}
                  >
                    <MenuItem value='all'>全部</MenuItem>
                    <MenuItem value='enabled'>启用中</MenuItem>
                    <MenuItem value='disabled'>已禁用</MenuItem>
                  </Select>
                </FormControl>
              </Stack>

              <Divider />

              <Stack spacing={1}>
                {extensionsQuery.isPending && extensions.length === 0 && (
                  <Typography color='text.secondary' variant='body2'>
                    正在加载扩展...
                  </Typography>
                )}
                {!extensionsQuery.isPending && filteredExtensions.length === 0 && (
                  <Typography color='text.secondary' variant='body2'>
                    暂无匹配扩展
                  </Typography>
                )}
                {filteredExtensions.map((ext) => {
                  const selected = selectedExtensionId === ext.id;
                  return (
                    <Paper
                      key={ext.id}
                      variant='outlined'
                      sx={{
                        p: 1.25,
                        cursor: 'pointer',
                        borderColor: selected ? 'primary.main' : 'divider',
                        bgcolor: selected ? 'action.selected' : 'background.paper',
                        contentVisibility: 'auto',
                        containIntrinsicSize: '1px 84px',
                      }}
                      onClick={() => setSelectedExtensionId(ext.id)}
                    >
                      <Stack spacing={1}>
                        <Stack direction='row' justifyContent='space-between' alignItems='center'>
                          <Typography fontWeight={600}>{ext.name}</Typography>
                          <Chip
                            label={ext.transport.toUpperCase()}
                            size='small'
                            variant='outlined'
                            color='primary'
                          />
                        </Stack>
                        <Stack direction='row' spacing={1} alignItems='center'>
                          <Chip
                            label={ext.status === 'enabled' ? '已启用' : '已禁用'}
                            size='small'
                            color={ext.status === 'enabled' ? 'success' : 'default'}
                          />
                        </Stack>
                      </Stack>
                    </Paper>
                  );
                })}
              </Stack>
            </Stack>
          </Paper>
        </Grid>
        <Grid size={{ xs: 12, md: 8 }}>
          <Paper variant='outlined' sx={{ p: 2, minHeight: 580 }}>
            {!selectedExtension ? (
              <Stack
                spacing={1}
                alignItems='center'
                justifyContent='center'
                sx={{ minHeight: 420, color: 'text.secondary' }}
              >
                <Typography variant='h6' color='text.primary'>
                  请选择一个扩展
                </Typography>
                <Typography variant='body2'>
                  在左侧选择扩展查看配置、工具与连接状态。
                </Typography>
              </Stack>
            ) : (
              <Stack spacing={2}>
                <Stack
                  direction={{ xs: 'column', sm: 'row' }}
                  justifyContent='space-between'
                  alignItems={{ xs: 'flex-start', sm: 'center' }}
                  spacing={1.5}
                >
                  <Box>
                    <Typography variant='h6'>{selectedExtension.name}</Typography>
                    <Typography variant='body2' color='text.secondary'>
                      创建于{' '}
                      <span suppressHydrationWarning>{selectedExtensionCreatedAtLabel}</span>
                    </Typography>
                  </Box>
                  <Stack direction='row' spacing={1}>
                    <Button
                      variant='outlined'
                      startIcon={<EditOutlinedIcon />}
                      onClick={() => openEditDrawer(selectedExtension)}
                    >
                      编辑
                    </Button>
                    <Button
                      variant='outlined'
                      startIcon={<SyncIcon />}
                      onClick={() => toggleExtensionStatus(selectedExtension)}
                      loading={updateMutation.isPending}
                    >
                      {selectedExtension.status === 'enabled' ? '禁用' : '启用'}
                    </Button>
                    <Button
                      variant='outlined'
                      color='error'
                      startIcon={<DeleteOutlineIcon />}
                      onClick={() => setDeleteTarget(selectedExtension)}
                    >
                      删除
                    </Button>
                  </Stack>
                </Stack>

                <Tabs value={activeTab} onChange={(_, value) => setActiveTab(Number(value))}>
                  <Tab label='配置' />
                  <Tab label='工具与连通性' />
                </Tabs>

                {activeTab === 0 && (
                  <Stack spacing={2}>
                    <Paper variant='outlined' sx={{ p: 1.5 }}>
                      <Stack spacing={1.25}>
                        <Stack direction='row' spacing={1} alignItems='center'>
                          <Chip
                            label={selectedExtension.transport.toUpperCase()}
                            size='small'
                            color='primary'
                            variant='outlined'
                          />
                          <Chip
                            label={
                              selectedExtension.status === 'enabled'
                                ? '已启用'
                                : '已禁用'
                            }
                            size='small'
                            color={
                              selectedExtension.status === 'enabled'
                                ? 'success'
                                : 'default'
                            }
                          />
                        </Stack>
                        <Typography variant='body2' color='text.secondary'>
                          传输方式：{selectedExtension.transport.toUpperCase()}
                        </Typography>
                        {selectedExtension.transport === 'http' &&
                          selectedExtension.http_config && (
                            <>
                              <Typography variant='body2' color='text.secondary'>
                                URL: {selectedExtension.http_config.url}
                              </Typography>
                              <Typography variant='body2' color='text.secondary'>
                                协议: {selectedExtension.http_config.protocol}
                              </Typography>
                            </>
                          )}
                        {selectedExtension.transport === 'stdio' &&
                          selectedExtension.stdio_config && (
                            <>
                              <Typography variant='body2' color='text.secondary'>
                                命令: {selectedExtension.stdio_config.command}
                              </Typography>
                              <Typography variant='body2' color='text.secondary'>
                                参数: {(selectedExtension.stdio_config.args ?? []).join(' ')}
                              </Typography>
                              {selectedExtension.stdio_config.cwd && (
                                <Typography variant='body2' color='text.secondary'>
                                  工作目录: {selectedExtension.stdio_config.cwd}
                                </Typography>
                              )}
                            </>
                          )}
                      </Stack>
                    </Paper>
                  </Stack>
                )}

                {activeTab === 1 && (
                  <Stack spacing={1.5}>
                    <Stack direction='row' justifyContent='space-between' alignItems='center'>
                      <Stack direction='row' spacing={1} alignItems='center'>
                        <Chip
                          size='small'
                          color={getConnectionStatusColor(
                            toolResponse?.connection_status ?? 'failed'
                          )}
                          label={getConnectionStatusLabel(
                            toolResponse?.connection_status ?? 'failed'
                          )}
                        />
                        {toolResponse?.latency_ms !== null &&
                          toolResponse?.latency_ms !== undefined && (
                            <Typography variant='caption' color='text.secondary'>
                              探测耗时 {toolResponse.latency_ms}ms
                            </Typography>
                          )}
                      </Stack>
                      <Button
                        variant='outlined'
                        startIcon={<RefreshIcon />}
                        onClick={() => toolsQuery.refetch()}
                        loading={toolsQuery.isFetching}
                      >
                        刷新工具
                      </Button>
                    </Stack>

                    {toolResponse?.last_error && (
                      <Paper variant='outlined' sx={{ p: 1.25, bgcolor: 'error.50' }}>
                        <Typography variant='body2' color='error.main'>
                          最近错误：{toolResponse.last_error}
                        </Typography>
                      </Paper>
                    )}

                    {toolsQuery.isPending ? (
                      <Typography color='text.secondary' variant='body2'>
                        正在加载工具列表...
                      </Typography>
                    ) : tools.length === 0 ? (
                      <Typography color='text.secondary' variant='body2'>
                        当前无可用工具。请检查扩展状态与连接配置。
                      </Typography>
                    ) : (
                      <Stack spacing={1}>
                        {tools.map((tool) => (
                          <Paper key={tool.name} variant='outlined' sx={{ p: 1.25 }}>
                            <Typography fontWeight={600}>{tool.name}</Typography>
                            {tool.description && (
                              <Typography variant='body2' color='text.secondary'>
                                {tool.description}
                              </Typography>
                            )}
                          </Paper>
                        ))}
                      </Stack>
                    )}
                  </Stack>
                )}
              </Stack>
            )}
          </Paper>
        </Grid>
      </Grid>
      <Drawer
        anchor='right'
        open={drawerOpen}
        onClose={() => {
          if (!saving) setDrawerOpen(false);
        }}
      >
        <Box sx={{ width: { xs: 360, md: 500 }, p: 2.5 }}>
          <Stack spacing={2}>
            <Typography variant='h6'>
              {editorMode === 'create' ? '新建扩展' : '编辑扩展'}
            </Typography>

            <Stack spacing={1}>
              <Typography variant='subtitle2'>导入 mcpServers JSON</Typography>
              <Typography variant='body2' color='text.secondary'>
                仅支持一次导入 1 个 server，可导入 HTTP url 或 STDIO command。
              </Typography>
              <TextField
                label='mcpServers JSON'
                value={mcpImportJson}
                onChange={(e) => setMcpImportJson(e.target.value)}
                placeholder={`示例：{\n  "mcpServers": {\n    "sequential-thinking": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"]\n    }\n  }\n}`}
                multiline
                minRows={7}
                fullWidth
              />
              <Stack direction='row' justifyContent='flex-end'>
                <Button
                  variant='outlined'
                  onClick={handleImportMcpJson}
                  disabled={saving || !mcpImportJson.trim()}
                >
                  导入配置
                </Button>
              </Stack>
            </Stack>

            <Divider />

            <TextField
              label='扩展名称'
              value={formState.name}
              onChange={(e) =>
                setFormState((prev) => ({ ...prev, name: e.target.value }))
              }
              required
              fullWidth
            />

            <Stack direction='row' spacing={1.5}>
              <FormControl fullWidth>
                <InputLabel id='transport-label'>传输方式</InputLabel>
                <Select
                  labelId='transport-label'
                  label='传输方式'
                  value={formState.transport}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      transport: e.target.value as ExtensionTransport,
                    }))
                  }
                >
                  <MenuItem value='http'>HTTP（Streamable）</MenuItem>
                  <MenuItem value='stdio'>STDIO</MenuItem>
                </Select>
              </FormControl>
            </Stack>

            {editorMode === 'create' && (
              <Typography variant='body2' color='text.secondary'>
                创建后默认状态为“已启用”，可在详情页随时禁用。
              </Typography>
            )}

            <Divider />

            {formState.transport === 'http' ? (
              <Stack spacing={1.5}>
                <Typography variant='subtitle2'>HTTP 配置</Typography>
                <TextField
                  label='MCP URL'
                  placeholder='示例：https://mcp.example.internal/mcp'
                  value={formState.httpUrl}
                  onChange={(e) =>
                    setFormState((prev) => ({ ...prev, httpUrl: e.target.value }))
                  }
                  fullWidth
                  required
                />
                <TextField
                  label='超时（秒）'
                  value={formState.httpTimeoutSeconds}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      httpTimeoutSeconds: e.target.value,
                    }))
                  }
                  placeholder='30'
                  fullWidth
                />
                <Stack direction='row' spacing={1.5}>
                  <FormControl fullWidth>
                    <InputLabel id='http-auth-type-label'>认证类型</InputLabel>
                    <Select
                      labelId='http-auth-type-label'
                      label='认证类型'
                      value={formState.httpAuthType}
                      onChange={(e) =>
                        setFormState((prev) => ({
                          ...prev,
                          httpAuthType: e.target.value as ExtensionAuthType,
                        }))
                      }
                    >
                      <MenuItem value='none'>None</MenuItem>
                      <MenuItem value='bearer'>Bearer</MenuItem>
                      <MenuItem value='basic'>Basic</MenuItem>
                    </Select>
                  </FormControl>
                </Stack>
                {formState.httpAuthType !== 'none' && (
                  <TextField
                    label='认证 Token'
                    value={formState.httpAuthToken}
                    onChange={(e) =>
                      setFormState((prev) => ({
                        ...prev,
                        httpAuthToken: e.target.value,
                      }))
                    }
                    fullWidth
                  />
                )}
                <TextField
                  label='Headers（JSON）'
                  value={formState.httpHeadersJson}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      httpHeadersJson: e.target.value,
                    }))
                  }
                  placeholder='示例：{"X-Trace-Source":"mcp-console"}'
                  multiline
                  minRows={4}
                  fullWidth
                />
              </Stack>
            ) : (
              <Stack spacing={1.5}>
                <Typography variant='subtitle2'>STDIO 配置</Typography>
                <TextField
                  label='命令'
                  value={formState.stdioCommand}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      stdioCommand: e.target.value,
                    }))
                  }
                  placeholder='npx'
                  required
                  fullWidth
                />
                <TextField
                  label='参数（每行一个）'
                  value={formState.stdioArgsText}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      stdioArgsText: e.target.value,
                    }))
                  }
                  multiline
                  minRows={4}
                  fullWidth
                />
                <TextField
                  label='环境变量（JSON）'
                  value={formState.stdioEnvJson}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      stdioEnvJson: e.target.value,
                    }))
                  }
                  placeholder='示例：{"MCP_MODE":"prod"}'
                  multiline
                  minRows={4}
                  fullWidth
                />
                <TextField
                  label='工作目录（可选）'
                  value={formState.stdioWorkingDirectory}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      stdioWorkingDirectory: e.target.value,
                    }))
                  }
                  placeholder='C:\\Tools\\mcp'
                  fullWidth
                />
                <TextField
                  label='超时（秒）'
                  value={formState.stdioTimeoutSeconds}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      stdioTimeoutSeconds: e.target.value,
                    }))
                  }
                  placeholder='30'
                  fullWidth
                />
              </Stack>
            )}

            <Divider />

            <Typography variant='subtitle2'>可观测性</Typography>
            <FormControlLabel
              control={
                <Switch
                  checked={formState.emitMetrics}
                  onChange={(e) =>
                    setFormState((prev) => ({
                      ...prev,
                      emitMetrics: e.target.checked,
                    }))
                  }
                />
              }
              label='启用基础指标采集'
            />
            <FormControl fullWidth>
              <InputLabel id='log-level-label'>日志级别覆盖</InputLabel>
              <Select
                labelId='log-level-label'
                label='日志级别覆盖'
                value={formState.logLevelOverride}
                onChange={(e) =>
                  setFormState((prev) => ({
                    ...prev,
                    logLevelOverride: e.target.value as ExtensionFormState['logLevelOverride'],
                  }))
                }
              >
                <MenuItem value=''>默认</MenuItem>
                <MenuItem value='DEBUG'>DEBUG</MenuItem>
                <MenuItem value='INFO'>INFO</MenuItem>
                <MenuItem value='WARNING'>WARNING</MenuItem>
                <MenuItem value='ERROR'>ERROR</MenuItem>
              </Select>
            </FormControl>

            <Stack direction='row' spacing={1} justifyContent='flex-end' sx={{ pt: 1 }}>
              <Button
                variant='outlined'
                onClick={() => setDrawerOpen(false)}
                disabled={saving}
              >
                取消
              </Button>
              <Button variant='contained' onClick={handleSave} loading={saving}>
                {editorMode === 'create' ? '创建扩展' : '保存修改'}
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Drawer>

      <ConfirmDialog
        open={deleteTarget !== null}
        title='删除扩展'
        message={
          deleteTarget
            ? `确定删除扩展「${deleteTarget.name}」？删除后需要重新配置。`
            : ''
        }
        confirmText='删除'
        cancelText='取消'
        variant='destructive'
        loading={deleteMutation.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={handleDelete}
      />
    </Box>
  );
}

export default ExtensionsPage;
