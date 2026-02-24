export type ChatSessionScope = 'general' | 'kb';

interface ChatSessionRequestKeyInput {
  scope: ChatSessionScope;
  sessionId: string | null;
  contextId?: string | null;
}

interface ActiveRequest {
  id: number;
  key: string;
  controller: AbortController;
}

export function buildChatSessionRequestKey(input: ChatSessionRequestKeyInput): string | null {
  if (!input.sessionId) {
    return null;
  }
  return `${input.scope}::${input.sessionId}::${input.contextId ?? '-'}`;
}

export class ChatSessionRequestControl {
  private counter = 0;
  private active: ActiveRequest | null = null;

  start(key: string): { id: number; signal: AbortSignal } {
    this.cancelActive();
    const controller = new AbortController();
    const id = ++this.counter;
    this.active = { id, key, controller };
    return { id, signal: controller.signal };
  }

  isLatest(id: number, key: string): boolean {
    if (!this.active) {
      return false;
    }
    return this.active.id === id && this.active.key === key && !this.active.controller.signal.aborted;
  }

  finish(id: number): void {
    if (this.active?.id === id) {
      this.active = null;
    }
  }

  cancelActive(): void {
    if (!this.active) {
      return;
    }
    this.active.controller.abort();
    this.active = null;
  }
}
