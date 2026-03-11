import type { KbGraphSchema } from './chats';

const KB_NODE_LABELS: Record<string, string> = {
  preprocess_subgraph: '\u9884\u5904\u7406\u5b50\u56fe',
  retrieval_subgraph: '\u68c0\u7d22\u5b50\u56fe',
  evidence_gate_subgraph: '\u8bc1\u636e\u95e8\u63a7\u5b50\u56fe',
  merge_context: '\u4e0a\u4e0b\u6587\u5408\u5e76',
  coref_rewrite: '\u6307\u4ee3\u6d88\u89e3',
  ambiguity_check: '\u6b67\u4e49\u5224\u65ad',
  normalize_rewrite: '\u95ee\u9898\u89c4\u8303',
  complexity_classify: '\u590d\u6742\u5ea6\u5206\u7c7b',
  adaptive_routing: '\u81ea\u9002\u5e94\u8def\u7531',
  simple_path: '\u7b80\u5355\u8def\u5f84',
  moderate_path: '\u4e2d\u7b49\u8def\u5f84',
  complex_path: '\u590d\u6742\u8def\u5f84',
  ENABLE_MULTI_QUERY_MOD: '\u4e2d\u7b49\u591a\u8def\u5f00\u5173',
  ENABLE_DECOMPOSITION: '\u62c6\u89e3\u5f00\u5173',
  ENABLE_MULTI_QUERY: '\u591a\u8def\u5f00\u5173',
  ENABLE_HYDE: 'HyDE\u5f00\u5173',
  decomposition: '\u95ee\u9898\u5206\u89e3',
  generate_variants_mod: '\u4e2d\u7b49\u53d8\u4f53\u751f\u6210',
  generate_variants: '\u591a\u8def\u6269\u5c55',
  entity_expand: '\u5b9e\u4f53\u6269\u5c55',
  hyde: 'HyDE\u6269\u5c55',
  prepare_messages: '\u6d88\u606f\u6574\u7406',
  preprocess_exit: '\u9884\u5904\u7406\u9000\u51fa',
  retrieval_budget_plan: '\u68c0\u7d22\u9884\u7b97\u89c4\u5212',
  dispatch_subqueries: '\u5b50\u67e5\u8be2\u6d3e\u53d1',
  retrieve_subquery: '\u5b50\u67e5\u8be2\u68c0\u7d22',
  merge_subquery_context: '\u5b50\u67e5\u8be2\u4e0a\u4e0b\u6587\u5408\u5e76',
  retrieve: '\u77e5\u8bc6\u68c0\u7d22',
  context_compress: '\u4e0a\u4e0b\u6587\u538b\u7f29',
  doc_gate_sufficiency: '\u8bc1\u636e\u5145\u5206\u5ea6',
  doc_gate_answerability: '\u53ef\u56de\u7b54\u6027',
  doc_gate_conflict: '\u8bc1\u636e\u51b2\u7a81\u68c0\u6d4b',
  doc_gate_fuse: '\u8bc1\u636e\u95e8\u63a7\u878d\u5408',
  doc_gate_route: '\u6587\u6863\u5224\u5b9a',
  transform_query: '\u67e5\u8be2\u6539\u5199',
  answer_subgraph: '\u7b54\u6848\u5b50\u56fe',
  draft_generate: '\u7b54\u6848\u8349\u7a3f\u751f\u6210',
  answer_review_dispatch: '\u5ba1\u67e5\u5206\u6d3e',
  answer_review_citation: '\u5f15\u7528\u8986\u76d6\u5ba1\u67e5',
  answer_review_factual: '\u4e8b\u5b9e\u6b63\u786e\u6027\u5ba1\u67e5',
  answer_review_answerability: '\u53ef\u56de\u7b54\u6027\u5ba1\u67e5',
  answer_review_fuse: '\u5ba1\u67e5\u7ed3\u679c\u878d\u5408',
  answer_repair: '\u7b54\u6848\u4fee\u590d',
  cove_check: '\u9ad8\u98ce\u9669\u5224\u5b9a',
  chain_of_verification: 'CoVe\u9a8c\u8bc1\u94fe',
  claim_citation_check: 'Claim-\u5f15\u7528\u6821\u9a8c',
  answer_commit: '\u7b54\u6848\u63d0\u4ea4',
  generate: '\u7b54\u6848\u751f\u6210',
  answer_review: '\u7b54\u6848\u5ba1\u67e5',
  finalize: '\u7b54\u6848\u6574\u7406',
  confidence_calibrate: '\u7f6e\u4fe1\u5ea6\u6821\u51c6',
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
