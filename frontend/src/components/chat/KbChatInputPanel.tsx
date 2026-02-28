import type { RefObject } from 'react';
import { InputComposer } from './InputComposer';
import { ChatInputDock } from './ChatInputDock';

interface KbChatInputPanelProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => Promise<void>;
  disabled: boolean;
  loading: boolean;
  hasPendingClarification: boolean;
  composerRef: RefObject<HTMLDivElement | null>;
}

export function KbChatInputPanel({
  value,
  onChange,
  onSend,
  disabled,
  loading,
  hasPendingClarification,
  composerRef,
}: KbChatInputPanelProps) {
  return (
    <ChatInputDock composerRef={composerRef} variant='kb' maxWidth={900}>
      <InputComposer
        value={value}
        onChange={onChange}
        onSend={onSend}
        disabled={disabled}
        loading={loading}
        placeholder={hasPendingClarification ? '请先补充上方澄清信息...' : '输入你的问题...'}
        showShortcutHint={false}
      />
    </ChatInputDock>
  );
}
