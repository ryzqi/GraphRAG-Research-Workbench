import { useState } from 'react';
import type {
  ExtensionStatus,
  ToolExtension,
  ToolExtensionCreate,
} from '../services/extensions';
import {
  useCreateExtension,
  useDeleteExtension,
  useExtensionTools,
  useExtensions,
  useUpdateExtension,
} from '../hooks/queries/useExtensions';
import { getErrorMessage } from '../lib/errorHandler';

export function ExtensionsPage() {
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [selectedExt, setSelectedExt] = useState<ToolExtension | null>(null);

  // 表单状态
  const [formData, setFormData] = useState<ToolExtensionCreate>({
    name: '',
    transport: 'http',
    endpoint: '',
  });

  const extensionsQuery = useExtensions();
  const extensions = extensionsQuery.data ?? [];
  const loading = extensionsQuery.isPending || extensionsQuery.isFetching;

  const toolsQuery = useExtensionTools(selectedExt?.id ?? undefined);
  const tools = toolsQuery.data ?? [];
  const toolsLoading = toolsQuery.isPending || toolsQuery.isFetching;

  const createMutation = useCreateExtension();
  const updateMutation = useUpdateExtension();
  const deleteMutation = useDeleteExtension();

  const mergedError =
    error ??
    (createMutation.error ? getErrorMessage(createMutation.error) : null) ??
    (updateMutation.error ? getErrorMessage(updateMutation.error) : null) ??
    (deleteMutation.error ? getErrorMessage(deleteMutation.error) : null) ??
    (extensionsQuery.error ? getErrorMessage(extensionsQuery.error) : null) ??
    (toolsQuery.error ? getErrorMessage(toolsQuery.error) : null);

  const handleCloseError = () => {
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

  const handleCreate = () => {
    if (!formData.name || !formData.endpoint) return;

    setError(null);
    createMutation.mutate(formData, {
      onSuccess: () => {
        setShowForm(false);
        setFormData({ name: '', transport: 'http', endpoint: '' });
      },
    });
  };

  const handleToggleStatus = (ext: ToolExtension) => {
    const newStatus: ExtensionStatus = ext.status === 'enabled' ? 'disabled' : 'enabled';

    setError(null);
    updateMutation.mutate({ id: ext.id, data: { status: newStatus } });
  };

  const handleDelete = (ext: ToolExtension) => {
    if (!confirm(`确定删除扩展 \"${ext.name}\"？`)) return;

    setError(null);
    deleteMutation.mutate(ext.id, {
      onSuccess: () => {
        if (selectedExt?.id === ext.id) {
          setSelectedExt(null);
        }
      },
    });
  };

  const handleViewTools = (ext: ToolExtension) => {
    setError(null);
    setSelectedExt(ext);
  };

  const createDisabled = !formData.name || !formData.endpoint || createMutation.isPending;

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ marginBottom: 8 }}>MCP扩展</h1>
          <p style={{ color: '#6b7280' }}>管理 MCP 扩展，增强普通代理能力</p>
        </div>
        <button
          onClick={() => setShowForm(true)}
          style={{
            padding: '10px 20px',
            background: '#111827',
            color: '#fff',
            border: 'none',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          添加扩展
        </button>
      </div>

      {mergedError && (
        <div style={{ padding: 12, background: '#fef2f2', color: '#dc2626', borderRadius: 8, marginBottom: 16 }}>
          {mergedError}
          <button onClick={handleCloseError} style={{ marginLeft: 8, cursor: 'pointer' }}>×</button>
        </div>
      )}

      {/* 添加表单 */}
      {showForm && (
        <div style={{ padding: 16, background: '#f9fafb', borderRadius: 8, marginBottom: 24 }}>
          <h3 style={{ marginBottom: 16 }}>添加扩展</h3>
          <div style={{ display: 'grid', gap: 12 }}>
            <input
              placeholder="扩展名称"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              style={{ padding: 10, borderRadius: 6, border: '1px solid #d1d5db' }}
            />
            <select
              value={formData.transport}
              onChange={(e) =>
                setFormData({ ...formData, transport: e.target.value as 'http' | 'stdio' })
              }
              style={{ padding: 10, borderRadius: 6, border: '1px solid #d1d5db' }}
            >
              <option value="http">HTTP</option>
              <option value="stdio">STDIO</option>
            </select>
            <input
              placeholder={
                formData.transport === 'http' ? 'http://localhost:3000' : 'python mcp_server.py'
              }
              value={formData.endpoint}
              onChange={(e) => setFormData({ ...formData, endpoint: e.target.value })}
              style={{ padding: 10, borderRadius: 6, border: '1px solid #d1d5db' }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={handleCreate}
                disabled={createDisabled}
                style={{
                  padding: '10px 20px',
                  background: createDisabled ? '#9ca3af' : '#111827',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: createDisabled ? 'not-allowed' : 'pointer',
                }}
              >
                {createMutation.isPending ? '创建中...' : '创建'}
              </button>
              <button
                onClick={() => setShowForm(false)}
                style={{
                  padding: '10px 20px',
                  background: '#e5e7eb',
                  border: 'none',
                  borderRadius: 6,
                  cursor: 'pointer',
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 扩展列表 */}
      {loading && extensions.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#6b7280', padding: 40 }}>加载中...</div>
      ) : extensions.length === 0 ? (
        <div style={{ textAlign: 'center', color: '#6b7280', padding: 40 }}>
          暂无扩展，点击「添加扩展」开始
        </div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {extensions.map((ext) => (
            <div
              key={ext.id}
              style={{
                padding: 16,
                background: '#fff',
                border: '1px solid #e5e7eb',
                borderRadius: 8,
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
              }}
            >
              <div>
                <div style={{ fontWeight: 600, marginBottom: 4 }}>{ext.name}</div>
                <div style={{ fontSize: 13, color: '#6b7280' }}>
                  {ext.transport.toUpperCase()} | {ext.endpoint}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span
                  style={{
                    padding: '4px 8px',
                    borderRadius: 4,
                    fontSize: 12,
                    background: ext.status === 'enabled' ? '#d1fae5' : '#f3f4f6',
                    color: ext.status === 'enabled' ? '#059669' : '#6b7280',
                  }}
                >
                  {ext.status === 'enabled' ? '已启用' : '已禁用'}
                </span>
                <button
                  onClick={() => handleToggleStatus(ext)}
                  style={{
                    padding: '6px 12px',
                    background: '#e5e7eb',
                    border: 'none',
                    borderRadius: 6,
                    cursor: 'pointer',
                  }}
                >
                  {ext.status === 'enabled' ? '禁用' : '启用'}
                </button>
                <button
                  onClick={() => handleViewTools(ext)}
                  style={{
                    padding: '6px 12px',
                    background: '#dbeafe',
                    border: 'none',
                    borderRadius: 6,
                    cursor: 'pointer',
                  }}
                >
                  查看工具
                </button>
                <button
                  onClick={() => handleDelete(ext)}
                  style={{
                    padding: '6px 12px',
                    background: '#fee2e2',
                    color: '#dc2626',
                    border: 'none',
                    borderRadius: 6,
                    cursor: 'pointer',
                  }}
                >
                  删除
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* 工具列表 */}
      {selectedExt && (
        <div style={{ marginTop: 24, padding: 16, background: '#f9fafb', borderRadius: 8 }}>
          <h3 style={{ marginBottom: 12 }}>{selectedExt.name} 提供的工具</h3>
          {toolsLoading ? (
            <div style={{ color: '#6b7280' }}>加载中...</div>
          ) : tools.length === 0 ? (
            <div style={{ color: '#6b7280' }}>无可用工具（扩展可能未启用或连接失败）</div>
          ) : (
            <div style={{ display: 'grid', gap: 8 }}>
              {tools.map((tool) => (
                <div
                  key={tool.name}
                  style={{
                    padding: 12,
                    background: '#fff',
                    borderRadius: 6,
                    border: '1px solid #e5e7eb',
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{tool.name}</div>
                  {tool.description && (
                    <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>
                      {tool.description}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ExtensionsPage;


