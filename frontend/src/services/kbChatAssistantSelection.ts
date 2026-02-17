export interface AssistantSelectionMessage {
  id: string;
  isStreaming?: boolean;
}

/**
 * Resolve which assistant message should be active in trace panel.
 */
export function resolveActiveAssistantId(
  assistantMessages: AssistantSelectionMessage[],
  activeAssistantId: string | null
): string | null {
  if (assistantMessages.length === 0) {
    return null;
  }
  const latest = assistantMessages[assistantMessages.length - 1];
  const exists = assistantMessages.some((msg) => msg.id === activeAssistantId);
  if (!activeAssistantId || !exists) {
    return latest.id;
  }
  if (latest.isStreaming && latest.id !== activeAssistantId) {
    return latest.id;
  }
  return activeAssistantId;
}
