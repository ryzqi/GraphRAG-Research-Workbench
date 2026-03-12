import type { KbGraphSchema } from './chats';
import { resolveKbNodeLabelFromCatalog } from './kbNodeCatalog';

function findSchemaNodeLabel(
  nodeId: string,
  schema: KbGraphSchema | null | undefined
): string | null {
  const found = schema?.nodes.find((node) => node.id === nodeId);
  if (!found) {
    return null;
  }
  const label = typeof found.label === 'string' ? found.label.trim() : '';
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
  return resolveKbNodeLabelFromCatalog(nodeId) ?? schemaLabel ?? nodeId;
}
