import type { RecentSession } from '../hooks/useRecentHistory';

type DeletedSessionNavigationParams = {
  pathname: string;
  currentSessionId: string | null;
  deletedSessionId: string;
  deletedSessionType: RecentSession['type'];
};

function matchesDeletedSessionRoute(
  pathname: string,
  sessionType: RecentSession['type']
): boolean {
  if (sessionType === 'general_chat') {
    return pathname.startsWith('/general-chat');
  }
  return pathname.startsWith('/kb-chat');
}

export function resolveDeletedSessionNavigationTarget(
  params: DeletedSessionNavigationParams
): string | null {
  const { pathname, currentSessionId, deletedSessionId, deletedSessionType } = params;
  if (!currentSessionId || currentSessionId !== deletedSessionId) {
    return null;
  }
  if (!matchesDeletedSessionRoute(pathname, deletedSessionType)) {
    return null;
  }
  return pathname;
}

export function shouldResetChatStateOnSessionClear(
  previousSessionId: string | null,
  currentSessionId: string | null
): boolean {
  return Boolean(previousSessionId) && !currentSessionId;
}
