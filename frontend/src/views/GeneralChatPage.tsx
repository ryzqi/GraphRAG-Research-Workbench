'use client';

import { GeneralChatView } from '../components/chat/GeneralChatView';
import { useGeneralChatController } from '../hooks/useGeneralChatController';

export function GeneralChatPage() {
  const controller = useGeneralChatController();

  return (
    <GeneralChatView
      session={controller.session}
      messages={controller.messages}
      input={controller.input}
      loading={controller.loading}
      error={controller.error}
      allowExternal={controller.allowExternal}
      webSearchAvailable={controller.webSearchAvailable}
      hasPendingApproval={controller.hasPendingApproval}
      isInputDisabled={controller.isInputDisabled}
      setAllowExternal={controller.setAllowExternal}
      setInput={controller.setInput}
      setError={controller.setError}
      onSend={controller.handleSend}
      onToolApprovalSubmit={controller.handleToolApproval}
      onSuggestionClick={controller.handleSuggestionClick}
    />
  );
}

export default GeneralChatPage;
