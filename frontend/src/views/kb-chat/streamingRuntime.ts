type TerminalRunStatus = 'succeeded' | 'failed' | 'canceled' | 'waiting_user';

export function resolveAssistantContentByRunStatus(params: {
  status: TerminalRunStatus;
  serverContent: string;
  lastGoodAnswer?: string | null;
}): string {
  const lastGoodAnswer =
    typeof params.lastGoodAnswer === 'string' ? params.lastGoodAnswer : null;
  if (
    params.status === 'failed' &&
    typeof lastGoodAnswer === 'string' &&
    lastGoodAnswer.trim().length > 0
  ) {
    return lastGoodAnswer;
  }
  return params.serverContent;
}
