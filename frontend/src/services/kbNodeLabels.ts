import type { KbGraphSchema } from './chats';
import { resolveKbNodeLabelFromCatalog, resolveKbSchemaNode } from './kbNodeCatalog';

const LEGACY_NODE_LABELS: Record<string, string> = {
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
