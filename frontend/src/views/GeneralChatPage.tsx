'use client';

import { GeneralChatView } from '../components/chat/GeneralChatView';
import { useGeneralChatController } from '../hooks/useGeneralChatController';
import { useRuntimeConfig } from '../hooks/queries/useRuntimeConfig';

export function GeneralChatPage() {
  const controller = useGeneralChatController();
  const runtimeConfigQuery = useRuntimeConfig();

  return (
    <GeneralChatView
      session={controller.session}
      messages={controller.messages}
      input={controller.input}
      loading={controller.loading}
      error={controller.error}
      allowExternal={controller.allowExternal}
      webSearch={controller.webSearch}
      hasPendingApproval={controller.hasPendingApproval}
      isInputDisabled={controller.isInputDisabled}
      runtimeConfig={runtimeConfigQuery.data}
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
