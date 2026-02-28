const GENERAL_CHAT_FALLBACK_TITLE = '普通对话';
const GENERAL_CHAT_TITLE_MAX_LENGTH = 30;

export function buildGeneralChatRecentTitle(content: string): string {
  const normalized = content.trim();
  if (!normalized) {
    return GENERAL_CHAT_FALLBACK_TITLE;
  }
  return normalized.slice(0, GENERAL_CHAT_TITLE_MAX_LENGTH);
}

export function shouldSkipGeneralChatHydration(
  pendingBootstrapSessionId: string | null,
  sessionIdFromUrl: string | null
): boolean {
  if (!pendingBootstrapSessionId || !sessionIdFromUrl) {
    return false;
  }
  return pendingBootstrapSessionId === sessionIdFromUrl;
}
