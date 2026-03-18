import type { ChatNodeIoEvent, KbGraphSchema } from './chats';

function normalizeNodeId(value: string): string {
  const hashIndex = value.indexOf('#');
  return hashIndex >= 0 ? value.slice(0, hashIndex) : value;
}

export function resolveFinalizeNodeIds(
  schema: KbGraphSchema | null | undefined
): Set<string> {
  const explicitTerminalNodeIds = new Set(['answer_commit', 'force_exit']);
  const ids = new Set<string>();
  for (const node of schema?.nodes ?? []) {
    if (typeof node.id !== 'string') {
      continue;
    }
    const trimmedId = node.id.trim();
    if (!trimmedId) {
      continue;
    }
    const normalizedId = normalizeNodeId(trimmedId);
    if (node.phase !== 'finalize' && !explicitTerminalNodeIds.has(normalizedId)) {
      continue;
    }
    ids.add(trimmedId);
    ids.add(normalizedId);
  }
  return ids;
}

export function shouldRevealAnswerOnNodeEvent(
  event: Pick<ChatNodeIoEvent, 'phase' | 'node_name' | 'node_id'>,
  finalizeNodeIds: ReadonlySet<string>
): boolean {
  if (event.phase !== 'end' || finalizeNodeIds.size === 0) {
    return false;
  }

  const candidates = [event.node_name, event.node_id]
    .filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
    .flatMap((value) => {
      const trimmed = value.trim();
      return [trimmed, normalizeNodeId(trimmed)];
    });

  return candidates.some((candidate) => finalizeNodeIds.has(candidate));
}
