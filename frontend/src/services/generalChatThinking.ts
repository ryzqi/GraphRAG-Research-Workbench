import type { ChatMessage } from '../components/chat/MessageList';

export function createStreamingAssistantMessage(
  id: string,
  thinkStartTime: number
): ChatMessage {
  return {
    id,
    role: 'assistant',
    content: '',
    think: '',
    isStreaming: true,
    thinkStartTime,
  };
}

export function restartStreamingAssistantMessage(
  message: ChatMessage,
  thinkStartTime: number
): ChatMessage {
  return {
    ...message,
    isStreaming: true,
    thinkStartTime,
  };
}
