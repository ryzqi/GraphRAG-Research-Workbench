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
              }}
            >
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  width: 20,
                  height: 20,
                  borderRadius: '50%',
                  background: '#3b82f6',
                  color: '#fff',
                  fontSize: 12,
                  fontWeight: 500,
                }}
              >
                {index + 1}
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
