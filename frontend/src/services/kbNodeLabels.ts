import type { KbGraphSchema } from './chats';
import { resolveKbNodeLabelFromCatalog, resolveKbSchemaNode } from './kbNodeCatalog';

const LEGACY_NODE_LABELS: Record<string, string> = {
  AMBIGUITY_CHECK_ENABLED: '歧义检查入口',
  adaptive_routing: '自适应路由',
  simple_path: '简单路径',
  moderate_path: '中等路径',
  complex_path: '复杂路径',
  ENABLE_MULTI_QUERY_MOD: '中等多路开关',
  ENABLE_DECOMPOSITION: '拆解开关',
  ENABLE_MULTI_QUERY: '多路开关',
  ENABLE_HYDE: 'HyDE开关',
  finalize: '答案整理',
};

function findSchemaNodeLabel(
  nodeId: string,
  schema: KbGraphSchema | null | undefined
): string | null {
  const found = resolveKbSchemaNode(nodeId, schema);
  if (!found) {
    return null;
  }
  const metadataLabel =
    found.metadata && typeof found.metadata === 'object' && !Array.isArray(found.metadata)
      ? found.metadata.label
      : null;
  const label =
    typeof metadataLabel === 'string' && metadataLabel.trim().length > 0
      ? metadataLabel.trim()
      : typeof found.label === 'string'
        ? found.label.trim()
        : '';
  return label || null;
}

export function resolveKbNodeLabel(
  nodeId: string,
  schema: KbGraphSchema | null | undefined
): string {
  const schemaLabel = findSchemaNodeLabel(nodeId, schema);
  if (schemaLabel && schemaLabel !== nodeId) {
    return schemaLabel;
  }
  return resolveKbNodeLabelFromCatalog(nodeId) ?? LEGACY_NODE_LABELS[nodeId] ?? schemaLabel ?? nodeId;
}
