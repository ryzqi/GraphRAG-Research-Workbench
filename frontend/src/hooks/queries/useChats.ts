/**
 * Chat data hooks based on SWR
 */
import {
  createChatSession,
  sendMessage,
  type ChatSessionCreate,
} from '../../services/chats';
import { useApiMutation } from '../../lib/swr';

const KEYS = {
  all: ['chats'] as const,
  session: (id: string) => [...KEYS.all, 'session', id] as const,
  messages: (sessionId: string) => [...KEYS.all, 'messages', sessionId] as const,
};

export function useCreateChatSession() {
  return useApiMutation((data: ChatSessionCreate) => createChatSession(data));
}

export function useSendMessage() {
  return useApiMutation(
    ({ sessionId, content }: { sessionId: string; content: string }) =>
      sendMessage(sessionId, content),
    {
      onSuccess: async (_, { sessionId }, { invalidate }) => {
        await invalidate([KEYS.messages(sessionId)]);
      },
    }
  );
}

export { KEYS as chatKeys };
