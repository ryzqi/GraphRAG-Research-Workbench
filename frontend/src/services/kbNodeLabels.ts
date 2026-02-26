import type { KbGraphSchema } from './chats';

const KB_NODE_LABELS: Record<string, string> = {
  merge_context: '\u4e0a\u4e0b\u6587\u5408\u5e76',
  coref_rewrite: '\u6307\u4ee3\u6d88\u89e3',
  ambiguity_check: '\u6b67\u4e49\u5224\u65ad',
  normalize_rewrite: '\u95ee\u9898\u89c4\u8303',
  complexity_router: '\u590d\u6742\u5ea6\u8def\u7531',
  decomposition: '\u95ee\u9898\u5206\u89e3',
  generate_variants: '\u591a\u8def\u6269\u5c55',
  entity_expand: '\u5b9e\u4f53\u6269\u5c55',
  hyde: 'HyDE\u6269\u5c55',
  prepare_messages: '\u6d88\u606f\u6574\u7406',
  dispatch_subqueries: '\u5b50\u67e5\u8be2\u6d3e\u53d1',
  retrieve_subquery: '\u5b50\u67e5\u8be2\u68c0\u7d22',
  merge_subquery_context: '\u5b50\u67e5\u8be2\u4e0a\u4e0b\u6587\u5408\u5e76',
  retrieve: '\u77e5\u8bc6\u68c0\u7d22',
  doc_gate_precheck: '\u6587\u6863\u9884\u5224',
  doc_grader_llm: '\u6587\u6863\u590d\u6838',
  doc_gate_route: '\u6587\u6863\u5224\u5b9a',
  doc_grader: '\u6587\u6863\u5224\u5b9a',
  transform_query: '\u67e5\u8be2\u6539\u5199',
  generate: '\u7b54\u6848\u751f\u6210',
  answer_review: '\u7b54\u6848\u5ba1\u67e5',
  finalize: '\u7b54\u6848\u6574\u7406',
  force_exit: '\u63d0\u524d\u7ec8\u6b62',
};

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
  return KB_NODE_LABELS[nodeId] ?? schemaLabel ?? nodeId;
}
