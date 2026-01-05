/**
 * 对话相关 React Query Hooks
 */
import { useMutation, useQueryClient } from '@tanstack/react-query';
import {
  createChatSession,
  sendMessage,
  type ChatSessionCreate,
} from '../../services/chats';

// Query Keys
const KEYS = {
  all: ['chats'] as const,
  session: (id: string) => [...KEYS.all, 'session', id] as const,
  messages: (sessionId: string) => [...KEYS.all, 'messages', sessionId] as const,
};

/**
 * 创建会话
 */
export function useCreateChatSession() {
  return useMutation({
    mutationFn: (data: ChatSessionCreate) => createChatSession(data),
  });
}

/**
 * 发送消息
 */
export function useSendMessage() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ sessionId, content }: { sessionId: string; content: string }) =>
      sendMessage(sessionId, content),
    onSuccess: (_, { sessionId }) => {
      queryClient.invalidateQueries({ queryKey: KEYS.messages(sessionId) });
    },
  });
}

export { KEYS as chatKeys };
