/**
 * 证据清单组件
 */

import type { EvidenceItem } from '../services/chats';

interface EvidenceListProps {
  evidence: EvidenceItem[];
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
      {evidence.map((item, index) => (
        <div
          key={index}
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
              {item.locator?.material_title && ` · ${item.locator.material_title}`}
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
      ))}
    </div>
  );
}
