/**
 * 证据清单组件
 */

import type { EvidenceItem } from '../services/chats';

interface EvidenceListProps {
  evidence: EvidenceItem[];
}

/**
 * 从 locator 中安全读取 string 字段（避免 unknown 直接渲染到 JSX）
 */
function getLocatorString(
  locator: Record<string, unknown> | null | undefined,
  key: string
): string | null {
  const value = locator?.[key];
  return typeof value === 'string' ? value : null;
}

function stripExtension(name: string): string {
  const trimmed = name.trim();
  if (!trimmed) {
    return '';
  }
  const normalized = trimmed.replace(/\\/g, '/');
  const base = normalized.split('/').pop() ?? normalized;
  const dotIndex = base.lastIndexOf('.');
  if (dotIndex <= 0) {
    return base;
  }
  return base.slice(0, dotIndex);
}

function getCitationLabel(item: EvidenceItem, index: number): string {
  const explicit = getLocatorString(item.locator, 'citation_label');
  if (explicit && explicit.trim()) {
    return explicit.trim();
  }
  const filename = getLocatorString(item.locator, 'filename');
  if (filename && filename.trim()) {
    const stem = stripExtension(filename);
    if (stem.trim()) {
      return stem.trim();
    }
  }
  return `资料${index + 1}`;
}

/**
 * 生成证据项的唯一 key
 */
function getEvidenceKey(item: EvidenceItem, index: number): string {
  // 优先使用 locator 中的 chunk_id
  const chunkId = getLocatorString(item.locator, 'chunk_id');
  if (chunkId) {
    return `chunk-${chunkId}`;
  }
  // 其次使用 kb_id + material_id 组合
  if (item.kb_id && item.material_id) {
    return `kb-${item.kb_id}-mat-${item.material_id}-${index}`;
  }
  // 最后使用 excerpt 的 hash 作为 key
  const excerptHash = item.excerpt.slice(0, 50).replace(/\s+/g, '-');
  return `${item.source_kind}-${excerptHash}-${index}`;
}

export function EvidenceList({ evidence }: EvidenceListProps) {
  if (evidence.length === 0) {
    return (
      <div style={{ color: '#6b7280', fontSize: 14, padding: '8px 0' }}>
        暂无相关证据
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontSize: 14, fontWeight: 500, color: '#374151' }}>
        参考来源 ({evidence.length})
      </div>
      {evidence.map((item, index) => {
        const materialTitle = getLocatorString(item.locator, 'material_title');
        const citationLabel = getCitationLabel(item, index);

        return (
          <div
            key={getEvidenceKey(item, index)}
            style={{
              padding: 12,
              background: '#f9fafb',
              borderRadius: 8,
              border: '1px solid #e5e7eb',
            }}
          >
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                marginBottom: 8,
                flexWrap: 'wrap',
              }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  borderRadius: 999,
                  padding: '2px 10px',
                  background: '#eff6ff',
                  border: '1px solid #bfdbfe',
                  fontSize: 12,
                  fontWeight: 500,
                  color: '#1e40af',
                }}
              >
                {citationLabel}
              </span>
              <span style={{ fontSize: 12, color: '#6b7280' }}>
                {item.source_kind === 'kb' ? '知识库' : '外部来源'}
                {materialTitle ? ` · ${materialTitle}` : null}
              </span>
            </div>
            <div
              style={{
                fontSize: 14,
                color: '#374151',
                lineHeight: 1.6,
                whiteSpace: 'pre-wrap',
              }}
            >
              {item.excerpt}
            </div>
          </div>
        );
      })}
    </div>
  );
}
