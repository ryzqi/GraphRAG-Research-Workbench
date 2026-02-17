import type { KnowledgeBase } from './knowledgeBases';

export function hasSelectedParentChildKnowledgeBase(
  selectedKbIds: string[],
  knowledgeBases: KnowledgeBase[] | undefined
): boolean {
  if (selectedKbIds.length === 0 || !knowledgeBases || knowledgeBases.length === 0) {
    return false;
  }

  const selected = new Set(selectedKbIds);
  return knowledgeBases.some(
    (kb) =>
      selected.has(kb.id) &&
      kb.index_config?.chunking.general_strategy === 'parent_child'
  );
}
