import { useState, useEffect, useCallback } from 'react';
import {
  listExtensions,
  createExtension,
  updateExtension,
  deleteExtension,
  getExtensionTools,
  type ToolExtension,
  type ToolExtensionCreate,
  type ExtensionStatus,
  type ToolDescriptor,
} from '../services/extensions';

export function ExtensionsPage() {
  const [extensions, setExtensions] = useState<ToolExtension[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [selectedExt, setSelectedExt] = useState<ToolExtension | null>(null);
  const [tools, setTools] = useState<ToolDescriptor[]>([]);
  const [toolsLoading, setToolsLoading] = useState(false);

  // 表单状态
  const [formData, setFormData] = useState<ToolExtensionCreate>({
    name: '',
    transport: 'http',
    endpoint: '',
  });

  const loadExtensions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listExtensions();
      setExtensions(res.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadExtensions();
  }, [loadExtensions]);

  const handleCreate = async () => {
    if (!formData.name || !formData.endpoint) return;
    setLoading(true);
    try {
      await createExtension(formData);
      setShowForm(false);
      setFormData({ name: '', transport: 'http', endpoint: '' });
      await loadExtensions();
    } catch (e) {
      setError(e instanceof Error ? e.message : '创建失败');
    } finally {
      setLoading(false);
    }
  };

  const handleToggleStatus = async (ext: ToolExtension) => {
    const newStatus: ExtensionStatus = ext.status === 'enabled' ? 'disabled' : 'enabled';
    try {
      await updateExtension(ext.id, { status: newStatus });
      await loadExtensions();
    } catch (e) {
      setError(e instanceof Error ? e.message : '更新失败');
    }
  };

  const handleDelete = async (ext: ToolExtension) => {
    if (!confirm(`确定删除扩展 "${ext.name}"？`)) return;
    try {
      await deleteExtension(ext.id);
      if (selectedExt?.id === ext.id) {
        setSelectedExt(null);
        setTools([]);
      }
      await loadExtensions();
    } catch (e) {
      setError(e instanceof Error ? e.message : '删除失败');
    }
  };

  const handleViewTools = async (ext: ToolExtension) => {
    setSelectedExt(ext);
    setToolsLoading(true);
    try {
      const res = await getExtensionTools(ext.id);
      setTools(res.items);
    } catch (e) {
      setTools([]);
      setError(e instanceof Error ? e.message : '获取工具列表失败');
    } finally {
      setToolsLoading(false);
    }
  };

  return (
    <div style={{ padding: 24, maxWidth: 1000, margin: '0 auto' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <h1 style={{ marginBottom: 8 }}>扩展管理</h1>
          <p style={{ color: '#6b7280' }}>管理 MCP 扩展，增强全能代理能力</p>
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

      {error && (
        <div style={{ padding: 12, background: '#fef2f2', color: '#dc2626', borderRadius: 8, marginBottom: 16 }}>
          {error}
          <button onClick={() => setError(null)} style={{ marginLeft: 8, cursor: 'pointer' }}>×</button>
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
              onChange={(e) => setFormData({ ...formData, transport: e.target.value as 'http' | 'stdio' })}
              style={{ padding: 10, borderRadius: 6, border: '1px solid #d1d5db' }}
            >
              <option value="http">HTTP</option>
              <option value="stdio">STDIO</option>
            </select>
            <input
              placeholder={formData.transport === 'http' ? 'http://localhost:3000' : 'python mcp_server.py'}
              value={formData.endpoint}
              onChange={(e) => setFormData({ ...formData, endpoint: e.target.value })}
              style={{ padding: 10, borderRadius: 6, border: '1px solid #d1d5db' }}
            />
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={handleCreate}
                disabled={!formData.name || !formData.endpoint}
                style={{
                  padding: '10px 20px',
                  background: !formData.name || !formData.endpoint ? '#9ca3af' : '#111827',
                  color: '#fff',
                  border: 'none',
                  borderRadius: 6,
                  cursor: !formData.name || !formData.endpoint ? 'not-allowed' : 'pointer',
                }}
              >
                创建
              </button>
              <button
                onClick={() => setShowForm(false)}
                style={{ padding: '10px 20px', background: '#e5e7eb', border: 'none', borderRadius: 6, cursor: 'pointer' }}
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
        <div style={{ textAlign: 'center', color: '#6b7280', padding: 40 }}>暂无扩展，点击"添加扩展"开始</div>
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
                  style={{ padding: '6px 12px', background: '#e5e7eb', border: 'none', borderRadius: 6, cursor: 'pointer' }}
                >
                  {ext.status === 'enabled' ? '禁用' : '启用'}
                </button>
                <button
                  onClick={() => handleViewTools(ext)}
                  style={{ padding: '6px 12px', background: '#dbeafe', border: 'none', borderRadius: 6, cursor: 'pointer' }}
                >
                  查看工具
                </button>
                <button
                  onClick={() => handleDelete(ext)}
                  style={{ padding: '6px 12px', background: '#fee2e2', color: '#dc2626', border: 'none', borderRadius: 6, cursor: 'pointer' }}
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
                <div key={tool.name} style={{ padding: 12, background: '#fff', borderRadius: 6, border: '1px solid #e5e7eb' }}>
                  <div style={{ fontWeight: 600 }}>{tool.name}</div>
                  {tool.description && <div style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>{tool.description}</div>}
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
